using System;
using System.Globalization;

namespace DataPrase.Core
{
    /// <summary>
    /// 复刻 VBA 字符串比较语义，供识别与标定使用（这些差异是移植时的真坑）。
    /// </summary>
    public static class VbaString
    {
        /// <summary>
        /// 复刻 VBA 的 <c>=</c> 字符串比较：较短串会被补尾空格，等价于两侧去尾空格后按序比较。
        /// 因此 <c>"abc" = "abc   "</c> 在 VBA 为 True。区分大小写（Option Compare Binary 默认）。
        /// 数值会自动转字符串参与比较（如 <c>1 = "1"</c> 为 True）。
        /// </summary>
        public static bool EqualsPadded(object value, string expected)
        {
            if (value == null || expected == null)
            {
                return false;
            }

            return string.Equals(
                CoerceToString(value).TrimEnd(' '),
                expected.TrimEnd(' '),
                StringComparison.Ordinal);
        }

        /// <summary>复刻 VBA <c>InStr(1, value, needle, vbTextCompare) &gt; 0</c>：不区分大小写的包含判断。</summary>
        public static bool ContainsIgnoreCase(object value, string needle)
        {
            if (value == null || string.IsNullOrEmpty(needle))
            {
                return false;
            }

            return CoerceToString(value).IndexOf(needle, StringComparison.OrdinalIgnoreCase) >= 0;
        }

        /// <summary>单元格值的字符串化（数值用不变文化，避免区域设置影响小数点）。</summary>
        public static string CoerceToString(object value)
        {
            if (value == null)
            {
                return string.Empty;
            }

            var s = value as string;
            if (s != null)
            {
                return s;
            }

            var d = value as double?;
            if (d.HasValue)
            {
                return d.Value.ToString("G", CultureInfo.InvariantCulture);
            }

            return Convert.ToString(value, CultureInfo.InvariantCulture) ?? string.Empty;
        }

        /// <summary>VBA 的 IsEmpty：仅空白单元格（null / Empty）为真；空串 "" 不算空白。</summary>
        public static bool IsBlank(object value)
        {
            return value == null || value is Missing;
        }
    }

    /// <summary>占位类型：对应 VBA 的 Empty/Missing 语义（测试与 COM 都可用）。</summary>
    public sealed class Missing
    {
        public static readonly Missing Value = new Missing();

        private Missing()
        {
        }
    }
}
