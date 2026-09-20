using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using DataPrase.Core;
using ExcelDna.Integration;
using Excel = Microsoft.Office.Interop.Excel;

namespace DataPrase.AddIn
{
    /// <summary>
    /// 无头自检：在临时工作簿上跑**真实的** <see cref="ExpControls.Build"/>，回报
    /// 「建出几个控件、每个落在第几行、OnAction 挂上了没」。
    ///
    /// 存在的理由：四轮 UI 改动全是在开发机上无法验证 Excel 侧行为的前提下提交的。
    /// 这个函数让 build/verify-installed.ps1 能自己把事实读出来，不必再让用户在 Excel 里点了回报。
    /// </summary>
    public static class SelfCheck
    {
        private const int PanelLastRow = 80;

        [ExcelFunction(IsHidden = true, Description = "加载项自检：重建 Exp 控件面板并回报落点")]
        public static string DpSelfCheck()
        {
            Excel.Application app = ExcelInterop.Application;
            bool alerts = app.DisplayAlerts;
            Excel.Workbook probe = null;

            try
            {
                app.DisplayAlerts = false;
                probe = app.Workbooks.Add();
                Excel.Worksheet sheet = (Excel.Worksheet)probe.Worksheets[1];

                // Exp 表行高实测 10.2pt，自检工作簿用默认 15pt；这里对齐，免得两条路径的落点不可比。
                sheet.Rows.RowHeight = 10.2;

                var names = new List<string> { "ItemA", "ItemB", "ItemC" };
                bool[] toggles = { true, true, false, false, false, false, false, false, false };
                ExpControls.Build(sheet, names, 0, toggles);

                double[] tops = RowTops(sheet);
                int created = 0;
                int landedOk = 0;
                int onActionOk = 0;
                int captionOk = 0;
                var detail = new StringBuilder();

                Excel.Shapes shapes = sheet.Shapes;
                for (int i = 1; i <= shapes.Count; i++)
                {
                    Excel.Shape shape = shapes.Item(i);
                    string name = shape.Name;
                    if (name == null || !name.StartsWith("DpExp", StringComparison.Ordinal))
                    {
                        continue;
                    }

                    created++;
                    int row = LandingRow(tops, shape.Top);
                    int expected = ExpectedRow(name);
                    bool landed = expected > 0 && row == expected;
                    if (landed)
                    {
                        landedOk++;
                    }

                    bool wired = string.Equals(shape.OnAction, ExpControls.CommandName, StringComparison.Ordinal);
                    if (wired)
                    {
                        onActionOk++;
                    }

                    // 标题没写上的话，现场会留下「复选框 5」这类 Excel 默认名——肉眼才看得出的毛病，
                    // 这里按「等于我们传进去的标题」判定，而不是只判非空。
                    string caption = ReadCaption(shape);
                    if (name != "DpExpItem")
                    {
                        if (caption == ExpectedCaption(name))
                        {
                            captionOk++;
                        }
                        else
                        {
                            detail.Append("  !! ").Append(name).Append(" caption='").Append(caption).Append("'\n");
                        }
                    }

                    detail.Append("  ").Append(name)
                        .Append(" row=").Append(row)
                        .Append(expected == row ? "" : " EXPECTED " + expected)
                        .Append(wired ? "" : " ONACTION='" + shape.OnAction + "'")
                        .Append('\n');
                }

                int expectedTotal = 1 + 5 + 9 + 1;
                return "SELFCHECK v" + AddInVersion.Value
                    + " controls=" + created + "/" + expectedTotal
                    + " landed=" + landedOk + "/" + expectedTotal
                    + " onaction=" + onActionOk + "/" + expectedTotal
                    + " captions=" + captionOk + "/15"
                    + "\n" + detail;
            }
            catch (Exception ex)
            {
                return "SELFCHECK FAILED: " + ex.Message;
            }
            finally
            {
                if (probe != null)
                {
                    probe.Close(false);
                }

                app.DisplayAlerts = alerts;
            }
        }

