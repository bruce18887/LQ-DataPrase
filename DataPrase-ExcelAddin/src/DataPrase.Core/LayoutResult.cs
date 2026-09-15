namespace DataPrase.Core
{
    /// <summary>datalog 的标定结果（对应 VBA 的 TestNameIndex / TestDataColIndex / TestDataRowIndex）。</summary>
    public sealed class LayoutResult
    {
        public int TesterIndex { get; internal set; }

        /// <summary>「Test Name」所在行号（1 基）。</summary>
        public int TestNameRow { get; internal set; }

        /// <summary>测试项起始列（1 基）。</summary>
        public int DataStartColumn { get; internal set; }

        /// <summary>测试项结束列（1 基）。</summary>
        public int DataStopColumn { get; internal set; }

        /// <summary>数据区起始行（1 基）。</summary>
        public int DataStartRow { get; internal set; }

        /// <summary>数据区结束行（1 基）；未找到终止行时为 0。</summary>
        public int DataStopRow { get; internal set; }

        /// <summary>插入公式行的行号（= TestNameRow + FormulaRowOffset - 1，对应 VBA DataSheetFormulaRow）。</summary>
        public int FormulaRow { get; internal set; }

        /// <summary>
        /// 复制一份并替换数据区行范围：行插入/删除后行号整体平移（ETS88 删空行还会造成非均匀偏移），
        /// 其余标定结果（列区间、Test Name 行）保持不变。
        /// </summary>
        public LayoutResult WithDataRows(int startRow, int stopRow)
        {
            return new LayoutResult
            {
                TesterIndex = TesterIndex,
                TestNameRow = TestNameRow,
                DataStartColumn = DataStartColumn,
                DataStopColumn = DataStopColumn,
                DataStartRow = startRow,
                DataStopRow = stopRow,
                FormulaRow = FormulaRow,
            };
        }
    }
}
