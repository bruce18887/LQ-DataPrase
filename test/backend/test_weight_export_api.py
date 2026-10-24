# test/backend/test_weight_export_api.py
"""POST /api/v1/weight/export/ 的契约：入站守卫、可见性/均值/色板真的落到工作簿、下载名走模板表。

本模块只断「端点把参数送到 build_weight_workbook 的正确位置」+「错误形状」；工作簿自身的表几何、
线型、色板逐项回退的行为判据在 `test_weight_xlsx.py` / `test_weight_xlsx_chart.py`，这里不重复。

三条承重口径（①②③；夹具是 14 组 × 4 的均匀形状，光数条数会被恒真断言骗过）：
① 可见性既不能多画也不能少画 ⇒ 单组可见时同时断**系列名 + y 区域的表内行号与列跨度**
   （只断「4 条」的话，「永远画前 4 行」这种实现也能绿）；
② `palette` 的长度守卫是「空色板静默换板」的唯一屏障 —— builder 那侧 `palette=[]` 是**合法**的，
   会静默退回 `DEFAULT_PALETTE`（`test_weight_xlsx.py:563` 就钉着那个行为），所以这里断 400；
③ 下载名必须由 `render_export_filename(user, 'weight_plot', …)` 派生 ⇒ 除默认值外还要断
   「用户改过的模板真的生效」（只断默认值时，视图里硬编码同一个串也能绿）。

中文文案口径（`frontend/src/utils/error.ts:60-64` 的 `pickMessage` 优先 `message` 再 `detail`，
最后才查 `ERROR_CODE_MAP`；`apps/common/errors.py:29` 会把非空字符串 detail 复制进 message）：
守卫的 detail 必须是 None，否则英文串盖掉前端中文 —— 由
`test_guard_body_has_no_message_and_no_detail` 钉住。

两条如实记账（Task 5 修复轮）：
④ 导出 lane **不是**「零写入」：`render_export_filename` 内部是 `UserSetting.objects.get_or_create`
   （`apps/common/export_naming.py:97`），会给「从没存过设置的账号」**INSERT 一行 UserSetting**
   —— 那是本仓每条既有导出通路共有的形态。所以这里从不写 `assertNumQueries(0)`，只断
   「不碰 DataFile/ParseHistory、不写 MEDIA_ROOT」，而这条落盘探测器有对照组
   （`media_probe.MediaProbeControlMixin`，本模块自己带一份，不靠 `test_weight_api` 那条）；
⑤ 后端两张表的**值**没有任何测试与 `frontend/src/constants/export-templates.ts` 比对 ——
   TS2741 只钉**键的存在**，不钉 default 串 / 变量元组 / 扩展名。跨语言的值校验是本仓没有的
   新形态，已交给整枝评审裁定，`test_weight_plot_backend_tables_hold_the_registered_values`
   只声明它实际断的东西（后端两份登记值），不再假装是「前端镜像」证明。
"""
import io
import json
import os
import re
import sys
import urllib.parse
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')
import django  # noqa: E402
django.setup()
from django.test import TestCase  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.accounts.models import User, UserSetting  # noqa: E402
from apps.common.export_naming import (  # noqa: E402
    EXPORT_TEMPLATE_DEFAULTS, EXPORT_TEMPLATE_VARIABLES, render_export_filename,
)
from apps.datafiles.models import DataFile, ParseHistory  # noqa: E402
from apps.weight.xlsx import (  # noqa: E402
    DEFAULT_PALETTE, DETAIL_COL_NAME, DETAIL_COL_VALUE0, DETAIL_FIRST_DATA_ROW, SUMMARY_SHEET,
)
from test.backend.media_probe import (  # noqa: E402
    MediaProbeControlMixin, media_paths,
)

URL = '/api/v1/weight/export/'
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(_ROOT, 'test', 'fixtures', 'weight', 'trim_weight_ci.csv')
XLSX_MIME = ('application/vnd.openxmlformats-officedocument'
             '.spreadsheetml.sheet')
SHEET = SUMMARY_SHEET
GROUPS = 14                    # 夹具真值（Task 1 钉住）
PER_GROUP = 4
ALL_SERIES = 56
ROWS_WITH_MEAN = 70            # 56 + 14 条均值
OK_PALETTE = ['2563eb'] * 8
FIRST_COL = get_column_letter(DETAIL_COL_VALUE0)
G3_SHEET = 'WT0004'             # 组 3 的 sheet 名
G3_ROW0 = DETAIL_FIRST_DATA_ROW  # 组 3 的数据在它自己 sheet 的第 25 行起


