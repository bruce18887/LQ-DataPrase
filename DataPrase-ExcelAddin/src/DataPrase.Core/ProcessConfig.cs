namespace DataPrase.Core
{
    /// <summary>处理选项（对应 VBA 的 ConfigInfo / UserForm1 上的勾选项）。</summary>
    public sealed class ProcessConfig
    {
        public bool EnableAutoDataDistribution { get; set; }

        public bool EnableAutoFreeze { get; set; }

        public bool EnableAutoFilter { get; set; }

        public bool EnableAutoHideColumns { get; set; }

        public bool EnableAutoCopyMarkedFile { get; set; }
    }
}
