using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using DataPrase.Core;
using Excel = Microsoft.Office.Interop.Excel;

namespace DataPrase.AddIn
{
    /// <summary>
    /// 工作簿处理执行器（移植自 VBA DataParser.ProcessDataAndMarkFailuresConfigRun 的行/列部分）。
    /// ⚠️ 这是**破坏性**操作：会删行、插行、写公式、改窗口状态——请务必在副本上验证。
    /// 数据分布表（Exp）与另存副本留待后续批次。
    /// </summary>
    internal static class ProcessRunner
    {
        public static string Run(Excel.Application app, Excel.Workbook workbook, Excel.Worksheet sheet, ProcessConfig config)
        {
            int rows;
            int columns;
            ICellReader reader = ExcelInterop.ReadSheet(sheet, out rows, out columns);

            TesterDetection detection = TesterDetector.Detect(reader);
            if (!detection.IsDetected)
            {
                throw new InvalidOperationException(detection.Message);
            }

            TesterSpec spec = TesterRegistry.Specs[detection.SpecIndex];
            LayoutResult layout = DatalogLayout.Compute(spec, detection.SpecIndex, reader, reCalibrate: false);
            if (layout.DataStopRow == DatalogLayout.NotFound)
            {
                throw new InvalidOperationException("未能标定数据区结束行，请检查 datalog 格式。");
            }

            ProcessPlan plan = ProcessPlanner.Build(spec, detection.SpecIndex, layout, reader);
            IDictionary<int, TestItem> items = TestItemReader.Read(layout, spec, reader);

            DeleteEmptyRows(sheet, plan);
            InsertFormulaRows(sheet, plan);
            WriteStatFormulas(sheet, spec, layout, plan);
            MarkFailures(sheet, spec, layout, plan, items);

            // 行号到此已定型，先记录上下文——后面的都是可选步骤，任一失败都不该让「分布表」失效。
            ProcessSession.Record(workbook.Name, sheet.Name, spec, layout, plan, items);

            var warnings = new List<string>();
            var summary = new StringBuilder("识别机台：" + spec.TesterName);

            // 只读工作簿：隐藏列与另存副本都做不了，直接说明原因，别丢一个 COM 错误给用户。
            if (workbook.ReadOnly)
            {
                warnings.Add("工作簿以只读方式打开：隐藏列与另存副本已跳过（请以可写方式打开后重跑）。");
            }

            // 先隐藏列再冻结：避免「冻结窗格后隐藏冻结区内列」这类交互（VBA 是反序，但结果等价）。
            if (config.EnableAutoHideColumns && !workbook.ReadOnly)
            {
                Append(summary, warnings, "隐藏列", () => HideColumns(sheet, plan), "已隐藏无关列");
            }

            if (config.EnableAutoFreeze)
            {
                Append(summary, warnings, "冻结窗格", () => FreezePanes(app, sheet, layout, plan), "已冻结窗格");
            }

            if (config.EnableAutoCopyMarkedFile && !workbook.ReadOnly)
            {
                try
                {
                    string saved = SaveMarkedCopy(workbook);
                    ProcessSession.UpdateWorkbookName(workbook.Name);   // SaveAs 后活动工作簿已换名
                    summary.Append("\r\n已另存副本：").Append(saved);
                }
                catch (Exception ex)
                {
                    warnings.Add("另存副本失败：" + ex.Message);
                }
            }

            if (config.EnableAutoDataDistribution)
            {
                Append(summary, warnings, "复制 Exp 分布表", () =>
                {
                    Excel.Worksheet exp = ExpTemplate.Inject(app, workbook);
                    // 模板里的公式全部指向外部工作簿（[1]Data!…），不填就是一张 #REF! 表；
                    // 这里直接按第一个测试项填好，用户之后可用「分布表」换项。
                    WriteExpDistribution(exp, workbook, layout, plan, spec, FirstDataColumn(items));
                }, "已复制并填充 Exp 分布表（第一个测试项）");
            }

            foreach (string warning in warnings)
            {
                summary.Append("\r\n⚠ ").Append(warning);
            }

            return summary.ToString();
        }

