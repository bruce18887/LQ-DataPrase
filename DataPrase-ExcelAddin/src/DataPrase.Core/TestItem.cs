namespace DataPrase.Core
{
    /// <summary>单个测试项（对应 VBA 的 TestItemInfo）。</summary>
    public sealed class TestItem
    {
        public TestItem(string testName, string unit, double lowLimit, double highLimit)
        {
            TestName = testName;
            Unit = unit;
            LowLimit = lowLimit;
            HighLimit = highLimit;
        }

        public string TestName { get; private set; }

        public string Unit { get; private set; }

        public double LowLimit { get; private set; }

        public double HighLimit { get; private set; }

        /// <summary>
        /// VBA: <c>NoLimit = (Lolimit = Empty And Hilimit = Empty)</c>，而 Lolimit/Hilimit 是
        /// Double，与 Empty 比较等价于与 0 比较 → 双限值都为 0 视为「无限制」。
        /// （限值单元格为空格时 VBA 不赋值，保持默认 0，因此同样落入此分支。）
        /// </summary>
        public bool HasNoLimit
        {
            get { return LowLimit == 0d && HighLimit == 0d; }
        }
    }
}
