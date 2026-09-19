"""CPK 三级阈值是否真的来自用户设置（系统设置 → 📐 CPK 阈值）。

回归背景：设置里 A/B/C 三个阈值曾「存了没人读」—— `compute_cpk` 虽然收
`cpk_a/cpk_b/cpk_c` 形参，但全仓调用点一个都不传，分级永远用函数默认值
1.67/1.33/1.0。用户把 A 阈改成 2.5，屏幕徽章、导出色、低 CPK 警报全不变。

用例只走视图 / service，不直调 `compute_cpk`：只有穿过调用链才能证明
「读设置 → 穿参 → 分级」没断，而直调函数即便上层硬编码也会通过。
"""
import types

import pandas as pd
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.common.user_settings import DEFAULT_CPK_THRESHOLDS, CpkThresholds, get_cpk_thresholds


def make_user(cpk_a=1.67, cpk_b=1.33, cpk_c=1.0, settings=True):
    """带 settings 的 user 替身（仿 tests_chart_config 的形态，不碰 DB）。

    settings=False 模拟「无 OneToOne 设置行」；只给部分字段模拟老替身。
    """
    user = types.SimpleNamespace(
        pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
        is_staff=False, is_superuser=False,
    )
    if settings:
        user.settings = types.SimpleNamespace(
            cpk_a_threshold=cpk_a, cpk_b_threshold=cpk_b, cpk_c_threshold=cpk_c)
    return user


# 合成数据：mean=10.4516…, std(ddof=0)≈0.0025, 限值 8.0/14.3
# → Cp=(14.3-8.0)/(6*std) 与 Cpk 都在数百量级，远大于默认 A 阈 1.67。
SYNTH_DF = pd.DataFrame({'Param0': [10.4480, 10.4495, 10.4510, 10.4519,
                                    10.4530, 10.4545, 10.4553]})
SYNTH_META = {'format': 'CTA8280F', 'mins': {'Param0': '8.0'},
              'maxs': {'Param0': '14.3'}, 'units': {'Param0': 'uA'}}


class GetCpkThresholdsTests(SimpleTestCase):
    """三值一起读；缺哪个字段哪个回退，不牵连其余两值。"""

    def test_reads_all_three_values(self):
        self.assertEqual(get_cpk_thresholds(make_user(2.5, 1.8, 1.2)),
                         CpkThresholds(2.5, 1.8, 1.2))

    def test_partial_settings_only_falls_back_for_missing_field(self):
        """只带 cpk_b 的替身（既有 tests_chart_config 就这形态）：a/c 用默认，b 用给的值。"""
        user = types.SimpleNamespace(settings=types.SimpleNamespace(cpk_b_threshold=2.0))
        self.assertEqual(get_cpk_thresholds(user), CpkThresholds(1.67, 2.0, 1.0))

    def test_missing_settings_row_falls_back_entirely(self):
        self.assertEqual(get_cpk_thresholds(make_user(settings=False)),
                         DEFAULT_CPK_THRESHOLDS)

    def test_none_user_falls_back(self):
        self.assertEqual(get_cpk_thresholds(None), DEFAULT_CPK_THRESHOLDS)

    def test_non_numeric_value_falls_back_for_that_field_only(self):
        user = types.SimpleNamespace(settings=types.SimpleNamespace(
            cpk_a_threshold='oops', cpk_b_threshold=2.0, cpk_c_threshold=1.0))
        self.assertEqual(get_cpk_thresholds(user), CpkThresholds(1.67, 2.0, 1.0))


