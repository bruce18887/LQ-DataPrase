using System;
using System.Collections.Generic;
using System.Windows.Forms;
using DataPrase.Core;
using ExcelDna.Integration;
using Excel = Microsoft.Office.Interop.Excel;

namespace DataPrase.AddIn
{
    /// <summary>
    /// Exp 表上 Form Control 的 OnAction 目标：Excel-DNA 的**宏命令**——不需要任何工作簿 VBA，
    /// 正好补上「ActiveX 的事件必须活在工作簿 VBA 工程里」这个加载项跨不过的坎。
    ///
    /// 点任意控件都会调到这里：读回全部控件状态 → 写 B36 / N1:V1 / B43 → 重算分布表。
    /// 走不通的分支一律**说明原因**：本函数由控件点击触发，静默返回等于「点了没反应」，
    /// 用户无从分辨是没生效还是没必要生效。
    /// </summary>
    public static class ExpCommands
    {
        [ExcelCommand]
        public static void DpExpRefresh()
        {
            Excel.Application app = ExcelInterop.Application;
            Excel.Workbook workbook = app.ActiveWorkbook;
            Excel.Worksheet exp = workbook == null
                ? null
                : ExcelInterop.FindSheet(workbook, ExpTemplate.SheetName);

            if (exp == null)
            {
                Notify("当前工作簿里没有 Exp 分布表。\r\n请先执行「处理并标记」。");
                return;
            }

            if (!ProcessSession.HasResult)
            {
                Notify("处理会话已失效——重启过 Excel 或换了工作簿就会这样。\r\n"
                    + "请重新执行「处理并标记」，或点选项卡的「分布表」重建面板。");
                return;
            }

            int dropdownIndex;
            int limitSelector;
            bool[] toggles;
            if (!ExpControls.TryRead(exp, out dropdownIndex, out limitSelector, out toggles))
            {
                Notify("Exp 表上没有控件面板（建到一半失败过）。\r\n点选项卡的「分布表」重建。");
                return;
            }

            IList<int> columns = ProcessRunner.SortedDataColumns(ProcessSession.Items);
            if (columns.Count == 0)
            {
                Notify("没有可用的测试项。");
                return;
            }

            int index = dropdownIndex < 0 ? 0 : (dropdownIndex >= columns.Count ? columns.Count - 1 : dropdownIndex);
            int column = columns[index];

            using (new ExcelStateGuard(app))
            {
                ProcessRunner.WriteLimitSelector(exp, limitSelector);
                ProcessRunner.WritePercentToggles(exp, toggles);
                ProcessRunner.WriteItemCaption(exp, ProcessSession.Items[column].TestName);
                ProcessRunner.WriteExpDistribution(
                    exp, workbook, ProcessSession.Layout, ProcessSession.Plan, ProcessSession.Spec, column);
            }
        }

        private static void Notify(string message)
        {
            // 无头/COM 自动化下（Application.Interactive = false）弹模态框会永久卡住调用方，
            // 自检脚本就是这么被挂住的；非交互场景直接放弃提示。
            if (!ExcelInterop.Application.Interactive)
            {
                return;
            }

            MessageBox.Show(message, "LQ-DataPrase - 分布表控件", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }
}
