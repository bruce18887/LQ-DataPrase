using System;
using System.Collections.Generic;
using System.Globalization;
using System.Windows.Forms;
using DataPrase.Core;
using Excel = Microsoft.Office.Interop.Excel;

namespace DataPrase.AddIn
{
    /// <summary>处理期间关闭屏幕刷新与自动重算，并在 finally 恢复（VBA 版异常时不恢复）。</summary>
    internal sealed class ExcelStateGuard : IDisposable
    {
        private readonly Excel.Application _app;
        private readonly bool _screenUpdating;
        private readonly Excel.XlCalculation _calculation;

        public ExcelStateGuard(Excel.Application app)
        {
            _app = app;
            _screenUpdating = app.ScreenUpdating;
            _calculation = app.Calculation;
            app.ScreenUpdating = false;
            app.Calculation = Excel.XlCalculation.xlCalculationManual;
        }

        public void Dispose()
        {
            _app.ScreenUpdating = _screenUpdating;
            _app.Calculation = _calculation;
        }
    }

    /// <summary>Ribbon 按钮的业务入口。</summary>
    internal static class Actions
    {
        public static void Import()
        {
            Run("导入数据", ImportCore);
        }

        public static void MarkFailures()
        {
            Run("处理并标记", MarkCore);
        }

        public static void GenerateDistribution()
        {
            Run("分布表", DistributionWindow.Show);
        }

        private static void Run(string title, Action action)
        {
            try
            {
                action();
            }
            catch (Exception ex)
            {
                MessageBox.Show(ex.Message, "LQ-DataPrase - " + title, MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        /// <summary>诊断用：识别机台 + 标定 + 读测试项，不做任何修改。</summary>
        private static void ImportCore()
        {
            Excel.Application app = ExcelInterop.Application;
            Excel.Workbook workbook = app.ActiveWorkbook;
            if (workbook == null)
            {
                throw new InvalidOperationException("请先打开数据工作簿。");
            }

            Excel.Worksheet sheet = GetDataSheet(app, workbook);

            using (new ExcelStateGuard(app))
            {
                DataContext context = BuildContext(sheet, reCalibrate: true);

                MessageBox.Show(
                    "识别机台：" + context.Spec.TesterName + "\r\n"
                    + "测试项： " + context.Items.Count + " 个（列 " + context.Layout.DataStartColumn
                    + "–" + context.Layout.DataStopColumn + "）\r\n"
                    + "数据区： 行 " + context.Layout.DataStartRow + "–" + context.Layout.DataStopRow + "\r\n"
                    + "Test Name 行：" + context.Layout.TestNameRow,
                    "LQ-DataPrase - 导入数据");
            }
        }

        private static void MarkCore()
        {
            Excel.Application app = ExcelInterop.Application;
            Excel.Workbook workbook = app.ActiveWorkbook;
            if (workbook == null)
            {
                throw new InvalidOperationException("请先打开数据工作簿。");
            }

            ProcessConfig config;
            using (var dialog = new ConfigDialog())
            {
                if (dialog.ShowDialog() != DialogResult.OK)
                {
                    return;
                }

                config = dialog.ToProcessConfig();
            }

            Excel.Worksheet sheet = GetDataSheet(app, workbook);

            using (new ExcelStateGuard(app))
            {
                string summary = ProcessRunner.Run(app, workbook, sheet, config);
                MessageBox.Show(
                    "处理完成（加载项 v" + AddInVersion.Value + "）。\r\n" + summary,
                    "LQ-DataPrase - 处理并标记");
            }
        }

        /// <summary>
        /// 取要处理的数据表：**不要求预先叫 "Data"**——用当前活动工作表，并改名为 "Data"
        /// （Exp 分布表的公式全部按 <c>Data!</c> 引用，这一步是必需的）。
        /// </summary>
        private static Excel.Worksheet GetDataSheet(Excel.Application app, Excel.Workbook workbook)
        {
            var sheet = app.ActiveSheet as Excel.Worksheet;
            if (sheet == null)
            {
                throw new InvalidOperationException("请先选中要处理的数据工作表。");
            }

            if (!string.Equals(sheet.Name, "Data", StringComparison.OrdinalIgnoreCase))
            {
                Excel.Worksheet conflicting = ExcelInterop.FindSheet(workbook, "Data");
                if (conflicting != null)
                {
                    throw new InvalidOperationException("工作簿已存在名为 \"Data\" 的工作表，请先重命名其中之一。");
                }

                sheet.Name = "Data";
            }

            return sheet;
        }

        private static DataContext BuildContext(Excel.Worksheet sheet, bool reCalibrate)
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
            LayoutResult layout = DatalogLayout.Compute(spec, detection.SpecIndex, reader, reCalibrate);
            IDictionary<int, TestItem> items = TestItemReader.Read(layout, spec, reader);

            return new DataContext
            {
                Reader = reader,
                Spec = spec,
                Layout = layout,
                Items = items,
            };
        }

        private sealed class DataContext
        {
            public ICellReader Reader;
            public TesterSpec Spec;
            public LayoutResult Layout;
            public IDictionary<int, TestItem> Items;
        }
    }
}