        /// <summary>面板各控件应落的行（与 ExpControls 的锚定常量一一对应）。</summary>
        private static int ExpectedRow(string name)
        {
            if (name == "DpExpItem" || name == "DpExpApply")
            {
                return 35;
            }

            if (name.StartsWith("DpExpLimit", StringComparison.Ordinal))
            {
                return 36 + ParseSuffix(name);
            }

            if (name.StartsWith("DpExpPct", StringComparison.Ordinal))
            {
                return 43 + ParseSuffix(name);
            }

            return -1;
        }

        private static string ReadCaption(Excel.Shape shape)
        {
            try
            {
                Excel.TextFrame frame = shape.TextFrame;
                try
                {
                    Excel.Characters characters = frame.Characters(System.Type.Missing, System.Type.Missing);
                    try
                    {
                        return Convert.ToString(characters.Text, CultureInfo.InvariantCulture);
                    }
                    finally
                    {
                        ExcelInterop.Release(characters);
                    }
                }
                finally
                {
                    ExcelInterop.Release(frame);
                }
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static string ExpectedCaption(string name)
        {
            if (name == "DpExpApply")
            {
                return "应用";
            }

            string[] limits = { "Data Range", "RowDataLimit", "CustomLimit", "3 Sigma", "6 Sigma" };
            string[] percents = { "All Site", "Site1", "Site2", "Site3", "Site4", "Site5", "Site6", "Site7", "Site8" };

            if (name.StartsWith("DpExpLimit", StringComparison.Ordinal))
            {
                int i = ParseSuffix(name);
                return i >= 0 && i < limits.Length ? limits[i] : null;
            }

            if (name.StartsWith("DpExpPct", StringComparison.Ordinal))
            {
                int i = ParseSuffix(name);
                return i >= 0 && i < percents.Length ? percents[i] : null;
            }

            return null;
        }

        private static int ParseSuffix(string name)
        {
            int end = name.Length;
            int start = end;
            while (start > 0 && char.IsDigit(name[start - 1]))
            {
                start--;
            }

            int value;
            return start < end && int.TryParse(name.Substring(start), out value) ? value : -1;
        }

        private static double[] RowTops(Excel.Worksheet sheet)
        {
            var tops = new double[PanelLastRow + 2];
            for (int r = 1; r <= PanelLastRow + 1; r++)
            {
                Excel.Range cell = (Excel.Range)sheet.Cells[r, 1];
                try
                {
                    tops[r] = cell.Top;
                }
                finally
                {
                    ExcelInterop.Release(cell);
                }
            }

            return tops;
        }

        /// <summary>
        /// 端到端自检：打开真实 datalog → 跑生产路径 <see cref="ProcessRunner.Run"/> →
        /// 回报「Exp 面板建了几个控件、分布公式是否已指向本簿、All Site 计数合计是否非零、
        /// 换测试项后标题是否跟着变」。
        ///
        /// 这条是「图表没有柱子」那类问题的回归闸门：它验的是落进工作簿的真实公式与真实计数，
        /// 不是控件建出来了没有。传入一个**副本** csv 路径即可，全程不保存。
        /// </summary>
        [ExcelFunction(IsHidden = true, Description = "加载项端到端自检：真实 datalog 跑一遍处理链")]
        public static string DpSelfCheckFlow(string csvPath)
        {
            Excel.Application app = ExcelInterop.Application;
            bool alerts = app.DisplayAlerts;
            Excel.Workbook wb = null;

            try
            {
                if (string.IsNullOrEmpty(csvPath) || !System.IO.File.Exists(csvPath))
                {
                    return "FLOW FAILED: 文件不存在：" + csvPath;
                }

                app.DisplayAlerts = false;
                wb = app.Workbooks.Open(csvPath);
                Excel.Worksheet sheet = (Excel.Worksheet)wb.ActiveSheet;
                sheet.Name = "Data";                       // Exp 的公式全按 Data! 引用

                ProcessRunner.Run(app, wb, sheet, new ProcessConfig
                {
                    EnableAutoDataDistribution = true,
                    EnableAutoFreeze = false,
                    EnableAutoHideColumns = false,
                    EnableAutoCopyMarkedFile = false,
                });

                Excel.Worksheet exp = ExcelInterop.FindSheet(wb, ExpTemplate.SheetName);
                if (exp == null)
                {
                    return "FLOW FAILED: 处理链跑完仍没有 Exp 表。";
                }

                app.Calculate();

                int panelCount = CountPanel(exp);
                string e3 = Convert.ToString(exp.Range["E3"].Formula, CultureInfo.InvariantCulture);
                double allSiteSum = SumRange(exp.Range["E4:E26"]);
                string caption1 = Convert.ToString(exp.Range["B43"].Value2, CultureInfo.InvariantCulture);

                // 换到第二个测试项：模拟用户改下拉后点控件，标题与计数都应跟着走。
                string caption2 = SwitchToSecondItem(app, exp);
                double allSiteSum2 = -1;
                if (caption2 != null)
                {
                    allSiteSum2 = SumRange(exp.Range["E4:E26"]);
                    caption2 = Convert.ToString(exp.Range["B43"].Value2, CultureInfo.InvariantCulture);
                }

                return "FLOW tester=" + ProcessSession.Spec.TesterName
                    + " items=" + ProcessSession.Items.Count
                    + " panel=" + panelCount + "/16"
                    + " allSiteSum=" + allSiteSum.ToString("0.###", CultureInfo.InvariantCulture)
                    + " e3RefData=" + (e3.Contains("Data!") && !e3.Contains("[1]Data!") ? "yes" : "NO -> " + e3)
                    + " caption=" + caption1
                    + " afterSwitch=" + (caption2 ?? "skipped")
                    + " allSiteSum2=" + allSiteSum2.ToString("0.###", CultureInfo.InvariantCulture);
            }
            catch (Exception ex)
            {
                return "FLOW FAILED: " + ex.Message;
            }
            finally
            {
                if (wb != null)
                {
                    wb.Close(false);
                }

                app.DisplayAlerts = alerts;
            }
        }

        private static string SwitchToSecondItem(Excel.Application app, Excel.Worksheet exp)
        {
            Excel.Shapes shapes = exp.Shapes;
            for (int i = 1; i <= shapes.Count; i++)
            {
                Excel.Shape shape = shapes.Item(i);
                if (!string.Equals(shape.Name, "DpExpItem", StringComparison.Ordinal))
                {
                    continue;
                }

                Excel.ControlFormat format = shape.ControlFormat;
                try
                {
                    if (format.ListCount < 2)
                    {
                        return null;
                    }

                    format.Value = 2;
                }
                finally
                {
                    ExcelInterop.Release(format);
                }

                ExpCommands.DpExpRefresh();
                app.Calculate();
                return string.Empty;
            }

            return null;
        }

        private static int CountPanel(Excel.Worksheet exp)
        {
            int count = 0;
            Excel.Shapes shapes = exp.Shapes;
            for (int i = 1; i <= shapes.Count; i++)
            {
                Excel.Shape shape = shapes.Item(i);
                string name = shape == null ? null : shape.Name;
                if (name != null && name.StartsWith("DpExp", StringComparison.Ordinal))
                {
                    count++;
                }
            }

            return count;
        }

        private static double SumRange(Excel.Range range)
        {
            object raw = range.Value2;
            var array = raw as Array;
            if (array == null)
            {
                return raw == null ? 0 : Convert.ToDouble(raw, CultureInfo.InvariantCulture);
            }

            double sum = 0;
            foreach (object value in array)
            {
                if (value != null)
                {
                    sum += Convert.ToDouble(value, CultureInfo.InvariantCulture);
                }
            }

            return sum;
        }

        /// <summary>
        /// 控件落在第几行。<c>AddFormControl</c> 只接受整数坐标，而 Exp 行高 10.2pt 带小数，
        /// 所以落点与目标行边界之间必然存在 ≤1pt 的取整误差——给 1.5pt 容差。
        /// 真正的错位（旧版按 15pt 硬算偏了 18 行）远大于这个量级，不会被容掉。
        /// </summary>
        private static int LandingRow(double[] tops, double top)
        {
            for (int r = PanelLastRow; r >= 1; r--)
            {
                if (tops[r] <= top + 1.5)
                {
                    return r;
                }
            }

            return 0;
        }
    }
}
