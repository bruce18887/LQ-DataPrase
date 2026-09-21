"""grep 档与客户端档的**结果集平价**（spec §3.3 的核心不变量）。

为什么单独一个文件：这条主张与「我们会发出什么命令」（test_sftp_search_grep.py）不是一
回事 —— 那里钉注入与选项形状，这里钉**两档必须给出同一个文件集合**。它还要多引进参照档
``walker`` 与一份 glob 复算器，塞进 grep 那个文件会把两边都推过 600 行上限。

假 SFTP 服务器只有 SFTP 子系统、没有 shell exec（spec §4.5），所以「跑一遍两档比结果」
在自动化里做不到。做法是：把 :func:`shell_grep.grep_stream` **真正发给远端的那条命令**
解出来，用 :mod:`fnmatch` 在样本文件名/目录名上复算一遍「grep 会保留哪些条目」，与参照档
:func:`walker.passes_metadata` / :func:`walker.is_pruned` 的判定逐个比。

两条实测（GNU grep 3.0，结论同步写在 :mod:`apps.sftp.search.filters`）：

- ``--include``/``--exclude`` 是一张**按命令行顺序求值、最后命中的那条决定去留**的规则表
  （不是「exclude 恒压 include」）。命令构造因此把 include 全排在 exclude 之前 —— 那是
  唯一在「最后命中者」与「exclude 恒压 include」两种语义下同解的排法。排反的后果实测过：
  16 个文件全回来，walker 侧只有 6 个。
- ``--exclude`` 只作用于文件、``--exclude-dir`` 只作用于目录 → dot 规则必须两条都出。

跑法：python manage.py test test.backend.test_sftp_search_parity
"""
import os
import posixpath
import shlex
import sys
from fnmatch import fnmatch, fnmatchcase

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp.search import contracts, shell_grep, walker  # noqa: E402


def spec(**over):
    base = {'roots': ['/data'], 'mode': 'content', 'term': 'ShadowReg2'}
    base.update(over)
    return contracts.parse_spec(base)


def flags(cmd):
    """只看选项区（第一个 ``--`` 之前）的 argv。"""
    head = shlex.split(cmd)
    return head[:head.index('--')] if '--' in head else head


class _Recorder:
    """只记命令的假 exec channel：``grep_stream`` 一进来就 ``exec_command``。

    拿「实际发出去的那条命令」而不是「测试自己重算一遍分支后的命令」——分支判据
    （``filters.needs_find``）本身也是被测对象，测试里重算等于跟着实现的假设走。
    """

    def __init__(self):
        self.commands = []

    def exec_command(self, cmd):
        self.commands.append(cmd)

    def makefile(self, *a, **k):
        return self

    def readline(self):
        return b''

    def recv_exit_status(self):
        return 1                                  # 1 = 没命中，正常收尾（>=2 才会抛）

    def close(self):
        pass

    def settimeout(self, seconds):
        pass


def sent_command(s):
    recorder = _Recorder()
    list(shell_grep.grep_stream(recorder, s))
    return recorder.commands[0]


def _option_values(argv, name):
    pre = f'{name}='
    return [t[len(pre):] for t in argv if t.startswith(pre)]


def selector(cmd):
    """把命令解成 ``(keep(文件名, 上层目录名元组), enters(目录名))`` 两个谓词。

    - grep 分支：按 argv 原序读 ``--include`` / ``--exclude``（最后命中者决定），
      ``--exclude-dir`` 单独判目录。
    - find 分支：只认 ``shell_grep`` 产出的固定形状
      ``find <roots> ( -type d ( -name G -o ... ) -prune ) -o ( -type f [! ] -name/-iname G ... )``。
      ``-size``/``-newermt`` 复算时恒真是刻意的：平价样本不带大小/时间条件，那两条
      与 walker 的对应关系由 test_sftp_search_walk.py 在 Python 侧钉。
    """
    argv = shlex.split(cmd.split('|')[0])
    if argv[0] == 'find':
        at = 1
        while at < len(argv) and argv[at].startswith('/'):
            at += 1                              # contracts 保证 roots 全是绝对路径
        argv = argv[at:]
        cut = argv.index('-prune')
        before = argv[:cut]
        prune_globs = [before[i + 1] for i, t in enumerate(before) if t == '-name']
        body = argv[cut + 1:]
        rules = [(t, body[i + 1], body[i - 1] == '!') for i, t in enumerate(body)
                 if t in ('-name', '-iname') and i + 1 < len(body)]

        def keep(name, dirs=()):
            if any(any(fnmatchcase(d, glob) for d in dirs) for glob in prune_globs):
                return False
            for kind, glob, negated in rules:
                hit = (fnmatchcase(name, glob) if kind == '-name'
                       else fnmatch(name, glob))
                if hit == negated:
                    return False
            return True

        def enters(dirname):
            return not any(fnmatchcase(dirname, glob) for glob in prune_globs)
        return keep, enters

    argv = flags(cmd)
    exclude_dirs = _option_values(argv, '--exclude-dir')
    file_rules = [(t[len(prefix):], prefix == '--include=')
                  for t in argv for prefix in ('--include=', '--exclude=')
                  if t.startswith(prefix)]

    def keep_grep(name, dirs=()):
        if any(fnmatchcase(d, glob) for d in dirs for glob in exclude_dirs):
            return False
        for glob, is_include in reversed(file_rules):
            if fnmatchcase(name, glob):
                return is_include
        return not any(is_include for _glob, is_include in file_rules)

    def enters_grep(dirname):
        return not any(fnmatchcase(dirname, glob) for glob in exclude_dirs)
    return keep_grep, enters_grep


