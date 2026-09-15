using System.Collections.Generic;

namespace DataPrase.Core
{
    /// <summary>
    /// 读取测试项元数据（移植自 VBA DataParser.TestItemInfoGet）。
    /// 返回以「列号」为键的字典——VBA 的 Items(j) 正是按绝对列号索引。
    /// </summary>
    public static class TestItemReader
    {
        public static IDictionary<int, TestItem> Read(LayoutResult layout, TesterSpec spec, ICellReader sheet)
        {
            var items = new Dictionary<int, TestItem>();

            for (int column = layout.DataStartColumn; column <= layout.DataStopColumn; column++)
            {
                string name = VbaString.CoerceToString(sheet.GetValue(layout.TestNameRow, column));

                double low = ReadLimit(sheet, layout.TestNameRow + spec.LowOffset, column);
                double high = ReadLimit(sheet, layout.TestNameRow + spec.HighOffset, column);
                string unit = VbaString.CoerceToString(sheet.GetValue(layout.TestNameRow + spec.UnitOffset, column));

                items[column] = new TestItem(name, unit, low, high);
            }

            return items;
        }

        /// <summary>
        /// VBA: <c>If cell.Value &lt;&gt; " " Then Lolimit = cell.Value</c>——限值格恰为单个空格时
        /// 不赋值（保持默认 0）。空白单元格因 <c>Empty &lt;&gt; " "</c> 为真而赋值 0，结果同为 0。
        /// 非数值内容在 VBA 会抛类型不匹配，这里从宽记为 0。
        /// </summary>
        private static double ReadLimit(ICellReader sheet, int row, int column)
        {
            object cell = sheet.GetValue(row, column);
            if (cell is string && (string)cell == " ")
            {
                return 0d;
            }

            double value;
            return LimitEvaluator.TryToDouble(cell, out value) ? value : 0d;
        }
    }
}
