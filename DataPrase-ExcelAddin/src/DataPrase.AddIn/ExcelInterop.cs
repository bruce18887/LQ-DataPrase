using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using DataPrase.Core;
using Excel = Microsoft.Office.Interop.Excel;

namespace DataPrase.AddIn
{
    /// <summary>Excel 互操作辅助。所有对工作簿的读/写都集中在这里，Core 侧保持零 Excel 依赖。</summary>
    internal static class ExcelInterop
    {
        /// <summary>终止行判定需要探到数据末尾之后，因此比 UsedRange 多读几行。</summary>
        private const int RowOverscan = 2;

        /// <summary>批量写色时每个 Range 地址串包含的单元格数上限（避免超出 Excel 地址长度限制）。</summary>
        private const int ColorChunkSize = 30;

        public static Excel.Application Application
        {
            get { return (Excel.Application)ExcelDna.Integration.ExcelDnaUtil.Application; }
        }

        public static Excel.Worksheet FindSheet(Excel.Workbook workbook, string name)
        {
            foreach (Excel.Worksheet sheet in workbook.Worksheets)
            {
                if (string.Equals(sheet.Name, name, StringComparison.OrdinalIgnoreCase))
                {
                    return sheet;
                }
            }

            return null;
        }

        /// <summary>
        /// 把工作表从 (1,1) 起读成 <see cref="ICellReader"/>（一次性批量读，避免逐单元格 interop）。
        /// 行数取 UsedRange 末行 + <see cref="RowOverscan"/>，让「连续空行」终止判定能生效。
        /// </summary>
        public static ICellReader ReadSheet(Excel.Worksheet sheet, out int scannedRows, out int scannedColumns)
        {
            Excel.Range used = sheet.UsedRange;
            object[,] values = null;
            Excel.Range block = null;
            Excel.Range topLeft = null;
            Excel.Range bottomRight = null;

            try
            {
                int lastRow = used.Row + used.Rows.Count - 1 + RowOverscan;
                int lastColumn = used.Column + used.Columns.Count - 1;

                topLeft = (Excel.Range)sheet.Cells[1, 1];
                bottomRight = (Excel.Range)sheet.Cells[lastRow, lastColumn];
                block = sheet.Range[topLeft, bottomRight];

                object raw = block.Value2;
                values = raw as object[,];
                if (values == null)
                {
                    values = new object[1, 1] { { raw } };
                }

                scannedRows = values.GetUpperBound(0) - values.GetLowerBound(0) + 1;
                scannedColumns = values.GetUpperBound(1) - values.GetLowerBound(1) + 1;
                return new ArrayCellReader(values);
            }
            finally
            {
                Release(block);
                Release(bottomRight);
                Release(topLeft);
                Release(used);
            }
        }

        /// <summary>把标记计划写回工作表：失效 Bin 格标红，数据格按压限(44)/越限(3+加粗)着色。</summary>
        public static void ApplyMarks(Excel.Worksheet sheet, MarkPlan plan, int binColumn)
        {
            foreach (int row in plan.FailBinRows)
            {
                Excel.Range cell = (Excel.Range)sheet.Cells[row, binColumn];
                try
                {
                    cell.Interior.ColorIndex = 3;
                }
                finally
                {
                    Release(cell);
                }
            }

            ApplyColorChunks(sheet, plan.Cells.Where(c => c.Mark == CellMark.LimitHit), 44, bold: false);
            ApplyColorChunks(sheet, plan.Cells.Where(c => c.Mark == CellMark.OutOfLimit), 3, bold: true);
        }

        private static void ApplyColorChunks(Excel.Worksheet sheet, IEnumerable<CellMarkTarget> targets, int colorIndex, bool bold)
        {
            // net462 无 LINQ 的 Chunk()，手动分批：地址串过长会超出 Excel 的 Range 地址限制。
            var addresses = new List<string>();

            foreach (CellMarkTarget target in targets)
            {
                addresses.Add(ColumnNames.ToLetter(target.Column) + target.Row);
                if (addresses.Count == ColorChunkSize)
                {
                    PaintAddresses(sheet, addresses, colorIndex, bold);
                    addresses.Clear();
                }
            }

            if (addresses.Count > 0)
            {
                PaintAddresses(sheet, addresses, colorIndex, bold);
            }
        }

        private static void PaintAddresses(Excel.Worksheet sheet, List<string> addresses, int colorIndex, bool bold)
        {
            Excel.Range range = sheet.Range[string.Join(",", addresses)];
            try
            {
                range.Interior.ColorIndex = colorIndex;
                if (bold)
                {
                    range.Font.Bold = true;
                }
            }
            finally
            {
                Release(range);
            }
        }

        public static void Release(object comObject)
        {
            if (comObject == null)
            {
                return;
            }

            try
            {
                if (Marshal.IsComObject(comObject))
                {
                    Marshal.ReleaseComObject(comObject);
                }
            }
            catch (InvalidComObjectException)
            {
            }
        }
    }
}