def _book(response, sheet=SHEET):
    """收流并返回 `(字节, 工作簿, 工作表)`。

    `FileResponse.streaming_content` 是一次性生成器：**只能读一遍**，所以字节与工作表必须
    一起返回。默认取总览表；`sheet=None` 时取第一张表（总览）。
    """
    data = b''.join(response.streaming_content)
    wb = load_workbook(io.BytesIO(data))
    ws = wb[sheet] if sheet else wb[wb.sheetnames[0]]
    return data, wb, ws


def _charts(wb):
    return [chart for name in wb.sheetnames if name != SUMMARY_SHEET
            for chart in wb[name]._charts]


def _chart_names(wb):
    """按「分项 sheet 序 × 图内序」展平；每项一张图，均值仍紧跟组末。"""
    return [s.tx.v for chart in _charts(wb) for s in chart.series]


def _y_ref(sheet: str, row: int, length: int) -> str:
    return f"'{sheet}'!${FIRST_COL}${row}:${get_column_letter(DETAIL_COL_VALUE0 + length - 1)}${row}"


def _chart_xml(data):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist() if re.fullmatch(r'xl/charts/chart\d+\.xml', n)]
        names.sort(key=lambda n: int(re.search(r'(\d+)\.xml$', n).group(1)))
        return ''.join(zf.read(n).decode('utf-8') for n in names)


def _download_name(response):
    """还原 `Content-Disposition` 里的下载名（中文与 ASCII 两种形态都要认）。

    实测本树 Django 6.0.5：名字含非 ASCII ⇒ 只出 **小写** `filename*=utf-8''<pct-编码>`，
    ASCII 回退段整个缺席；纯 ASCII 名 ⇒ 只出 `filename="…"`。探测器只认其中一种就会把
    「中文源文件名」或「默认模板」那一侧的用例直接 IndexError，所以两条都解析。
    """
    cd = response['Content-Disposition']
    if 'filename*=' in cd:
        star = cd.split('filename*=')[1].split(';')[0].strip()
        return urllib.parse.unquote(star.split("''", 1)[1].strip().strip('"'))
    m = re.search(r'filename="([^"]*)"', cd)
    assert m, f'Content-Disposition 里没有 filename：{cd!r}'
    return m.group(1)


class EndpointFixtureMixin:
    """两个端点类共用：夹具原文（类级读一次）+ 认证客户端 + 默认载荷（修复轮 R6）。

    原先 `setUpClass` 的读文件与那 6 行默认载荷在 `ExportEndpointTests` /
    `ExportDownloadNameTests` 里**逐字重复**：往请求体契约里加一个键时只补一处，
    另一类的用例就在测**另一个**请求体（且不会有人发现）。子类只需给 `username`
    （两组各用各的账号，下载名那组断 `{user}` 时不受另一组牵连）。
    """

    username = ''            # 子类必须给，空串会被 create_user 直接拒掉

    @classmethod
    def setUpClass(cls):
        super().setUpClass()          # 必须调：TestCase 的类级钩子在这里挂
        with io.open(FIXTURE, encoding='utf-8', newline='') as f:
            cls.text = f.read()

    def setUp(self):
        super().setUp()               # 同理：混入不能截断 TestCase 的钩子链
        self.user = User.objects.create_user(username=self.username, password='x-pass-12345678')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)   # R6①：Permission 读 request._auth

    def _post(self, **over):
        payload = {'filename': 'trim_weight_ci.csv', 'text': self.text,
                   'visible_group_indexes': list(range(GROUPS)), 'show_mean': False,
                   'palette': list(OK_PALETTE), 'mean_color': '4b5563'}
        payload.update(over)
        return self.client.post(URL, data=json.dumps(payload), content_type='application/json')


