"""导出图表 DPI 是否真的跟随用户设置（系统设置 → 📊 显示设置 → 图表 DPI）。

回归背景：`chart_dpi` 曾「存了没人读」——`charts.py` 的 `_get_export_dpi()` 无参恒
返回 100、`export_ppt.py` 另写死 120，用户改设置零反应。这批断言把整条链路钉住：
读库 → 钳位 → 穿进多进程渲染任务 → 落到 PNG 实际像素。
"""
import io
import os
import re
import shutil
import struct
import tempfile
import unittest
import zipfile
from unittest import mock

import pandas as pd
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import UserSetting
from apps.datafiles.models import DataFile
from apps.datafiles.parsers import get_parser

from .charts import (
    EXPORT_DPI_DEFAULT,
    EXPORT_DPI_MAX,
    EXPORT_DPI_MIN,
    _render_histogram_payload,
    clamp_export_dpi,
)
from .user_prefs import get_export_dpi

User = get_user_model()

GAGE_S1_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'Data', 'SampleData', 'Gage', 'gage_m_S1.csv',
)


def set_user_chart_dpi(user, value: int):
    """把某个账号的 chart_dpi 写成 value，没有行就补一行（UserSetting 不随 create_user
    自动建行，全仓没有 post_save 信号）。

    **写走 manager，不经 `user` 实例上那份反向缓存** —— 生产里 `chart_dpi` 的写手是
    「另一个请求里的另一个对象」（`UserSettingsView.put` 经 serializer 保存**它自己那个请求**
    的 `request.user` 挂着的行），它同步不了**本请求**实例上的那份缓存。D4 之后的
    `_record_last_visit` **不是**这种形状、别再拿它当例子：它就在同一个请求里 save 挂在
    `request.user` 缓存上的那个对象（第二轮实测：调用后缓存与库里是同一个值）。
    改成 `user.settings.save()` 看着也能过，但它用写侧补齐了读侧的缓存，等于把
    「一次写能不能到达下一次读」这张端到端网删掉（D1 评审实测到的形状是同实例连改两次
    设置后 `989 not greater than 989` 的假绿，网一断就再也抓不到）。配套的读侧见
    `DpiReachesRenderedPngTests._authenticate_fresh`：每个请求重新取实例，两边合起来
    才是生产的读→写→读。阶段 2 若给 `UserSetting` 加进程内 TTL 缓存，这两条用例就是
    负责当场变红的东西。
    """
    if UserSetting.objects.filter(user=user).update(chart_dpi=value):
        return
    UserSetting.objects.create(user=user, chart_dpi=value)


def png_size(blob: bytes):
    """从 PNG 字节头读宽高（IHDR 的 width/height 是两个大端 uint32）。"""
    assert blob[:8] == b'\x89PNG\r\n\x1a\n', '不是 PNG'
    width, height = struct.unpack('>II', blob[16:24])
    return width, height


class ClampExportDpiTests(TestCase):
    """钳位：只接受 72–600（与设置页 el-input-number 的 min/max 同口径），其余回退默认。"""

    def test_values_in_range_pass_through(self):
        self.assertEqual(clamp_export_dpi(72), EXPORT_DPI_MIN)
        self.assertEqual(clamp_export_dpi(150), 150)
        self.assertEqual(clamp_export_dpi(600), EXPORT_DPI_MAX)

    def test_out_of_range_and_garbage_fall_back(self):
        self.assertEqual(clamp_export_dpi(10), EXPORT_DPI_MIN, '过小 → 下限')
        self.assertEqual(clamp_export_dpi(9999), EXPORT_DPI_MAX, '过大 → 上限')
        for bad in (None, '', 'abc', float('nan'), [], {}):
            self.assertEqual(clamp_export_dpi(bad), EXPORT_DPI_DEFAULT, f'{bad!r} 应回退默认')


