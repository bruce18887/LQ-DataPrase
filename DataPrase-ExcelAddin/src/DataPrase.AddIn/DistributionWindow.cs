using System;
using System.Drawing;
using System.Windows.Forms;
using DataPrase.Core;
using Excel = Microsoft.Office.Interop.Excel;

namespace DataPrase.AddIn
{
    /// <summary>
    /// 分布表面板（还原原 Exp 表上那排常驻控件：1 下拉 + 5 单选 + 9 复选 + 应用）。
    ///
    /// 用无模式浮动窗口实现：Excel-DNA 的 CustomTaskPaneFactory 在本机会「静默失败」——
    /// 不抛异常但面板不显示。窗口归属 Excel 主窗口，切到 Excel 时不会被压到后面。
    /// 窗口跑在 Excel 主线程上，所以「应用」的点击回调可以直接调 Excel COM，无需跨线程编组。
    ///
    /// 万一无模式窗口也没显示出来（Show() 返回成功但窗口不存在），退到本加载项里已被
    /// 证实可用的**模态**路径（配置对话框一直用的就是它）。判断依据是「窗口是否真的可见」
    /// 这个**事实**，不是等异常——因为静默失败根本不抛异常。
    /// </summary>
    internal static class DistributionWindow
    {
        private static Form _form;
        private static ExpPaneControl _control;

        public static void Show()
        {
            Excel.Application app = ExcelInterop.Application;

            if (_form == null || _form.IsDisposed)
            {
                CreateForm();
            }
            else
            {
                _form.Activate();
            }

            Populate(app);
            Present(app);
        }

        /// <summary>在 Excel 线程上准备 Exp 表并读回当前状态，刷新面板。</summary>
        private static void Populate(Excel.Application app)
        {
            if (_control == null)
            {
                return;
            }

            string prepError = null;
            try
            {
                EnsureExpSheet(app);
            }
            catch (Exception ex)
            {
                prepError = "准备 Exp 表失败：" + ex.Message;
            }

            if (!ProcessSession.HasResult)
            {
                _control.Reload(null, 0, null);
            }
            else
            {
                Excel.Worksheet exp = FindExp(app);
                _control.Reload(
                    ProcessSession.Items,
                    exp == null ? 0 : ProcessRunner.ReadLimitSelector(exp),
                    exp == null ? null : ProcessRunner.ReadPercentToggles(exp));
            }

            if (prepError != null)
            {
                _control.SetStatus(prepError);
            }
        }

        /// <summary>Exp 表缺失时补注入（处理时若关掉了「自动生成分布表」就不会有）。</summary>
        private static void EnsureExpSheet(Excel.Application app)
        {
            if (!ProcessSession.HasResult)
            {
                return;
            }

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

        /// <summary>显示窗口：先试无模式；确认没显示出来再退到模态。</summary>
        private static void Present(Excel.Application app)
        {
            IWin32Window owner = OwnerOf(app);

            _form.Show(owner);
            if (_form.Visible)
            {
                return;
            }

            // 事实性兜底：Show() 没抛错但窗口没出来。重建后用模态路径。
            DisposeForm();
            CreateForm();
            Populate(app);
            _control.SetStatus("无模式窗口未能显示，已改用模态对话框（关闭后重新点「分布表」）。");
            _form.ShowDialog(owner);
            DisposeForm();
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
        }

        private static void DisposeForm()
        {
            if (_form != null && !_form.IsDisposed)
            {
                _form.Dispose();
            }

            _form = null;
            _control = null;
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
                    if (_control != null)
                    {
                        _control.SetStatus("未找到 Exp 表，请先执行「处理并标记」。");
                    }

                    return;
                }

                using (new ExcelStateGuard(app))
                {
                    ProcessRunner.WriteLimitSelector(exp, limitSelector);
                    ProcessRunner.WritePercentToggles(exp, toggles);
                    ProcessRunner.WriteExpDistribution(
                        exp, workbook, ProcessSession.Layout, ProcessSession.Plan, ProcessSession.Spec, column);
                }

                if (_control != null)
                {
                    _control.SetStatus("已更新（列 " + column + "，阶梯基准 B36=" + limitSelector + "）。");
                }
            }
            catch (Exception ex)
            {
                if (_control != null)
                {
                    _control.SetStatus("失败：" + ex.Message);
                }
            }
        }

        private static Excel.Worksheet FindExp(Excel.Application app)
        {
            Excel.Workbook workbook = app.ActiveWorkbook;
            return workbook == null ? null : ExcelInterop.FindSheet(workbook, ExpTemplate.SheetName);
        }

        private static IWin32Window OwnerOf(Excel.Application app)
        {
            try
            {
                int hwnd = app.Hwnd;
                return hwnd == 0 ? null : new WindowWrapper(new IntPtr(hwnd));
            }
            catch
            {
                return null;
            }
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