class ExportEndpointTests(EndpointFixtureMixin, MediaProbeControlMixin, TestCase):
    """夹具 → 工作簿：状态码、表名、可见性、均值、色板守卫。"""

    username = 'w-exp'

    # ── 正常路径 ──────────────────────────────────────────────────

    def test_returns_xlsx_bytes_with_summary_and_detail_sheets(self):
        r = self._post()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], XLSX_MIME)
        data, wb, ws = _book(r)
        self.assertEqual(data[:2], b'PK')               # 真是 zip 容器，不是空串/HTML
        self.assertEqual(wb.sheetnames,
                         [SUMMARY_SHEET] + [f'WT{i + 1:04d}' for i in range(GROUPS)])

    def test_requires_auth(self):
        anon = APIClient()
        r = anon.post(URL, data='{}', content_type='application/json')
        self.assertIn(r.status_code, (401, 403))

    def test_all_visible_without_mean_is_the_control(self):
        # 对照组：56 是「全可见 + 未开均值」的真值，下一条 70 才有可比性
        self.assertEqual(len(_chart_names(_book(self._post())[1])), ALL_SERIES)

    def test_show_mean_adds_exactly_one_series_per_group(self):
        names = _chart_names(_book(self._post(show_mean=True))[1])
        self.assertEqual(len(names), ROWS_WITH_MEAN)
        self.assertEqual(names.count('WT0001_Avg'), 1)
        self.assertEqual(sum(1 for n in names if n.endswith('_Avg')), GROUPS)
        # 均值排在**自己组的成员之后**（组 0 的 4 条成员 + 第 5 条才是它的均值）
        self.assertEqual(names[:PER_GROUP + 1],
                         [f'WT0001_{i + 1}' for i in range(PER_GROUP)] + ['WT0001_Avg'])

    def test_single_visible_group_charts_that_group_not_the_first(self):
        _data, wb, _ws = _book(self._post(visible_group_indexes=[3]))
        charts = _charts(wb)
        # 组 3 = WT0004（它自己 sheet 的第 25-28 行、数组长度 8）；组 0 = WT0001（长度 16）。
        # 图数 + 图标题 + 名字 + 行号 + 列跨度一起断 ⇒「画的是第 3 组而不是第 1 组」才是被证出来的
        self.assertEqual(len(charts), 1)
        self.assertEqual(charts[0].title.tx.rich.p[0].r[0].t, 'WT0004')
        series = charts[0].series
        self.assertEqual([s.tx.v for s in series], [f'WT0004_{i + 1}' for i in range(PER_GROUP)])
        for i, s in enumerate(series):
            self.assertEqual(s.yVal.numRef.f, _y_ref(G3_SHEET, G3_ROW0 + i, 8))

    def test_empty_visible_list_has_only_the_summary_header(self):
        _data, wb, ws = _book(self._post(visible_group_indexes=[]))
        self.assertEqual(len(_chart_names(wb)), 0)
        self.assertEqual(_charts(wb), [])
        self.assertEqual(wb.sheetnames, [SUMMARY_SHEET])
        self.assertEqual([ws.cell(2, c).value for c in range(1, 8)], [None] * 7)

    def test_junk_visible_indexes_degrade_quietly(self):
        # 越界/负数/脏类型不 500、不抛，按「不可见」处理（Task 5 只验「是不是 list」，不验内容）
        r = self._post(visible_group_indexes=[-1, 999, 'x', None, {}])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(_chart_names(_book(r)[1])), 0)

    def test_omitted_visible_indexes_chart_every_group(self):
        # 键整个缺席 ⇒ None → 全可见（前端「没做任何过滤」那条路径）
        payload = {'filename': 'trim_weight_ci.csv', 'text': self.text, 'palette': list(OK_PALETTE)}
        r = self.client.post(URL, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(_chart_names(_book(r)[1])), ALL_SERIES)

    # ── 色板：值容错 vs 长度守卫 ─────────────────────────────────

    def test_probe_palette_reaches_the_chart_xml(self):
        """探测器灵敏度对照组：8 个互不相同的探针色逐个能在 chart XML 里查得到，
        且默认板第 0 项**查不到** ⇒ 下面两条用 `assertIn(DEFAULT_PALETTE[0])` 证明「回退发生了」，
        依据正是这条把它排除掉（否则「XML 里本来就有 2563EB」也能绿）。"""
        probe = [f'{i:02X}{i:02X}{i:02X}' for i in range(8)]
        xml = _chart_xml(_book(self._post(palette=probe))[0])
        for colour in probe:
            self.assertIn(f'val="{colour}"', xml, colour)
        self.assertNotIn(f'val="{DEFAULT_PALETTE[0]}"', xml)

    def test_malformed_palette_values_fall_back_per_slot(self):
        # 8 个「形状对、值非法」的色 ⇒ 颜色属表现层：逐项回退默认色，不拒整个导出
        r = self._post(palette=['zzzzzz', 'x'] + [''] * 6)
        self.assertEqual(r.status_code, 200)
        data, wb, _ws = _book(r)
        self.assertEqual(len(_chart_names(wb)), ALL_SERIES)
        xml = _chart_xml(data)
        self.assertNotIn('ZZZZZZ', xml)                     # 脏串绝不能进 XML
        self.assertIn(f'val="{DEFAULT_PALETTE[0]}"', xml)    # 回退真的发生了

    def test_non_string_palette_items_are_malformed_not_rejected(self):
        # 长度对、个别项是数字/None ⇒ 与「值非法」同一口径（表现层容错），不 400
        r = self._post(palette=[1, None] + ['047857'] * 6)
        self.assertEqual(r.status_code, 200)
        self.assertIn(f'val="{DEFAULT_PALETTE[0]}"', _chart_xml(_book(r)[0]))

    def test_palette_wrong_length_or_type_is_param_required(self):
        # 与上一条配对：长度不对必须拒。空表尤其危险 —— 它到了 builder 会静默换成
        # DEFAULT_PALETTE（`test_weight_xlsx.py::test_empty_palette_falls_back_to_default`），
        # 这条守卫是「用户色板不被悄悄替换」的唯一屏障。
        for bad in ([], ['2563eb'] * 7, ['2563eb'] * 9, '2563eb', None, {'a': 1}, 8):
            r = self._post(palette=bad)
            self.assertEqual(r.status_code, 400, bad)
            body = r.json()
            self.assertEqual(body['code'], 'param_required', bad)
            self.assertEqual(body['field'], 'palette', bad)

    # ── 入站守卫 ────────────────────────────────────────────────

    def test_missing_or_wrong_typed_fields_are_param_required(self):
        # 每条都断到**具体哪个字段**被拒：只断 code 的话，守卫顺序一错（比如 text 抢在
        # show_mean 前面命中）就变成「绿着但测错了东西」。detail/message 为 None 那半边
        # 由 `test_guard_body_has_no_message_and_no_detail` 负责，不在这里重复。
        cases = [({'text': ''}, 'text'), ({'text': 123}, 'text'), ({'text': None}, 'text'),
                 ({'filename': ''}, 'filename'), ({'filename': ['a.csv']}, 'filename'),
                 ({'visible_group_indexes': 'nope'}, 'visible_group_indexes'),
                 ({'visible_group_indexes': 3}, 'visible_group_indexes'),
                 ({'mean_color': 123}, 'mean_color'), ({'palette': None}, 'palette'),
                 # `show_mean` 是**布尔**：truthy 的脏类型以前会静默出一份画满均值的错工作簿
                 # （`bool('false')` = True ⇒ 70 条系列），现在与邻居同口径直接 400。
                 ({'show_mean': 'false'}, 'show_mean'), ({'show_mean': '0'}, 'show_mean'),
                 ({'show_mean': 1}, 'show_mean'), ({'show_mean': [True]}, 'show_mean'),
                 ({'show_mean': None}, 'show_mean')]
        for over, field in cases:
            r = self._post(**over)
            self.assertEqual(r.status_code, 400, over)
            body = r.json()
            self.assertEqual(body['code'], 'param_required', over)
            self.assertEqual(body['field'], field, over)
            self.assertIsNone(body['message'], over)

    def test_body_that_is_not_an_object_is_param_required(self):
        # R3②：`request.data.get(...)` 在 list/str/int body 上直接 AttributeError = 500
        for bad in ([1, 2], 'plain string', 123, None, True):
            r = self.client.post(URL, data=json.dumps(bad), content_type='application/json')
            self.assertEqual(r.status_code, 400, bad)
            self.assertEqual(r.json()['code'], 'param_required', bad)
            self.assertNotIn('error', r.json())    # 错误形态契约（P1-5）

    def test_guard_body_has_no_message_and_no_detail(self):
        """接线证明：守卫的 `message` 与 `detail` 都必须是 None。

        `error_response()` 把非空字符串 detail 复制进 message（`apps/common/errors.py:29`），
        `pickMessage` 又优先读 message、再读 detail，最后才查 `ERROR_CODE_MAP`
        （`frontend/src/utils/error.ts:60-64`）⇒ 任何非空 detail（英文也算）都会盖掉前端中文。
        只断 `code` 的话，`_bad_input('text is required')` 那种写法照样全绿。
        """
        for over in ({'text': ''}, {'filename': ''}, {'palette': []},
                     {'visible_group_indexes': 'x'}, {'mean_color': 1},
                     {'show_mean': 'false'}):
            body = self._post(**over).json()
            self.assertEqual(body['code'], 'param_required', over)
            self.assertIsNone(body['message'], over)
            self.assertIsNone(body['detail'], over)
            self.assertIn('field', body, over)      # 机器可读信息改走 extra

    def test_parse_error_passes_through_untouched(self):
        r = self._post(text='nothing here\n')
        self.assertEqual(r.status_code, 400)
        body = r.json()
        self.assertEqual(body['code'], 'no_declaration')
        self.assertIsNone(body['message'])          # 解析码的中文由前端 ERROR_CODE_MAP 出（Task 7）

    def test_parse_error_with_structured_fields_keeps_detail_as_dict(self):
        # 对照：解析错误的 detail 是**字典** ⇒ 不是字符串，不会被复制成 message，前端照常用码表
        body = self._post(text='double A[3] = {1.0};\n').json()
        self.assertEqual(body['code'], 'weight_length_mismatch')
        self.assertEqual((body['detail']['declared'], body['detail']['actual']), (3, 1))
        self.assertIsNone(body['message'])

    def test_filename_is_capped_and_still_reaches_both_sheets(self):
        r = self._post(filename='长' * 300 + '.csv')
        self.assertEqual(r.status_code, 200)
        _data, wb, _ws = _book(r, sheet=None)
        self.assertEqual(len(wb.sheetnames), 1 + GROUPS)   # sheet 名由测试项名决定，与超长文件名无关
        self.assertEqual(wb.sheetnames[0], SUMMARY_SHEET)
        self.assertLessEqual(len(_download_name(r)), 160)   # FILENAME_MAX(120) + 前后缀 + 扩展名

    # ── 端点承诺：不写盘、不碰数据表 ────────────────────────────

    def test_export_writes_nothing_to_media_root_or_data_tables(self):
        # 承诺同 parse（spec §4）。这里**不能**用 assertNumQueries(0)：
        # `render_export_filename` 内部是 `UserSetting.objects.get_or_create(user=…)`
        # （`apps/common/export_naming.py:97`）⇒ 它会**发 SQL**，并且对「从没存过设置的账号」
        # **INSERT 一行 UserSetting**。那是本仓每条既有导出通路共有的形态、写的是账号设置而不是
        # 权重数据 ⇒ 承诺只能写成下面这样（不碰 DataFile/ParseHistory、不写 MEDIA_ROOT），
        # **任何人别在它上面搭「零写入 / 零 SQL」**。落盘探测器的对照组见 `media_probe`。
        before_media = media_paths()
        r = self._post()
        self.assertEqual(r.status_code, 200)
        self.assertGreater(len(_book(r)[0]), 4096)          # 流读完再谈「没落盘」，否则探测在半成品上
        self.assertEqual((DataFile.objects.count(), ParseHistory.objects.count()), (0, 0))
        self.assertEqual(media_paths(), before_media)


