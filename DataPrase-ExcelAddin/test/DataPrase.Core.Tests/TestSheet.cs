using DataPrase.Core;

namespace DataPrase.Core.Tests
{
    /// <summary>构造测试用 ICellReader 的小辅助（1 基 Set，未设置处为空白 null）。</summary>
    internal sealed class SheetBuilder
    {
        private readonly object[,] _data;

        public SheetBuilder(int rows, int columns)
        {
            _data = new object[rows, columns];
        }

        public SheetBuilder Set(int row, int column, object value)
        {
            _data[row - 1, column - 1] = value;
            return this;
        }

        /// <summary>从指定行起，沿某列依次写入。</summary>
        public SheetBuilder Column(int column, int startRow, params object[] values)
        {
            for (int i = 0; i < values.Length; i++)
            {
                _data[startRow - 1 + i, column - 1] = values[i];
            }

            return this;
        }

        public ICellReader Build()
        {
            return new ArrayCellReader(_data);
        }
    }
}
