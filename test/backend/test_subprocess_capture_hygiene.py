"""源码扫描绊线：子进程的**文本捕获**必须显式给 encoding。

同族缺陷在本仓咬过三次（`docs/reference/testing-gates.md` §4）：`text=True` 而不给
`encoding=` 时按本机 locale（中文 Windows = cp936）解码，父进程一带 `PYTHONIOENCODING=utf-8`，
子进程那侧的 UTF-8 中文 traceback 会让 `_readerthread` 抛 `UnicodeDecodeError`，而该异常被
读取线程吞掉、`result.stderr` 落成 `None` —— 于是断言收到空串，红项写成
`not found in ''`，看着像产品缺字符串，其实是捕获层坏了。

判据承重的方式：先自证扫描器抓得住那个形状（合成脏片段），再证明它不冤枉正确写法，
最后才对全仓下断言。少了前两条，这条绊线可能永远在比一个空集合。

跑法：python manage.py test test.backend.test_subprocess_capture_hygiene
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parents[2]
SCANNED_ROOTS = ('test', 'scripts')
SKIP_DIRS = {'__pycache__', 'node_modules', 'dist'}

CALL_RE = re.compile(r'subprocess\.(?:run|Popen|check_output|call)\s*\(')

# 合成片段刻意写成两段拼接：源文本里 `subprocess.run` 后面紧跟的是引号而不是左括号，
# CALL_RE 扫不到本行，运行时拼出来的却正是那个危险形状。（不这么做的话，本文件会
# 把自己当成违规者抓出来 —— 收口时就撞上了这一条。）
BAD_ONE_LINE = "subprocess.run" + "(cmd, capture_output=True, text=True)"
BAD_MULTI_LINE = (
    "subprocess.Popen" + "(\n"
    "    [sys.executable, SERVER],\n"
    "    stdout=subprocess.PIPE, text=True)\n"
)
GOOD_WITH_ENCODING = (
    "subprocess.run" + "(cmd, capture_output=True, text=True,\n"
    "                   encoding='utf-8', errors='replace')"
)
GOOD_BINARY = "subprocess.run(cmd, capture_output=True)  # 没有 text=True，拿到的是 bytes"


def unclosed_text_captures(text: str) -> list:
    """返回「带 text=True 却没给 encoding=」的 subprocess 调用片段。

    括号平衡地取实参，因为线上那次真形态就是跨行的 `Popen(...)`；按行扫会漏。
    """
    found = []
    for m in CALL_RE.finditer(text):
        start = m.end() - 1
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '(':
                depth += 1
            elif text[i] == ')':
                depth -= 1
                if depth == 0:
                    seg = text[start:i + 1]
                    if 'text=True' in seg and 'encoding=' not in seg:
                        found.append(seg)
                    break
    return found


class ScannerSelfTests(SimpleTestCase):
    """扫描器自己先得当用 —— 否则下面那条全仓断言是在比空集合。"""

    def test_catches_the_documented_shape(self):
        self.assertEqual(1, len(unclosed_text_captures(BAD_ONE_LINE)))

    def test_catches_the_multiline_shape(self):
        """按行扫的写法会漏掉这一种：`text=True` 和 `subprocess.Popen(` 不在同一行。"""
        self.assertEqual(1, len(unclosed_text_captures(BAD_MULTI_LINE)))

    def test_does_not_flag_the_fixed_shape(self):
        self.assertEqual([], unclosed_text_captures(GOOD_WITH_ENCODING))

    def test_does_not_flag_binary_capture(self):
        """不带 text=True 时拿到的是 bytes，本来就没有解码问题 —— 别把它也算成红。"""
        self.assertEqual([], unclosed_text_captures(GOOD_BINARY))


class RepoCaptureHygieneTests(SimpleTestCase):
    def test_no_text_capture_in_scanned_roots_omits_encoding(self):
        offenders = []
        for root in SCANNED_ROOTS:
            base = REPO / root
            if not base.is_dir():
                continue
            for path in sorted(base.rglob('*.py')):
                if SKIP_DIRS & set(path.parts):
                    continue
                if unclosed_text_captures(path.read_text(encoding='utf-8', errors='replace')):
                    offenders.append(path.relative_to(REPO).as_posix())
        self.assertEqual(
            [], offenders,
            '这些文件捕获子进程文本时没给 encoding=，父进程一带 PYTHONIOENCODING '
            '就会把中文 traceback 解成 None（testing-gates §4）')
