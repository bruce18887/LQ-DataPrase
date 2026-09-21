"""grep 命令构造与能力探测（spec §3.6）。

全项目唯一拼 shell 命令字符串的模块，所以注入断言是这里的主菜。
测的是「我们会发出什么命令」，不是「grep 真跑出什么」——后者见 Task 11 人工验证。

跑法：python manage.py test test.backend.test_sftp_search_grep
"""
import os
import shlex
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp.search import contracts, shell_grep  # noqa: E402


def spec(**over):
    base = {'roots': ['/data'], 'mode': 'content', 'term': 'ShadowReg2'}
    base.update(over)
    return contracts.parse_spec(base)


def flags(cmd):
    """只看选项区（第一个 `--` 之前）的 argv，避免被路径与内容干扰断言。"""
    head = shlex.split(cmd)
    return head[:head.index('--')] if '--' in head else head


class CommandShapeTests(SimpleTestCase):
    def test_always_fixed_string(self):
        """-F 在，term 才永远是字面量，正则元字符不改变行为。"""
        self.assertIn('-F', flags(shell_grep.build_command(
            spec(term='.*|[a-z]+'), use_find=False)))

    def test_recursive_line_number_and_filename(self):
        f = flags(shell_grep.build_command(spec(), use_find=False))
        for flag in ('-r', '-n', '-H', '-a'):
            self.assertIn(flag, f)

    def test_match_limit_one_when_first_hit_only(self):
        f = flags(shell_grep.build_command(spec(), use_find=False))
        self.assertEqual(f[f.index('-m') + 1], '1')

    def test_match_limit_carries_max_when_all_wanted(self):
        s = spec(first_hit_per_file=False, max_matches=37)
        f = flags(shell_grep.build_command(s, use_find=False))
        self.assertEqual(f[f.index('-m') + 1], '37')

    def test_case_insensitive_by_default(self):
        self.assertIn('-i', flags(shell_grep.build_command(spec(), use_find=False)))

    def test_case_sensitive_drops_i(self):
        self.assertNotIn('-i', flags(shell_grep.build_command(
            spec(case_sensitive=True), use_find=False)))

    def test_whole_word_adds_w(self):
        self.assertIn('-w', flags(shell_grep.build_command(
            spec(matching='whole_word'), use_find=False)))

    def test_include_only_with_pattern(self):
        with_pat = shell_grep.build_command(spec(name_pattern='*RT*.csv'),
                                            use_find=False)
        without = shell_grep.build_command(spec(), use_find=False)
        self.assertTrue(any(t.startswith('--include=') for t in flags(with_pat)))
        self.assertFalse(any(t.startswith('--include=') for t in flags(without)))

    def test_lc_all_c_prefix(self):
        self.assertTrue(shell_grep.build_command(spec(), use_find=False)
                        .startswith('LC_ALL=C '))

    def test_find_variant_for_time_filter(self):
        cmd = shell_grep.build_command(spec(modified_after='2026-09-01'),
                                       use_find=True)
        for piece in ('find ', '-newermt', '-print0', 'xargs -0 -r'):
            self.assertIn(piece, cmd)

    def test_empty_term_rejected(self):
        """select_engine 已保证非空，这里是第二道闸。"""
        s = contracts.parse_spec({'roots': ['/d'], 'mode': 'name'})
        with self.assertRaises(ValueError):
            shell_grep.build_command(s, use_find=False)


