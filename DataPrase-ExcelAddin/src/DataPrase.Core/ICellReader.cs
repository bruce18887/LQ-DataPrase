namespace DataPrase.Core
{
    /// <summary>
    /// 只读单元格访问抽象（1 基行/列，与 Excel 一致）。Core 只依赖此接口，
    /// 从而完全脱离 Excel 对象模型、可离线单测。AddIn 侧用批量读入的数组实现它。
    /// </summary>
    public interface ICellReader
    {
        /// <summary>可扫描的最大行号（1 基）。调用方应比数据区多留几行，以便标定能探测到「连续空行」终止。</summary>
        int RowCount { get; }

        /// <summary>可读的最大列号（1 基）。</summary>
        int ColumnCount { get; }

        /// <summary>取单元格值；空白单元格返回 null，越界返回 null。注意：空串 "" 与空白 null 语义不同（对齐 VBA IsEmpty）。</summary>
        object GetValue(int row, int column);
    }
}
