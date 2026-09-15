namespace DataPrase.Core
{
    /// <summary>列号 ↔ 列名转换（1 基）。ToLetter 移植自 VBA Utilities.ColumnNumberToLetter。</summary>
    public static class ColumnNames
    {
        public static string ToLetter(int columnNumber)
        {
            string letter = string.Empty;
            int n = columnNumber;

            while (n > 0)
            {
                int remainder = (n - 1) % 26;
                letter = (char)('A' + remainder) + letter;
                n = (n - 1) / 26;
            }

            return letter;
        }

        /// <summary>
        /// 解析列名/列引用为列号，容忍 VBA 风格的 "$" 前缀（如 "$C" → 3）。
        /// 非法输入返回 0。
        /// </summary>
        public static int ToNumber(string columnRef)
        {
            if (string.IsNullOrEmpty(columnRef))
            {
                return 0;
            }

            int n = 0;
            bool sawLetter = false;

            foreach (char raw in columnRef)
            {
                char c = char.ToUpperInvariant(raw);
                if (c == '$' || c == ' ')
                {
                    continue;
                }

                if (c < 'A' || c > 'Z')
                {
                    return 0;
                }

                sawLetter = true;
                n = n * 26 + (c - 'A' + 1);
            }

            return sawLetter ? n : 0;
        }
    }
}

