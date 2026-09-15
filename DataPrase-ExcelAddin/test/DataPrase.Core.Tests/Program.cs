using System;
using System.Reflection;
using NUnitLite;

namespace DataPrase.Core.Tests
{
    /// <summary>
    /// NUnitLite 自包含测试入口：直接运行 exe 即执行全部用例（无需 vstest/dotnet SDK）。
    /// 用法：DataPrase.Core.Tests.exe [--where ...] [--labels=All]
    /// </summary>
    public static class Program
    {
        [STAThread]
        public static int Main(string[] args)
        {
            return new AutoRun(Assembly.GetExecutingAssembly()).Execute(args);
        }
    }
}
