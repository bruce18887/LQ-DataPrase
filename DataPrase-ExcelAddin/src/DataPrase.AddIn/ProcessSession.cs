using System.Collections.Generic;
using DataPrase.Core;

namespace DataPrase.AddIn
{
    /// <summary>
    /// 跨按钮共享的处理上下文（对应 VBA 的模块级全局变量 g_DataWS / g_TesterType /
    /// TestDataRowIndex / Items）。只存名字不存 COM 引用，避免长持有对象；用名字重新解析。
    /// </summary>
    internal static class ProcessSession
    {
        public static string WorkbookName { get; private set; }

        public static string SheetName { get; private set; }

        public static TesterSpec Spec { get; private set; }

        public static LayoutResult Layout { get; private set; }

        public static ProcessPlan Plan { get; private set; }

        public static IDictionary<int, TestItem> Items { get; private set; }

        public static bool HasResult
        {
            get { return Spec != null && Plan != null; }
        }

        public static void Record(
            string workbookName,
            string sheetName,
            TesterSpec spec,
            LayoutResult layout,
            ProcessPlan plan,
            IDictionary<int, TestItem> items)
        {
            WorkbookName = workbookName;
            SheetName = sheetName;
            Spec = spec;
            Layout = layout;
            Plan = plan;
            Items = items;
        }

        public static void Clear()
        {
            WorkbookName = null;
            SheetName = null;
            Spec = null;
            Layout = null;
            Plan = null;
            Items = null;
        }
    }
}