class HistogramCpkLevelFollowsSettingsTests(SimpleTestCase):
    """``POST /analysis/histogram/`` 的 cpk_level / cpk_color 按账号阈值分级。"""

    URL = '/api/v1/analysis/histogram/'

    def _post(self, user):
        import apps.analysis.views.analysis_views as mod
        from apps.analysis.views import AnalysisViewSet

        original = mod._load_df_from_request          # 必须在打补丁之前取原值
        datafile = types.SimpleNamespace(id=1, filename='fake.csv',
                                         format_type=SYNTH_META['format'])
        mod._load_df_from_request = lambda request: (SYNTH_DF, datafile, SYNTH_META, None)
        self.addCleanup(setattr, mod, '_load_df_from_request', original)

        request = APIRequestFactory().post(
            self.URL, {'file_id': 1, 'params': ['Param0']}, format='json')
        force_authenticate(request, user=user)
        response = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        response.render()
        self.assertEqual(response.status_code, 200, response.content)
        return response.data['results']['Param0']

    def _cpk_value(self):
        return self._post(make_user())['cpk']

    def test_default_thresholds_grade_a(self):
        row = self._post(make_user())
        self.assertGreater(row['cpk'], 1.67, '前置：样本 CPK 应在默认 A 阈之上')
        self.assertEqual(row['cpk_level'], 'A级 (优秀)')
        self.assertEqual(row['cpk_color'], 'green')

    def test_raising_thresholds_downgrades_the_same_cpk(self):
        """CPK 数值不变、只把三级阈值抬到它之上 → 必须掉到 D级。

        这条就是「设置真被读」的判据：阈值若仍硬编码，等级不会动。
        """
        v = self._cpk_value()
        raised = self._post(make_user(v + 1, v + 2, v + 3))
        self.assertEqual(raised['cpk'], v, 'CPK 本身不该随阈值变')
        self.assertEqual(raised['cpk_level'], 'D级 (不足)')
        self.assertEqual(raised['cpk_color'], 'red')

    def test_b_and_c_boundaries_use_user_values(self):
        """B/C 边界同样跟随：a 卡在 v 之上，b/c 夹住 v → 在 B级与 C级之间切换。"""
        v = self._cpk_value()
        at_b = self._post(make_user(v + 1, v, v - 1))
        self.assertEqual(at_b['cpk_level'], 'B级 (良好)', 'cpk == b 阈应判 B级')
        at_c = self._post(make_user(v + 1, v + 0.5, v))
        self.assertEqual(at_c['cpk_level'], 'C级 (一般)', 'cpk == c 阈应判 C级')

    def test_custom_limit_cpk_also_follows(self):
        """CL 模式的 custom_cpk_* 走同一份阈值（同函数内第 2 个 compute_cpk 点）。"""
        import apps.analysis.views.analysis_views as mod
        from apps.analysis.views import AnalysisViewSet

        original = mod._load_df_from_request
        datafile = types.SimpleNamespace(id=1, filename='fake.csv',
                                         format_type=SYNTH_META['format'])
        mod._load_df_from_request = lambda request: (SYNTH_DF, datafile, SYNTH_META, None)
        self.addCleanup(setattr, mod, '_load_df_from_request', original)

        v = self._cpk_value()
        request = APIRequestFactory().post(self.URL, {
            'file_id': 1, 'params': ['Param0'],
            'range_type': 'CL', 'custom_low': 10.40, 'custom_high': 10.50,
        }, format='json')
        force_authenticate(request, user=make_user(v + 1, v + 2, v + 3))
        response = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        response.render()
        row = response.data['results']['Param0']
        self.assertIsNotNone(row['custom_cpk'], '前置：CL 模式应算出 custom_cpk')
        self.assertEqual(row['custom_cpk_level'], 'D级 (不足)',
                         'custom_cpk 的分级也必须用账号阈值')


