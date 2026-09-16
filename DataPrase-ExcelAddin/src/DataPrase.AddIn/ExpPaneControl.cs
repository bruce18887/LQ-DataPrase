using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;
using DataPrase.Core;

namespace DataPrase.AddIn
{
    /// <summary>
    /// 分布表面板（任务窗格内容）。还原原 Exp 表上的 15 个 ActiveX 控件：
    ///   1 个 ComboBox  -> 测试项
    ///   5 个 OptionButton -> 阶梯基准（标题照原样：Data Range / RowDataLimit / CustomLimit / 3 Sigma / 6 Sigma）
    ///   9 个 CheckBox  -> 百分比列开关（All Site / Site1..Site8，对应 Exp 表 N1:V1）
    /// </summary>
    internal sealed class ExpPaneControl : UserControl
    {
        /// <summary>标题与 B36 取值一一对应（0..4 → 模板第 36..40 行）。</summary>
        private static readonly string[] LimitBaseCaptions =
        {
            "Data Range",
            "RowDataLimit",
            "CustomLimit",
            "3 Sigma",
            "6 Sigma",
        };

        /// <summary>与 Exp 表 N1:V1 同序。</summary>
        private static readonly string[] PercentCaptions =
        {
            "All Site", "Site1", "Site2", "Site3", "Site4", "Site5", "Site6", "Site7", "Site8",
        };

        private readonly ComboBox _itemCombo = new ComboBox();
        private readonly RadioButton[] _limitRadios = new RadioButton[LimitBaseCaptions.Length];
        private readonly CheckBox[] _percentChecks = new CheckBox[PercentCaptions.Length];
        private readonly Label _status = new Label();
        private readonly List<int> _columns = new List<int>();

        /// <summary>点「应用」时回调：(测试项列, B36 值, N1:V1 的 9 个开关)。</summary>
        public event Action<int, int, bool[]> Applied;

        public ExpPaneControl()
        {
            Dock = DockStyle.Fill;
            Padding = new Padding(10);
            AutoScroll = true;

            var layout = new FlowLayoutPanel
            {
                Dock = DockStyle.Fill,
                FlowDirection = FlowDirection.TopDown,
                WrapContents = false,
                AutoScroll = true,
            };

            layout.Controls.Add(Section("测试项"));
            _itemCombo.DropDownStyle = ComboBoxStyle.DropDownList;
            _itemCombo.Width = 240;
            layout.Controls.Add(_itemCombo);

            layout.Controls.Add(Section("阶梯基准"));
            for (int i = 0; i < LimitBaseCaptions.Length; i++)
            {
                var radio = new RadioButton { Text = LimitBaseCaptions[i], AutoSize = true, Margin = new Padding(3, 2, 3, 2) };
                _limitRadios[i] = radio;
                layout.Controls.Add(radio);
            }

            layout.Controls.Add(Section("百分比列"));
            for (int i = 0; i < PercentCaptions.Length; i++)
            {
                var check = new CheckBox { Text = PercentCaptions[i], AutoSize = true, Checked = true, Margin = new Padding(3, 2, 3, 2) };
                _percentChecks[i] = check;
                layout.Controls.Add(check);
            }

            var apply = new Button { Text = "应用", Width = 100, Margin = new Padding(3, 12, 3, 3) };
            apply.Click += (s, e) => RaiseApplied();
            layout.Controls.Add(apply);

            _status.AutoSize = true;
            _status.ForeColor = Color.DimGray;
            _status.Margin = new Padding(3, 8, 3, 3);
            layout.Controls.Add(_status);

            Controls.Add(layout);
        }

        /// <summary>按当前 Exp 表状态刷新面板（未知状态传 null 表示保持默认）。</summary>
        public void Reload(IDictionary<int, TestItem> items, int currentLimitSelector, bool[] currentToggles)
        {
            _columns.Clear();
            _itemCombo.Items.Clear();

            if (items != null)
            {
                var keys = new List<int>(items.Keys);
                keys.Sort();
                foreach (int column in keys)
                {
                    _columns.Add(column);
                    _itemCombo.Items.Add(items[column].TestName);
                }
            }

            if (_itemCombo.Items.Count > 0)
            {
                _itemCombo.SelectedIndex = 0;
            }

            int limit = (currentLimitSelector >= 0 && currentLimitSelector < _limitRadios.Length)
                ? currentLimitSelector
                : 0;
            _limitRadios[limit].Checked = true;

            for (int i = 0; i < _percentChecks.Length; i++)
            {
                _percentChecks[i].Checked = currentToggles == null || i >= currentToggles.Length || currentToggles[i];
            }

            _status.Text = items == null ? "请先执行「处理并标记」。" : string.Empty;
        }

        private void RaiseApplied()
        {
            int index = _itemCombo.SelectedIndex;
            if (index < 0 || index >= _columns.Count || Applied == null)
            {
                return;
            }

            int limit = 0;
            for (int i = 0; i < _limitRadios.Length; i++)
            {
                if (_limitRadios[i].Checked)
                {
                    limit = i;
                    break;
                }
            }

            var toggles = new bool[_percentChecks.Length];
            for (int i = 0; i < _percentChecks.Length; i++)
            {
                toggles[i] = _percentChecks[i].Checked;
            }

            Applied(_columns[index], limit, toggles);
        }

        public void SetStatus(string text)
        {
            _status.Text = text ?? string.Empty;
        }

        private static Label Section(string text)
        {
            return new Label
            {
                Text = text,
                AutoSize = true,
                Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Bold),
                Margin = new Padding(3, 10, 3, 2),
            };
        }
    }
}
