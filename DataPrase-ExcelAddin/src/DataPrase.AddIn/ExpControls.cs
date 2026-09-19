using System;
using System.Collections.Generic;
using DataPrase.Core;
using Excel = Microsoft.Office.Interop.Excel;

namespace DataPrase.AddIn
{
    /// <summary>
    /// Exp 分布表上那排**长在表上**的 Form Control（还原原模板的 16 个 MSForms ActiveX 控件）。
    ///
    /// 为什么用 Form Control 而不是 ActiveX：ActiveX 的点击事件过程必须活在工作簿**自己的 VBA 工程**
    /// 里，而加载项没有工作簿 VBA；Form Control 的 OnAction 可以直接指向本加载项注册的
    /// <see cref="ExpCommands.DpExpRefresh"/>（Excel-DNA 的 [ExcelCommand] 宏），因此**无需任何工作簿 VBA**。
    /// 另：Form Control 在 .xlsx 里也能保存（ActiveX 不能），正好匹配「数据源是 CSV」的使用方式。
    ///
    /// 控件：1 下拉（测试项）+ 5 单选（阶梯基准）+ 9 复选（站点百分比列）+ 1 按钮。
    /// 全部挂同一个 OnAction：点任意控件 → 读回全部控件状态 → 重算分布表。
    /// </summary>
    internal static class ExpControls
    {
        /// <summary>控件 OnAction 指向的命令名（= <see cref="ExpCommands.DpExpRefresh"/> 的方法名）。</summary>
        internal const string CommandName = "DpExpRefresh";

        private static readonly string[] LimitBaseCaptions =
        {
            "Data Range", "RowDataLimit", "CustomLimit", "3 Sigma", "6 Sigma",
        };

        private static readonly string[] PercentCaptions =
        {
            "All Site", "Site1", "Site2", "Site3", "Site4", "Site5", "Site6", "Site7", "Site8",
        };

        private const string NamePrefix = "DpExp";
        private const int ItemListColumn = 52;          // AZ：下拉列表来源列（测试项名）
        private const int ColumnLeft = 48;              // B 列左缘（点）
        private const int ControlHeight = 15;
        private const int DropdownRow = 37;
        private const int FirstLimitRow = 39;
        private const int FirstPercentRow = 45;
        private const int ApplyRow = 55;

        /// <summary>（重）建控件面板。幂等：先删掉上一轮的控件再建。</summary>
        public static void Build(Excel.Worksheet exp, IList<string> itemNames, int limitSelector, bool[] toggles)
        {
            DeleteExisting(exp);
            int itemCount = WriteItemList(exp, itemNames);

            Excel.Shape dropdown = Add(exp, Excel.XlFormControl.xlDropDown, DropdownRow, 170);
            dropdown.Name = NamePrefix + "Item";
            dropdown.OnAction = CommandName;
            Excel.ControlFormat ddFormat = dropdown.ControlFormat;
            try
            {
                ddFormat.ListFillRange = "$" + ColumnNames.ToLetter(ItemListColumn) + "$1:$" +
                    ColumnNames.ToLetter(ItemListColumn) + "$" + itemCount;
                ddFormat.Value = 1;
            }
            finally
            {
                ExcelInterop.Release(ddFormat);
            }

            for (int i = 0; i < LimitBaseCaptions.Length; i++)
            {
                Excel.Shape option = Add(exp, Excel.XlFormControl.xlOptionButton, FirstLimitRow + i, 120);
                option.Name = NamePrefix + "Limit" + i;
                option.OnAction = CommandName;
                SetCaption(option, LimitBaseCaptions[i]);
                SetValue(option, i == limitSelector ? 1 : -1);
            }

            for (int i = 0; i < PercentCaptions.Length; i++)
            {
                Excel.Shape check = Add(exp, Excel.XlFormControl.xlCheckBox, FirstPercentRow + i, 120);
                check.Name = NamePrefix + "Pct" + i;
                check.OnAction = CommandName;
                SetCaption(check, PercentCaptions[i]);
                SetValue(check, toggles != null && i < toggles.Length && toggles[i] ? 1 : -1);
            }

            Excel.Shape apply = Add(exp, Excel.XlFormControl.xlButtonControl, ApplyRow, 80);
            apply.Name = NamePrefix + "Apply";
            apply.OnAction = CommandName;
            SetCaption(apply, "应用");
        }

