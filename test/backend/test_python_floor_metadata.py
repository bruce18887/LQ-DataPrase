"""T1：Python 版本下限三处口径必须同源，且不得比已安装依赖自身的要求更宽松。

起因（2026-10-24）：`pyproject.toml` 写 `requires-python = ">=3.11"`、README 写「Python 3.11+」，
而当天钉上的 Django 6.0.9 wheel 元数据是 `Requires-Python: >=3.12` —— 等于对外声明了一个
pip 根本装不上来的下限。`contourpy` 同样要 3.12。

判据承重：先自证比较器（宽松的声明必须被判成不合格、相等与更严必须放行），
再对真元数据下断言。没有前三条，这条绊线可能在比一个恒真的式子。

跑法：python manage.py test test.backend.test_python_floor_metadata
"""
import importlib.metadata
import re
from pathlib import Path

from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parents[2]
FLOOR_RE = re.compile(r'>=\s*(\d+)\.(\d+)')


def parse_floor(text: str):
    """取 `>=X.Y` 里最严的那个下限；没有下限时返回 None。"""
    pairs = FLOOR_RE.findall(text or '')
    if not pairs:
        return None
    return max((int(major), int(minor)) for major, minor in pairs)


def declared_floor_of_pyproject() -> str:
    src = (REPO / 'pyproject.toml').read_text(encoding='utf-8')
    m = re.search(r'^requires-python\s*=\s*"([^"]+)"', src, re.M)
    if not m:
        raise AssertionError('pyproject.toml 里没有 requires-python 这一行')
    return m.group(1)


def declared_floor_of_readme() -> str:
    src = (REPO / 'README.md').read_text(encoding='utf-8')
    m = re.search(r'-\s*Python\s+(\d+)\.(\d+)\+', src)
    if not m:
        raise AssertionError('README「环境要求」里找不到 Python 下限那一行')
    return f'>={m.group(1)}.{m.group(2)}'


def strictest_installed_floor():
    """已安装依赖里最严的 Requires-Python（本仓分发的是二进制，用户装的就是这一组）。"""
    floors = []
    for dist in importlib.metadata.distributions():
        floor = parse_floor(dist.metadata.get('Requires-Python') or '')
        if floor:
            floors.append(floor)
    return max(floors)


class ComparatorSelfTests(SimpleTestCase):
    """比较器先自证 —— 否则后面的断言可能永远为真。"""

    def test_detects_a_too_loose_declaration(self):
        self.assertLess(parse_floor('>=3.11'), parse_floor('>=3.12'),
                        '3.11 的声明挡住不住 3.12 的要求，这条必须被测出来')

    def test_equal_and_stricter_declarations_pass(self):
        self.assertEqual(parse_floor('>=3.12'), parse_floor('>=3.12'))
        self.assertGreater(parse_floor('>=3.13'), parse_floor('>=3.12'))

    def test_handles_bounds_and_missing_floor(self):
        self.assertEqual((3, 12), parse_floor('>=3.12,<4.0'))
        self.assertIsNone(parse_floor(''))
        self.assertIsNone(parse_floor('~=3.12'))   # 没有 >= 时不参与比较


class FloorConsistencyTests(SimpleTestCase):
    def test_pyproject_is_not_looser_than_installed_dependencies(self):
        declared = parse_floor(declared_floor_of_pyproject())
        required = strictest_installed_floor()
        self.assertIsNotNone(declared)
        self.assertGreaterEqual(
            declared, required,
            f'pyproject 声明 >= {declared[0]}.{declared[1]}，但已安装依赖里有 '
            f'{required[0]}.{required[1]} 的硬下限 —— 照着声明装会当场失败')

    def test_readme_agrees_with_pyproject(self):
        """散文与元数据各写一份下限，就是这次漂移的成因；两条必须逐字相等。"""
        self.assertEqual(declared_floor_of_readme(), declared_floor_of_pyproject())

    def test_running_interpreter_satisfies_the_declaration(self):
        declared = parse_floor(declared_floor_of_pyproject())
        import sys
        self.assertGreaterEqual(sys.version_info[:2], declared,
                                f'当前解释器 {sys.version_info[:2]} 低于声明的下限 {declared}')

    def test_the_floor_is_pinned_where_the_build_actually_reads_it(self):
        """CI 读 `.python-version`，不是 pyproject —— 两个值的关系必须是「实测 ≥ 声明」。"""
        ver_file = REPO / '.python-version'
        self.assertTrue(ver_file.is_file(), 'CI 的 python-version-file 指向它（.github/workflows/ci.yml）')
        built = tuple(int(x) for x in ver_file.read_text(encoding='utf-8').strip().split('.')[:2])
        declared = parse_floor(declared_floor_of_pyproject())
        self.assertGreaterEqual(built, declared)
