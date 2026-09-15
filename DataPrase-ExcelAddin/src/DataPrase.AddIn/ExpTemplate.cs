using System;
using System.IO;
using Excel = Microsoft.Office.Interop.Excel;

namespace DataPrase.AddIn
{
    /// <summary>
    /// 把内嵌的 Exp 分布表模板复制进目标工作簿（替代 VBA 的 <c>ThisWorkbook.Sheets("Exp").Copy</c>——
    /// XLL 没有宿主工作簿，模板只能随加载项内嵌）。
    ///
    /// 模板以「禁用宏 + 不更新外部链接 + 不弹警告」方式打开，只取走 Exp 工作表后即关闭，不落盘留存。
    /// </summary>
    internal static class ExpTemplate
    {
        public const string SheetName = "Exp";

        private const string ResourceName = "DataPrase.AddIn.Resources.Exp-template.xlsb";

        public static Excel.Worksheet Inject(Excel.Application app, Excel.Workbook target)
        {
            string tempPath = Path.Combine(
                Path.GetTempPath(), "DataPrase-ExpTemplate-" + Guid.NewGuid().ToString("N") + ".xlsb");

            try
            {
                WriteResourceTo(tempPath);
                return CopySheetFrom(app, target, tempPath);
            }
            finally
            {
                try
                {
                    if (File.Exists(tempPath))
                    {
                        File.Delete(tempPath);
                    }
                }
                catch (IOException)
                {
                }
                catch (UnauthorizedAccessException)
                {
                }
            }
        }

        private static Excel.Worksheet CopySheetFrom(Excel.Application app, Excel.Workbook target, string tempPath)
        {
            Excel.Workbook template = OpenQuietly(app, tempPath);

            try
            {
                Excel.Worksheet source = ExcelInterop.FindSheet(template, SheetName);
                if (source == null)
                {
                    throw new InvalidOperationException("内嵌模板中未找到 " + SheetName + " 工作表。");
                }

                object lastSheet = target.Sheets[target.Sheets.Count];
                source.Copy(Type.Missing, lastSheet);

                var injected = app.ActiveSheet as Excel.Worksheet;
                return injected ?? ExcelInterop.FindSheet(target, SheetName);
            }
            finally
            {
                template.Close(false);
                ExcelInterop.Release(template);
            }
        }

        private static void WriteResourceTo(string path)
        {
            using (Stream stream = typeof(ExpTemplate).Assembly.GetManifestResourceStream(ResourceName))
            {
                if (stream == null)
                {
                    throw new InvalidOperationException("未找到内嵌的 Exp 模板资源：" + ResourceName);
                }

                using (var file = File.Create(path))
                {
                    stream.CopyTo(file);
                }
            }
        }

        private static Excel.Workbook OpenQuietly(Excel.Application app, string path)
        {
            bool askToUpdateLinks = app.AskToUpdateLinks;
            bool alerts = app.DisplayAlerts;
            Microsoft.Office.Core.MsoAutomationSecurity security = app.AutomationSecurity;

            try
            {
                app.AskToUpdateLinks = false;
                app.DisplayAlerts = false;
                app.AutomationSecurity = Microsoft.Office.Core.MsoAutomationSecurity.msoAutomationSecurityForceDisable;
                return app.Workbooks.Open(path, 0, true);   // UpdateLinks=0（不更新外部链接）、ReadOnly=true
            }
            finally
            {
                app.AutomationSecurity = security;
                app.AskToUpdateLinks = askToUpdateLinks;
                app.DisplayAlerts = alerts;
            }
        }
    }
}
