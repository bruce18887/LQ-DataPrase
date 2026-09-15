namespace DataPrase.Core
{
    /// <summary>
    /// 某台测试机 datalog 的行/列偏移配置（对应 VBA 的 TesterDataInfo）。
    /// 命名沿用 VBA 的 Offset 语义：相对「Test Name 行」的行号增量，或「数据区」的列增量。
    /// </summary>
    public sealed class TesterSpec
    {
        public string TesterName { get; set; }

        /// <summary>用于识别机台的首格标记。VBA 里 Tester(0) 的标记带尾部空格，
        /// 因 VBA 的 = 比较会给较短串补尾空格；C# 侧统一存去尾空格后的规范值，
        /// 匹配时按同样语义处理（见 TesterDetector，批次 2）。</summary>
        public string DatalogIdentifier { get; set; }

        /// <summary>true 表示用「包含」匹配标记（VBA 的 InStr），false 表示整格相等。</summary>
        public bool IdentifierIsSubstring { get; set; }

        /// <summary>Test 行里第一个测试项所在列号（1 起）。</summary>
        public int TestItemStartIndex { get; set; }

        /// <summary>标识「Test Name 行」的值。</summary>
        public string TestNameRowIdentifier { get; set; }

        public int DataRowOffset { get; set; }
        public int FormulaRowOffset { get; set; }
        public int LimitRowOffset { get; set; }
        public int MeanOffset { get; set; }
        public int LowOffset { get; set; }
        public int HighOffset { get; set; }
        public int UnitOffset { get; set; }
        public int MinOffset { get; set; }
        public int MaxOffset { get; set; }
        public int RangeOffset { get; set; }
        public int StdOffset { get; set; }
        public int CpkOffset { get; set; }

        /// <summary>Bin 列，形如 "$C"（含 $ 前缀，沿用 VBA 拼接方式）。</summary>
        public string BinColumn { get; set; }

        /// <summary>Site 列，形如 "$A"。</summary>
        public string SiteColumn { get; set; }
    }
}
