using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;
using DataPrase.Core;

namespace DataPrase.AddIn
{
    /// <summary>
    /// 测试项选择对话框（替代 VBA Exp 表上的 ComboBox1）。按数据列顺序列出测试项名。
    /// </summary>
    internal sealed class ItemPickerDialog : Form
    {
        private readonly ComboBox _combo;
        private readonly IList<TestItem> _items;
        private readonly List<int> _columns;

        public int SelectedColumn { get; private set; }

        public ItemPickerDialog(IDictionary<int, TestItem> itemsByColumn)
        {
            _items = new List<TestItem>();
            _columns = new List<int>();

            var keys = new List<int>(itemsByColumn.Keys);
            keys.Sort();
            foreach (int column in keys)
            {
                _columns.Add(column);
                _items.Add(itemsByColumn[column]);
            }

            Text = "选择测试项";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;
            ClientSize = new Size(360, 110);

            _combo = new ComboBox
            {
                DropDownStyle = ComboBoxStyle.DropDownList,
                Location = new Point(12, 24),
                Width = 336,
            };

            foreach (TestItem item in _items)
            {
                _combo.Items.Add(item.TestName);
            }

            if (_combo.Items.Count > 0)
            {
                _combo.SelectedIndex = 0;
            }

            var buttons = new FlowLayoutPanel
            {
                FlowDirection = FlowDirection.RightToLeft,
                Location = new Point(12, 64),
                Size = new Size(336, 34),
            };

            var btnOk = new Button { Text = "确定", DialogResult = DialogResult.OK, Width = 80 };
            var btnCancel = new Button { Text = "取消", DialogResult = DialogResult.Cancel, Width = 80 };
            buttons.Controls.Add(btnOk);
            buttons.Controls.Add(btnCancel);

            Controls.Add(new Label { Text = "测试项：", Location = new Point(12, 6), AutoSize = true });
            Controls.Add(_combo);
            Controls.Add(buttons);

            AcceptButton = btnOk;
            CancelButton = btnCancel;

            btnOk.Click += (s, e) =>
            {
                int index = _combo.SelectedIndex;
                SelectedColumn = (index >= 0 && index < _columns.Count) ? _columns[index] : 0;
            };
        }
    }
}