class WalkerParityTests(SimpleTestCase):
    NAMES = ('RT_001.csv', 'DATA.CSV', 'A.Csv', 'Sum_1.csv', 'sum_1.csv', 'SUM_9.CSV',
             'sUm_x.csv', 'summary.csv', 'sumx.csv', 'notes.txt', 'csv', 'a.csv.bak',
             'x..csv', 'b.csv.', 'log.csv.gz', 'READ.ME', '.hidden.csv', '.csv')
    DIRS = ('batch1', 'cache', '.git', '.snapshot', 'Sum_dir', 'backup_2020', 'a.b.c')
    SPECS = ({},
             {'data_files_only': False},
             {'prune_dirs': ['cache', '*bak*']},
             {'prune_dirs': ['Sum_dir'], 'data_files_only': False},
             {'name_pattern': 'RT_*'},
             {'name_pattern': '*.txt', 'data_files_only': False},
             {'name_pattern': 'RT_*', 'prune_dirs': ['cache', 'batch?']})

    def test_command_selects_exactly_what_walker_selects(self):
        for over in self.SPECS:
            s = spec(**over)
            keep, enters = selector(sent_command(s))

            def walker_enters(dirname, spec_=s):
                return not (walker.is_pruned(dirname, spec_.prune_dirs)
                            or dirname.startswith('.'))

            # 命令侧 keep(文件, 上层目录) 对应 walker 的两件事：那条目录要进得去，且文件
            # 本身过 passes_metadata。少乘一半就会把「被剪子树里的文件」当成应有候选。
            for name in self.NAMES:
                with self.subTest(**over, name=name):
                    self.assertEqual(
                        keep(name, ('batch1',)),
                        walker.passes_metadata(name, None, None, s)
                        and walker_enters('batch1'),
                        f'两档对 {name!r} 的取舍不同：{sent_command(s)}')
            for dirname in self.DIRS:
                with self.subTest(**over, dirname=dirname):
                    self.assertEqual(enters(dirname), walker_enters(dirname))

    def test_globs_also_match_the_documented_definitions(self):
        """上一条拿 walker 当参照，两档一起漂移测不出来 → 再拿字面定义核一遍。

        字面定义另有两个出处：汇总 CSV 是 ``_helpers.py:71`` 的
        ``basename(filename).lower().startswith('sum_')``，dot 跳过是 ``views.py:537``
        ``_collect_files`` 的 ``name.startswith('.')``。
        """
        keep = selector(sent_command(spec()))[0]
        for name in self.NAMES:
            documented = (not name.startswith('.')
                          and posixpath.splitext(name)[1].lower() == '.csv'
                          and not name.lower().startswith('sum_'))
            with self.subTest(name=name):
                self.assertEqual(keep(name, ()), documented)

    def test_summary_and_csv_globs_are_the_bracket_spellings(self):
        """grep 的 ``--exclude``/``--include`` 大小写敏感 → 必须逐字母 bracket。"""
        cmd = sent_command(spec())
        self.assertIn("--exclude='[sS][uU][mM]_*'", cmd)
        self.assertIn("--include='*.[cC][sS][vV]'", cmd)

    def test_dot_rule_emits_both_a_file_and_a_directory_exclude(self):
        argv = flags(sent_command(spec()))
        self.assertIn('--exclude=.*', argv)
        self.assertIn('--exclude-dir=.*', argv)

    def test_file_rules_put_every_include_before_every_exclude(self):
        """排法本身也是平价断言（见模块 docstring 的第一条实测）。"""
        argv = flags(sent_command(spec()))
        kinds = [t.split('=', 1)[0] for t in argv
                 if t.startswith('--include=') or t.startswith('--exclude=')]
        self.assertEqual(kinds, sorted(kinds, key=lambda kind: kind != '--include='),
                         f'--include 必须全部排在 --exclude 之前：{kinds}')

    def test_prune_patterns_each_become_one_quoted_exclude_dir(self):
        """每条 ``prune_dirs`` 各一个 ``--exclude-dir``，且照旧过 ``shlex.quote``。"""
        s = spec(prune_dirs=['cache', '$(id)', 'a b'], data_files_only=False)
        cmd = sent_command(s)
        for glob in ('cache', '$(id)', 'a b'):
            self.assertIn(f'--exclude-dir={shlex.quote(glob)}', cmd)
        argv = flags(cmd)
        self.assertEqual(_option_values(argv, '--exclude-dir'),
                         ['.*', 'cache', '$(id)', 'a b'])

    def test_find_branch_translates_the_same_three_rules(self):
        """find 分支用谓词，不走 ``--exclude``；三条规则同样得在。"""
        keep, enters = selector(sent_command(
            spec(prune_dirs=['cache'], modified_after='2026-09-01')))
        self.assertFalse(enters('.snapshot'))
        self.assertTrue(enters('batch1'))
        self.assertFalse(keep('.hidden.csv', ()))
        self.assertFalse(keep('Sum_1.CSV', ()))
        self.assertFalse(keep('notes.txt', ()))
        self.assertTrue(keep('DATA.CSV', ()))
        self.assertFalse(keep('RT_1.csv', ('cache',)))

    def test_grep_branch_never_carries_two_includes(self):
        """两条 ``--include`` 是并集而非交集，出现即说明求交被错误地塞进了 grep 分支。"""
        for over in self.SPECS:
            s = spec(**over)
            cmd = sent_command(s)
            if cmd.startswith('find '):
                continue
            with self.subTest(**over):
                self.assertLessEqual(
                    len([t for t in flags(cmd) if t.startswith('--include=')]), 1)

    def test_name_pattern_intersecting_csv_goes_to_find_branch(self):
        """``name_pattern`` ∩「仅数据文件」：grep 分支装不下，必须整条改走 find。"""
        cmd = sent_command(spec(name_pattern='*RT*.csv'))
        self.assertTrue(cmd.startswith('find '), cmd)
        self.assertIn("-name '*RT*.csv'", cmd)
        self.assertIn("-iname '*.csv'", cmd)
        self.assertIn("! -iname 'sum_*'", cmd.replace("'!' ", "! "))


