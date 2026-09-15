using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;
using DataPrase.Core;

namespace DataPrase.AddIn
{
    /// <summary>
    /// 分布表选项对话框（替代 VBA Exp 表上的 ComboBox1 + 5 个 OptionButton）。
    /// 原模板里 B36 由 5 个 ActiveX 选项按钮驱动，用户瘦身模板时控件被删掉了，
    /// 这里把该选择搬进加载项 UI。
    /// </summary>
    internal sealed class ItemPickerDialog : Form
    {
        /// <summary>B36 取值 0..4 依次对应模板第 36..40 行（数据源见 Exp 表 D36:D40）。</summary>
        private static readonly string[] LimitBases =
        {
            "Low Limit 起算（模板默认）",
            "Min / Max",
            "模板第 38 行（固定 0 / 2）",
            "Mean ± 3σ",
            "Mean ± 6σ",
        };

        private readonly ComboBox _itemCombo;
        private readonly ComboBox _limitCombo;
        private readonly List<int> _columns;

        public int SelectedColumn { get; private set; }

        public int SelectedLimitSelector { get; private set; }

        public ItemPickerDialog(IDictionary<int, TestItem> itemsByColumn, int currentLimitSelector)
        {
            _columns = new List<int>(itemsByColumn.Keys);
            _columns.Sort();

            Text = "分布表";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;
            ClientSize = new Size(420, 150);

            _itemCombo = new ComboBox
            {
                DropDownStyle = ComboBoxStyle.DropDownList,
                Location = new Point(96, 16),
                Width = 308,
            };

            foreach (int column in _columns)
            {
                _itemCombo.Items.Add(itemsByColumn[column].TestName);
            }

            if (_itemCombo.Items.Count > 0)
            {
                _itemCombo.SelectedIndex = 0;
            }

            _limitCombo = new ComboBox
            {
                DropDownStyle = ComboBoxStyle.DropDownList,
                Location = new Point(96, 50),
                Width = 308,
            };

            foreach (string text in LimitBases)
            {
                _limitCombo.Items.Add(text);
            }

            _limitCombo.SelectedIndex = (currentLimitSelector >= 0 && currentLimitSelector < LimitBases.Length)
                ? currentLimitSelector
                : 0;

            var buttons = new FlowLayoutPanel
            {
                FlowDirection = FlowDirection.RightToLeft,
                Location = new Point(96, 92),
                Size = new Size(308, 34),
            };

            var btnOk = new Button { Text = "确定", DialogResult = DialogResult.OK, Width = 80 };
            var btnCancel = new Button { Text = "取消", DialogResult = DialogResult.Cancel, Width = 80 };
            buttons.Controls.Add(btnOk);
            buttons.Controls.Add(btnCancel);

            Controls.Add(new Label { Text = "测试项：", Location = new Point(16, 20), AutoSize = true });
            Controls.Add(new Label { Text = "阶梯基准：", Location = new Point(16, 54), AutoSize = true });
            Controls.Add(_itemCombo);
            Controls.Add(_limitCombo);
            Controls.Add(buttons);

            AcceptButton = btnOk;
            CancelButton = btnCancel;

            btnOk.Click += (s, e) =>
            {
                int index = _itemCombo.SelectedIndex;
                SelectedColumn = (index >= 0 && index < _columns.Count) ? _columns[index] : 0;
                SelectedLimitSelector = _limitCombo.SelectedIndex < 0 ? 0 : _limitCombo.SelectedIndex;
            };
        }
    }
}