        /// <summary>执行一个可选步骤：失败只记警告，不中断整体处理。</summary>
        private static void Append(StringBuilder summary, IList<string> warnings, string label, Action action, string okText)
        {
            try
            {
                action();
                summary.Append("\r\n").Append(okText);
            }
            catch (Exception ex)
            {
                warnings.Add(label + "失败：" + ex.Message);
            }
        }

        /// <summary>把当前（已标记的）工作簿另存为同目录的 &lt;原名&gt;Copy.xlsx；原文件保持未修改。</summary>
        private static string SaveMarkedCopy(Excel.Workbook workbook)
        {
            string fullName = workbook.FullName;
            string folder = Path.GetDirectoryName(fullName);
            string target = Path.Combine(
                folder ?? string.Empty,
                Path.GetFileNameWithoutExtension(fullName) + "Copy.xlsx");

            workbook.SaveAs(target, Excel.XlFileFormat.xlOpenXMLWorkbook);
            return target;
        }

        private static void DeleteEmptyRows(Excel.Worksheet sheet, ProcessPlan plan)
        {
            foreach (int row in plan.EmptyRowsToDelete)   // 已按降序排列
            {
                Excel.Range entireRow = SheetRange(sheet, "A" + row).EntireRow;
                try
                {
                    entireRow.Delete(Excel.XlDeleteShiftDirection.xlShiftUp);
                }
                finally
                {
                    ExcelInterop.Release(entireRow);
                }
            }
        }

        private static void InsertFormulaRows(Excel.Worksheet sheet, ProcessPlan plan)
        {
            for (int i = 0; i < plan.InsertCount; i++)
            {
                Excel.Range entireRow = SheetRange(sheet, "A" + plan.InsertRow).EntireRow;
                try
                {
                    entireRow.Insert(
                        Excel.XlInsertShiftDirection.xlShiftDown,
                        Excel.XlInsertFormatOrigin.xlFormatFromLeftOrAbove);
                }
                finally
                {
                    ExcelInterop.Release(entireRow);
                }
            }
        }

        /// <summary>写入统计标签（第一列）与 6 个 SUBTOTAL/Range/CPK 公式（跨测试项列，Excel 自动按列调整）。</summary>
        private static void WriteStatFormulas(Excel.Worksheet sheet, TesterSpec spec, LayoutResult layout, ProcessPlan plan)
        {
            string columnLetter = ColumnNames.ToLetter(layout.DataStartColumn);
            StatsFormulaSet formulas = StatsFormulaBuilder.BuildDataSheetFormulas(
                columnLetter, layout.TestNameRow, plan.DataStartRow, plan.DataStopRow, spec);

            string[] rowFormulas = { formulas.Min, formulas.Average, formulas.Max, formulas.Range, formulas.Std, formulas.Cpk };

            for (int i = 0; i < plan.StatLabels.Count; i++)
            {
                int row = plan.FormulaTopRow + 1 + i;

                Excel.Range label = (Excel.Range)sheet.Cells[row, 1];
                try
                {
                    label.Value2 = plan.StatLabels[i];
                }
                finally
                {
                    ExcelInterop.Release(label);
                }

                Excel.Range first = (Excel.Range)sheet.Cells[row, layout.DataStartColumn];
                Excel.Range last = (Excel.Range)sheet.Cells[row, layout.DataStopColumn];
                Excel.Range span = sheet.Range[first, last];
                try
                {
                    span.Formula = rowFormulas[i];
                }
                finally
                {
                    ExcelInterop.Release(span);
                    ExcelInterop.Release(last);
                    ExcelInterop.Release(first);
                }
            }
        }

        private static void MarkFailures(
            Excel.Worksheet sheet,
            TesterSpec spec,
            LayoutResult layout,
            ProcessPlan plan,
            IDictionary<int, TestItem> items)
        {
            // 插行/删行后行号已变（ETS88 删空行造成非均匀偏移）→ 重新读表，按平移后的行号标记。
            int rows;
            int columns;
            ICellReader fresh = ExcelInterop.ReadSheet(sheet, out rows, out columns);

            LayoutResult shifted = layout.WithDataRows(plan.DataStartRow, plan.DataStopRow);
            MarkPlan markPlan = MarkPlanner.Build(shifted, spec, items, fresh);
            ExcelInterop.ApplyMarks(sheet, markPlan, ColumnNames.ToNumber(spec.BinColumn));
        }