class RootExclusionGuardTests(SimpleTestCase):
    """``--exclude-dir`` / ``-prune`` 会命中**命令行上那个根目录本身**（实测 grep 3.0
    与 find 同），而 walker 永远会进根目录（剪枝与 dot 规则只判 listing 里的条目）。
    根目录名撞上目录排除模式时两档无法平价，命令构造必须拒绝而不是安静给出 0 命中。
    """

    def test_root_named_like_a_prune_pattern_is_refused(self):
        with self.assertRaises(ValueError):
            shell_grep.build_command(spec(roots=['/data/backup'],
                                          prune_dirs=['backup*']), use_find=False)

    def test_hidden_root_is_refused(self):
        with self.assertRaises(ValueError):
            shell_grep.build_command(spec(roots=['/data/.snapshot']), use_find=False)

    def test_hidden_root_is_refused_on_find_branch_too(self):
        with self.assertRaises(ValueError):
            shell_grep.build_command(spec(roots=['/data/.snapshot'],
                                          modified_after='2026-09-01'), use_find=True)

    def test_only_the_last_component_of_the_root_is_guarded(self):
        """中间层目录名撞上剪枝模式不要紧：两档都会进那个根（实测 grep 只判 basename）。"""
        cmd = shell_grep.build_command(spec(roots=['/data/backup/lot12'],
                                            prune_dirs=['backup']), use_find=False)
        self.assertIn('--exclude-dir=backup', flags(cmd))
