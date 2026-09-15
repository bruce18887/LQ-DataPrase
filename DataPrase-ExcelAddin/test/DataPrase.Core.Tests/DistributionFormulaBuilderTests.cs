using System.Linq;
using DataPrase.Core;
using NUnit.Framework;

namespace DataPrase.Core.Tests
{
    [TestFixture]
    public class DistributionFormulaBuilderTests
    {
        private static TesterSpec Ets88 { get { return TesterRegistry.Specs[0]; } }

        private static System.Collections.Generic.IList<FormulaWrite> Build()
        {
            return DistributionFormulaBuilder.Build(
                columnLetter: "BL",
                testNameRow: 5,
                dataStartRow: 11,
                dataStopRow: 14,
                limitSelectorValue: 0,
                spec: Ets88);
        }

        private static string Formula(System.Collections.Generic.IList<FormulaWrite> writes, string address)
        {
            return writes.Single(w => w.Address == address).Formula;
        }

        [Test]
        public void Ladder_Uses_B_Column_Multiplier_And_Limit_Base_Row()
        {
            var writes = Build();
            Assert.That(Formula(writes, "D3:D27"), Is.EqualTo("=$D$36+B3*$F$36"));
        }

        [Test]
        public void Limit_Selector_Shifts_The_Base_Row()
        {
            var writes = DistributionFormulaBuilder.Build("BL", 5, 11, 14, 3, Ets88);
            Assert.That(Formula(writes, "D3:D27"), Is.EqualTo("=$D$39+B3*$F$39"));
        }

        [Test]
        public void All_Site_Counts_Match_Legacy_Vba()
        {
            var writes = Build();

            Assert.That(Formula(writes, "E3"),
                Is.EqualTo("=COUNTIFS(Data!BL$11:Data!BL$14,\"<=\" & Exp!$D3)"));
            Assert.That(Formula(writes, "E27"),
                Is.EqualTo("=COUNTIFS(Data!BL$11:Data!BL$14,\">=\" & Exp!$D27)"));
            Assert.That(Formula(writes, "E4:E26"),
                Is.EqualTo("=COUNTIFS(Data!BL$11:Data!BL$14,\">\" & Exp!$D3,"
                           + "Data!BL$11:Data!BL$14,\"<=\"& Exp!$D4)"));
        }

        [Test]
        public void Site_Counts_Land_On_F_Through_M()
        {
            var writes = Build();

            Assert.That(Formula(writes, "F3"),
                Is.EqualTo("=COUNTIFS(Data!BL$11:Data!BL$14,\"<=\" & Exp!$D3,"
                           + "Data!$A$11:Data!$A$14,\"= 1\")"));
            Assert.That(Formula(writes, "M3"),
                Is.EqualTo("=COUNTIFS(Data!BL$11:Data!BL$14,\"<=\" & Exp!$D3,"
                           + "Data!$A$11:Data!$A$14,\"= 8\")"));
            Assert.That(writes.Any(w => w.Address.StartsWith("N")), Is.False);   // 百分比列由模板自算
        }

        [Test]
        public void Scalar_References_Match_Legacy_Vba()
        {
            var writes = Build();

            Assert.That(Formula(writes, "G36"), Is.EqualTo("=Data!BL9"));    // Unit  = 5+4
            Assert.That(Formula(writes, "C53"), Is.EqualTo("=Data!BL13"));   // Range = 5+8
            Assert.That(Formula(writes, "C54"), Is.EqualTo("=Data!BL11"));   // Mean  = 5+6
            Assert.That(Formula(writes, "C55"), Is.EqualTo("=Data!BL14"));   // STD   = 5+9
            Assert.That(Formula(writes, "C56"), Is.EqualTo("=Data!BL15"));   // CPK   = 5+10
            Assert.That(Formula(writes, "D36"), Is.EqualTo("=Data!BL7"));    // LSL   = 5+2
            Assert.That(Formula(writes, "E36"), Is.EqualTo("=Data!BL8"));    // HSL   = 5+3
            Assert.That(Formula(writes, "D37"), Is.EqualTo("=Data!BL10"));   // Min   = 5+5
            Assert.That(Formula(writes, "E37"), Is.EqualTo("=Data!BL12"));   // Max   = 5+7
            Assert.That(Formula(writes, "D39"), Is.EqualTo("=Data!BL11-3*Data!BL14"));
            Assert.That(Formula(writes, "E39"), Is.EqualTo("=Data!BL11+3*Data!BL14"));
            Assert.That(Formula(writes, "D40"), Is.EqualTo("=Data!BL11-6*Data!BL14"));
            Assert.That(Formula(writes, "E40"), Is.EqualTo("=Data!BL11+6*Data!BL14"));
        }

        [Test]
        public void Total_Write_Count_Is_Ladder_Plus_3_All_Site_Plus_8x3_Site_Plus_13_Scalars()
        {
            Assert.That(Build().Count, Is.EqualTo(1 + 3 + 24 + 13));
        }
    }
}
