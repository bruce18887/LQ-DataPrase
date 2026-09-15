using System.Globalization;

namespace DataPrase.Core
{
    /// <summary>单元格标记结果（对应 VBA 的 ColorIndex：3=失效、44=压限）。</summary>
    public enum CellMark
    {
        /// <summary>不标记。</summary>
        None = 0,

        /// <summary>恰好等于单侧限值（ColorIndex 44）。</summary>
        LimitHit,

        /// <summary>超出限值（ColorIndex 3 + 加粗）。</summary>
        OutOfLimit,
    }

    /// <summary>
    /// 失效判定（移植自 VBA DataParser.TestDataMark，纯计算、不接触 Excel）。
    /// </summary>
    public static class LimitEvaluator
    {
        /// <summary>
        /// 是否失效 Bin（VBA: <c>BinValue &lt;&gt; "" And BinValue &lt;&gt; 1</c>）。
        /// 空白与空串都不算失效 Bin（VBA 里 Empty 与 "" 相等）；数值 1 或其字符串形式视为 Pass。
        /// 注：非数值 Bin 在 VBA 会因类型不匹配报错，这里从宽视为失效 Bin。
        /// </summary>
        public static bool IsFailBin(object binValue)
        {
            if (VbaString.IsBlank(binValue))
            {
                return false;
            }

            if (VbaString.CoerceToString(binValue).Length == 0)
            {
                return false;
            }

            double numeric;
            return !(TryToDouble(binValue, out numeric) && numeric == 1d);
        }

        /// <summary>判定单个测试值相对测试项限值的结果。</summary>
        public static CellMark EvaluateCell(object value, TestItem item)
        {
            if (item == null || item.HasNoLimit)
            {
                return CellMark.None;
            }

            // VBA: CellValue <> "" —— 空白（Empty）与空串都跳过。
            if (VbaString.IsBlank(value) || VbaString.CoerceToString(value).Length == 0)
            {
                return CellMark.None;
            }

            double v;
            if (!TryToDouble(value, out v))
            {
                return CellMark.None;
            }

            double low = item.LowLimit;
            double high = item.HighLimit;

            // VBA: (v = Hi And v <> Lo) Or (v <> Hi And v = Lo) —— 恰好压中单侧限值。
            if ((v == high && v != low) || (v != high && v == low))
            {
                return CellMark.LimitHit;
            }

            if (v > high || v < low)
            {
                return CellMark.OutOfLimit;
            }

            return CellMark.None;
        }

        internal static bool TryToDouble(object value, out double result)
        {
            result = 0d;
            if (value == null)
            {
                return false;
            }

            if (value is double)
            {
                result = (double)value;
                return true;
            }

            if (value is bool)
            {
                return false;
            }

            string s = VbaString.CoerceToString(value);
            return double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out result);
        }
    }
}
