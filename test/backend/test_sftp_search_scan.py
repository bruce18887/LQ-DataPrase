"""扫描内核（spec §3.5）：字节级内容匹配（参考工具 csv_content_searcher.py）
+ CSV 列值读取（参考工具 csv_column_reader.py）。

跑法：python manage.py test test.backend.test_sftp_search_scan
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp.search import contracts, scanners, walker  # noqa: E402
from test.backend.sftp_fake import FakeSftp  # noqa: E402

CRLF = b'\r\n'
PATH = '/d/a.csv'


def spec(**over):
    base = {'roots': ['/d'], 'mode': 'content', 'term': 'ShadowReg2'}
    base.update(over)
    return contracts.parse_spec(base)


def scan(content: bytes, path: str = PATH, **over):
    cand = walker.Candidate(path, os.path.basename(path), len(content), 0)
    return scanners.scan_file(FakeSftp({path: content}), cand, spec(**over))


class _NoPrefetchFile:
    """只暴露 read/readline/close/with 的句柄壳：真 paramiko 老版本就没有 ``prefetch``。

    ``readline`` 也得有 —— ``read_column`` 是行级读取，只给 ``read`` 就等于把
    「没有 prefetch」测成了「没有 readline」，那是另一回事。
    """

    def __init__(self, inner):
        self._inner = inner

    def read(self, n: int = -1) -> bytes:
        return self._inner.read(n)

    def readline(self) -> bytes:
        return self._inner.readline()

    def close(self):
        self._inner.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class _NoPrefetchSftp(FakeSftp):
    """``FakeSftp(no_prefetch=True)`` 的本模块替身。

    计划 Task 6 Step 1 的收敛要求是把 ``no_prefetch`` 加进共享夹具
    ``test/backend/sftp_fake.py``；那是四个任务共用的基座，本任务不动它，
    改成在这里包一层（**不**用 ``del type(f).prefetch``——那会改坏共享类，
    污染同进程其它测试）。夹具真加上参数后，本类删掉即可。
    """

    def open(self, path: str, mode: str = 'rb', bufsize: int = -1):
        return _NoPrefetchFile(super().open(path, mode, bufsize))


class _SpySftp(FakeSftp):
    """留下 scan_file 自己开的那个句柄，用来验 prefetch 真的被发起了。"""

    def __init__(self, files):
        super().__init__(files)
        self.handles = []

    def open(self, path: str, mode: str = 'rb', bufsize: int = -1):
        handle = super().open(path, mode, bufsize)
        self.handles.append(handle)
        return handle


class NeedleTests(SimpleTestCase):
    def test_ascii_needle_with_case_folding(self):
        needles, fold = scanners.build_needles('Shadow', False)
        self.assertEqual(needles, [b'shadow'])
        self.assertTrue(fold)

    def test_ascii_case_sensitive_no_folding(self):
        self.assertFalse(scanners.build_needles('Shadow', True)[1])

    def test_non_ascii_gets_one_needle_per_encoding(self):
        needles, _fold = scanners.build_needles('漏电电流', True)
        for enc in ('utf-8', 'gbk', 'utf-16-le', 'utf-16-be'):
            self.assertIn('漏电电流'.encode(enc), needles)

    def test_empty_term_yields_no_needles(self):
        self.assertEqual(scanners.build_needles('', False)[0], [])


class SubstringTests(SimpleTestCase):
    def test_hit_reports_line_number_and_snippet(self):
        out = scan(b'[DATA]' + CRLF + b'SN,ShadowReg2' + CRLF + b'1,0.42' + CRLF)
        self.assertIsNotNone(out)
        self.assertEqual(out['line'], 2)
        self.assertIn('ShadowReg2', out['snippet'])

    def test_case_insensitive_hit(self):
        self.assertIsNotNone(scan(b'x,shadowreg2,y' + CRLF))

    def test_case_sensitive_misses_other_case(self):
        self.assertIsNone(scan(b'x,shadowreg2,y' + CRLF, case_sensitive=True))

    def test_no_hit_returns_none(self):
        self.assertIsNone(scan(b'[DATA]' + CRLF + b'SN,Vcc' + CRLF + b'1,3' + CRLF))

    def test_snippet_capped_at_200(self):
        out = scan(b'a' * 500 + b'ShadowReg2' + b'b' * 500 + CRLF)
        self.assertLessEqual(len(out['snippet']), scanners.SNIPPET_MAX)

    def test_carriage_return_stripped_from_snippet(self):
        self.assertEqual(scan(b'x,ShadowReg2,3' + CRLF)['snippet'],
                         'x,ShadowReg2,3')


class WholeWordTests(SimpleTestCase):
    def test_superstring_rejected(self):
        """整词若挡不掉 Vccc，这个选项就是装饰。

        计划原文的数据是 ``SN,Vcc,Vccc``，可那里第一个 Vcc 两侧都是逗号，
        ``LC_ALL=C grep -w Vcc`` 对它**返回命中**（实测 exit=0）—— 断言与它自己要钉的
        grep 语义互斥。换成纯超串，钉的才是「超串不算整词」这条。
        """
        self.assertIsNone(scan(b'SN,Vccc,Vcccc' + CRLF, term='Vcc',
                               matching='whole_word'))

    def test_exact_word_accepted(self):
        self.assertIsNotNone(scan(b'SN,Vcc,Vddd' + CRLF, term='Vcc',
                                  matching='whole_word'))

    def test_punctuation_boundary_accepted(self):
        self.assertIsNotNone(scan(b'a,Vcc,b' + CRLF, term='Vcc',
                                  matching='whole_word'))

    def test_digit_is_a_word_byte(self):
        self.assertIsNone(scan(b'SN,Vcc1' + CRLF, term='Vcc',
                               matching='whole_word'))

    def test_underscore_is_a_word_byte(self):
        self.assertIsNone(scan(b'SN,_Vcc' + CRLF, term='Vcc',
                               matching='whole_word'))

    def test_non_ascii_byte_is_a_boundary(self):
        """C locale 下 >=0x80 属非 word 字符，因此可作边界 —— 必须与 grep -w 一致。"""
        self.assertTrue(scanners.word_ok('值Vcc'.encode('utf-8'), 3, 3))

    def test_word_ok_uses_ascii_class_not_unicode(self):
        """钉住「不得改用 re 的 \\b」：用 \\b 就会与 grep 档分叉。"""
        self.assertFalse(scanners.word_ok(b'xVcc', 1, 3))
        self.assertTrue(scanners.word_ok(b'x Vcc y', 2, 3))


class FuzzyTests(SimpleTestCase):
    def test_subsequence_hits(self):
        self.assertIsNotNone(scan(b'SN,Shadow_Reg_2_ish' + CRLF, term='SRe2',
                                  matching='fuzzy'))

    def test_out_of_order_misses(self):
        self.assertIsNone(scan(b'SN,2eRwod_Sa' + CRLF, term='SRe2',
                               matching='fuzzy'))

    def test_one_hit_per_line_even_with_multiple_matches(self):
        """fuzzy 是**行级**谓词（参考工具 content_searcher.py:100）：游标必须越过整行。

        若按 idx+1 续扫，第 1 行的尾巴 'N,Shadow_Reg_2_ish' 自己又是 SRe2 的子序列，
        同一行会被报两次。
        """
        content = b'SN,Shadow_Reg_2_ish' + CRLF + b'zz SRe2 zz' + CRLF
        out = scan(content, term='SRe2', matching='fuzzy',
                   first_hit_per_file=False, matches_per_file=2)
        self.assertEqual([h['line'] for h in out['hits']], [1, 2])


class EncodingTests(SimpleTestCase):
    def test_gbk_file_with_chinese_term(self):
        raw = '测试项,值\r\n漏电电流,0.5\r\n'.encode('gbk')
        self.assertIsNotNone(scan(raw, term='漏电电流'))

    def test_utf8_file_with_chinese_term(self):
        raw = '测试项\r\n漏电电流\r\n'.encode('utf-8')
        self.assertIsNotNone(scan(raw, term='漏电电流'))

    def test_utf16le_content_found_by_bomless_needle(self):
        """utf-16-le 正文靠 utf-16-le needle 命中。

        计划原文用 ASCII 词 'ShadowReg2'，那与它自己钉的「ASCII 时单 needle」
        （test_ascii_needle_with_case_folding 的 assertEqual）互斥：utf-16-le 字节
        两两夹 NUL，单 needle 不可能命中。故换成非 ASCII 词，验的还是同一条性质。
        """
        self.assertIsNotNone(scan('SN,漏电电流\r\n'.encode('utf-16-le'),
                                  term='漏电电流'))

    def test_gbk_snippet_is_not_mojibake(self):
        self.assertEqual(scan('x,ShadowReg2'.encode('gbk') + CRLF)['snippet'],
                         'x,ShadowReg2')

    def test_detect_encoding_prefers_utf8(self):
        self.assertEqual(scanners.detect_encoding(b'SN,Value'), 'utf-8')


class ChunkingTests(SimpleTestCase):
    def test_needle_split_across_chunk_boundary_is_found(self):
        """滚动窗口的存在理由：needle 恰好被 1MB 切成两半。"""
        gap = b'x' * (scanners.CHUNK_SIZE + 7)
        self.assertIsNotNone(scan(gap + b'ShadowReg2' + CRLF))

    def test_line_number_correct_past_many_chunks(self):
        lines = [b'row-' + str(i).encode() for i in range(200_000)]
        lines[150_000] = b'hit ShadowReg2 here'
        self.assertEqual(scan(CRLF.join(lines) + CRLF)['line'], 150_001)

    def test_scan_budget_stops_before_end_of_file(self):
        """5GB 日志不该被整读：超预算就停，且不得因此报命中。"""
        content = b'y' * (2 << 20) + b'ShadowReg2' + CRLF
        self.assertIsNone(scan(content, max_scan_bytes=1 << 20))

    def test_prefetch_is_requested(self):
        """不发起 prefetch 就等于每个 chunk 一个来回，流水线白搭。"""
        content = b'z' * (scanners.CHUNK_SIZE + 10) + b'ShadowReg2' + CRLF
        fake = FakeSftp({PATH: content})
        with fake.open(PATH) as remote:
            remote.prefetch(len(content), scanners.MAX_INFLIGHT)
            self.assertTrue(remote.prefetched)
        scan(content)
        self.assertGreaterEqual(fake.open_count, 1)

    def test_scan_file_itself_requests_prefetch(self):
        """上面那条其实没验到 scan_file（open_count 被它自己的 with 先加过），
        这里盯住 scan_file 打开的那个句柄。"""
        content = b'q' * (scanners.CHUNK_SIZE + 3) + b'ShadowReg2' + CRLF
        fake = _SpySftp({PATH: content})
        cand = walker.Candidate(PATH, 'a.csv', len(content), 0)
        self.assertIsNotNone(scanners.scan_file(fake, cand, spec()))
        self.assertEqual(len(fake.handles), 1)
        self.assertTrue(fake.handles[0].prefetched)


class HitCountTests(SimpleTestCase):
    THREE = (b'ShadowReg2 a' + CRLF + b'ShadowReg2 b' + CRLF
             + b'ShadowReg2 c' + CRLF)

    def test_first_hit_per_file_returns_one(self):
        out = scan(self.THREE, first_hit_per_file=True, matches_per_file=5)
        self.assertEqual(len(out['hits']), 1)

    def test_matches_per_file_returns_that_many(self):
        out = scan(self.THREE, first_hit_per_file=False, matches_per_file=2)
        self.assertEqual([h['line'] for h in out['hits']], [1, 2])

    def test_all_lines_when_asked(self):
        out = scan(self.THREE, first_hit_per_file=False, matches_per_file=20)
        self.assertEqual([h['line'] for h in out['hits']], [1, 2, 3])


class HeadMetadataTests(SimpleTestCase):
    ATE = (b'[HEADER]' + CRLF
           + b'TestFile,D:\\stdf\\lotA_w01.stdf' + CRLF
           + b'StartTime,2026-09-01 08:12:33,' + CRLF
           + b'PtsModifyTime,2026-09-01 09:00:00,' + CRLF
           + b'[DATA]' + CRLF
           + b'SN,ShadowReg2' + CRLF
           + b'1,0.42' + CRLF)

    def test_three_fields_extracted(self):
        out = scan(self.ATE)
        self.assertEqual(out['test_file'], 'lotA_w01.stdf')
        self.assertEqual(out['start_time'], '2026-09-01 08:12:33')
        self.assertEqual(out['pts_modify_time'], '2026-09-01 09:00:00')

    def test_windows_path_reduced_to_basename(self):
        self.assertNotIn('\\', scan(self.ATE)['test_file'])

    def test_stops_at_data_section(self):
        """计划原文把唯一含 term 的那行整个替换掉，替换后无命中 → scan 返回 None。
        意图是「[DATA] 之后的 TestFile 不得覆盖头部值」，所以补一行命中。"""
        ate = self.ATE.replace(b'SN,ShadowReg2',
                               b'TestFile,should_not_win' + CRLF + b'SN,ShadowReg2')
        self.assertEqual(scan(ate)['test_file'], 'lotA_w01.stdf')

    def test_truncated_head_does_not_yield_a_partial_value(self):
        """head 按字节切可能停在半行；留着半行会把残缺值当真值。"""
        cut = scanners.truncate_head_for_test(self.ATE)
        self.assertEqual(scanners.parse_head(cut)[:2],
                         ('lotA_w01.stdf', '2026-09-01 08:12:33'))

    def test_half_line_cut_on_a_tracked_key_yields_no_value(self):
        """truncate_head_for_test 恰好把半行留在非追踪键上，判不出 drop 规则；
        这条让残行落在 StartTime 上，没 drop 就会读出 '2026-09-01 08:' 当值。"""
        self.assertEqual(
            scanners.parse_head(b'[HEADER]' + CRLF
                                + b'TestFile,D:\\stdf\\lotA_w01.stdf' + CRLF
                                + b'StartTime,2026-09-01 08:')[:2],
            ('lotA_w01.stdf', ''))

    def test_absent_metadata_yields_empty_strings(self):
        out = scan(b'[DATA]' + CRLF + b'SN,ShadowReg2' + CRLF)
        self.assertEqual(
            (out['test_file'], out['start_time'], out['pts_modify_time']),
            ('', '', ''))


class ErrorPathTests(SimpleTestCase):
    def test_unreadable_file_returns_none_and_logs(self):
        with self.assertLogs('apps.sftp.search.scanners', level='WARNING'):
            cand = walker.Candidate('/d/missing.csv', 'missing.csv', 10, 0)
            self.assertIsNone(scanners.scan_file(FakeSftp({}), cand, spec()))

    def test_connection_error_propagates_for_the_caller_to_replace(self):
        """连接级异常必须上抛，让 SearchSession 换掉脏连接 ——
        就地吞掉会让后续每个文件都在同一条坏死连接上失败。"""
        cand = walker.Candidate(PATH, 'a.csv', 10, 0)
        with self.assertRaises(scanners.CONNECTION_ERRORS):
            scanners.scan_file(FakeSftp({}, broken=True), cand, spec())

    def test_missing_prefetch_attribute_still_works(self):
        """老 paramiko 或别的替身没有 prefetch，不能因此失败，只是慢。"""
        content = b'x,ShadowReg2' + CRLF
        cand = walker.Candidate(PATH, 'a.csv', len(content), 0)
        self.assertIsNotNone(scanners.scan_file(
            _NoPrefetchSftp({PATH: content}), cand, spec()))


class ColumnTests(SimpleTestCase):
    ATE = ('[HEADER]\r\nTestFile,D:\\stdf\\x.stdf\r\n'
           'StartTime,2026-09-01 08:00:00,\r\n[DATA]\r\n'
           'SN,ShadowReg2,Vcc\r\n1,0.42,3\r\n2,,3.1\r\n3,0.44,\r\n').encode()

    def read(self, content=None, column='ShadowReg2', rows=10, **over):
        raw = self.ATE if content is None else content
        base = {'roots': ['/d'], 'mode': 'column',
                'column_name': column, 'column_rows': rows}
        base.update(over)
        cand = walker.Candidate(PATH, 'a.csv', len(raw), 0)
        return scanners.read_column(FakeSftp({PATH: raw}), cand,
                                    contracts.parse_spec(base))

    def test_values_in_row_order_skipping_blanks(self):
        self.assertEqual(self.read()['values'], ['0.42', '0.44'])

    def test_respects_column_rows(self):
        self.assertEqual(self.read(rows=1)['values'], ['0.42'])

    def test_absent_column_returns_none(self):
        self.assertIsNone(self.read(column='NoSuchCol'))

    def test_column_position_follows_header_order(self):
        """表头顺序才是列位置的事实来源，不能按列名猜偏移。"""
        self.assertEqual(self.read(column='Vcc')['values'], ['3', '3.1'])

    def test_header_metadata_extracted(self):
        out = self.read()
        self.assertEqual(out['test_file'], 'x.stdf')
        self.assertEqual(out['start_time'], '2026-09-01 08:00:00')

    def test_no_data_section_means_no_table(self):
        """[DATA] 之前的 key,value 行不是数据表。参考工具缺这条约束，
        列名撞上文件头键名就会读出垃圾 —— 这里钉住它。"""
        self.assertIsNone(self.read(
            content=b'TestFile,a\r\nSN,ShadowReg2\r\n1,0.5\r\n'))

    def test_gbk_column_name_and_values(self):
        raw = '[DATA]\r\nSN,漏电电流\r\n1,0.5\r\n'.encode('gbk')
        self.assertEqual(self.read(content=raw, column='漏电电流')['values'],
                         ['0.5'])

    def test_short_rows_are_skipped_not_index_error(self):
        raw = b'[DATA]\r\nSN,ShadowReg2,Vcc\r\n1\r\n2,0.9,4\r\n'
        self.assertEqual(self.read(content=raw)['values'], ['0.9'])

    def test_no_values_returns_none(self):
        self.assertIsNone(self.read(
            content=b'[DATA]\r\nSN,ShadowReg2\r\n1,\r\n2,\r\n'))

    def test_unreadable_file_returns_none_and_logs(self):
        with self.assertLogs('apps.sftp.search.scanners', level='WARNING'):
            cand = walker.Candidate('/d/nope.csv', 'nope.csv', 1, 0)
            self.assertIsNone(scanners.read_column(
                FakeSftp({}), cand,
                contracts.parse_spec({'roots': ['/d'], 'mode': 'column',
                                      'column_name': 'x'})))

    def test_connection_error_propagates(self):
        cand = walker.Candidate(PATH, 'a.csv', 10, 0)
        with self.assertRaises(scanners.CONNECTION_ERRORS):
            scanners.read_column(FakeSftp({}, broken=True), cand,
                                 contracts.parse_spec(
                                     {'roots': ['/d'], 'mode': 'column',
                                      'column_name': 'x'}))

    # —— 计划外补的钉桩：都是「用户看得见结果」的分支，不是实现细节 ——

    def test_absent_column_is_not_a_read_failure(self):
        """「列不存在」与「文件读失败」都返回 None，分水岭就是有没有 WARNING：
        列不存在是正常无结果（几千个文件里只有几个含该列是常态），不该刷日志。"""
        with self.assertNoLogs('apps.sftp.search.scanners', level='WARNING'):
            self.assertIsNone(self.read(column='NoSuchCol'))

    def test_blank_line_between_data_marker_and_header_is_skipped(self):
        """防御性容错分支，**不是**真实形态：`Data/` 按原始字节复算，56/56 个含 ``[DATA]``
        的 datalog 都是**表头紧跟标记行**，空行只出现在标记**之前**（49/56）。这条测的是
        「万一标记与表头之间夹了空行（未知生产者、手工编辑的文件），列仍取得到」。
        别把它读成「真数据有此空行」——上一轮就是这么记反了方位的。"""
        self.assertEqual(
            self.read(content=b'[DATA]' + CRLF + CRLF
                      + b'SN,ShadowReg2' + CRLF + b'1,0.42' + CRLF)['values'],
            ['0.42'])

    def test_unit_and_limit_rows_are_skipped(self):
        """表头下紧邻的 Unit/Min/Max 三行**不是**读数（2026-09-21 产品拍板跳过；此前与
        参考工具一致地把它们当值取走）。真数据 56/56 个含 ``[DATA]`` 的 datalog 都在表头
        下方写这三行（``Data/`` 全量比对每行首格），不跳的话结果前几格是单位与限值。
        位置判据的另一个来源是 ``apps/datafiles/parsers/base.py:154-155``
        （CTA8290D/CTA8280F：header +1 / unit +2 / min +3 / max +4 / data +5）。"""
        raw = (b'[DATA]' + CRLF + b'SN,LKG_VIN' + CRLF
               + b'Unit,nA' + CRLF + b'Min,-50.00' + CRLF
               + b'Max,50.00' + CRLF + b'1,7.495500' + CRLF)
        self.assertEqual(self.read(content=raw, column='LKG_VIN')['values'],
                         ['7.495500'])

    def test_skip_is_capped_at_three_rows(self):
        """只跳表头下**紧邻**的最多三行，第四行起一律当数据：没有 Unit/Min/Max 的文件
        不能被白吃三行读数，未知生产者多写一行也不该连带吃掉真值。"""
        raw = (b'[DATA]' + CRLF + b'SN,LKG_VIN' + CRLF
               + b'Unit,nA' + CRLF + b'Min,-50.00' + CRLF + b'Max,50.00' + CRLF
               + b'Min,-1.00' + CRLF + b'1,7.0' + CRLF)
        self.assertEqual(self.read(content=raw, column='LKG_VIN')['values'],
                         ['-1.00', '7.0'])

    def test_limit_tokens_match_case_insensitively(self):
        """首格比 token 集合走小写：真数据写的是 ``Unit``/``Min``/``Max``，
        大小写混排的生产者不该因此漏跳。"""
        raw = (b'[DATA]' + CRLF + b'SN,LKG_VIN' + CRLF
               + b'UNITS,nA' + CRLF + b'min,-50.00' + CRLF + b'Max,50.00' + CRLF
               + b'1,7.0' + CRLF)
        self.assertEqual(self.read(content=raw, column='LKG_VIN')['values'],
                         ['7.0'])

    def test_column_with_only_limit_rows_is_not_a_hit(self):
        """跳过之后该列再无值 → 不算命中。这是语义变更的另一半：以前光靠单位行就能
        命中一个文件，现在必须有真读数。"""
        raw = (b'[DATA]' + CRLF + b'SN,LKG_VIN' + CRLF
               + b'Unit,nA' + CRLF + b'Min,-50.00' + CRLF + b'Max,50.00' + CRLF)
        self.assertIsNone(self.read(content=raw, column='LKG_VIN'))

    def test_naive_comma_split_matches_quoted_field_free_data(self):
        """切分口径：本域 ``[DATA]`` 段实测**没有**引号字段也没有内嵌逗号
        （Data/ 全量比对 naive ``split(',')`` 与 ``csv.reader`` 逐行结果一致，含 342 列的
        表头），所以沿用参考工具的朴素切分。这条钉住「表头里没有带引号的项名」这个前提。"""
        header = b'SN,LKG_VIN,Vcc'
        out = self.read(content=b'[DATA]' + CRLF + header + CRLF
                        + b'1,7.49,3' + CRLF, column='Vcc')
        self.assertEqual(out['values'], ['3'])

    def test_quoted_field_with_embedded_comma_shifts_the_index(self):
        """朴素切分的**可观察代价**（本域实测不发生，钉行为而非钉理想）：含引号逗号的
        项名会把列索引右移，于是该列一格都读不到 → None。真出现这种 datalog 时该改的是
        切分方式，而不是把 None 当「这个文件没有该列」放过。"""
        self.assertIsNone(self.read(
            column='Vcc',
            content=b'[DATA]' + CRLF + b'SN,"A,B",Vcc' + CRLF + b'1,x,3' + CRLF))

    def test_result_carries_candidate_metadata(self):
        """engine/SSE 直接消费这个 dict，形状在此钉住，别等前端发现。"""
        out = self.read()
        self.assertEqual(out['path'], PATH)
        self.assertEqual(out['name'], 'a.csv')
        self.assertEqual(out['size'], len(self.ATE))
        self.assertEqual(out['mtime'], 0)
        self.assertEqual(out['column_name'], 'ShadowReg2')

    def test_long_value_capped_at_snippet_max(self):
        raw = b'[DATA]' + CRLF + b'SN,ShadowReg2' + CRLF + b'1,' + b'9' * 400 + CRLF
        self.assertEqual(len(self.read(content=raw)['values'][0]),
                         scanners.SNIPPET_MAX)

    def test_scan_budget_applies_to_column_reads(self):
        """``max_scan_bytes`` 是搜索级预算、与模式无关：某列全空时不该把巨型日志整读
        （contracts 明写「会悄悄失效的字段比报错更糟」）。"""
        raw = (b'[DATA]' + CRLF + b'SN,ShadowReg2' + CRLF
               + (b'1,' + CRLF) * 4000)
        self.assertIsNone(self.read(content=raw, max_scan_bytes=4096))

    def test_missing_prefetch_attribute_still_reads_column(self):
        """列值读取同样只把 prefetch 当加速，不是必需能力。"""
        raw = b'[DATA]' + CRLF + b'SN,ShadowReg2' + CRLF + b'1,0.42' + CRLF
        cand = walker.Candidate(PATH, 'a.csv', len(raw), 0)
        out = scanners.read_column(
            _NoPrefetchSftp({PATH: raw}), cand,
            contracts.parse_spec({'roots': ['/d'], 'mode': 'column',
                                  'column_name': 'ShadowReg2'}))
        self.assertEqual(out['values'], ['0.42'])