class InjectionTests(SimpleTestCase):
    EVIL_TERM = "x'; touch /tmp/pwn; #`id`$(id)"
    EVIL_PATTERN = '$(touch /tmp/pwn2)'
    # 不以 / 结尾：contracts._normalise_roots 的 posixpath.normpath 会削掉尾斜杠，
    # 计划原文的 '/data; rm -rf /' 到 spec.roots 里已经变成 '/data; rm -rf'，
    # 断言会钉在「路径归一」而不是「引号」上（见本次交付报告）。
    EVIL_ROOT = '/data; rm -rf /x'

    def test_term_round_trips_as_one_argv_token(self):
        tokens = shlex.split(shell_grep.build_command(
            spec(term=self.EVIL_TERM), use_find=False))
        self.assertEqual(tokens[tokens.index('-e') + 1], self.EVIL_TERM)

    def test_term_metacharacters_not_reinterpreted(self):
        cmd = shell_grep.build_command(spec(term=self.EVIL_TERM), use_find=False)
        tokens = shlex.split(cmd)
        self.assertEqual([t for t in tokens if 'touch' in t], [self.EVIL_TERM])

    def test_term_starting_with_dash_is_a_value_not_a_flag(self):
        tokens = shlex.split(shell_grep.build_command(
            spec(term='-rf'), use_find=False))
        self.assertEqual(tokens[tokens.index('-e') + 1], '-rf')
        self.assertNotIn('-rf', tokens[:tokens.index('-e')])

    def test_name_pattern_quoted_as_one_token(self):
        cmd = shell_grep.build_command(spec(name_pattern=self.EVIL_PATTERN),
                                       use_find=False)
        self.assertTrue(any(t == f'--include={self.EVIL_PATTERN}'
                            for t in shlex.split(cmd)))
        self.assertNotIn('--include=$(', cmd)

    def test_root_quoted_and_last(self):
        tokens = shlex.split(shell_grep.build_command(
            spec(roots=[self.EVIL_ROOT]), use_find=False))
        self.assertEqual(tokens[-1], self.EVIL_ROOT)
        self.assertNotIn('rm', tokens[:-1])

    def test_root_with_space_preserved(self):
        tokens = shlex.split(shell_grep.build_command(
            spec(roots=['/data dir/sub']), use_find=False))
        self.assertEqual(tokens[-1], '/data dir/sub')

    def test_find_variant_quotes_paths_too(self):
        cmd = shell_grep.build_command(
            spec(roots=[self.EVIL_ROOT], modified_after='2026-09-01'),
            use_find=True)
        self.assertIn(shlex.quote(self.EVIL_ROOT), cmd)

    def test_prune_and_column_never_reach_the_command(self):
        """这两项只在客户端引擎用到；出现在 grep 命令里就是设计被绕过。"""
        cmd = shell_grep.build_command(
            spec(prune_dirs=['$(id)'], column_name='`id`'), use_find=False)
        self.assertNotIn('$(id)', cmd)
        self.assertNotIn('`id`', cmd)

    # —— 以下为计划外补充：Task 8 交付要求点名的三类载荷，逐条钉住 ——

    def test_term_with_command_substitution_payloads(self):
        """`x'; touch /tmp/pwn; #`：单引号闭合 + 命令替换，必须整体成一个 argv。"""
        term = "x'; touch /tmp/pwn; #"
        tokens = shlex.split(shell_grep.build_command(
            spec(term=term), use_find=False))
        self.assertEqual(tokens[tokens.index('-e') + 1], term)
        self.assertEqual([t for t in tokens if t in (';', '#', 'touch')], [])
        self.assertIn('-F', tokens)

    def test_name_pattern_with_glob_and_command_substitution(self):
        pattern = '*.$(id).csv'
        cmd = shell_grep.build_command(spec(name_pattern=pattern), use_find=False)
        # 命令串里它带着引号（未引的形态一出现就说明远端会自己去展开）；
        # shlex.split 解掉引号后必须正好还原成一个 argv。
        self.assertIn(f"--include={shlex.quote(pattern)}", cmd)
        self.assertNotIn(f"--include={pattern}", cmd)
        self.assertIn(f'--include={pattern}', shlex.split(cmd))

    def test_roots_with_backticks_and_newline_stay_single_tokens(self):
        """反引号与换行是最容易「看起来引用过了」的两种载荷。"""
        roots = ['/data/`id`', '/data/a\nb; echo pwn']
        tokens = shlex.split(shell_grep.build_command(
            spec(roots=roots), use_find=False))
        self.assertEqual(tokens[-len(roots):], roots)
        self.assertNotIn('id', tokens)
        self.assertNotIn('echo', tokens)

    def test_find_variant_quotes_pattern_dates_and_bang(self):
        """find 分支同样逐 token 引：`!` 在 bash 里是历史展开，也必须引。"""
        cmd = shell_grep.build_command(
            spec(roots=['/data/`id`'], name_pattern='$(id)*.csv',
                 modified_after='2026-09-01', modified_before='2026-09-30'),
            use_find=True)
        self.assertIn(shlex.quote('/data/`id`'), cmd)
        self.assertIn('-name ' + shlex.quote('$(id)*.csv'), cmd)
        self.assertIn(shlex.quote('!') + ' -newermt ', cmd)
        self.assertNotIn('-name $(id)', cmd)
        self.assertNotIn('-newermt $(', cmd)
        self.assertIn('-F', cmd.split('|')[1])

    def test_fixed_string_flag_survives_in_every_variant(self):
        """-F 不在，term 就被当正则解释：'.*' 会命中所有行。两档都必须带。"""
        for use_find in (False, True):
            cmd = shell_grep.build_command(
                spec(term='.*', modified_after='2026-09-01'), use_find=use_find)
            self.assertIn('-F', shlex.split(cmd), f'use_find={use_find} 丢了 -F')


