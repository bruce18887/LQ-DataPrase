using DataPrase.Core;
using NUnit.Framework;

namespace DataPrase.Core.Tests
{
    [TestFixture]
    public class ColumnNamesTests
    {
        [TestCase(1, "A")]
        [TestCase(2, "B")]
        [TestCase(26, "Z")]
        [TestCase(27, "AA")]
        [TestCase(28, "AB")]
        [TestCase(52, "AZ")]
        [TestCase(53, "BA")]
        [TestCase(702, "ZZ")]
        [TestCase(703, "AAA")]
        public void ToLetter_Converts_Like_Vba(int columnNumber, string expected)
        {
            Assert.That(ColumnNames.ToLetter(columnNumber), Is.EqualTo(expected));
        }

        [TestCase("A", 1)]
        [TestCase("Z", 26)]
        [TestCase("AA", 27)]
        [TestCase("$C", 3)]
        [TestCase("$F", 6)]
        [TestCase("$AA", 27)]
        [TestCase("c", 3)]
        [TestCase("A1", 0)]
        [TestCase("", 0)]
        [TestCase("$", 0)]
        public void ToNumber_Parses_Column_Ref(string columnRef, int expected)
        {
            Assert.That(ColumnNames.ToNumber(columnRef), Is.EqualTo(expected));
        }
    }
}
