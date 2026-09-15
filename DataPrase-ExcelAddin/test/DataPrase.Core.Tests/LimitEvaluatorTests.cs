using DataPrase.Core;
using NUnit.Framework;

namespace DataPrase.Core.Tests
{
    [TestFixture]
    public class LimitEvaluatorTests
    {
        [TestCase(null, false)]
        [TestCase("", false)]
        [TestCase(1d, false)]
        [TestCase("1", false)]
        [TestCase(2d, true)]
        [TestCase("2", true)]
        [TestCase(0d, true)]
        public void IsFailBin_Matches_Vba_Bin_Rule(object binValue, bool expected)
        {
            Assert.That(LimitEvaluator.IsFailBin(binValue), Is.EqualTo(expected));
        }

        [TestCase(0.5, CellMark.OutOfLimit)]
        [TestCase(1.0, CellMark.LimitHit)]
        [TestCase(1.5, CellMark.None)]
        [TestCase(2.0, CellMark.LimitHit)]
        [TestCase(3.0, CellMark.OutOfLimit)]
        public void EvaluateCell_Classifies_Value(double value, CellMark expected)
        {
            var item = new TestItem("Vth", "V", 1.0, 2.0);
            Assert.That(LimitEvaluator.EvaluateCell(value, item), Is.EqualTo(expected));
        }

        [Test]
        public void EvaluateCell_Skips_Blank_And_Empty_String()
        {
            var item = new TestItem("Vth", "V", 1.0, 2.0);
            Assert.That(LimitEvaluator.EvaluateCell(null, item), Is.EqualTo(CellMark.None));
            Assert.That(LimitEvaluator.EvaluateCell(string.Empty, item), Is.EqualTo(CellMark.None));
        }

        [Test]
        public void EvaluateCell_No_Limit_Item_Never_Marks()
        {
            var item = new TestItem("Dut_Pass", "", 0d, 0d);
            Assert.That(item.HasNoLimit, Is.True);
            Assert.That(LimitEvaluator.EvaluateCell(99d, item), Is.EqualTo(CellMark.None));
        }

        [Test]
        public void EvaluateCell_Equal_Both_Sides_Is_Not_LimitHit()
        {
            // VBA: lo == hi == v 时既不满足 LimitHit 两个子句，也不越限 → None。
            var item = new TestItem("X", "", 2.0, 2.0);
            Assert.That(item.HasNoLimit, Is.False);
            Assert.That(LimitEvaluator.EvaluateCell(2.0, item), Is.EqualTo(CellMark.None));
        }

        [Test]
        public void EvaluateCell_Numeric_String_Value_Is_Parsed()
        {
            var item = new TestItem("Vth", "V", 1.0, 2.0);
            Assert.That(LimitEvaluator.EvaluateCell("3", item), Is.EqualTo(CellMark.OutOfLimit));
        }
    }
}