        /// <summary>读回控件状态。返回 false 表示面板不存在（还没建）。</summary>
        public static bool TryRead(
            Excel.Worksheet exp, out int dropdownIndex, out int limitSelector, out bool[] toggles)
        {
            dropdownIndex = 0;
            limitSelector = 0;
            toggles = new bool[PercentCaptions.Length];

            Excel.Shape dropdown = Find(exp, NamePrefix + "Item");
            if (dropdown == null)
            {
                return false;
            }

            int value = ReadValue(dropdown, 1) - 1;                 // 下拉的 ControlFormat.Value 是 1 基
            dropdownIndex = value < 0 ? 0 : value;

            for (int i = 0; i < LimitBaseCaptions.Length; i++)
            {
                Excel.Shape option = Find(exp, NamePrefix + "Limit" + i);
                if (option != null && ReadValue(option, -1) == 1)
                {
                    limitSelector = i;
                    break;
                }
            }

            for (int i = 0; i < toggles.Length; i++)
            {
                Excel.Shape check = Find(exp, NamePrefix + "Pct" + i);
                toggles[i] = check != null && ReadValue(check, -1) == 1;
            }

            return true;
        }

        private static void DeleteExisting(Excel.Worksheet exp)
        {
            Excel.Shapes shapes = exp.Shapes;
            for (int i = shapes.Count; i >= 1; i--)
            {
                Excel.Shape shape = shapes.Item(i);
                string name = shape == null ? null : shape.Name;
                if (name != null && name.StartsWith(NamePrefix, StringComparison.Ordinal))
                {
                    shape.Delete();
                }
            }
        }

        /// <summary>把测试项名写到 AZ 列（下拉的 ListFillRange 来源），返回条数（至少 1）。</summary>
        private static int WriteItemList(Excel.Worksheet exp, IList<string> itemNames)
        {
            Excel.Range clear = exp.Range["AZ1:AZ200"];
            try
            {
                clear.ClearContents();
            }
            finally
            {
                ExcelInterop.Release(clear);
            }

            int count = itemNames == null ? 0 : itemNames.Count;
            Excel.Range first = (Excel.Range)exp.Cells[1, ItemListColumn];
            Excel.Range last = (Excel.Range)exp.Cells[Math.Max(1, count), ItemListColumn];
            Excel.Range span = exp.Range[first, last];
            try
            {
                if (count == 0)
                {
                    span.Value2 = string.Empty;
                    return 1;
                }

                object[,] values = new object[count, 1];
                for (int i = 0; i < count; i++)
                {
                    values[i, 0] = itemNames[i];
                }

                span.Value2 = values;
                return count;
            }
            finally
            {
                ExcelInterop.Release(span);
                ExcelInterop.Release(last);
                ExcelInterop.Release(first);
            }
        }

        private static Excel.Shape Add(Excel.Worksheet exp, Excel.XlFormControl type, int row, int width)
        {
            return exp.Shapes.AddFormControl(type, ColumnLeft, (row - 1) * ControlHeight, width, ControlHeight);
        }

        private static Excel.Shape Find(Excel.Worksheet exp, string name)
        {
            Excel.Shapes shapes = exp.Shapes;
            for (int i = 1; i <= shapes.Count; i++)
            {
                Excel.Shape shape = shapes.Item(i);
                if (string.Equals(shape.Name, name, StringComparison.Ordinal))
                {
                    return shape;
                }
            }

            return null;
        }

        private static void SetCaption(Excel.Shape shape, string text)
        {
            try
            {
                shape.TextFrame2.TextRange.Text = text;
                return;
            }
            catch (Exception)
            {
                // 某些控件类型没有 TextFrame2，退回旧接口。
            }

            try
            {
                shape.TextFrame.Characters(Type.Missing, Type.Missing).Text = text;
            }
            catch (Exception)
            {
                // 标题设置失败不影响控件功能，忽略。
            }
        }

        private static void SetValue(Excel.Shape shape, int value)
        {
            Excel.ControlFormat format = shape.ControlFormat;
            try
            {
                format.Value = value;
            }
            finally
            {
                ExcelInterop.Release(format);
            }
        }

        private static int ReadValue(Excel.Shape shape, int defaultValue)
        {
            Excel.ControlFormat format = shape.ControlFormat;
            try
            {
                object value = format.Value;
                return value == null ? defaultValue : Convert.ToInt32(value);
            }
            catch (Exception)
            {
                return defaultValue;
            }
            finally
            {
                ExcelInterop.Release(format);
            }
        }
    }
}
