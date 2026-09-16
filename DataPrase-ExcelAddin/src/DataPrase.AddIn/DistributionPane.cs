using System;
using DataPrase.Core;
using ExcelDna.Integration.CustomUI;
using Excel = Microsoft.Office.Interop.Excel;

namespace DataPrase.AddIn
{
    /// <summary>
    /// 分布表任务窗格（把原 Exp 表上常驻的控件搬到 Excel 右侧）。
    /// 创建失败（不同 Excel 版本行为差异）时返回 false，由调用方退回模态对话框。
    /// </summary>
    internal static class DistributionPane
    {
        private static CustomTaskPane _pane;
        private static ExpPaneControl _control;

        public static bool TryShow()
        {
            try
            {
                if (_pane == null)
                {
                    _control = new ExpPaneControl();
                    _control.Applied += OnApplied;
                    _pane = CustomTaskPaneFactory.CreateCustomTaskPane(_control, "DataPrase 分布表");
                    _pane.DockPosition = MsoCTPDockPosition.msoCTPDockPositionRight;
                    _pane.Width = 300;
                }

                Reload();
                _pane.Visible = true;
                return true;
            }
            catch (Exception)
            {
                _pane = null;
                _control = null;
                return false;
            }
        }

        private static void Reload()
        {
            if (!ProcessSession.HasResult)
            {
                _control.Reload(null, 0, null);
                return;
            }

            Excel.Worksheet exp = FindExp();
            if (exp == null)
            {
                _control.Reload(ProcessSession.Items, 0, null);
                return;
            }

            _control.Reload(ProcessSession.Items, ProcessRunner.ReadLimitSelector(exp), ProcessRunner.ReadPercentToggles(exp));
        }

        private static void OnApplied(int column, int limitSelector, bool[] toggles)
        {
            try
            {
                Excel.Application app = ExcelInterop.Application;
                Excel.Workbook workbook = app.ActiveWorkbook;
                Excel.Worksheet exp = workbook == null ? null : ExcelInterop.FindSheet(workbook, ExpTemplate.SheetName);
                if (exp == null)
                {
                    _control.SetStatus("未找到 Exp 表，请先执行「处理并标记」。");
                    return;
                }

                using (new ExcelStateGuard(app))
                {
                    ProcessRunner.WriteLimitSelector(exp, limitSelector);
                    ProcessRunner.WritePercentToggles(exp, toggles);
                    ProcessRunner.WriteExpDistribution(
                        exp, workbook, ProcessSession.Layout, ProcessSession.Plan, ProcessSession.Spec, column);
                }

                _control.SetStatus("已更新（列 " + column + "，阶梯基准 B36=" + limitSelector + "）。");
            }
            catch (Exception ex)
            {
                _control.SetStatus("失败：" + ex.Message);
            }
        }

        private static Excel.Worksheet FindExp()
        {
            Excel.Workbook workbook = ExcelInterop.Application.ActiveWorkbook;
            return workbook == null ? null : ExcelInterop.FindSheet(workbook, ExpTemplate.SheetName);
        }
    }
}
