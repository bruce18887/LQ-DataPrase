using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
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
        public static string Run(Excel.Application app, Excel.Worksheet sheet, ProcessConfig config)
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

            if (config.EnableAutoFreeze)
            {
                FreezePanes(app, sheet, layout, plan);
            }

            if (config.EnableAutoHideColumns)
            {
                HideColumns(sheet, plan);
            }

            if (config.EnableAutoFilter)
            {
                ApplyAutoFilter(app, sheet, plan);
            }

            return spec.TesterName;
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
            foreach (int column in plan.HiddenColumns)
            {
                string letter = ColumnNames.ToLetter(column);
                Excel.Range range = sheet.Range[letter + ":" + letter];
                try
                {
                    range.Hidden = true;
                }
                finally
                {
                    ExcelInterop.Release(range);
                }
            }
        }

        private static void ApplyAutoFilter(Excel.Application app, Excel.Worksheet sheet, ProcessPlan plan)
        {
            // 复刻 VBA：选中数据区上一行后开关 AutoFilter。
            Excel.Range headerRow = SheetRange(sheet, "A" + (plan.DataStartRow - 1)).EntireRow;
            try
            {
                headerRow.Select();
                ((Excel.Range)app.Selection).AutoFilter();
            }
            finally
            {
                ExcelInterop.Release(headerRow);
            }
        }

        private static Excel.Range SheetRange(Excel.Worksheet sheet, string address)
        {
            return sheet.Range[address];
        }
    }
}
