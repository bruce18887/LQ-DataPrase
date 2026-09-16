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

    internal static class AddInVersion
    {
        public const string Value = "0.2.2";
    }
}
