using System.Collections.Generic;

namespace DataPrase.Core
{
    /// <summary>一条待写入 Exp 表的公式：<see cref="Formula"/> 写进 <see cref="Address"/> 的左上角单元格
    /// （多行地址由 Excel 按相对引用自动填充，与 VBA 的 Range.Formula 行为一致）。</summary>
    public sealed class FormulaWrite
    {
        public FormulaWrite(string address, string formula)
        {
            Address = address;
            Formula = formula;
        }

        public string Address { get; private set; }

        public string Formula { get; private set; }
    }

    /// <summary>
    /// Exp 分布表公式构建（移植自 VBA DataParser.DataDistribtuionFormula_Refresh）。
    ///
    /// 口径已用真实模板 `Exp-template.xlsm` 逐格核对过：模板 D2='Range' / E2='All Site' /
    /// F2:M2='Site1/N'..'Site8/N'；D 列是 bin 边界（`=$D$36+B3*$F$36`），E 列 All Site 计数，
    /// F–M 为 Site1–8 计数，N–V 百分比由模板自带公式计算。**VBA 的写入位置与模板完全一致**，
    /// 因此这里原样移植，不做任何「修正」。
    /// </summary>
    public static class DistributionFormulaBuilder
    {
        /// <summary>限值基准行：B36 的值表示从第 36 行起下移几行作为基准。</summary>
        public const int LimitBaseRow = 36;

        /// <summary>阶梯首/末行（对应模板第 3..27 行）。</summary>
        public const int LadderFirstRow = 3;

        public const int LadderLastRow = 27;

        public static IList<FormulaWrite> Build(
            string columnLetter,
            int testNameRow,
            int dataStartRow,
            int dataStopRow,
            int limitSelectorValue,
            TesterSpec spec)
        {
            var writes = new List<FormulaWrite>();

            string dataRange = "Data!" + columnLetter + "$" + dataStartRow
                               + ":Data!" + columnLetter + "$" + dataStopRow;
            string siteRange = "Data!" + spec.SiteColumn + "$" + dataStartRow
                               + ":Data!" + spec.SiteColumn + "$" + dataStopRow;

            string lsl = columnLetter + (testNameRow + spec.LowOffset);
            string hsl = columnLetter + (testNameRow + spec.HighOffset);
            string min = columnLetter + (testNameRow + spec.MinOffset);
            string max = columnLetter + (testNameRow + spec.MaxOffset);
            string unit = columnLetter + (testNameRow + spec.UnitOffset);
            string rangeCell = columnLetter + (testNameRow + spec.RangeOffset);
            string mean = columnLetter + (testNameRow + spec.MeanOffset);
            string std = columnLetter + (testNameRow + spec.StdOffset);
            string cpk = columnLetter + (testNameRow + spec.CpkOffset);

            // bin 边界阶梯 D3:D27，基准行由 B36 选择器决定
            int limitRow = LimitBaseRow + limitSelectorValue;
            writes.Add(new FormulaWrite(
                ColumnNames.ToLetter(4) + LadderFirstRow + ":" + ColumnNames.ToLetter(4) + LadderLastRow,
                "=$D$" + limitRow + "+B" + LadderFirstRow + "*$F$" + limitRow));

            // All Site 计数：E 列
            writes.Add(new FormulaWrite("E" + LadderFirstRow,
                "=COUNTIFS(" + dataRange + ",\"<=\" & Exp!$D" + LadderFirstRow + ")"));
            writes.Add(new FormulaWrite("E" + LadderLastRow,
                "=COUNTIFS(" + dataRange + ",\">=\" & Exp!$D" + LadderLastRow + ")"));
            writes.Add(new FormulaWrite(
                "E" + (LadderFirstRow + 1) + ":E" + (LadderLastRow - 1),
                "=COUNTIFS(" + dataRange + ",\">\" & Exp!$D" + LadderFirstRow
                + "," + dataRange + ",\"<=\"& Exp!$D" + (LadderFirstRow + 1) + ")"));

            // Site1~8 计数：F~M 列（VBA 的 Cells(row, 5+i)）
            for (int site = 1; site <= 8; site++)
            {
                string letter = ColumnNames.ToLetter(5 + site);
                string siteArg = ",\"= " + site + "\")";

                writes.Add(new FormulaWrite(letter + LadderFirstRow,
                    "=COUNTIFS(" + dataRange + ",\"<=\" & Exp!$D" + LadderFirstRow
                    + "," + siteRange + siteArg));

                writes.Add(new FormulaWrite(letter + LadderLastRow,
                    "=COUNTIFS(" + dataRange + ",\">=\" & Exp!$D" + LadderLastRow
                    + "," + siteRange + siteArg));

                writes.Add(new FormulaWrite(
                    letter + (LadderFirstRow + 1) + ":" + letter + (LadderLastRow - 1),
                    "=COUNTIFS(" + dataRange + ",\">\" & Exp!$D" + LadderFirstRow
                    + "," + dataRange + ",\"<=\"& Exp!$D" + (LadderFirstRow + 1)
                    + "," + siteRange + siteArg));
            }

            // 限值 / 单位 / 统计标量
            writes.Add(new FormulaWrite("G36", "=Data!" + unit));
            writes.Add(new FormulaWrite("C53", "=Data!" + rangeCell));
            writes.Add(new FormulaWrite("C54", "=Data!" + mean));
            writes.Add(new FormulaWrite("C55", "=Data!" + std));
            writes.Add(new FormulaWrite("C56", "=Data!" + cpk));
            writes.Add(new FormulaWrite("D36", "=Data!" + lsl));
            writes.Add(new FormulaWrite("E36", "=Data!" + hsl));
            writes.Add(new FormulaWrite("D37", "=Data!" + min));
            writes.Add(new FormulaWrite("E37", "=Data!" + max));
            writes.Add(new FormulaWrite("D39", "=Data!" + mean + "-3*Data!" + std));
            writes.Add(new FormulaWrite("E39", "=Data!" + mean + "+3*Data!" + std));
            writes.Add(new FormulaWrite("D40", "=Data!" + mean + "-6*Data!" + std));
            writes.Add(new FormulaWrite("E40", "=Data!" + mean + "+6*Data!" + std));

            return writes;
        }
    }
}