class BatchChartsExportCpkFollowsSettingsTests(SimpleTestCase):
    """批量图表导出的 CPK 等级色也必须跟随账号阈值（与分析页同一份）。"""

    def _summary_cpk_fill(self, thresholds):
        import io

        import openpyxl

        from apps.export.export_batch_charts_xlsx import (
            build_batch_charts_xlsx_with_charts,
        )

        buf = build_batch_charts_xlsx_with_charts(
            SYNTH_DF, SYNTH_META, ['Param0'], cpk_thresholds=thresholds)
        ws = openpyxl.load_workbook(io.BytesIO(buf))['总览']
        # 总览第 1 个参数行 = 第 2 行；CPK 在第 8 列（export_batch_charts_xlsx.py 的
        # cell_cpk + _apply_cpk_style）
        return ws.cell(row=2, column=8).fill.start_color.rgb

    def test_fill_follows_thresholds(self):
        base = self._summary_cpk_fill(DEFAULT_CPK_THRESHOLDS)
        self.assertTrue(base.endswith('4CAF50'), f'默认阈值下应为 green 底色，实得 {base}')
        v = compute_histogram_cpk_value()
        tight = self._summary_cpk_fill(CpkThresholds(v + 1, v + 2, v + 3))
        self.assertTrue(tight.endswith('F44336'),
                        f'阈值抬到 CPK={v} 之上后应为 red 底色，实得 {tight}')

    def test_ppt_builder_passes_account_thresholds(self):
        """PPT 分支的等级只出现在烘进 PNG 的标题里，读不回 → 用间谍钉住穿参这一跳。"""
        import apps.export.export_ppt as mod
        from apps.export.export_ppt import build_batch_charts_pptx

        seen = {}
        real = mod.compute_cpk

        def spy(*args, **kwargs):
            seen.update(kwargs)
            return real(*args, **kwargs)

        mod.compute_cpk = spy
        self.addCleanup(setattr, mod, 'compute_cpk', real)
        datafile = types.SimpleNamespace(id=1, filename='fake.csv')
        build_batch_charts_pptx(datafile, SYNTH_DF, SYNTH_META, ['Param0'],
                                cpk_thresholds=CpkThresholds(2.5, 1.8, 1.2))
        self.assertEqual(seen.get('cpk_a'), 2.5, f'PPT 未把 A 阈传给 compute_cpk：{seen}')
        self.assertEqual(seen.get('cpk_b'), 1.8)
        self.assertEqual(seen.get('cpk_c'), 1.2)


def compute_histogram_cpk_value():
    """取合成数据在默认阈值下的 CPK 数值（供各用例把阈值夹到它两侧）。"""
    from apps.analysis.services.statistics import compute_cpk, compute_range_statistics

    stats = compute_range_statistics(SYNTH_DF['Param0'], SYNTH_META, 'Param0')
    return compute_cpk(stats['mean'], stats['std'], stats['rdl'][0], stats['rdl'][1])['cpk']


class DashboardCpkFollowsSettingsTests(SimpleTestCase):
    """仪表板总览等级 + 低 CPK 警报与分析页共用同一份阈值（防两套口径）。"""

    def _rows(self, thresholds):
        from apps.dashboard.views import compute_test_item_overview
        return compute_test_item_overview(SYNTH_DF, SYNTH_META, {},
                                          thresholds=thresholds)

    def test_overview_level_follows_thresholds(self):
        base = self._rows(DEFAULT_CPK_THRESHOLDS)[0]
        self.assertEqual(base['cpk_level'], 'A级 (优秀)')
        v = base['cpk']
        tight = self._rows(CpkThresholds(v + 1, v + 2, v + 3))[0]
        self.assertEqual(tight['cpk_level'], 'D级 (不足)')
        self.assertEqual(tight['cpk_color'], 'red')

    def test_low_cpk_alert_uses_user_b_threshold(self):
        """警报的判定线与文案都必须是用户的 B 阈，不能写死 1.33。"""
        from apps.dashboard.views import _derive_param_stats, compute_quality_alerts

        base = self._rows(DEFAULT_CPK_THRESHOLDS)
        v = base[0]['cpk']
        stats = _derive_param_stats(base)

        loose = compute_quality_alerts(99.0, stats, [],
                                       thresholds=DEFAULT_CPK_THRESHOLDS)
        self.assertFalse([a for a in loose if a['type'] == 'low_cpk'],
                         '默认阈值下 CPK≈数百 不该被判低')

        tight = compute_quality_alerts(99.0, stats, [],
                                       thresholds=CpkThresholds(v + 1, v + 2, v + 3))
        alerts = [a for a in tight if a['type'] == 'low_cpk']
        self.assertTrue(alerts, f'阈值抬到 {v} 之上应报低 CPK')
        self.assertIn(f'{v + 2:g}', alerts[0]['message'],
                      f'警报文案应内插用户 B 阈，实际：{alerts[0]["message"]}')
