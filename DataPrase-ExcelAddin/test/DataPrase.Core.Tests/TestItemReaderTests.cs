using DataPrase.Core;
using NUnit.Framework;

namespace DataPrase.Core.Tests
{
    [TestFixture]
    public class TestItemReaderTests
    {
        // CTA8290D（index 1）：TestItemStartIndex=14，Low=2/High=3/Unit=1（相对 Test Name 行）
        private static TesterSpec Cta { get { return TesterRegistry.Specs[1]; } }

        private static ICellReader Sheet()
        {
            return new SheetBuilder(15, 20)
                .Set(1, 1, "[GENERAL]")
                .Set(3, 1, "Serial_No")
                .Set(3, 14, "ItemA")
                .Set(3, 15, "ItemB")
                .Set(4, 14, "V")     // unit
                .Set(5, 14, 1.0)     // low
                .Set(6, 14, 2.0)     // high
                .Column(1, 7, "x", "x", "x", "x")
                .Build();
        }

        private static LayoutResult Layout()
        {
            return DatalogLayout.Compute(Cta, 1, Sheet(), reCalibrate: false);
        }

        [Test]
        public void Reads_Test_Name_Unit_And_Limits()
        {
            var items = TestItemReader.Read(Layout(), Cta, Sheet());

            Assert.That(items[14].TestName, Is.EqualTo("ItemA"));
            Assert.That(items[14].Unit, Is.EqualTo("V"));
            Assert.That(items[14].LowLimit, Is.EqualTo(1.0));
            Assert.That(items[14].HighLimit, Is.EqualTo(2.0));
            Assert.That(items[14].HasNoLimit, Is.False);
        }

        [Test]
        public void Blank_Limits_Yield_NoLimit_Item()
        {
            var items = TestItemReader.Read(Layout(), Cta, Sheet());

            Assert.That(items[15].TestName, Is.EqualTo("ItemB"));
            Assert.That(items[15].Unit, Is.EqualTo(string.Empty));
            Assert.That(items[15].HasNoLimit, Is.True);
        }

        [Test]
        public void Single_Space_Limit_Cell_Is_Treated_As_Unset()
        {
            var sheet = new SheetBuilder(15, 20)
                .Set(1, 1, "[GENERAL]")
                .Set(3, 1, "Serial_No")
                .Set(3, 14, "ItemA")
                .Set(5, 14, " ")     // 恰为单个空格 → VBA 不赋值
                .Set(6, 14, 5.0)
                .Column(1, 7, "x", "x", "x", "x")
                .Build();

            var layout = DatalogLayout.Compute(Cta, 1, sheet, reCalibrate: false);
            var items = TestItemReader.Read(layout, Cta, sheet);

            Assert.That(items[14].LowLimit, Is.EqualTo(0.0));
            Assert.That(items[14].HighLimit, Is.EqualTo(5.0));
        }
    }
}
