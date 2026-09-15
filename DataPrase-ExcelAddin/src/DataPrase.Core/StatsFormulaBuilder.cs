namespace DataPrase.Core
{
    /// <summary>写入 Data 表公式行的公式串（对应 VBA ProcessDataAndMarkFailuresConfigRun 的 formula_*）。</summary>
    public sealed class StatsFormulaSet
    {
        /// <summary>Min，=SUBTOTAL(105, 数据区)（忽略隐藏行）。</summary>
        public string Min { get; internal set; }

        /// <summary>Avg，=SUBTOTAL(101, 数据区)。</summary>
        public string Average { get; internal set; }

        /// <summary>Max，=SUBTOTAL(104, 数据区)。</summary>
        public string Max { get; internal set; }

        /// <summary>Range，=datalog Max - datalog Min（引用原始统计行，非 SUBTOTAL）。</summary>
        public string Range { get; internal set; }

        /// <summary>STD，=SUBTOTAL(108, 数据区)。</summary>
        public string Std { get; internal set; }

        /// <summary>CPK，引用 datalog 的 Mean/STD 与 LSL/HSL。</summary>
        public string Cpk { get; internal set; }
    }

    /// <summary>
    /// 统计公式构建（移植自 VBA，纯字符串、无 Excel 依赖）。
    /// 口径说明：Min/Avg/Max/STD 是对数据列做 SUBTOTAL；Range 与 CPK 引用的是**新插入的
    /// 统计行**（Lower/High/Unit 各 Offset 落在插入点之上，Min/Mean/Max/STD/CPK 各 Offset
    /// 落在插入的统计行上——spec 的偏移表本就按此设计，不是 datalog 自带的统计行）。
    /// </summary>
    public static class StatsFormulaBuilder
    {
        public static StatsFormulaSet BuildDataSheetFormulas(
            string columnLetter, int testNameRow, int dataStartRow, int dataStopRow, TesterSpec spec)
        {
            string lslCell = Cell(columnLetter, testNameRow + spec.LowOffset);
            string hslCell = Cell(columnLetter, testNameRow + spec.HighOffset);
            string minCell = Cell(columnLetter, testNameRow + spec.MinOffset);
            string maxCell = Cell(columnLetter, testNameRow + spec.MaxOffset);
            string meanCell = Cell(columnLetter, testNameRow + spec.MeanOffset);
            string stdCell = Cell(columnLetter, testNameRow + spec.StdOffset);

            string dataRange = Cell(columnLetter, dataStartRow) + ":" + Cell(columnLetter, dataStopRow);

            return new StatsFormulaSet
            {
                Min = "=SUBTOTAL(105," + dataRange + ")",
                Average = "=SUBTOTAL(101," + dataRange + ")",
                Max = "=SUBTOTAL(104," + dataRange + ")",
                Range = "=" + maxCell + "-" + minCell,
                Std = "=SUBTOTAL(108," + dataRange + ")",
                Cpk = "=IF(OR(" + stdCell + "=0,AND(" + lslCell + "=\"\"," + hslCell + "=\"\")),\"\","
                      + "MIN((" + meanCell + "-" + lslCell + ")/3/" + stdCell + ","
                      + "(" + hslCell + "-" + meanCell + ")/3/" + stdCell + "))",
            };
        }

        private static string Cell(string columnLetter, int row)
        {
            return columnLetter + row;
        }
    }
}
