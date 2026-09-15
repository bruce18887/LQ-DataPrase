namespace DataPrase.Core
{
    /// <summary>
    /// datalog 行/列标定（移植自 VBA DataParser.TestDataRowCalibration 的扫描段）。
    ///
    /// 与 VBA 的**唯一有意偏离**：列头行（Test Name / Serial_No / …）的选取。VBA 取第一列
    /// 最后一次匹配，而真实 ETS88 datalog 里有两行 "Test Name"——第 8 行的设备名行只占 2 段，
    /// 真正的列头行有上千段。这里改为在全部候选中取**非空单元格最多**的一行（并列取靠后者，
    /// 与 VBA 的「后者覆盖」一致），据此定位列头。
    /// </summary>
    public static class DatalogLayout
    {
        /// <summary>未找到列头行时的占位行号。</summary>
        public const int NotFound = 0;

        public static LayoutResult Compute(TesterSpec spec, int testerIndex, ICellReader sheet, bool reCalibrate)
        {
            var result = new LayoutResult { TesterIndex = testerIndex };

            int headerRow = FindHeaderRow(spec, sheet);
            if (headerRow == NotFound)
            {
                return result;
            }

            result.TestNameRow = headerRow;
            result.FormulaRow = headerRow + spec.FormulaRowOffset - 1;
            result.DataStartColumn = spec.TestItemStartIndex;
            result.DataStopColumn = FindLastItemColumn(sheet, headerRow, spec.TestItemStartIndex);

            result.DataStartRow = reCalibrate
                ? headerRow + spec.DataRowOffset + 7 - (testerIndex == 0 ? 1 : 0)
                : headerRow + spec.DataRowOffset;

            result.DataStopRow = FindDataStopRow(spec, testerIndex, sheet, result.DataStartRow);
            return result;
        }

        /// <summary>在「第一列等于列头标识」的候选中取最宽的一行；找不到返回 <see cref="NotFound"/>。</summary>
        private static int FindHeaderRow(TesterSpec spec, ICellReader sheet)
        {
            int bestRow = NotFound;
            int bestWidth = -1;

            for (int row = 1; row <= sheet.RowCount; row++)
            {
                if (!VbaString.EqualsPadded(sheet.GetValue(row, 1), spec.TestNameRowIdentifier))
                {
                    continue;
                }

                int width = CountNonBlank(sheet, row);
                if (width >= bestWidth)
                {
                    bestWidth = width;
                    bestRow = row;
                }
            }

            return bestRow;
        }

        private static int CountNonBlank(ICellReader sheet, int row)
        {
            int count = 0;
            for (int column = 1; column <= sheet.ColumnCount; column++)
            {
                if (!VbaString.IsBlank(sheet.GetValue(row, column)))
                {
                    count++;
                }
            }

            return count;
        }

        /// <summary>从起始列向右读到第一个空白单元格，返回其前一列（VBA 口径）。</summary>
        private static int FindLastItemColumn(ICellReader sheet, int headerRow, int startColumn)
        {
            int column = startColumn;
            while (!VbaString.IsBlank(sheet.GetValue(headerRow, column)))
            {
                column++;
            }

            return column - 1;
        }

        /// <summary>
        /// 数据区终止行：非 ETS88 用「连续两行第一列为空白」，ETS88 用第一列出现
        /// "Data Collection Start Date"；命中时取 row-2。未找到返回 0。
        /// </summary>
        private static int FindDataStopRow(TesterSpec spec, int testerIndex, ICellReader sheet, int dataStartRow)
        {
            for (int row = dataStartRow + 1; row <= sheet.RowCount; row++)
            {
                if (testerIndex != 0)
                {
                    if (VbaString.IsBlank(sheet.GetValue(row, 1))
                        && VbaString.IsBlank(sheet.GetValue(row - 1, 1)))
                    {
                        return row - 2;
                    }
                }
                else if (VbaString.EqualsPadded(sheet.GetValue(row, 1), "Data Collection Start Date"))
                {
                    return row - 2;
                }
            }

            return 0;
        }
    }
}
