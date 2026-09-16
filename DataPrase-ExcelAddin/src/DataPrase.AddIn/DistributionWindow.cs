using System;
using System.Drawing;
using System.Windows.Forms;
using DataPrase.Core;
using Excel = Microsoft.Office.Interop.Excel;

namespace DataPrase.AddIn
{
    /// <summary>
    /// 分布表面板窗口（还原原 Exp 表上常驻的一排控件）。
    ///
    /// 用**无模式浮动窗口**而不是任务窗格：Excel-DNA 的 CustomTaskPaneFactory 在本机
    /// Excel 上会「静默失败」——CreateCustomTaskPane 不抛异常但面板不显示，导致任何
    /// based-on-exception 的兜底都失效。WinForms 窗口在本加载项里已被证实可用
    /// （配置对话框能正常弹出），所以走这条确定能成的路。
    /// 窗口归属 Excel 主窗口，切到 Excel 时不会被压到后面。
    /// </summary>
    internal static class DistributionWindow
    {
        private static Form _form;
        private static ExpPaneControl _control;

        public static void Show()
        {
            if (_form == null || _form.IsDisposed)
            {
                CreateForm();
            }
            else
            {
                _form.Activate();
            }

            try
            {
                EnsureExpSheet();
            }
            catch (Exception ex)
            {
                _control.SetStatus("准备 Exp 表失败：" + ex.Message);
                return;
            }

            Reload();
        }

        /// <summary>Exp 表缺失时补注入（处理时若关掉了「自动生成分布表」就不会有）。</summary>
        private static void EnsureExpSheet()
        {
            if (!ProcessSession.HasResult)
            {
                return;
            }

            Excel.Application app = ExcelInterop.Application;
            Excel.Workbook workbook = app.ActiveWorkbook;
            if (workbook == null || ExcelInterop.FindSheet(workbook, ExpTemplate.SheetName) != null)
            {
                return;
            }

            using (new ExcelStateGuard(app))
            {
                ExpTemplate.Inject(app, workbook);
            }
        }

        private static void CreateForm()
        {
            _control = new ExpPaneControl();
            _control.Applied += OnApplied;

            _form = new Form
            {
                Text = "DataPrase 分布表",
                ClientSize = new Size(330, 470),
                FormBorderStyle = FormBorderStyle.SizableToolWindow,
                StartPosition = FormStartPosition.Manual,
                ShowInTaskbar = false,
                MinimizeBox = false,
                MaximizeBox = false,
            };

            Rectangle work = Screen.PrimaryScreen.WorkingArea;
            _form.Location = new Point(work.Right - _form.Width - 24, work.Top + 120);

            _form.Controls.Add(_control);
            _form.FormClosed += (s, e) =>
            {
                _form = null;
                _control = null;
            };

            Excel.Application app = ExcelInterop.Application;
            _form.Show(new WindowWrapper(new IntPtr(app.Hwnd)));
        }

        private static void Reload()
        {
            if (_control == null)
            {
                return;
            }

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

        /// <summary>把 Excel 主窗口句柄包成 IWin32Window，作为浮动窗口的宿主。</summary>
        private sealed class WindowWrapper : IWin32Window
        {
            public WindowWrapper(IntPtr handle)
            {
                Handle = handle;
            }

            public IntPtr Handle { get; private set; }
        }
    }
}
