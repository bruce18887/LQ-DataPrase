"""序列列（Serial_No）候选识别与 Part_Id 回退的回归测试。
（自 2473 行的 tests.py 按主题拆出，用例逐字搬迁。）
"""
import pandas as pd
import types
from django.test import SimpleTestCase
from apps.analysis.tests_param_guards import StaleParamAcrossFileSwitchTests


class SerialColumnPartIdFallbackTests(SimpleTestCase):
    """STS8200 文件（无 Serial 列）的序列分布回退到 PART_ID。

    回归：STS8200 数据列头是 SITE_NUM/PART_ID/...，没有 Serial_No，
    ``get_serial_column`` 只匹配 "serial" 导致 serial_distribution 返回
    400 no_serial_column，序列分布图无法绘制。修复：helpers 层增加
    'part'+'id' 列回退（与 wafer_map 既有逻辑一致），本测试钉住
    PART_ID 作为序列列 + 按 site 分组 + bin 失败判定的完整行为。
    """

    METADATA = {
        'format': 'STS8200',
        'mins': {'CONT_GATE': '-0.65'},
        'maxs': {'CONT_GATE': '-0.47'},
        'units': {'CONT_GATE': 'V'},
    }

    def _frame(self):
        # 8 行：PART_ID 是每 site 内的部件序号（1..4），无任何 serial 列
        return pd.DataFrame({
            'SITE_NUM': [8, 8, 7, 8, 7, 8, 7, 6],
            'PART_ID': [1, 2, 1, 3, 2, 4, 3, 1],
            'PASSFG': ['True', 'False', 'True', 'True', 'True',
                       'False', 'True', 'True'],
            'SOFT_BIN': [1, 5, 1, 1, 1, 2, 1, 1],
            'CONT_GATE': [-0.54, -0.54, -0.55, -0.53, -0.54, -0.52, -0.55, -0.54],
        })

    def _post(self, payload):
        factory, force_authenticate, restore = \
            StaleParamAcrossFileSwitchTests._patched_view(
                self._frame(), metadata=self.METADATA)
        self.addCleanup(restore)
        import types
        request = factory.post('/api/v1/analysis/serial_distribution/',
                               payload, format='json')
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False))
        return request

    def test_serial_distribution_falls_back_to_part_id(self):
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'param': 'CONT_GATE'})
        resp = AnalysisViewSet.as_view({'post': 'serial_distribution'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['serial_col'], 'PART_ID')
        # 按 site 分组：Site 6/7/8 各一个 series，共 8 个点
        names = [s['name'] for s in resp.data['series_data']]
        self.assertEqual(names, ['Site 6', 'Site 7', 'Site 8'])
        total = sum(len(s['data']) for s in resp.data['series_data'])
        self.assertEqual(total, 8)
        # 连续序列 x 轴 = PART_ID 1..4
        self.assertEqual(resp.data['continuous_serials'], [1, 2, 3, 4])
        # bin 判定：SOFT_BIN 5（行1）与 2（行5）为失败
        self.assertEqual(resp.data['pass_count'], 6)
        self.assertEqual(resp.data['fail_count'], 2)

    def test_part_id_rejected_as_data_param(self):
        """PART_ID 是分组键：作为数据参数必须 400（与 Serial_No 同规则）。"""
        from apps.analysis.views import AnalysisViewSet
        request = self._post({'file_id': 1, 'param': 'PART_ID'})
        resp = AnalysisViewSet.as_view({'post': 'serial_distribution'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.data['error'], 'param_is_metadata')


class SerialColumnCandidatesTests(SimpleTestCase):
    """CTA8280F Dut_No 序列分布适配 + 多候选 serial 列优先级。

    回归：``Site12358-Chip12345_c.csv``（真实机台导出）[Data] 表头
    无 Serial_No/Index_No，只有 Dut_No（100 × 5 site = 500 dies），
    旧 ``get_serial_column`` 只匹配 serial / part+id → 序列分布 400
    no_serial_column。修复：helpers 集中式候选检测（serial > dut >
    part+id 优先级，Dut_Pass 等布尔列不误匹配）+ 端点 ``serial_col``
    覆盖参数 + 响应 ``serial_candidates``。
    """

    METADATA = {
        'format': 'CTA8280F',
        'mins': {'KELVIN_VIN': '0'},
        'maxs': {'KELVIN_VIN': '10'},
        'units': {'KELVIN_VIN': 'ohm'},
    }

    def _frame_c_shape(self, sites=(1, 2, 3, 5, 8), duts=100):
        """_c 形态：无 Serial_No，Dut_No × Site_No 唯一确定一颗 die。"""
        rows = []
        for s in sites:
            for d in range(1, duts + 1):
                rows.append({
                    'Dut_No': d, 'Site_No': s, 'Dut_Pass': True,
                    'SW_Bin': 1, 'KELVIN_VIN': round(0.5 + d * 0.01, 4),
                })
        return pd.DataFrame(rows)

    def _frame_n_shape(self, duts=3):
        """_n 形态：Serial_No 与 Dut_No 并存（Serial_No 列序在后）。"""
        df = self._frame_c_shape(duts=duts)
        df.insert(0, 'Serial_No', range(1, len(df) + 1))
        return df

    def _patched_post(self, df, payload):
        from apps.analysis.views import AnalysisViewSet
        factory, force_authenticate, restore = \
            StaleParamAcrossFileSwitchTests._patched_view(df, metadata=self.METADATA)
        self.addCleanup(restore)
        request = factory.post('/api/v1/analysis/serial_distribution/',
                               {'file_id': 1, **payload}, format='json')
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False))
        return AnalysisViewSet.as_view({'post': 'serial_distribution'})(request)

    def test_get_serial_column_prefers_serial_over_dut(self):
        from apps.analysis.services.statistics import get_serial_column
        df = self._frame_n_shape()
        # 优先级：Serial_No 存在时必须选它，即使 Dut_No 列序在前
        self.assertEqual(get_serial_column(df), 'Serial_No')
        # 显式覆盖优先
        self.assertEqual(get_serial_column(df, preferred='Dut_No'), 'Dut_No')
        self.assertEqual(get_serial_column(df, preferred='Nope'), 'Serial_No')

    def test_get_serial_column_falls_back_to_dut_no(self):
        from apps.analysis.services.statistics import get_serial_column
        df = self._frame_c_shape()
        self.assertEqual(get_serial_column(df), 'Dut_No')

    def test_get_serial_candidates_order_and_dut_pass_excluded(self):
        from apps.analysis.services.statistics import get_serial_candidates
        df = self._frame_n_shape()
        self.assertEqual(get_serial_candidates(df), ['Serial_No', 'Dut_No'])
        # Dut_Pass 布尔列不得误匹配
        self.assertNotIn('Dut_Pass', get_serial_candidates(df))
        df2 = self._frame_c_shape()
        self.assertEqual(get_serial_candidates(df2), ['Dut_No'])
        # 既无 serial 也无 dut/part 列 → 空候选
        df3 = pd.DataFrame({'Site_No': [1, 1], 'SW_Bin': [1, 1],
                            'KELVIN_VIN': [0.5, 0.6]})
        self.assertEqual(get_serial_candidates(df3), [])

    def test_serial_distribution_dut_no_full_flow(self):
        """端点全链路：500 行 _c 形态 → 200、Dut_No、500 点、按 site 分组。"""
        df = self._frame_c_shape()
        df.loc[len(df) - 1, 'SW_Bin'] = 5  # 最后一颗 die fail
        resp = self._patched_post(df, {'param': 'KELVIN_VIN'})
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['serial_col'], 'Dut_No')
        self.assertEqual(resp.data['serial_candidates'], ['Dut_No'])
        total = sum(len(s['data']) for s in resp.data['series_data'])
        self.assertEqual(total, 500)
        names = [s['name'] for s in resp.data['series_data']]
        self.assertEqual(names, ['Site 1', 'Site 2', 'Site 3', 'Site 5', 'Site 8'])
        self.assertEqual(resp.data['continuous_serials'][0], 1)
        self.assertEqual(resp.data['continuous_serials'][-1], 100)
        self.assertEqual(resp.data['pass_count'], 499)
        self.assertEqual(resp.data['fail_count'], 1)

    def test_serial_col_override_and_candidates(self):
        """serial_col 覆盖：_n 形态显式选 Dut_No → 响应用 Dut_No。"""
        df = self._frame_n_shape()
        resp = self._patched_post(df, {'param': 'KELVIN_VIN',
                                       'serial_col': 'Dut_No'})
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['serial_col'], 'Dut_No')
        self.assertEqual(resp.data['serial_candidates'],
                         ['Serial_No', 'Dut_No'])

    def test_serial_col_invalid_400(self):
        df = self._frame_c_shape()
        resp = self._patched_post(df, {'param': 'KELVIN_VIN',
                                       'serial_col': 'Nope'})
        resp.render()
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.data['error'], 'serial_col_not_found')

    def test_serial_distribution_no_candidate_400(self):
        df = pd.DataFrame({'Site_No': [1, 1], 'SW_Bin': [1, 1],
                           'KELVIN_VIN': [0.5, 0.6]})
        resp = self._patched_post(df, {'param': 'KELVIN_VIN'})
        resp.render()
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.data['error'], 'no_serial_column')

    def test_param_list_excludes_all_serial_candidates(self):
        """_n 形态（Serial_No + Dut_No 并存）：参数列表两者都不能出现。

        回归：旧逻辑只排除自动选中的第一个 serial 列，Dut_No 作为数值列
        泄漏进参数选择器，用户可把它当直方图参数（本身是分组键）。
        """
        from apps.analysis.views import AnalysisViewSet
        df = self._frame_n_shape()
        df['KELVIN_SW'] = df['KELVIN_VIN'] * 2  # 额外数值列
        factory, force_authenticate, restore = \
            StaleParamAcrossFileSwitchTests._patched_view(df, metadata=self.METADATA)
        self.addCleanup(restore)
        request = factory.post('/api/v1/analysis/histogram/',
                               {'file_id': 1}, format='json')
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False))
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        params = list(resp.data['results'].keys())
        self.assertNotIn('Serial_No', params)
        self.assertNotIn('Dut_No', params)
        self.assertNotIn('Dut_Pass', params)
        self.assertIn('KELVIN_VIN', params)
        self.assertIn('KELVIN_SW', params)
