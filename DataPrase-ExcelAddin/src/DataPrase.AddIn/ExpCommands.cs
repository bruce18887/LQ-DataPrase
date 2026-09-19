using System;
using System.Collections.Generic;
using ExcelDna.Integration;
using DataPrase.Core;
using Excel = Microsoft.Office.Interop.Excel;

namespace DataPrase.AddIn
{
    /// <summary>
    /// Exp 表上 Form Control 的 OnAction 目标：Excel-DNA 的**宏命令**——不需要任何工作簿 VBA，
    /// 正好补上「ActiveX 的事件必须活在工作簿 VBA 工程里」这个加载项跨不过的坎。
    ///
    /// 点任意控件都会调到这里：读回全部控件状态 → 写 B36 / N1:V1 → 重算分布表。
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

            if (exp == null || !ProcessSession.HasResult)
            {
                return;
            }

            int dropdownIndex;
            int limitSelector;
            bool[] toggles;
            if (!ExpControls.TryRead(exp, out dropdownIndex, out limitSelector, out toggles))
            {
                return;
            }

            IList<int> columns = ProcessRunner.SortedDataColumns(ProcessSession.Items);
            if (columns.Count == 0)
            {
                return;
            }

            int index = dropdownIndex < 0 ? 0 : (dropdownIndex >= columns.Count ? columns.Count - 1 : dropdownIndex);
            int column = columns[index];

            using (new ExcelStateGuard(app))
            {
                ProcessRunner.WriteLimitSelector(exp, limitSelector);
                ProcessRunner.WritePercentToggles(exp, toggles);
                ProcessRunner.WriteExpDistribution(
                    exp, workbook, ProcessSession.Layout, ProcessSession.Plan, ProcessSession.Spec, column);
            }
        }
    }
}
