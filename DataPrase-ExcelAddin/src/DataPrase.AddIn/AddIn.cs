using ExcelDna.Integration;

namespace DataPrase.AddIn
{
    /// <summary>加载项生命周期入口（对应 VBA 的 ThisWorkbook/加载时机）。</summary>
    public class AddIn : IExcelAddIn
    {
        public void AutoOpen()
        {
        }

        public void AutoClose()
        {
        }
    }

    /// <summary>冒烟用工作表函数：验证加载项已被 Excel 加载。</summary>
    public static class SmokeFunctions
    {
        [ExcelFunction(Description = "LQ-DataPrase 加载项连通性检查")]
        public static string DpPing()
        {
            return "DataPrase " + AddInVersion.Value;
        }
    }

    /// <summary>
    /// 版本号的唯一事实源是 <c>Properties/AssemblyInfo.cs</c> 的 AssemblyVersion——
    /// 之前这里是另一个手写常量，两处各改各的，导致「文件名、文件属性、运行时字符串」互不印证。
    /// </summary>
    internal static class AddInVersion
    {
        public static readonly string Value =
            typeof(AddIn).Assembly.GetName().Version.ToString(3);
    }
}