class ParseLineTests(SimpleTestCase):
    def test_splits_path_line_content(self):
        self.assertEqual(
            shell_grep.parse_line(b'/data/a.csv:42:SN,ShadowReg2\r\n'),
            ('/data/a.csv', 42, b'SN,ShadowReg2'))

    def test_colons_inside_content_preserved(self):
        self.assertEqual(
            shell_grep.parse_line(b'/d/a.csv:7:StartTime,2026:09:01')[2],
            b'StartTime,2026:09:01')

    def test_colon_inside_path_splits_first_two_only(self):
        self.assertEqual(shell_grep.parse_line(b'/d/a:b.csv:3:hello'),
                         ('/d/a:b.csv', 3, b'hello'))

    def test_binary_marker_ignored(self):
        self.assertIsNone(shell_grep.parse_line(
            b'Binary file /data/a.csv matches'))

    def test_blank_line_ignored_without_logging(self):
        self.assertIsNone(shell_grep.parse_line(b''))

    def test_unparseable_line_warns_not_dropped_silently(self):
        """静默丢行就是静默漏结果。"""
        with self.assertLogs('apps.sftp.search.shell_grep', level='WARNING'):
            self.assertIsNone(shell_grep.parse_line(b'nonsense without colons'))

    def test_non_numeric_line_number_warns(self):
        with self.assertLogs('apps.sftp.search.shell_grep', level='WARNING'):
            self.assertIsNone(shell_grep.parse_line(b'/d/a.csv:x:hello'))

    def test_ambiguous_colon_in_path_warns_but_is_not_dropped(self):
        """文件名里带「:数字:」时冒号分词有歧义（计划 §6 风险表）。

        取最左候选继续给结果，但**必须留下 WARNING**——静默按错的 path 去 stat
        比丢一行更难查。
        """
        with self.assertLogs('apps.sftp.search.shell_grep', level='WARNING'):
            self.assertEqual(shell_grep.parse_line(b'/d/a:1:x.csv:5:hello'),
                             ('/d/a', 1, b'x.csv:5:hello'))


