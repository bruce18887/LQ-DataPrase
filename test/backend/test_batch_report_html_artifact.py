"""D3 Minor 5：批次 HTML 报告的**产物判据**（证据入库，不留在 ``tasks/`` 的日志里）。

为什么要这一条：本任务最承重的风险是「HTML 分支静默退化」——那四段分区在
``apps/export/html_report/batch.py`` 里全是 ``payload.get(...) or {}``，
所以少带一段不会报错，只会少一块图。上一轮这类证据只落在 gitignored 的 ``tasks/*``
里，换一台机器就没法复现「产物与改前逐字节相同」这句话。本文件把它变成**任何人、
任何机器都能重跑**的判据，写法照本仓已接受的形状（钉住的 sha 常量 + 出处说明，
见 ``test/backend/test_gage_sheet_shape.py`` 的 ``PIN_SHA256`` 与
``scripts/make_gage_ci_fixture.py``）。

夹具走 **CI 虚拟化副本**（``test/fixtures/gage/``，口径见
``docs/reference/testing-gates.md`` §6「虚拟化夹具」），解析走**真实解析器**
（这里一个 mock 都没有）⇒ 判据覆盖的是 ``compute_batch_yield_data(for_html_report=True)``
→ ``build_batch_html_report`` 的整条产线，不是它的替身。

**洗掉什么、为什么只洗这些**（``_scrub`` 的口径）：
每个 ``data:image/png;base64,`` 的**位图负载**换成定长占位符 ``<PNG>``。
PNG 字节由 matplotlib/FreeType 的**字体回退**决定（``report_charts`` 那句
``apply_matplotlib_fonts()`` + ``bbox_inches='tight'`` ⇒ 换一台机器连画布尺寸都可能变），
钉它就等于把判据绑在本机字体清单上。除此之外**一个字节都不洗**：
区块标题、表格单元格、``<img alt=...>`` 与 ``<img>`` 的**数量与次序**全部进 digest，
而「哪一块静默消失」恰好只体现在这些被保留的文本上 ⇒ 洗掉的是不可移植的部分，
留住的是要抓的那一类。``generated_at`` 由本文件传死值，所以它不需要洗。

配套的三条判据：
① ``test_scrubbed_artifact_matches_pinned_digest`` —— 文档本体（区块标题清单 + 图表
   清单 + 洗过的字节 digest）；
② ``test_pin_bites_when_a_partition_is_silently_dropped`` —— 钉值自己必须咬得动
   （摘掉 ``trend_data`` 后重渲染，digest 必须与 ① 的钉值不同）；否则 ① 是个抓不住
   「静默少一块」的空哨兵。入口守卫（``test_html_report_batch.py`` 那条）是同一件事的
   第一道闸，本文件是第二道：守卫挡「整个开关忘了开」，digest 挡「开了但少带一段」。
   两条独立成立 —— 2026-10-30 变异表实测：M2b（漏开关、守卫在）由守卫拦下转红，
   M2c（漏开关 **且**删守卫）仍由 digest 转红，所以这道闸不靠守卫撑着。
③ ``test_pins_look_real`` —— 钉值不许停在占位串上（同 ``test_gage_sheet_shape.py``
   的那条「防基线表退化成永真」）。

runner: ``python -X utf8 manage.py test test.backend.test_batch_report_html_artifact``
"""

import hashlib
import os
import re

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.batch_report.services import compute_batch_yield_data
from apps.datafiles.models import DataFile
from apps.export.html_report import build_batch_html_report

User = get_user_model()

FIXTURE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'gage'))

BATCH = 'D3ART'
GENERATED_AT = '2026-01-01 00:00:00'
DPI = 150

# ``(DataFile.filename, 夹具文件名)``：三个**不同阶段**（CP1/CP2/FT1，由
# ``apps/batch_report/phase_parsing.detect_phase`` 认得）⇒ 趋势折线 3 个点、
# Bin Pareto 有柱、Bin×Site 交叉表有行，HTML 那三块全落在判据范围内。
# 夹具只有 S1..S4 四份，取 S1/S2/S4 让三份内容互不相同（同一份复制三次会让
# 「按阶段聚合」那一块的形状变平，判据覆盖面变窄）。
SOURCES = (
    ('LOT_D3ART_CP1_20260101.csv', 'gage_m_S1.csv'),
    ('LOT_D3ART_CP2_20260101.csv', 'gage_m_S2.csv'),
    ('LOT_D3ART_FT1_20260101.csv', 'gage_m_S4.csv'),
)

_BASE64_PNG = re.compile(r'(data:image/png;base64,)[A-Za-z0-9+/=]+')
_IMG_ALT = re.compile(r'<img alt="([^"]*)"')
_H2 = re.compile(r'<h2>(.*?)</h2>')

# 钉住的基线（本机 2026-10-30 实测；D3 那批改动前后同值 —— 那正是本条要钉的「零产物漂移」）。
# 换 matplotlib / numpy / 字体相关依赖的版本要先重测这三条再改本文件的钉值（同
# ``test_gage_sheet_shape.py`` 对 excelize/numpy 的口径）。
PIN_IMG_ALTS = ['良率趋势', 'Bin 分布']
#: 区块标题按文档顺序钉一份：digest 红了时用这条定位是哪一块动了，也顺带把覆盖面写明 ——
#: CI 夹具的 ``SW_Bin`` **全是 pass bin**（``bin_table_data`` 只有 ``Bin 1`` 与 ``Total``），
#: 所以 ``_bin_site_matrix`` 拿不到 Fail Bin ⇒ 热力图合法缺席（alts 是 2 不是 3）。
#: Bin×Site 交叉表本身仍在场（``合计`` 那一句由 ``tables.bin_site_table`` 独家产出）。
PIN_SECTION_TITLES = ['阶段汇总', '良率趋势', '阶段明细表',
                      'Site × 阶段 矩阵', 'Bin 分布', 'UPH 效率明细']
