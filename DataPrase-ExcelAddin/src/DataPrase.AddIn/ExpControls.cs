using System;
using System.Collections.Generic;
using DataPrase.Core;
using Excel = Microsoft.Office.Interop.Excel;

namespace DataPrase.AddIn
{
    /// <summary>
    /// Exp 分布表上那排**长在表上**的 Form Control，还原原模板 Exp 表的控件面板
    /// （15 个 MSForms ActiveX + 1 个按钮）。
    ///
    /// 为什么用 Form Control 而不是 ActiveX：ActiveX 的点击事件过程必须活在工作簿**自己的 VBA 工程**
    /// 里，而加载项没有工作簿 VBA；Form Control 的 OnAction 可以直接指向本加载项注册的
    /// <see cref="ExpCommands.DpExpRefresh"/>（Excel-DNA 的 [ExcelCommand] 宏），因此**无需任何工作簿 VBA**。
    ///
    /// 位置一律**按单元格锚定**（取目标区域的 Top/Left/Width/Height），不做「行号 × 行高」换算——
    /// Exp 表实测行高 10.2pt，按 15pt 硬算会让整面板下漂 1.47 倍。
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

        // 原模板控件位置，实测自 Exp-template.xlsm 的 xl/drawings/vmlDrawing1.vml <x:Anchor>
        // （0 基行列已转成 Excel 行列）：ComboBox1 在 H35 跨 5 列 2 行；OptionButton1-5 逐行 B36-B40；
        // CheckBox1-9 逐行 B43-B51；ReImportTestItem 按钮在 N35 跨 3 列 2 行。
        private const int DropdownRow = 35;
        private const int DropdownColumn = 8;           // H
        private const int DropdownWidthColumns = 5;     // H..L
        private const int DropdownHeightRows = 2;

        private const int PanelColumn = 2;              // B
        private const int PanelWidthColumns = 2;        // B..C
        private const int FirstLimitRow = 36;           // B36..B40
        private const int FirstPercentRow = 43;         // B43..B51

        private const int ApplyRow = 35;
        private const int ApplyColumn = 14;             // N
        private const int ApplyWidthColumns = 3;        // N..P
        private const int ApplyHeightRows = 2;

        /// <summary>Exp 行高 10.2pt，单行高的复选/单选难点中，给个下限。</summary>
        private const int MinControlHeight = 12;

        /// <summary>（重）建控件面板。幂等：先删掉上一轮的控件再建。</summary>
        public static void Build(Excel.Worksheet exp, IList<string> itemNames, int limitSelector, bool[] toggles)
        {
            DeleteExisting(exp);
            int itemCount = WriteItemList(exp, itemNames);

            Excel.Shape dropdown = Add(
                exp, Excel.XlFormControl.xlDropDown, DropdownRow, DropdownColumn, DropdownWidthColumns, DropdownHeightRows);
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
                Excel.Shape option = Add(
                    exp, Excel.XlFormControl.xlOptionButton, FirstLimitRow + i, PanelColumn, PanelWidthColumns, 1);
                option.Name = NamePrefix + "Limit" + i;
                option.OnAction = CommandName;
                SetCaption(option, LimitBaseCaptions[i]);
                SetValue(option, i == limitSelector);
            }

            for (int i = 0; i < PercentCaptions.Length; i++)
            {
                Excel.Shape check = Add(
                    exp, Excel.XlFormControl.xlCheckBox, FirstPercentRow + i, PanelColumn, PanelWidthColumns, 1);
                check.Name = NamePrefix + "Pct" + i;
                check.OnAction = CommandName;
                SetCaption(check, PercentCaptions[i]);
                SetValue(check, toggles != null && i < toggles.Length && toggles[i]);
            }

            Excel.Shape apply = Add(
                exp, Excel.XlFormControl.xlButtonControl, ApplyRow, ApplyColumn, ApplyWidthColumns, ApplyHeightRows);
            apply.Name = NamePrefix + "Apply";
            apply.OnAction = CommandName;
            SetCaption(apply, "应用");
        }

        /// <summary>面板是否已建好（下拉控件存在即认定面板在）。</summary>
        public static bool Exists(Excel.Worksheet exp)
        {
            return Find(exp, NamePrefix + "Item") != null;
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

            // 单选互斥由 Excel 自己保证（实测：同表裸放的两个单选按钮都设选中时，前一个自动取消）。
            for (int i = 0; i < LimitBaseCaptions.Length; i++)
            {
                Excel.Shape option = Find(exp, NamePrefix + "Limit" + i);
                if (option != null && ReadValue(option, 0) == 1)
                {
                    limitSelector = i;
                    break;
                }
            }

            for (int i = 0; i < toggles.Length; i++)
            {
                Excel.Shape check = Find(exp, NamePrefix + "Pct" + i);
                toggles[i] = check != null && ReadValue(check, 0) == 1;
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

        /// <summary>在指定单元格区域上放一个 Form Control：几何全部取自该区域本身。</summary>
        private static Excel.Shape Add(
            Excel.Worksheet exp, Excel.XlFormControl type, int row, int column, int widthColumns, int heightRows)
        {
            Excel.Range corner = (Excel.Range)exp.Cells[row, column];
            Excel.Range anchor = corner.Resize[heightRows, widthColumns];
            try
            {
                // AddFormControl 只吃整数坐标，而 10.2pt 的行高让 Top/Width 天然带小数：
                // 直接强转会向下截断，控件整体比目标行偏上不到 1pt，逐行累积后看起来就是「错位」。
                int height = Math.Max(MinControlHeight, (int)Math.Round(anchor.Height));
                return exp.Shapes.AddFormControl(
                    type,
                    (int)Math.Round(anchor.Left),
                    (int)Math.Round(anchor.Top),
                    (int)Math.Round(anchor.Width),
                    height);
            }
            finally
            {
                ExcelInterop.Release(anchor);
                ExcelInterop.Release(corner);
            }
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
            // Form Control 不认 TextFrame2（实测必抛「在此对象上找不到属性 Text」），只有旧式 TextFrame 可用。
            Excel.TextFrame frame = shape.TextFrame;
            try
            {
                Excel.Characters characters = frame.Characters(Type.Missing, Type.Missing);
                try
                {
                    characters.Text = text;
                }
                finally
                {
                    ExcelInterop.Release(characters);
                }
            }
            finally
            {
                ExcelInterop.Release(frame);
            }
        }

        /// <summary>Form Control 的选中态只接受 1/0；实测写 -1（ActiveX 的 vbUnchecked 约定）必抛。</summary>
        private static void SetValue(Excel.Shape shape, bool isChecked)
        {
            Excel.ControlFormat format = shape.ControlFormat;
            try
            {
                format.Value = isChecked ? 1 : 0;
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
