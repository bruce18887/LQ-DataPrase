using System.Drawing;
using System.Windows.Forms;

namespace DataPrase.AddIn
{
    /// <summary>
    /// 处理选项对话框（替代 VBA UserForm1）。骨架阶段仅承载配置项，未接线到处理流程。
    /// </summary>
    public sealed class ConfigDialog : Form
    {
        private readonly CheckBox _chkDataDistribution;
        private readonly CheckBox _chkFreeze;
        private readonly CheckBox _chkFilter;
        private readonly CheckBox _chkHideColumns;
        private readonly CheckBox _chkCopyMarkedFile;

        public bool EnableAutoDataDistribution { get { return _chkDataDistribution.Checked; } }
        public bool EnableAutoFreeze { get { return _chkFreeze.Checked; } }
        public bool EnableAutoFilter { get { return _chkFilter.Checked; } }
        public bool EnableAutoHideColumns { get { return _chkHideColumns.Checked; } }
        public bool EnableAutoCopyMarkedFile { get { return _chkCopyMarkedFile.Checked; } }

        public DataPrase.Core.ProcessConfig ToProcessConfig()
        {
            return new DataPrase.Core.ProcessConfig
            {
                EnableAutoDataDistribution = _chkDataDistribution.Checked,
                EnableAutoFreeze = _chkFreeze.Checked,
                EnableAutoFilter = _chkFilter.Checked,
                EnableAutoHideColumns = _chkHideColumns.Checked,
                EnableAutoCopyMarkedFile = _chkCopyMarkedFile.Checked,
            };
        }

        public ConfigDialog()
        {
            Text = "DataPrase 处理选项";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;
            ClientSize = new Size(340, 220);

            var panel = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                ColumnCount = 1,
                Padding = new Padding(12),
            };

            _chkDataDistribution = MakeCheck("自动生成数据分布表", true);
            _chkFreeze = MakeCheck("自动冻结窗格", true);
            _chkFilter = MakeCheck("自动筛选", true);
            _chkHideColumns = MakeCheck("自动隐藏无关列", true);
            _chkCopyMarkedFile = MakeCheck("自动另存标记副本", false);

            panel.Controls.Add(_chkDataDistribution);
            panel.Controls.Add(_chkFreeze);
            panel.Controls.Add(_chkFilter);
            panel.Controls.Add(_chkHideColumns);
            panel.Controls.Add(_chkCopyMarkedFile);

            var buttons = new FlowLayoutPanel
            {
                Dock = DockStyle.Bottom,
                FlowDirection = FlowDirection.RightToLeft,
                Height = 40,
                Padding = new Padding(8),
            };

            var btnOk = new Button { Text = "确定", DialogResult = DialogResult.OK, Width = 80 };
            var btnCancel = new Button { Text = "取消", DialogResult = DialogResult.Cancel, Width = 80 };
            buttons.Controls.Add(btnOk);
            buttons.Controls.Add(btnCancel);

            Controls.Add(panel);
            Controls.Add(buttons);
            AcceptButton = btnOk;
            CancelButton = btnCancel;
        }

        private static CheckBox MakeCheck(string text, bool isChecked)
        {
            return new CheckBox
            {
                Text = text,
                Checked = isChecked,
                AutoSize = true,
                Margin = new Padding(3, 6, 3, 6),
            };
        }
    }
}
