using System.Collections.Generic;
using System.Linq;
using DataPrase.Core;
using NUnit.Framework;

namespace DataPrase.Core.Tests
{
    [TestFixture]
    public class MarkPlannerTests
    {
        private static TesterSpec Cta { get { return TesterRegistry.Specs[1]; } }   // Bin=$F(6)

        // 第 3 行=Test Name（列 14/15）；数据行 7..10；col6=Bin；col14 限值 1..2；col15 无限制
        private static ICellReader Sheet()
        {
            return new SheetBuilder(15, 20)
                .Set(1, 1, "[GENERAL]")
                .Set(3, 1, "Serial_No")
                .Set(3, 14, "ItemA")
                .Set(3, 15, "ItemB")
                .Set(5, 14, 1.0)
                .Set(6, 14, 2.0)
                .Column(1, 7, "x", "x", "x", "x")        // 数据行标记（供终止判定）
                .Set(7, 6, 1d)                            // Bin=1 pass
                .Set(8, 6, 2d)                            // Bin=2 fail
                .Set(9, 6, 1d)                            // Bin=1 pass
                .Set(10, 6, 3d)                           // Bin=3 fail
                .Set(7, 14, 1.5)
                .Set(8, 14, 3.0)                          // 越上限
                .Set(9, 14, 1.0)                          // 压限，但该行 Bin 为 pass → 不标记
                .Set(10, 14, 2.0)                         // 压上限
                .Set(8, 15, 999.0)                        // ItemB 无限制 → 永不标记
                .Build();
        }

        private static MarkPlan Plan()
        {
            var sheet = Sheet();
            var layout = DatalogLayout.Compute(Cta, 1, sheet, reCalibrate: false);
            IDictionary<int, TestItem> items = TestItemReader.Read(layout, Cta, sheet);
            return MarkPlanner.Build(layout, Cta, items, sheet);
        }

        [Test]
        public void FailBinRows_Are_Only_Non_Pass_Bins()
        {
            Assert.That(Plan().FailBinRows, Is.EqualTo(new[] { 8, 10 }));
        }

        [Test]
        public void Only_Fail_Bin_Rows_Contribute_Marks()
        {
            var cells = Plan().Cells;

            Assert.That(cells.Select(c => c.Row).Distinct(), Is.EquivalentTo(new[] { 8, 10 }));
        }

        [Test]
        public void Classifies_OutOfLimit_And_LimitHit()
        {
            var cells = Plan().Cells.ToList();

            Assert.That(cells, Has.Count.EqualTo(2));
            Assert.That(cells[0].Row, Is.EqualTo(8));
            Assert.That(cells[0].Column, Is.EqualTo(14));
            Assert.That(cells[0].Mark, Is.EqualTo(CellMark.OutOfLimit));
            Assert.That(cells[1].Row, Is.EqualTo(10));
            Assert.That(cells[1].Column, Is.EqualTo(14));
            Assert.That(cells[1].Mark, Is.EqualTo(CellMark.LimitHit));
        }

        [Test]
        public void NoLimit_Item_Is_Never_Marked()
        {
            Assert.That(Plan().Cells.Any(c => c.Column == 15), Is.False);
        }
    }
}
