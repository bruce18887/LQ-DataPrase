"""page_size 边界的单一事实源：设置域上下界 == 设置页 == 前端块大小；browse 执行域**上界**与之同源。

背景（2026-10-14 部署整改批 2）：`apps/datafiles/views/browse_views.py:164` 自钳到
``100000``，而合法设置域是 50–500 —— **校验域与执行域脱钩**（差 200 倍）。
lessons 2026-09-19「同一个数值区间的多份字面量必然漂移，改一处忘两处是常态」，
本文件按同一条先例（`apps/export/tests_chart_dpi.py` 的源码扫描）把四处钉在一起。

行为用例刻意写**字面 500 / 50**，不从被测常量取值：否则常量搬错方向时两边一起错。

运行：``manage.py test test.backend.test_page_size_bounds``
"""
import os
import re
import sys
import tempfile

# test/backend/ → 项目根（为了 `import config` / `from apps...`）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import SimpleTestCase, TestCase  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.datafiles.models import DataFile  # noqa: E402

User = get_user_model()

PASSWORD = 'x-pass-12345678'
META_HEADER = 'CTA8280F\nDevice Name,TEST_DEVICE\nTestFileName,C:\\x\\prog.dll\n'

# 与 test_browse_api.py 同构的 12 列 CTA8280F，但行数放大到 600 > 合法上界 500，
# 这样「请求被钳到 500」会从**少返回 100 行**这一可观察后果上得到证明，
# 而不是只看回显字段。
N_ROWS = 600
CLAMPED_MAX = 500   # 期望的合法上界（= 设置页下拉最大值）
CLAMPED_MIN = 50    # 期望的合法下界


def build_cta_csv(n_rows: int) -> str:
    lines = [
        META_HEADER + '[Data]\n',
        'Index_No,Dut_No,Serial_No,Site_No,Dut_Pass,SW_Bin,X_COORD,Y_COORD,'
        'QR_Code,Test_Time,Data_Num,KELVIN_VIN,\n',
        'Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,ohm,\n',
        'Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,0,\n',
        'Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,2,\n',
    ]
    for i in range(1, n_rows + 1):
        lines.append(f'{i},1,{i},{(i % 3) + 1},TRUE,{1 if i % 2 else 5},0,0,'
                     f'None,4.1,10,{1.0 if i % 2 else 9.0},\n')
    return ''.join(lines)


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TABLE_FORM_VUE = os.path.join(
    REPO_ROOT, 'frontend', 'src', 'pages', 'settings', 'components', 'TableSettingsForm.vue')
BROWSER_GRID_VUE = os.path.join(
    REPO_ROOT, 'frontend', 'src', 'pages', 'data', 'DataBrowserAgGrid.vue')
SETTINGS_PAGE_VUE = os.path.join(
    REPO_ROOT, 'frontend', 'src', 'pages', 'settings', 'SettingsPage.vue')
# 2026-10-22「渲染进程块预算」批把 IRM 的块大小三件（初值与上下界）从 `DataBrowserAgGrid.vue`
# 搬进了 `composables/useIrmSizing.ts`，另按列数封顶的两个同名常数住在 `blockCap.ts`。
# **载体搬了，不变量没搬**：设置域 == 前端块大小 == 后端钳位区间。所以下面两条结构用例扫的是
# 这一组载体的**并集**，并且要求「一个都没命中」也判红 —— 只盯单个文件的写法在搬家后会因为
# 正则零命中而得到空集，把哨兵变成假绿（lessons 那条「搬载体层级要补接线哨兵」）。
IRM_SIZING_TS = os.path.join(
    REPO_ROOT, 'frontend', 'src', 'pages', 'data', 'composables', 'useIrmSizing.ts')
BLOCK_CAP_TS = os.path.join(
    REPO_ROOT, 'frontend', 'src', 'pages', 'data', 'components', 'browser', 'blockCap.ts')
IRM_CARRIERS = (BROWSER_GRID_VUE, IRM_SIZING_TS, BLOCK_CAP_TS)


def literal_sets_by_carrier(pattern: str, carriers) -> dict:
    """按 `pattern` 扫每个载体，返回 {文件名: 命中的数字集合}，只收有命中的载体。

    返回空 dict = 没有任何载体定义这组字面量 ⇒ 调用方必须判红（搬家后漏指新载体的形状）。
    """
    found = {}
    for path in carriers:
        nums = {int(v) for v in re.findall(pattern, read(path))}
        if nums:
            found[os.path.basename(path)] = nums
    return found


def read(path: str) -> str:
    with open(path, encoding='utf-8') as fh:
        return fh.read()