class GetExportDpiFromUserTests(TestCase):
    """读库：账号值生效；无设置行/脏值回退默认，不抛。"""

    def setUp(self):
        self.user = User.objects.create_user(username='dpi-owner', password='pw')

    def test_reads_the_users_stored_value(self):
        set_user_chart_dpi(self.user, 300)
        self.assertEqual(get_export_dpi(self.user), 300)

    def test_clamps_stored_value_out_of_ui_range(self):
        set_user_chart_dpi(self.user, 9999)
        self.assertEqual(get_export_dpi(self.user), EXPORT_DPI_MAX)

    def test_missing_settings_row_falls_back_to_default(self):
        """「没有行」得在**新实例**上验：D1 之后通路 2 先看 `user` 上的那份反向缓存。

        同一实例上「写 300 → 读（缓存装上）→ 用 manager 删行 → 再读」拿到的是缓存里那份
        stale 300 —— 那是 Django 反向缓存的既有语义（manager 侧的 DELETE 不会通知实例缓存），
        不是 helper 的 bug，本条把它一起钉住，免得后人把「读到 300」当成读路径缺陷去改
        `get_user_setting`。真实请求的起点是每请求新建的 `User`（同
        `DpiReachesRenderedPngTests._authenticate_fresh`），所以「无行 → 默认值」用新实例断。
        """
        set_user_chart_dpi(self.user, 300)
        self.assertEqual(get_export_dpi(self.user), 300)
        UserSetting.objects.filter(user=self.user).delete()
        self.assertEqual(get_export_dpi(self.user), 300,
                         '库里已无行但实例缓存没被通知 ⇒ 仍是 300（Django 语义，别改读路径）')
        self.assertEqual(get_export_dpi(User.objects.get(pk=self.user.pk)), EXPORT_DPI_DEFAULT)

    def test_none_user_falls_back_to_default(self):
        self.assertEqual(get_export_dpi(None), EXPORT_DPI_DEFAULT)