class ExportDownloadNameTests(EndpointFixtureMixin, TestCase):
    """下载名 = `render_export_filename(user, 'weight_plot', …)`，不是硬编码串。"""

    username = 'w-name'

    def test_default_template_is_used(self):
        self.assertRegex(_download_name(self._post()),
                         r'^Weight_Plot_trim_weight_ci_\d{8}\.xlsx$')

    def test_chinese_source_name_goes_through_rfc5987(self):
        # WSGI 头只认 latin-1：手写 Content-Disposition 会 UnicodeEncodeError ⇒ 必须用 FileResponse
        r = self._post(filename='权重测试-2.csv')
        self.assertEqual(r.status_code, 200)
        cd = r['Content-Disposition']
        self.assertIn("filename*=utf-8''", cd)      # 实测 Django 6.0.5 的 charset 段是小写
        self.assertNotIn('filename="', cd)          # 非 ASCII 名时 ASCII 回退段本就缺席（不是漏写）
        self.assertRegex(_download_name(r), r'^Weight_Plot_权重测试-2_\d{8}\.xlsx$')

    def test_user_template_wins_over_the_default(self):
        # 接线证明：视图真的把 'weight_plot' 交给 render_export_filename
        # （若视图硬编码 `Weight_Plot_{stem}_{date}`，上面默认值那条照样绿）
        UserSetting.objects.update_or_create(
            user=self.user,
            defaults={'export_filename_templates': {'weight_plot': 'WP-{filename}-{user}'}})
        self.assertEqual(_download_name(self._post()),
                         f'WP-trim_weight_ci-{self.user.username}.xlsx')

    def test_unknown_variable_placeholder_is_kept_for_self_diagnosis(self):
        UserSetting.objects.update_or_create(
            user=self.user,
            defaults={'export_filename_templates': {'weight_plot': '{filename}-{nope}'}})
        self.assertEqual(_download_name(self._post()), 'trim_weight_ci-{nope}.xlsx')

    def test_windows_invalid_chars_in_source_name_are_sanitized(self):
        # `:` `*` `?` 是 Windows 非法字符，出现在源文件名里必须变 `_`（不是原样进头）
        name = _download_name(self._post(filename='a:b*c?.csv'))
        self.assertTrue(name.startswith('Weight_Plot_a_b_c__'), name)
        self.assertFalse(re.search(r'[:*?"<>|]', name), name)
        self.assertTrue(name.endswith('.xlsx'), name)

    def test_source_extension_is_not_carried_into_the_download_name(self):
        # 视图喂模板的 context['filename'] 是**去扩展名**的 stem ⇒ 下载名里不该出现 `.csv`
        name = _download_name(self._post(filename='报告_v3.csv'))
        self.assertNotIn('.csv', name)
        self.assertIn('报告_v3', name)
        self.assertTrue(name.endswith('.xlsx'), name)


