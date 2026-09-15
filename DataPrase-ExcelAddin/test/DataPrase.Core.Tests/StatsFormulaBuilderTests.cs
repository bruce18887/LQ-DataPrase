using DataPrase.Core;
using NUnit.Framework;

namespace DataPrase.Core.Tests
{
    [TestFixture]
    public class StatsFormulaBuilderTests
    {
        [Test]
        public void Ets88_Column_B_Formulas_Match_Legacy_Vba()
        {
            var ets = TesterRegistry.Specs[0];   // low2 high3 min5 mean6 max7 std9 cpk10
            var formulas = StatsFormulaBuilder.BuildDataSheetFormulas(
                columnLetter: "B",
                testNameRow: 5,
                dataStartRow: 11,
                dataStopRow: 14,
                spec: ets);

            Assert.That(formulas.Min, Is.EqualTo("=SUBTOTAL(105,B11:B14)"));
            Assert.That(formulas.Average, Is.EqualTo("=SUBTOTAL(101,B11:B14)"));
            Assert.That(formulas.Max, Is.EqualTo("=SUBTOTAL(104,B11:B14)"));
            Assert.That(formulas.Range, Is.EqualTo("=B12-B10"));   // datalog Max - datalog Min
            Assert.That(formulas.Std, Is.EqualTo("=SUBTOTAL(108,B11:B14)"));
            Assert.That(formulas.Cpk,
                Is.EqualTo("=IF(OR(B14=0,AND(B7=\"\",B8=\"\")),\"\",MIN((B11-B7)/3/B14,(B8-B11)/3/B14))"));
        }

        [Test]
        public void Multi_Letter_Column_Letter_Is_Prefixed_Directly()
        {
            var ets = TesterRegistry.Specs[0];
            var formulas = StatsFormulaBuilder.BuildDataSheetFormulas("AA", 5, 11, 14, ets);

            Assert.That(formulas.Min, Is.EqualTo("=SUBTOTAL(105,AA11:AA14)"));
            Assert.That(formulas.Cpk, Does.Contain("AA14=0"));
        }

        [Test]
        public void Reversed_Low_High_Offsets_Are_Reflected_In_Cpk_Cells()
        {
            var last = TesterRegistry.Specs[4];  // low3 high2 → LSL 在 HSL 下方
            var formulas = StatsFormulaBuilder.BuildDataSheetFormulas("C", 10, 20, 25, last);

            // TestNameRow=10 → LSL=C13、HSL=C12；Mean=C16；STD=C19；CPK=C20
            Assert.That(formulas.Cpk, Does.Contain("C19=0"));
            Assert.That(formulas.Cpk, Does.Contain("AND(C13=\"\",C12=\"\")"));
            Assert.That(formulas.Cpk, Does.Contain("MIN((C16-C13)/3/C19,(C12-C16)/3/C19)"));
        }
    }
}
