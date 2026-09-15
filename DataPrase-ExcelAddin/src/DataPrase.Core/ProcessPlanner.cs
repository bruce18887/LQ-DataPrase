using System.Collections.Generic;

namespace DataPrase.Core
{
    /// <summary>处理计划的动作项（对应 VBA ProcessDataAndMarkFailuresConfigRun 的工作簿改动）。</summary>
    public sealed class ProcessPlan
    {
        public ProcessPlan()
        {
            EmptyRowsToDelete = new List<int>();
            HiddenColumns = new List<int>();
            StatLabels = new List<string> { "Min", "Avg", "Max", "Range", "STD", "CPK" };
        }

        /// <summary>ETS88 需要删除的行（降序，直接照此顺序删即可避免行号漂移）。</summary>
        public IList<int> EmptyRowsToDelete { get; private set; }

        /// <summary>插入公式行的位置（1 基，插在此行之前）。</summary>
        public int InsertRow { get; internal set; }

        /// <summary>插入行数（6 或 7，随机型）。</summary>
        public int InsertCount { get; internal set; }

        /// <summary>插入后数据区起始行。</summary>
        public int DataStartRow { get; internal set; }

        /// <summary>插入后数据区结束行。</summary>
        public int DataStopRow { get; internal set; }

        /// <summary>统计标签/公式区首行（= 插入位置对上一行；标签写在它下面 6 行）。</summary>
        public int FormulaTopRow { get; internal set; }

        /// <summary>统计行标签，依次落在 FormulaTopRow+1 .. +6 的第一列。</summary>
        public IList<string> StatLabels { get; private set; }

        /// <summary>需要隐藏的列号（1 基）。</summary>
        public IList<int> HiddenColumns { get; private set; }
    }

    /// <summary>
    /// 生成工作簿处理计划（移植自 VBA ProcessDataAndMarkFailuresConfigRun 的行/列部分）。
    /// 只计算「要做什么」，不接触 Excel；AddIn 侧据此执行。
    /// </summary>
    public static class ProcessPlanner
    {
        private static readonly int[] Cta8290DHiddenColumns = { 2, 5, 7, 8, 9, 10, 12, 13 };   // B, E, G:J, L:M

        public static ProcessPlan Build(TesterSpec spec, int testerIndex, LayoutResult layout, ICellReader sheet)
        {
            var plan = new ProcessPlan();

            // ETS88：站点之间夹着空行，需先删；降序遍历保证行号不漂移。
            if (testerIndex == 0)
            {
                for (int row = layout.DataStopRow; row >= layout.DataStartRow; row--)
                {
                    if (IsEmptyRow(sheet.GetValue(row, 1)))
                    {
                        plan.EmptyRowsToDelete.Add(row);
                    }
                }
            }

            plan.InsertRow = layout.TestNameRow + spec.FormulaRowOffset;
            plan.InsertCount = (testerIndex == 0 || testerIndex == 3) ? 6 : 7;
            plan.DataStartRow = layout.DataStartRow + plan.InsertCount;
            plan.DataStopRow = layout.DataStopRow + plan.InsertCount - plan.EmptyRowsToDelete.Count;
            plan.FormulaTopRow = layout.TestNameRow + spec.FormulaRowOffset - 1;

            if (testerIndex == 1)
            {
                foreach (int column in Cta8290DHiddenColumns)
                {
                    plan.HiddenColumns.Add(column);
                }
            }

            return plan;
        }

        /// <summary>VBA 里判据是 <c>Cells(row,1).Value = ""</c>：空白单元格（Empty="") 与空串都算。</summary>
        private static bool IsEmptyRow(object cellValue)
        {
            return VbaString.IsBlank(cellValue) || VbaString.CoerceToString(cellValue).Length == 0;
        }
    }
}