class ExportNamingRegisteredTests(TestCase):
    """后端两张登记表里 `weight_plot` 的登记值（第三处联动 = `export-templates.ts` 的 meta）。"""

    def setUp(self):
        # render_export_filename 内部 UserSetting.objects.get_or_create(user=…) ⇒ 必须真实 user
        self.user = User.objects.create_user(username='w-naming', password='x-pass-12345678')

    def test_weight_plot_backend_tables_hold_the_registered_values(self):
        """后端这两张表的登记值（default 串 + 变量元组 + 扩展名口径）逐字钉住。

        名字只说它实际断的东西：**没有**任何东西拿它去比 `export-templates.ts`
        —— 全仓不读 TS 文件，`Record<ExportTypeKey, ExportTemplateMeta>` 的 TS2741 只保证
        **键存在**，不保证 default/variables/extension 同值 ⇒ 跨语言的**值**漂移（设置页预览
        前端那份、服务端渲染后端那份）目前不会有任何测试变红。这条缺口已如实记进
        task-5-report.md，等整枝评审裁定要不要立「跨语言值校验」这个新形态。
        """
        self.assertEqual(EXPORT_TEMPLATE_DEFAULTS['weight_plot'],
                         'Weight_Plot_{filename}_{date}')
        self.assertEqual(EXPORT_TEMPLATE_VARIABLES['weight_plot'],
                         ('filename', 'date', 'time', 'datetime', 'user'))

    # 「weight_plot 在不在两张表里」不单独开例（修复轮裁定）：上一条直接下标这两张表
    # ⇒ 缺键就是 KeyError，**存在 + 值**一次断完。键集合本身另有两处枚举在管 ——
    # `apps/common/tests.py::test_defaults_covers_all_export_types`（比对两张表的键集合
    # 相等，并逐个键渲染一遍）与 `apps/accounts/tests.py::test_get_settings_returns_all_template_keys`
    # （硬编码含 weight_plot 的完整键集合，故意不同源 ⇒ 漏登记必红）。

    def test_filename_is_not_the_silent_export_default(self):
        # `export_naming.py:99` 的 `.get(export_type, 'export')` 会静默给出 export.xlsx
        # ⇒ 这条同时是「DEFAULTS 里有 weight_plot」的下界证据（缺键就会拿到 export.xlsx）
        name = render_export_filename(self.user, 'weight_plot', 'xlsx',
                                      {'filename': 'trim_weight_ci', 'date': '20261019'})
        self.assertEqual(name, 'Weight_Plot_trim_weight_ci_20261019.xlsx')
        self.assertNotEqual(name, 'export.xlsx')


if __name__ == '__main__':
    from django.test.runner import DiscoverRunner
    sys.exit(1 if DiscoverRunner(verbosity=1).run_tests(['test.backend.test_weight_export_api']) else 0)