class _Chan:
    """最小 paramiko Channel 替身：按序回放 stdout，记录发过的命令。"""

    def __init__(self, replies, exit_status=0, stderr=b''):
        self.replies = list(replies)
        self.stderr = stderr
        self.commands = []
        self.exit_status = exit_status
        self.closed = False

    def exec_command(self, cmd):
        self.commands.append(cmd)

    def makefile(self, *a, **k):
        return self

    def read(self, n=-1):
        return self.replies.pop(0) if self.replies else b''

    def readline(self):
        return self.replies.pop(0) if self.replies else b''

    def recv_exit_status(self):
        return self.exit_status

    def close(self):
        self.closed = True


class ProbeTests(SimpleTestCase):
    def test_grep_available(self):
        chan = _Chan([b'grep (GNU grep) 3.7\n', b'find 4.9\nxargs 4.9\n',
                      b'MAPPING_OK\n', b''])
        self.assertTrue(shell_grep.probe(lambda: chan, ['/data']).has_grep)

    def test_missing_grep_unusable_with_displayable_reason(self):
        chan = _Chan([b'', b'bash: grep: command not found\n'])
        probe = shell_grep.probe(lambda: chan, ['/data'])
        self.assertFalse(probe.has_grep)
        self.assertFalse(probe.usable)
        self.assertTrue(probe.reason.strip())

    def test_find_xargs_absence_reported_separately(self):
        """缺 find/xargs 只该关掉时间过滤这条路，不该把 grep 整体判死。"""
        chan = _Chan([b'grep (GNU grep) 3.7\n', b'', b'MAPPING_OK\n', b''])
        probe = shell_grep.probe(lambda: chan, ['/data'])
        self.assertTrue(probe.has_grep)
        self.assertFalse(probe.has_find_xargs)

    def test_chroot_mapping_mismatch_blocks_grep(self):
        """SFTP 里存在的路径在 shell 侧可能不在同一位置（chroot）。
        不验就会 grep 一个不存在的路径、安静返回 0 命中。"""
        chan = _Chan([b'grep 3.7\n', b'find 4.9\n', b'', b''])
        probe = shell_grep.probe(lambda: chan, ['/data'])
        self.assertTrue(probe.has_grep)
        self.assertFalse(probe.path_mapping_ok)
        self.assertIn('路径映射', probe.reason)

    def test_probe_closes_its_channel(self):
        chan = _Chan([b'grep 3.7\n', b'', b'MAPPING_OK\n', b''])
        shell_grep.probe(lambda: chan, ['/data'])
        self.assertTrue(chan.closed)

    def test_probe_exception_becomes_unusable_not_a_crash(self):
        def boom():
            raise OSError('server refused the exec channel')
        probe = shell_grep.probe(boom, ['/data'])
        self.assertFalse(probe.usable)
        self.assertIn('exec channel', probe.reason)


class GrepStreamTests(SimpleTestCase):
    def test_yields_one_dict_per_match(self):
        chan = _Chan([b'/d/a.csv:3:SN,ShadowReg2\r\n',
                      b'/d/b.csv:9:x,ShadowReg2\r\n'])
        out = list(shell_grep.grep_stream(
            chan, spec(), deadline=__import__('time').monotonic() + 30))
        self.assertEqual([o['path'] for o in out], ['/d/a.csv', '/d/b.csv'])
        self.assertEqual(out[0]['line'], 3)

    def test_cancel_event_closes_channel(self):
        import threading
        ev = threading.Event()
        ev.set()
        chan = _Chan([b'/d/a.csv:3:x\r\n'])
        list(shell_grep.grep_stream(chan, spec(), cancel_event=ev))
        self.assertTrue(chan.closed)

    def test_exit_status_two_with_no_match_raises_for_fallback(self):
        """>=2 是 grep 自己出错了：必须抛出让上层回落，不能当成「没有命中」。"""
        chan = _Chan([b'grep: invalid option\n'], exit_status=2)
        with self.assertRaises(RuntimeError):
            list(shell_grep.grep_stream(chan, spec()))

    def test_exit_status_one_is_a_normal_zero_result(self):
        chan = _Chan([], exit_status=1)
        self.assertEqual(list(shell_grep.grep_stream(chan, spec())), [])

    # —— 以下为计划外补充：grep_stream 自己决定 use_find，钉住三条口径 ——

    def test_plain_query_sends_plain_grep(self):
        chan = _Chan([b'/d/a.csv:3:x\r\n'])
        list(shell_grep.grep_stream(chan, spec()))
        self.assertNotIn('find ', chan.commands[0])
        self.assertTrue(chan.commands[0].startswith('LC_ALL=C grep'))

    def test_time_filter_sends_find_pipeline(self):
        chan = _Chan([])
        list(shell_grep.grep_stream(chan, spec(modified_after='2026-09-01')))
        self.assertIn('xargs -0 -r', chan.commands[0])

    def test_size_filter_sends_find_pipeline(self):
        """grep 没有「按大小筛文件」的原语，只有 find 分支能表达 min/max_size。

        少这一条就会变成：用户勾了大小范围、grep 档悄悄把范围丢掉。
        """
        chan = _Chan([])
        list(shell_grep.grep_stream(chan, spec(min_size=1024)))
        self.assertIn('-size +1024c', chan.commands[0])


