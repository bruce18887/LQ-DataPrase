using System.Collections.Generic;

namespace DataPrase.Core
{
    /// <summary>一个待标记的单元格（行/列 1 基）。</summary>
    public struct CellMarkTarget
    {
        public CellMarkTarget(int row, int column, CellMark mark)
        {
            Row = row;
            Column = column;
            Mark = mark;
        }

        public readonly int Row;

        public readonly int Column;

        public readonly CellMark Mark;
    }

    /// <summary>标记计划：需要标红的 Bin 格行 + 需着色的数据格。</summary>
    public sealed class MarkPlan
    {
        public MarkPlan()
        {
            FailBinRows = new List<int>();
            Cells = new List<CellMarkTarget>();
        }

        /// <summary>失效 Bin 所在行号（其 Bin 格标红，对应 VBA ColorIndex 3）。</summary>
        public IList<int> FailBinRows { get; private set; }

        /// <summary>数据区里需着色的单元格（LimitHit→44，OutOfLimit→3+加粗）。</summary>
        public IList<CellMarkTarget> Cells { get; private set; }
    }

    /// <summary>
    /// 标记规划（移植自 VBA DataParser.TestDataMark 的判定循环，纯计算）。
    /// 规则：逐行看 Bin 格，只有「失效 Bin」（非空且 ≠ 1）的行才继续逐格判限值；
    /// 对每个「有限制」的测试项，按 <see cref="LimitEvaluator.EvaluateCell"/> 得出标记。
    /// </summary>
    public static class MarkPlanner
    {
        public static MarkPlan Build(
            LayoutResult layout,
            TesterSpec spec,
            IDictionary<int, TestItem> items,
            ICellReader sheet)
        {
            var plan = new MarkPlan();
            int binColumn = ColumnNames.ToNumber(spec.BinColumn);

            for (int row = layout.DataStartRow; row <= layout.DataStopRow; row++)
            {
                if (!LimitEvaluator.IsFailBin(sheet.GetValue(row, binColumn)))
                {
                    continue;
                }

                plan.FailBinRows.Add(row);

                for (int column = layout.DataStartColumn; column <= layout.DataStopColumn; column++)
                {
                    TestItem item;
                    if (!items.TryGetValue(column, out item))
                    {
                        continue;
                    }

                    CellMark mark = LimitEvaluator.EvaluateCell(sheet.GetValue(row, column), item);
                    if (mark != CellMark.None)
                    {
                        plan.Cells.Add(new CellMarkTarget(row, column, mark));
                    }
                }
            }

            return plan;
        }
    }
}
