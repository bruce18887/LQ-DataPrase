using System;
using System.Drawing;
using System.Windows.Forms;
using System.Collections.Generic;
using System.Text;
using ExcelDna.Integration;
using ExcelDna.Integration.CustomUI;

namespace DataPrase.AddIn
{
    /// <summary>
    /// Ribbon 定义与回调（替代 VBA 的宏入口 + UserForm 按钮）。
    /// 使用 2006/01 customUI 命名空间以兼容 Excel 2007（2009/07 命名空间在 2007 上不生效）。
    ///
    /// 图标走 <c>imageMso</c>（Office 内置图标库）：不引图片资源、不进打包链。
    /// 但 id 能否取到图**只能实机肉眼看**——本机 Office 16.0.19127 上 <c>ToolsOptions</c> 与
    /// <c>OptionsDialog</c> 都取不到图，而 imageMso 名字表在 Office 二进制里不是明文，离线查不出来。
    /// 所以「设置」改用 <c>getImage</c> 回调自绘齿轮位图：不依赖任何内置 id，画不出图也只退化成无图按钮。
    /// 版本号直接写进「关于」按钮的 label——本轮踩过的坑就是「文件名和文件属性都看不出装的是哪版」。
    /// </summary>
    [System.Runtime.InteropServices.ComVisible(true)]
    public class Ribbon : ExcelRibbon
    {
        private static string RibbonXml
        {
            get
            {
                return @"<customUI xmlns='http://schemas.microsoft.com/office/2006/01/customui'>
  <ribbon>
    <tabs>
      <tab id='DataPraseTab' label='DataPrase'>
        <group id='DataPraseDataGroup' label='数据'>
          <button id='btnImport' label='导入数据' size='large' imageMso='FileOpen'
                  onAction='OnImport' screentip='导入并识别测试机 datalog' />
        </group>
        <group id='DataPraseActionGroup' label='处理'>
          <button id='btnMark' label='处理并标记' size='large' imageMso='FilterAutoFilter'
                  onAction='OnMark' screentip='插公式行/冻结/隐藏列，并按 Bin 与限值标记失效' />
          <button id='btnDistribution' label='分布表' size='large' imageMso='ChartInsert'
                  onAction='OnDistribution' screentip='在 Exp 表上重建控件面板并写入分布公式' />
        </group>
        <group id='DataPraseHelpGroup' label='帮助'>
          <button id='btnSettings' label='设置' size='large' getImage='GetSettingsImage'
                  onAction='OnSettings' screentip='处理选项' />
          <button id='btnAbout' label='关于 v" + AddInVersion.Value + @"' size='large' imageMso='Help'
                  onAction='OnAbout' screentip='版本与加载路径' />
        </group>
      </tab>
    </tabs>
  </ribbon>
</customUI>";
            }
        }

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

        public void OnDistribution(IRibbonControl control)
        {
            Actions.GenerateDistribution();
        }

        public void OnSettings(IRibbonControl control)
        {
            using (var dialog = new ConfigDialog())
            {
                dialog.ShowDialog();
            }
        }

        public void OnAbout(IRibbonControl control)
        {
            MessageBox.Show(AboutText(), "LQ-DataPrase - 关于", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }

        /// <summary>把「装的是哪一版、从哪个文件加载的」摊开说清楚。</summary>
        internal static string AboutText()
        {
            string xllPath;
            try
            {
                xllPath = ExcelDnaUtil.XllPath;
            }
            catch (System.Exception ex)
            {
                xllPath = "取不到（" + ex.Message + "）";
            }

            // VBA 原件里 Tester(2) 与 Tester(4) 本来就同名（同一台机的两套 datalog 布局，
            // 见 DataParser.cls:98 与 :139），所以这里按名字去重：列的是「支持哪些机台」，
            // 不是「注册表里有几条 spec」。
            var seen = new HashSet<string>(StringComparer.Ordinal);
            var testers = new StringBuilder();
            foreach (DataPrase.Core.TesterSpec spec in DataPrase.Core.TesterRegistry.Specs)
            {
                if (!seen.Add(spec.TesterName))
                {
                    continue;
                }

                if (testers.Length > 0)
                {
                    testers.Append("、");
                }

                testers.Append(spec.TesterName);
            }

            return "版本：v" + AddInVersion.Value + "\r\n"
                + "加载文件：" + xllPath + "\r\n"
                + "位数：" + (System.IntPtr.Size == 8 ? "64 位" : "32 位") + "\r\n"
                + "Excel：" + ExcelDnaUtil.ExcelVersion + "\r\n"
                + "支持机台：" + testers;
        }

        /// <summary>
        /// 「设置」按钮的图标。内置 imageMso 在这版 Office 上取不到齿轮类图标，只能自绘；
        /// 任何一步失败都返回 null 退化成无图按钮，绝不能让整条 ribbon 加载失败。
        /// </summary>
        public object GetSettingsImage(IRibbonControl control)
        {
            try
            {
                using (var bmp = new Bitmap(32, 32))
                {
                    using (Graphics g = Graphics.FromImage(bmp))
                    {
                        g.Clear(Color.Transparent);
                        g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.AntiAlias;
                        using (var font = new Font("Segoe UI Symbol", 26f, FontStyle.Regular, GraphicsUnit.Pixel))
                        {
                            g.DrawString("\u2699", font, Brushes.DimGray, new PointF(-2f, -3f));
                        }
                    }

                    return RibbonImageConverter.ToPictureDisp(bmp);
                }
            }
            catch (Exception)
            {
                return null;
            }
        }
    }

    /// <summary>AxHost 的受保护静态转换口：把 GDI+ 位图变成 Office ribbon 认的 IPictureDisp。</summary>
    internal sealed class RibbonImageConverter : AxHost
    {
        private RibbonImageConverter() : base("00000000-0000-0000-C000-000000000046")
        {
        }

        public static object ToPictureDisp(System.Drawing.Image image)
        {
            return GetIPictureDispFromPicture(image);
        }
    }
}