class ShellSurfaceTests(SimpleTestCase):
    """「shell_grep 是全项目唯一拼 shell 命令的地方」这句承诺要有测试兜住。

    允许别的模块 ``open_session()``（Task 9 借通道给 grep 用就是这一类）——开
    channel 不是注入面，**能 exec 一条命令字符串才是**。所以两条断言合起来钉住：
    只有 shell_grep 里出现 exec_command，且任何自己开 session 的模块必须把
    channel 交给 shell_grep，不许就地拼命令。
    """

    _NEEDLES = ('exec_command(', 'open_session(')
    APPS_DIR = os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')),
        'apps')

    def _py_files(self):
        for dirpath, dirnames, filenames in os.walk(self.APPS_DIR):
            dirnames[:] = [d for d in dirnames if d != '__pycache__']
            for name in filenames:
                if name.endswith('.py'):
                    yield os.path.join(dirpath, name)

    def test_only_shell_grep_executes_shell_commands(self):
        owner = os.path.join('apps', 'sftp', 'search', 'shell_grep.py')
        exec_sites, session_sites = [], []
        for path in self._py_files():
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
            rel = os.path.relpath(path, os.path.dirname(self.APPS_DIR))
            if 'exec_command(' in text:
                exec_sites.append(rel)
            # 文档串里的 ``open_session``（不带括号）不算，只钉真调用
            if 'open_session(' in text:
                session_sites.append(rel)
        self.assertEqual(
            exec_sites, [owner],
            f'exec_command 只能出现在 shell_grep.py，实际：{exec_sites}')
        for rel in session_sites:
            if rel == owner:
                continue
            with open(os.path.join(self.APPS_DIR, *rel.split(os.sep)[1:]),
                      encoding='utf-8') as fh:
                self.assertIn(
                    'shell_grep', fh.read(),
                    f'{rel} 自己开了 exec channel 却不把命令交给 shell_grep 构造')

    def test_bash_only_gbk_needle_trick_is_not_ported(self):
        """参考工具用 ANSI-C 引用（dollar-quote + 逐字节 hex 逃逸）追加 GBK needle。

        本设计里非 ASCII 已被 select_engine 整体挡在 grep 档外，这里钉住「没被顺手
        移植回来」——那会把结果是否完整押在远端是 bash 还是 dash 上。钉的是**写法**
        （dollar-quote / hex 逃逸是那条路子的指纹），不是「不许提 GBK」。
        """
        path = os.path.join(self.APPS_DIR, 'sftp', 'search', 'shell_grep.py')
        with open(path, encoding='utf-8') as fh:
            src = fh.read()
        self.assertNotIn("$'", src)
        self.assertNotIn('\\x', src)
        self.assertNotIn(':02x', src)