PIN_SCRUBBED_SHA256 = 'fbac4d8a74eb50af758467e8a23c565ed135dc7991d4ebcc2e8b4e601c6f7398'
#: 咬合自检用的偏离值（只摘 ``trend_data`` 那一份产物）：必须是**另一个** 64 位十六进制串，
#: 不能与基线相同。
PIN_MUTATED_SHA256 = 'edb1bce031562d1c5f0359ced2e22d9b94d8b9cec60182aa718f417016fb4c28'


def _scrub(document):
    """``(洗过的文档, 图表 alt 清单, 区块标题清单)``；洗的范围见模块 docstring。"""
    alts = _IMG_ALT.findall(document)
    return _BASE64_PNG.sub(r'\1<PNG>', document), alts, _H2.findall(document)


class BatchHtmlReportArtifactTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='d3art_user', password='pw')
        for filename, fixture in SOURCES:
            path = os.path.join(FIXTURE_DIR, fixture)
            self.assertTrue(os.path.exists(path), f'CI 夹具缺失：{path}')
            DataFile.objects.create(
                owner=self.user, filename=filename, file_path=path,
                file_size=os.path.getsize(path), format_type='CTA8290D',
                file_type='batch', batch_name=BATCH, status='ready',
            )

    def _render(self, **overrides):
        """走**生产通路**渲染一次：真解析 → 真载荷 → 真 HTML；返回洗过的三元组。"""
        payload = compute_batch_yield_data(
            self.user, BATCH, for_html_report=True)
        for key in overrides.get('drop', ()):
            payload.pop(key)
        document = build_batch_html_report(
            payload, dpi=DPI, generated_at=GENERATED_AT)
        return _scrub(document)

    def test_scrubbed_artifact_matches_pinned_digest(self):
        scrubbed, alts, titles = self._render()
        digest = hashlib.sha256(scrubbed.encode('utf-8')).hexdigest()
        # 判据自己先要可复现：同进程内两次构建必须同串（否则下面的钉值毫无意义）。
        again = hashlib.sha256(self._render()[0].encode('utf-8')).hexdigest()
        self.assertEqual(digest, again, '两次渲染洗过之后字节不同 ⇒ 产物里有未洗掉的易变项')
        self.assertEqual(
            titles, PIN_SECTION_TITLES,
            f'区块标题清单与基线不同（实测 {titles}）⇒ HTML 报告多了一块或少了一块')
        self.assertEqual(
            alts, PIN_IMG_ALTS,
            f'内联图表的数量/次序/alt 变了（实测 {alts}）⇒ 某块图静默消失了')
        self.assertEqual(
            digest, PIN_SCRUBBED_SHA256,
            f'批次 HTML 产物偏离基线（实测 {digest}）⇒ 版式或分区数据真的变了；'
            '若确认是有意改动，重跑本用例取新值并在提交信息里写明谁受益')

    def test_pin_bites_when_a_partition_is_silently_dropped(self):
        """钉值的**咬合力**自检：只摘 ``trend_data``，守卫照样放行，digest 必须变。

        这一条防的是「scrub 把要抓的东西一起洗掉了」：如果区块标题/表格文本不在 digest
        里，摘掉一块图不会改变它，那 ``test_scrubbed_artifact_matches_pinned_digest``
        就退化成一台机器上的字节回声。这里刻意**不删** ``bin_site_columns``、也**不补**
        ``site_pass_data`` ⇒ ``build_batch_html_report`` 的入口守卫仍按 HTML 形状放行，
        走到渲染里去。
        """
        scrubbed, alts, titles = self._render(drop=('trend_data',))
        self.assertNotIn('良率趋势', titles,
                         '前置：摘掉 trend_data 后那块区块真的消失了（否则下面是在比两份相同文档）')
        digest = hashlib.sha256(scrubbed.encode('utf-8')).hexdigest()
        self.assertNotEqual(
            digest, PIN_SCRUBBED_SHA256,
            '少了整个趋势分区而 digest 不变 ⇒ scrub 洗掉了承重文本，基线判据是空的')
        self.assertEqual(digest, PIN_MUTATED_SHA256,
                         f'偏离形态本身也要可复现（实测 {digest}）')
        self.assertEqual(alts, ['Bin 分布'], '偏离形态里的图表清单漂了')

    def test_pins_look_real(self):
        """钉值表不许停在占位值上 —— 否则上面两条全都恒绿。"""
        for table in (PIN_SCRUBBED_SHA256, PIN_MUTATED_SHA256):
            self.assertNotIn('PLACEHOLDER', table)
            self.assertRegex(table, r'^[0-9a-f]{64}$')
        self.assertNotEqual(PIN_SCRUBBED_SHA256, PIN_MUTATED_SHA256)
        self.assertTrue(PIN_IMG_ALTS, '空 alt 清单等于不钉任何图表')
        self.assertTrue(PIN_SECTION_TITLES, '空区块清单等于不钉任何区块')
        for table in (PIN_IMG_ALTS, PIN_SECTION_TITLES):
            self.assertNotIn('PLACEHOLDER', str(table))
