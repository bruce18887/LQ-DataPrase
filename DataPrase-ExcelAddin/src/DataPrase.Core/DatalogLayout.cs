namespace DataPrase.Core
{
    /// <summary>
    /// datalog 行/列标定（移植自 VBA DataParser.TestDataRowCalibration 的扫描段）。
    ///
    /// 算法：沿第 1 列自上而下找「Test Name 行」；在其右侧从 TestItemStartIndex 起
    /// 连续读到第一个空白单元格前一列，作为测试项结束列；数据区起始行由
    /// TestNameRow ± DataRowOffset 推出（reCalibrate 时额外 +7，ETS88 再 -1）。
    /// 终止行：非 ETS88 用「连续两行第 1 列为空白」，ETS88 用第 1 列出现
    /// "Data Collection Start Date"；命中时取 row-2。
    /// </summary>
    public static class DatalogLayout
    {
        public static LayoutResult Compute(TesterSpec spec, int testerIndex, ICellReader sheet, bool reCalibrate)
        {
            var result = new LayoutResult { TesterIndex = testerIndex };
            int dataStartRow = 0;

            for (int row = 1; row <= sheet.RowCount; row++)
            {
                object firstColumnValue = sheet.GetValue(row, 1);

                if (VbaString.EqualsPadded(firstColumnValue, spec.TestNameRowIdentifier))
                {
                    result.TestNameRow = row;
                    result.FormulaRow = row + spec.FormulaRowOffset - 1;
                    result.DataStartColumn = spec.TestItemStartIndex;

                    int col = spec.TestItemStartIndex;
                    while (!VbaString.IsBlank(sheet.GetValue(result.TestNameRow, col)))
                    {
                        col++;
                    }

                    result.DataStopColumn = col - 1;

                    if (!reCalibrate)
                    {
                        dataStartRow = row + spec.DataRowOffset;
                    }
                    else
                    {
                        dataStartRow = row + spec.DataRowOffset + 7;
                        if (testerIndex == 0)
                        {
                            dataStartRow--;
                        }
                    }

                    result.DataStartRow = dataStartRow;
                }

                if (dataStartRow != 0 && row > dataStartRow)
                {
                    if (testerIndex != 0)
                    {
                        if (VbaString.IsBlank(sheet.GetValue(row, 1))
                            && VbaString.IsBlank(sheet.GetValue(row - 1, 1)))
                        {
                            result.DataStopRow = row - 2;
                            break;
                        }
                    }
                    else if (VbaString.EqualsPadded(firstColumnValue, "Data Collection Start Date"))
                    {
                        result.DataStopRow = row - 2;
                        break;
                    }
                }
            }

            return result;
        }
    }
}