        private static void FreezePanes(Excel.Application app, Excel.Worksheet sheet, LayoutResult layout, ProcessPlan plan)
        {
            Excel.Window window = app.ActiveWindow;
            sheet.Activate();
            window.ScrollRow = layout.TestNameRow;

            Excel.Range anchor = (Excel.Range)sheet.Cells[plan.DataStartRow, layout.DataStartColumn];
            try
            {
                anchor.Select();
                window.FreezePanes = true;
            }
            finally
            {
                ExcelInterop.Release(anchor);
            }
        }

        private static void HideColumns(Excel.Worksheet sheet, ProcessPlan plan)
        {
            if (sheet.ProtectContents)
            {
                throw new InvalidOperationException("工作表处于受保护状态，无法隐藏列。");
            }

            if (plan.HiddenColumns.Count == 0)
            {
                return;
            }

            foreach (int column in plan.HiddenColumns)
            {
                string letter = ColumnNames.ToLetter(column);
                Excel.Range columnRange = sheet.Range[letter + ":" + letter];
                Excel.Range entireColumn = null;

                try
                {
                    // Range.Hidden 只在「整列/整行」范围内有效；显式取 EntireColumn 与 VBA 的
                    // Columns("B").Hidden 完全等价。
                    entireColumn = columnRange.EntireColumn;
                    entireColumn.Hidden = true;
                }
                catch (COMException ex)
                {
                    throw new InvalidOperationException(
                        "隐藏 " + letter + " 列失败（" + ex.Message + "）。", ex);
                }
                finally
                {
                    ExcelInterop.Release(entireColumn);
                    ExcelInterop.Release(columnRange);
                }
            }
        }

        /// <summary>把 Exp 分布表按指定测试项列填好（Actions 的「分布表」按钮与自动填充共用）。</summary>
        internal static void WriteExpDistribution(
            Excel.Worksheet exp, Excel.Workbook workbook, LayoutResult layout, ProcessPlan plan, TesterSpec spec, int column)
        {
            IList<FormulaWrite> writes = DistributionFormulaBuilder.Build(
                ColumnNames.ToLetter(column),
                layout.TestNameRow,
                plan.DataStartRow,
                plan.DataStopRow,
                ReadLimitSelector(exp),
                spec);

            foreach (FormulaWrite write in writes)
            {
                Excel.Range range = exp.Range[write.Address];
                try
                {
                    range.Formula = write.Formula;
                }
                finally
                {
                    ExcelInterop.Release(range);
                }
            }

            // 覆盖后仍在的其他外部引用（模板残留）会显示 #REF!，直接断开链接。
            BreakExternalLinks(workbook);
        }

        internal static int FirstDataColumn(IDictionary<int, TestItem> items)
        {
            int first = int.MaxValue;
            foreach (int column in items.Keys)
            {
                if (column < first)
                {
                    first = column;
                }
            }

            return first == int.MaxValue ? 0 : first;
        }

        internal static int ReadLimitSelector(Excel.Worksheet exp)
        {
            Excel.Range cell = (Excel.Range)exp.Cells[DistributionFormulaBuilder.LimitBaseRow, 2];   // B36
            try
            {
                object value = cell.Value2;
                double parsed = 0;
                bool ok = value != null && double.TryParse(
                    Convert.ToString(value, CultureInfo.InvariantCulture),
                    NumberStyles.Float, CultureInfo.InvariantCulture, out parsed);
                return ok ? (int)parsed : 0;
            }
            finally
            {
                ExcelInterop.Release(cell);
            }
        }

        internal static void BreakExternalLinks(Excel.Workbook workbook)
        {
            var links = workbook.LinkSources(Excel.XlLink.xlExcelLinks) as Array;
            if (links == null)
            {
                return;
            }

            foreach (object link in links)
            {
                workbook.BreakLink((string)link, Excel.XlLinkType.xlLinkTypeExcelLinks);
            }
        }

        private static Excel.Range SheetRange(Excel.Worksheet sheet, string address)
        {
            return sheet.Range[address];
        }
    }
}
