using System;
using System.Collections.Generic;
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

    /// <summary>Ribbon 按钮的业务入口。对应 VBA 的 ImportButton_Changed / ProcessDataAndMarkFailuresConfigRun。</summary>
    internal static class Actions
    {
        public static void Import()
        {
            Run("导入数据", ImportCore);
        }

        public static void MarkFailures()
        {
            Run("标记失效", MarkCore);
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

        private static void ImportCore()
        {
            Excel.Application app = ExcelInterop.Application;
            Excel.Worksheet sheet = GetDataSheet(app);

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
            Excel.Worksheet sheet = GetDataSheet(app);

            ProcessConfig config;
            using (var dialog = new ConfigDialog())
            {
                if (dialog.ShowDialog() != DialogResult.OK)
                {
                    return;
                }

                config = dialog.ToProcessConfig();
            }

            using (new ExcelStateGuard(app))
            {
                string testerName = ProcessRunner.Run(app, sheet, config);
                MessageBox.Show(
                    "处理完成。\r\n识别机台：" + testerName,
                    "LQ-DataPrase - 标记失效");
            }
        }

        private static Excel.Worksheet GetDataSheet(Excel.Application app)
        {
            Excel.Workbook workbook = app.ActiveWorkbook;
            if (workbook == null)
            {
                throw new InvalidOperationException("请先打开数据工作簿。");
            }

            Excel.Worksheet sheet = ExcelInterop.FindSheet(workbook, "Data");
            if (sheet == null)
            {
                throw new InvalidOperationException("当前工作簿没有名为 \"Data\" 的工作表。");
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