@unittest.skipUnless(
    os.path.exists(GAGE_S1_PATH),
    'SampleData/Gage 目录不存在（跳过）',
)
class DpiReachesRenderedPngTests(APITestCase):
    """端到端：改设置 → 导出文件里嵌入的 PNG 像素真的变。"""

    def setUp(self):
        # 作业产物落在 MEDIA_ROOT/jobs/… 下：重定向到临时目录，别污染真实 media/
        self.media = tempfile.mkdtemp(prefix='lqdp-dpi-')
        self.addCleanup(shutil.rmtree, self.media, True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(username='dpi-exporter', password='pw')
        self.client.force_authenticate(self.user)
        self.datafile = DataFile.objects.create(
            owner=self.user,
            filename='gage_m_S1.csv',
            file_path=GAGE_S1_PATH,
            file_size=os.path.getsize(GAGE_S1_PATH),
            format_type='CTA8290D',
            status='ready',
        )
        df_parsed, _ = get_parser('CTA8290D').parse(GAGE_S1_PATH)
        self.param = next(
            c for c in df_parsed.columns if df_parsed[c].dtype in ('int64', 'float64')
        )

    def _authenticate_fresh(self):
        """每次发请求前重新取一份 `User` 实例：真实请求里认证中间件都是新建的
        `request.user`，挂在实例上的反向缓存必然是空的。直接复用 `setUp` 里
        `force_authenticate(self.user)` 那个对象，等于把两个请求钉在同一个实例上，
        「上一次写能不能被下一次读到」就再也没有人验了（见 `set_user_chart_dpi` 的说明）。
        """
        self.client.force_authenticate(User.objects.get(pk=self.user.pk))

    def _export_one_chart(self, fmt: str) -> bytes:
        self._authenticate_fresh()
        # 同步重活端点已删（B8）：走作业池，并强制走「池不可用」的同步回落分支
        # ——判据只关心 DPI 设置能不能穿到产物，不该在这里等异步队列。
        with mock.patch('apps.jobs.executor.executor_available', return_value=False):
            resp = self.client.post('/api/v1/jobs/export_batch_charts/', {
                'file_id': self.datafile.id,
                'params': [self.param],
                'format': fmt,
            }, format='json')
        self.assertEqual(resp.status_code, 200)
        return b''.join(resp.streaming_content)

    @staticmethod
    def _first_png(archive_bytes: bytes, media_dir: str) -> bytes:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
            names = [n for n in zf.namelist() if n.startswith(media_dir) and n.endswith('.png')]
            assert names, f'压缩包里找不到 {media_dir}/*.png'
            return zf.read(sorted(names)[0])

    def test_histogram_payload_pixels_scale_with_dpi(self):
        """渲染原语本身收 dpi：同数据 dpi 翻倍 → 位图尺寸同步变大。"""
        df_parsed, _ = get_parser('CTA8290D').parse(GAGE_S1_PATH)
        series = pd.to_numeric(df_parsed[self.param], errors='coerce').dropna().to_numpy()
        common = dict(
            param=self.param, data_series=series, site_values=None, site_series=None,
            mean_val=float(series.mean()), std_val=float(series.std()),
            rdl_min=float(series.min()), rdl_max=float(series.max()),
        )
        low = png_size(_render_histogram_payload(dpi=EXPORT_DPI_MIN, **common).getvalue())
        high = png_size(_render_histogram_payload(dpi=300, **common).getvalue())
        self.assertGreater(high[0], low[0], '宽应随 dpi 增长')
        self.assertGreater(high[1], low[1], '高应随 dpi 增长')
        ratio = high[0] / low[0]
        self.assertAlmostEqual(ratio, 300 / EXPORT_DPI_MIN, delta=0.1,
                               msg='像素应与 dpi 成正比（同一图形尺寸）')

    def test_xlsx_embedded_png_follows_user_setting(self):
        set_user_chart_dpi(self.user, EXPORT_DPI_DEFAULT)
        small = png_size(self._first_png(
            self._export_one_chart('xlsx'), 'xl/media/'))

        set_user_chart_dpi(self.user, 300)
        large = png_size(self._first_png(
            self._export_one_chart('xlsx'), 'xl/media/'))

        self.assertGreater(large[0], small[0],
                           f'用户把 DPI 调到 300 后嵌入图必须变大：{small} → {large}')

    def test_pptx_embedded_png_follows_user_setting(self):
        """同一份 DPI 设置必须同时管住 xlsx 与 pptx（与缺陷 #6 的「两分支同配置」同口径）。"""
        set_user_chart_dpi(self.user, EXPORT_DPI_DEFAULT)
        small = png_size(self._first_png(
            self._export_one_chart('pptx'), 'ppt/media/'))

        set_user_chart_dpi(self.user, 300)
        large = png_size(self._first_png(
            self._export_one_chart('pptx'), 'ppt/media/'))

        self.assertGreater(large[0], small[0], f'PPTX 也要跟随 DPI：{small} → {large}')


class DpiRangeContractTests(TestCase):
    """区间三方一致：写入校验 / 读取钳位 / 设置页控件必须同一个上下界。

    三处各写一份字面量是「改了 UI 上限但后端仍拒」这类失效的温床，故用源码断言钉住。
    先例：test/backend/test_export_stats_consistency.py 也用源码扫描做契约护栏。
    """

    CHART_FORM_VUE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'frontend', 'src', 'pages', 'settings', 'components', 'ChartSettingsForm.vue',
    )

    def test_serializer_bounds_match_render_bounds(self):
        from apps.accounts.serializers import CHART_DPI_MAX, CHART_DPI_MIN
        self.assertEqual((CHART_DPI_MIN, CHART_DPI_MAX),
                         (EXPORT_DPI_MIN, EXPORT_DPI_MAX))

    def test_settings_page_input_matches_render_bounds(self):
        with open(self.CHART_FORM_VUE, encoding='utf-8') as fh:
            src = fh.read()
        # 图表 DPI 那个 el-input-number 的 min/max（用 :min=/:max= 绑定）
        block = re.search(r'图表 DPI.*?</el-form-item>', src, re.S)
        self.assertIsNotNone(block, '设置页应保留「图表 DPI」表单项')
        nums = re.findall(r':(?:min|max)="(\d+)"', block.group(0))
        self.assertEqual([int(n) for n in nums], [EXPORT_DPI_MIN, EXPORT_DPI_MAX],
                         '设置页 DPI 上下界必须与后端钳位区间一致')

    def test_model_default_is_the_render_default(self):
        """模型默认值必须等于 EXPORT_DPI_DEFAULT：否则新用户的"默认"会静默改变导出体积。"""
        field = UserSetting._meta.get_field('chart_dpi')
        self.assertEqual(field.default, EXPORT_DPI_DEFAULT)


class ChartDpiApiValidationTests(APITestCase):
    """写入侧守卫：越界 DPI 必须 400，别让导出被 100000 DPI 拖爆。"""

    def setUp(self):
        self.user = User.objects.create_user(username='dpi-api', password='pw')
        self.client.force_authenticate(self.user)

    def _put(self, value):
        return self.client.put('/api/v1/auth/settings/',
                               {'chart_dpi': value}, format='json')

    def test_in_range_accepted(self):
        self.assertEqual(self._put(300).status_code, 200)

    def test_out_of_range_rejected(self):
        for bad in (EXPORT_DPI_MIN - 1, EXPORT_DPI_MAX + 1, 0, -5):
            self.assertEqual(self._put(bad).status_code, 400, f'{bad} 应被拒')

    def test_rejected_write_does_not_change_stored_value(self):
        self._put(300)
        self._put(99999)
        self.assertEqual(get_export_dpi(self.user), 300)
