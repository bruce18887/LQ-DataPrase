using System.Windows.Forms;
using ExcelDna.Integration.CustomUI;

namespace DataPrase.AddIn
{
    /// <summary>
    /// Ribbon 定义与回调（替代 VBA 的宏入口 + UserForm 按钮）。
    /// 使用 2006/01 customUI 命名空间以兼容 Excel 2007（2009/07 命名空间在 2007 上不生效）。
    /// </summary>
    [System.Runtime.InteropServices.ComVisible(true)]
    public class Ribbon : ExcelRibbon
    {
        private const string RibbonXml = @"<customUI xmlns='http://schemas.microsoft.com/office/2006/01/customui'>
  <ribbon>
    <tabs>
      <tab id='DataPraseTab' label='DataPrase'>
        <group id='DataPraseDataGroup' label='数据'>
          <button id='btnImport' label='导入数据' size='large' onAction='OnImport' screentip='导入并识别测试机 datalog' />
        </group>
        <group id='DataPraseActionGroup' label='处理'>
          <button id='btnMark' label='标记失效' size='large' onAction='OnMark' screentip='按 Bin 与限值标记失效数据' />
          <button id='btnSettings' label='设置' size='large' onAction='OnSettings' screentip='处理选项' />
        </group>
      </tab>
    </tabs>
  </ribbon>
</customUI>";

        public override string GetCustomUI(string RibbonID)
        {
            return RibbonXml;
        }

        public void OnImport(IRibbonControl control)
        {
            Actions.Import();
        }

        public void OnMark(IRibbonControl control)
        {
            Actions.MarkFailures();
        }

        public void OnSettings(IRibbonControl control)
        {
            using (var dialog = new ConfigDialog())
            {
                dialog.ShowDialog();
            }
        }
    }
}
