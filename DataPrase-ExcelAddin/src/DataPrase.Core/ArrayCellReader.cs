namespace DataPrase.Core
{
    /// <summary>
    /// 用二维数组支撑的 <see cref="ICellReader"/>。数组下界任意：
    /// 兼容单测的 0 基数组与 Excel COM 返回的 1 基数组。
    /// </summary>
    public sealed class ArrayCellReader : ICellReader
    {
        private readonly object[,] _values;
        private readonly int _rowLower;
        private readonly int _colLower;

        public ArrayCellReader(object[,] values)
        {
            _values = values;
            _rowLower = values.GetLowerBound(0);
            _colLower = values.GetLowerBound(1);
            RowCount = values.GetUpperBound(0) - _rowLower + 1;
            ColumnCount = values.GetUpperBound(1) - _colLower + 1;
        }

        public int RowCount { get; private set; }

        public int ColumnCount { get; private set; }

        public object GetValue(int row, int column)
        {
            if (row < 1 || column < 1 || row > RowCount || column > ColumnCount)
            {
                return null;
            }

            return _values[row - 1 + _rowLower, column - 1 + _colLower];
        }
    }
}
