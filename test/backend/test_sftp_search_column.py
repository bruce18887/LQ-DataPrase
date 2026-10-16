"""列值读取 ``scanners.read_column``（spec §3.5 末段，参考工具 csv_column_reader.py）。

跑法：python manage.py test test.backend.test_sftp_search_column

从 ``test_sftp_search_scan.py`` 拆出来是因为那个文件已逼近 600 行硬上限，
而 ``scanners.py`` 本就是两个入口（``scan_file`` 字节匹配 / ``read_column`` 列值），
测试跟着这个边界分。内容匹配的内核（needle / 编码 / 整词 / 分块）仍在那一份。
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


def col_pairs(out):
    """``read_column`` 结果的 ``(列名, 值)`` 序列。测试只在这一处解新形状。"""
    return [(c['column_name'], c['values']) for c in out['columns']]


def values_of(out):
    """第一个匹配列的读数：多数用例只关心单列，多列场景一律用 :func:`col_pairs`。"""
    return out['columns'][0]['values']


class ColumnHeaderMatchTests(SimpleTestCase):
    """列名档的表头匹配谓词：含 glob 元字符才按通配，否则仍是精确相等。

    元字符集是 ``*`` ``?`` ``[`` 三个 —— 与 :func:`apps.sftp.search.walker.is_pruned`、
    ``name_pattern`` 同一套 fnmatch 语义（``fnmatchcase``，大小写敏感）。
    """

    HEADERS = ['SN', 'BV2', 'CBV21', 'CBV12', 'ShadowReg2']

    def test_plain_name_is_exact_not_substring(self):
        """不含元字符 = 精确相等。既有口径不许因为加了通配而放宽。"""
        self.assertEqual(scanners.match_headers(self.HEADERS, 'BV2'), [1])

    def test_plain_name_absent_yields_no_indexes(self):
        self.assertEqual(scanners.match_headers(self.HEADERS, 'BV'), [])

    def test_glob_yields_every_match_in_header_order(self):
        self.assertEqual(scanners.match_headers(self.HEADERS, '*BV*2*'), [1, 2, 3])

    def test_glob_is_anchored_to_the_whole_name(self):
        """fnmatch 匹的是**整个**列名，首尾都锚定：``*BV*2`` 读作「以 2 结尾」，
        要「任意位置含 2」必须写 ``*BV*2*``。这条是用户最常踩的，help 提示要交代。"""
        self.assertEqual(scanners.match_headers(self.HEADERS, '*BV*2'), [1, 3])

    def test_glob_is_case_sensitive(self):
        """服务器是大小写敏感的 POSIX；换成 ``fnmatch.fnmatch`` 会让开发机与
        生产机对同一个查询给出不同的列（``walker.py:80`` 同一个理由）。"""
        self.assertEqual(scanners.match_headers(self.HEADERS, '*bv*2'), [])

    def test_question_mark_counts_as_a_metacharacter(self):
        """代价必须钉住：列名里真带 ``?`` 时，那条精确查询会被放宽成单字符通配。
        所以它必须同时出现在前端 help 提示里，不能只写在 spec。"""
        self.assertEqual(scanners.match_headers(['BV?2', 'BVx2'], 'BV?2'), [0, 1])

    def test_unclosed_bracket_degrades_to_literal(self):
        """未闭合的 ``[`` 让模式进 glob 分支，但 fnmatch 把它当字面量 ——
        钉住「不 IndexError、也不悄悄放宽成匹到 BV2」。"""
        self.assertEqual(scanners.match_headers(['BV[2', 'BV2'], 'BV[2'), [0])


class ColumnTests(SimpleTestCase):
    ATE = ('[HEADER]\r\nTestFile,D:\\stdf\\x.stdf\r\n'
           'StartTime,2026-09-01 08:00:00,\r\n[DATA]\r\n'
           'SN,ShadowReg2,Vcc\r\n1,0.42,3\r\n2,,3.1\r\n3,0.44,\r\n').encode()

    def read_full(self, content=None, column='ShadowReg2', rows=10, **over):
        """原样返回 ``(命中结果, 是否撞到预算)`` —— 只有预算那条用例要第二个元素。"""
        raw = self.ATE if content is None else content
        base = {'roots': ['/d'], 'mode': 'column',
                'column_name': column, 'column_rows': rows}
        base.update(over)
        cand = walker.Candidate(PATH, 'a.csv', len(raw), 0)
        return scanners.read_column(FakeSftp({PATH: raw}), cand,
                                    contracts.parse_spec(base))

    def read(self, content=None, column='ShadowReg2', rows=10, **over):
        return self.read_full(content, column, rows, **over)[0]

    def test_normal_read_is_not_truncation(self):
        out, truncated = self.read_full()
        self.assertIsNotNone(out)
        self.assertFalse(truncated)

    def test_budget_truncation_is_reported(self):
        """逐行读的这一档也要自报截断：预算内连表头都没读到 = 这一趟一无所知。"""
        raw = b'x\r\n' * scanners.CHUNK_SIZE        # 逐行读，预算在这里到点
        out, truncated = self.read_full(content=raw, max_scan_bytes=scanners.CHUNK_SIZE)
        self.assertIsNone(out)
        self.assertTrue(truncated)

    def test_values_in_row_order_skipping_blanks(self):
        self.assertEqual(values_of(self.read()), ['0.42', '0.44'])

    def test_respects_column_rows(self):
        self.assertEqual(values_of(self.read(rows=1)), ['0.42'])

    def test_absent_column_returns_none(self):
        self.assertIsNone(self.read(column='NoSuchCol'))

    def test_column_position_follows_header_order(self):
        """表头顺序才是列位置的事实来源，不能按列名猜偏移。"""
        self.assertEqual(values_of(self.read(column='Vcc')), ['3', '3.1'])

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
        self.assertEqual(values_of(self.read(content=raw, column='漏电电流')),
                         ['0.5'])

    def test_short_rows_are_skipped_not_index_error(self):
        raw = b'[DATA]\r\nSN,ShadowReg2,Vcc\r\n1\r\n2,0.9,4\r\n'
        self.assertEqual(values_of(self.read(content=raw)), ['0.9'])

    def test_unreadable_file_returns_none_and_logs(self):
        with self.assertLogs('apps.sftp.search.scanners', level='WARNING'):
            cand = walker.Candidate('/d/nope.csv', 'nope.csv', 1, 0)
            self.assertIsNone(scanners.read_column(
                FakeSftp({}), cand,
                contracts.parse_spec({'roots': ['/d'], 'mode': 'column',
                                      'column_name': 'x'}))[0])

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
        的 datalog 都是**表头紧跟标记行**，空行只出现在标记**之前**（49/56）。真数据走不到
        本分支，它挡的是未知生产者或手工编辑留的空行。别把它读成「真数据有此空行」。"""
        self.assertEqual(
            values_of(self.read(content=b'[DATA]' + CRLF + CRLF
                                + b'SN,ShadowReg2' + CRLF + b'1,0.42' + CRLF)),
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
        self.assertEqual(values_of(self.read(content=raw, column='LKG_VIN')),
                         ['7.495500'])

    def test_skip_is_capped_at_three_rows(self):
        """只跳表头下**紧邻**的最多三行，第四行起一律当数据：没有 Unit/Min/Max 的文件
        不能被白吃三行读数，未知生产者多写一行也不该连带吃掉真值。"""
        raw = (b'[DATA]' + CRLF + b'SN,LKG_VIN' + CRLF
               + b'Unit,nA' + CRLF + b'Min,-50.00' + CRLF + b'Max,50.00' + CRLF
               + b'Min,-1.00' + CRLF + b'1,7.0' + CRLF)
        self.assertEqual(values_of(self.read(content=raw, column='LKG_VIN')),
                         ['-1.00', '7.0'])

    def test_limit_tokens_match_case_insensitively(self):
        """首格比 token 集合走小写：真数据写的是 ``Unit``/``Min``/``Max``，
        大小写混排的生产者不该因此漏跳。"""
        raw = (b'[DATA]' + CRLF + b'SN,LKG_VIN' + CRLF
               + b'UNITS,nA' + CRLF + b'min,-50.00' + CRLF + b'Max,50.00' + CRLF
               + b'1,7.0' + CRLF)
        self.assertEqual(values_of(self.read(content=raw, column='LKG_VIN')),
                         ['7.0'])

    def test_naive_comma_split_matches_quoted_field_free_data(self):
        """切分口径：本域 ``[DATA]`` 段实测**没有**引号字段也没有内嵌逗号
        （Data/ 全量比对 naive ``split(',')`` 与 ``csv.reader`` 逐行结果一致，含 342 列的
        表头），所以沿用参考工具的朴素切分。这条钉住「表头里没有带引号的项名」这个前提。"""
        out = self.read(content=b'[DATA]' + CRLF + b'SN,LKG_VIN,Vcc' + CRLF
                        + b'1,7.49,3' + CRLF, column='Vcc')
        self.assertEqual(values_of(out), ['3'])

    def test_result_carries_candidate_metadata(self):
        """engine/SSE 直接消费这个 dict，形状在此钉住，别等前端发现。"""
        out = self.read()
        self.assertEqual(out['path'], PATH)
        self.assertEqual(out['name'], 'a.csv')
        self.assertEqual(out['size'], len(self.ATE))
        self.assertEqual(out['mtime'], 0)
        self.assertEqual(col_pairs(out), [('ShadowReg2', ['0.42', '0.44'])])

    def test_long_value_capped_at_snippet_max(self):
        raw = b'[DATA]' + CRLF + b'SN,ShadowReg2' + CRLF + b'1,' + b'9' * 400 + CRLF
        self.assertEqual(len(values_of(self.read(content=raw))[0]),
                         scanners.SNIPPET_MAX)

    def test_missing_prefetch_attribute_still_reads_column(self):
        """列值读取同样只把 prefetch 当加速，不是必需能力。"""
        raw = b'[DATA]' + CRLF + b'SN,ShadowReg2' + CRLF + b'1,0.42' + CRLF
        cand = walker.Candidate(PATH, 'a.csv', len(raw), 0)
        out = scanners.read_column(
            FakeSftp({PATH: raw}, no_prefetch=True), cand,
            contracts.parse_spec({'roots': ['/d'], 'mode': 'column',
                                  'column_name': 'ShadowReg2'}))[0]
        self.assertEqual(values_of(out), ['0.42'])

    # —— 通配匹配与 no data（2026-09-24 语义变更，spec §3.5）——

    def test_glob_hit_returns_every_matching_column(self):
        """一个文件一条命中，含**所有**匹配列 —— 用户要的是一次看全 ``*BV*2`` 系列。"""
        raw = (b'[DATA]' + CRLF + b'SN,BV2,CBV12,Vcc' + CRLF
               + b'1,0.1,0.2,3' + CRLF + b'2,0.3,0.4,4' + CRLF)
        self.assertEqual(col_pairs(self.read(content=raw, column='*BV*')),
                         [('BV2', ['0.1', '0.3']), ('CBV12', ['0.2', '0.4'])])

    def test_each_column_fills_to_its_own_column_rows(self):
        """早停判据是**所有**匹配列都凑够：只看第一列会把后面的列截在半途。"""
        raw = (b'[DATA]' + CRLF + b'SN,BV1,BV2' + CRLF
               + b'1,0.1,0.2' + CRLF + b'2,,0.3' + CRLF + b'3,0.4,0.4' + CRLF)
        self.assertEqual(
            col_pairs(self.read(content=raw, column='BV?', rows=2)),
            [('BV1', ['0.1', '0.4']), ('BV2', ['0.2', '0.3'])])

    def test_all_blank_column_is_a_hit_with_no_values(self):
        """新命中判据：表头匹配到列 = 命中，值全空照样返回（前端渲染 ``no data``）。
        取代 2026-09-21 的「命中必须有真读数」——那正是本条要区分的两种情况
        （「有这列但没数据」与「没这列」）被压成同一种的根源。"""
        raw = b'[DATA]' + CRLF + b'SN,ShadowReg2' + CRLF + b'1,' + CRLF + b'2,' + CRLF
        self.assertEqual(col_pairs(self.read(content=raw)),
                         [('ShadowReg2', [])])

    def test_column_with_only_limit_rows_reports_no_values(self):
        """只有 Unit/Min/Max 的列：测试项在表头里，但一个读数都没有 → 同上一条，
        是 ``no data`` 而不是「没有这一列」。"""
        raw = (b'[DATA]' + CRLF + b'SN,LKG_VIN' + CRLF
               + b'Unit,nA' + CRLF + b'Min,-50.00' + CRLF + b'Max,50.00' + CRLF)
        self.assertEqual(col_pairs(self.read(content=raw, column='LKG_VIN')),
                         [('LKG_VIN', [])])

    def test_scan_budget_exhausted_never_claims_no_data(self):
        """``max_scan_bytes`` 截断 ≠ 这一列没有数据。读到一半就没预算了，
        报 ``no data`` 是谎报，所以一个值都没取到时仍按无结果处理。"""
        raw = (b'[DATA]' + CRLF + b'SN,ShadowReg2' + CRLF
               + (b'1,' + CRLF) * 4000)
        self.assertIsNone(self.read(content=raw, max_scan_bytes=4096))

    def test_truncated_run_omits_columns_it_could_not_observe(self):
        """多列时的同一件事：**no data 只在读到 EOF 的那趟才声明**。
        BV1 取到了值、BV2 还没读到就截断 → 结果里只留 BV1，不给 BV2 挂 no data
        （那会被读成「这列没数据」，而真相是「没读完」；runner 的
        ``scan_budget_exceeded`` notice 说的就是后者）。"""
        raw = (b'[DATA]' + CRLF + b'SN,BV1,BV2' + CRLF
               + b'1,0.1,' + CRLF + (b'2,,' + CRLF) * 3000)
        self.assertEqual(col_pairs(self.read(content=raw, column='BV?',
                                             max_scan_bytes=4096)),
                         [('BV1', ['0.1'])])

    def test_glob_matching_nothing_is_silent_no_result(self):
        """通配没匹到任何列仍是「正常无结果」：不打 WARNING，与精确名同一分水岭。"""
        with self.assertNoLogs('apps.sftp.search.scanners', level='WARNING'):
            self.assertIsNone(self.read(column='*NoSuch*'))

    def test_quoted_field_with_embedded_comma_now_claims_no_data(self):
        """朴素切分的**可观察代价**（本域实测不发生，钉行为而非钉理想）：含引号逗号的
        项名把列索引右移，于是该列一格都读不到。通配/no data 改造后这件事**变严重了**：
        以前是静默无结果，现在会正面宣称「这列没有数据」。真出现这种 datalog 时必须改
        切分方式（``csv.reader``），而不是放过这个假 ``no data``。"""
        out = self.read(column='Vcc',
                        content=b'[DATA]' + CRLF + b'SN,"A,B",Vcc' + CRLF
                        + b'1,x,3' + CRLF)
        self.assertEqual(col_pairs(out), [('Vcc', [])])