class BrowseClampTests(TestCase):
    """执行域：browse 的**上界**与账号设置域同源；下界保持 1（见反「对齐」钉那条）。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmpdir = tempfile.mkdtemp(prefix='page_size_bounds_')

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user('ps_clamp', 'ps@localhost', PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)  # R6①：Permission 读 request._auth
        path = os.path.join(self.tmpdir, f'ps_{self._testMethodName}.csv')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(build_cta_csv(N_ROWS))
        self.datafile = DataFile.objects.create(
            owner=self.user,
            filename=os.path.basename(path),
            file_path=path,
            file_size=os.path.getsize(path),
            format_type='CTA8280F',
            status='ready',
        )

    def _browse(self, **params):
        params.setdefault('datafile_id', self.datafile.id)
        return self.client.get('/api/v1/browse/', params)

    def test_oversized_page_size_clamped_to_setting_max(self):
        """越界请求（100000）被钳到 500：回显钳后值，且**真的只回 500 行、翻成 2 页**。"""
        body = self._browse(page_size=100000).json()
        self.assertEqual(body['total'], N_ROWS)
        self.assertEqual(body['page_size'], CLAMPED_MAX)
        self.assertEqual(len(body['data']), CLAMPED_MAX)
        self.assertEqual(body['total_pages'], 2)

    def test_small_page_size_is_honoured_not_enlarged(self):
        """**下界刻意不钳到设置域**：请求 3 行就回 3 行。

        设置页的 50 下限是为「滚动别变成请求风暴」；对端点而言小页只是更小的载荷，
        不是百兆链路上的风险。把它抬到 50 会静默改变调用方要的块大小，也会让
        `test_browse_api.py` 按小页验证切片/越界的用例无法表达。
        本用例是**反「对齐」钉**：将来有人把下界也钳成对称区间，这条该红。
        """
        body = self._browse(page_size=3).json()
        self.assertEqual(body['page_size'], 3)
        self.assertEqual(len(body['data']), 3)
        self.assertEqual(body['total_pages'], 200)  # 600 行 / 每页 3 行

    def test_zero_and_negative_page_size_fall_back_to_one(self):
        """0/负数不能变成「整表」也不能崩 —— 防御性下界 1 必须还在。"""
        for bad in (0, -5):
            resp = self._browse(page_size=bad)
            self.assertEqual(resp.status_code, 200, f'page_size={bad}')
            self.assertEqual(resp.json()['page_size'], 1, f'page_size={bad}')

    def test_in_range_page_size_untouched(self):
        """合法值 200 必须原样通过 —— 钳位不能把正常块大小也吃掉。"""
        body = self._browse(page_size=200).json()
        self.assertEqual(body['page_size'], 200)
        self.assertEqual(len(body['data']), 200)


class ConstantsSingleSourceTests(SimpleTestCase):
    """结构：区间常量必须住在无 Django 依赖的公共常量模块，且写入侧引用它。"""

    def test_bounds_live_in_shared_constants(self):
        from apps.common import constants
        self.assertEqual(constants.PAGE_SIZE_MIN, CLAMPED_MIN)
        self.assertEqual(constants.PAGE_SIZE_MAX, CLAMPED_MAX)

    def test_serializer_no_longer_defines_its_own_copy(self):
        """序列化器只能引用共享常量，不能再自己赋一遍字面量。"""
        src = read(os.path.join(REPO_ROOT, 'apps', 'accounts', 'serializers.py'))
        self.assertIsNone(
            re.search(r'^PAGE_SIZE_(?:MIN|MAX)\s*=\s*\d+', src, re.M),
            'serializers.py 里不应再出现 PAGE_SIZE_MIN/MAX 的本地赋值（唯一事实源在 apps.common.constants）')
        self.assertIn('from apps.common.constants import', src)

    def test_model_default_matches_frontend_default(self):
        """「默认每页行数」的三份默认值必须相等：模型 100 / SettingsPage.vue 100 / 块大小初值 100。

        先例：chart_dpi 曾有模型 150 / 前端 150 / 代码 100 三个值（lessons 2026-09-19）。
        """
        from apps.accounts.models import UserSetting
        model_default = UserSetting._meta.get_field('page_size').default

        settings_src = read(SETTINGS_PAGE_VUE)
        page_defaults = re.findall(r'page_size:\s*(\d+)', settings_src)
        self.assertTrue(page_defaults, 'SettingsPage.vue 应保留 page_size 默认值')
        self.assertEqual({int(v) for v in page_defaults}, {model_default})

        block_defaults = literal_sets_by_carrier(r'PAGE_SIZE_DEFAULT\s*=\s*(\d+)', IRM_CARRIERS)
        self.assertTrue(block_defaults,
                        '块大小初值没有任何载体在定义（载体搬走时要同步把扫描指过去，不能空集放过）')
        for name, nums in block_defaults.items():
            self.assertEqual(nums, {model_default},
                             f'{name} 的块大小初值必须与模型默认 {model_default} 相等')


class FrontendLiteralScanTests(SimpleTestCase):
    """结构：前端两份字面量必须等于后端共享区间（改一处忘两处 → 本用例红）。"""

    def test_settings_dropdown_endpoints_match_bounds(self):
        src = read(TABLE_FORM_VUE)
        block = re.search(r'默认每页行数.*?</el-form-item>', src, re.S)
        self.assertIsNotNone(block, '设置页应保留「默认每页行数」表单项')
        values = [int(v) for v in re.findall(r':value="(\d+)"', block.group(0))]
        self.assertTrue(values, '表单项内应有 el-option 取值')
        self.assertEqual(min(values), CLAMPED_MIN)
        self.assertEqual(max(values), CLAMPED_MAX)

    def test_grid_block_size_bounds_match_bounds(self):
        bounds = literal_sets_by_carrier(r'BLOCK_SIZE_(?:MIN|MAX)\s*=\s*(\d+)', IRM_CARRIERS)
        self.assertTrue(bounds,
                        '前端 IRM 块大小上下界没有任何载体在定义（载体搬走时要同步把扫描指过去）')
        for name, nums in bounds.items():
            self.assertEqual(nums, {CLAMPED_MIN, CLAMPED_MAX},
                             f'{name} 的 IRM 块大小上下界必须与后端钳位区间一致')


if __name__ == '__main__':
    from django.test.utils import get_runner
    from django.conf import settings as dj_settings

    runner = get_runner(dj_settings)(['test.backend.test_page_size_bounds'], verbosity=2)
    sys.exit(runner.run_tests())
