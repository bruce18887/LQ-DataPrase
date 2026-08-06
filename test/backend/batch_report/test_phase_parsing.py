"""
测试阶段解析逻辑 (Phase Detection)

覆盖：
- 标准格式: _CP1_, _FT1-1_, _QA1-2_, _UIS1.0_, _UISQA1_
- 复合格式: EQC1_QA1-1, FT1_FT1-1, FT1_RT1-1, EQC1-2D3D
- UIS 阶段: UIS1.0/1.1/2.0/3.0, UISQA1/2（独立阶段）
- 回退: 无法识别时返回去扩展名的短文件名（不再返回 UNKNOWN）
- 排序: phase_sort_key（UIS 在 CP 后 FT 前，UISQA 在 UIS 版本后）
- 聚合: stage_of（分阶段良率一级聚合）
"""
import pytest

from apps.batch_report.phase_parsing import (
    detect_phase, phase_sort_key, stage_of, stage_sort_key,
)


class TestStandardPhaseFormat:
    """标准格式: _PHASE_ 或 _PHASE-SEQ_"""

    def test_cp1(self):
        assert detect_phase('SOMEDATA_CP1_MORE') == 'CP1'

    def test_ft1(self):
        assert detect_phase('SOMEDATA_FT1_MORE') == 'FT1'

    def test_qa1(self):
        assert detect_phase('SOMEDATA_QA1_MORE') == 'QA1'

    def test_rt1(self):
        assert detect_phase('SOMEDATA_RT1_MORE') == 'RT1'

    def test_bf1(self):
        assert detect_phase('SOMEDATA_BF1_MORE') == 'BF1'

    def test_ft1_with_seq(self):
        assert detect_phase('SOMEDATA_FT1-1_MORE') == 'FT1-1'

    def test_qa1_with_seq(self):
        assert detect_phase('SOMEDATA_QA1-2_MORE') == 'QA1-2'

    def test_rt1_with_seq(self):
        assert detect_phase('SOMEDATA_RT1-1_MORE') == 'RT1-1'


class TestUISPhaseFormat:
    """UIS 阶段: 版本号带 .，UISQA 为独立阶段"""

    def test_uis1_0(self):
        fname = 'BPD80590_C01JC6#AAA1A12606290025_UIS1.0_P262702101_20260715001944.csv'
        assert detect_phase(fname) == 'UIS1.0'

    def test_uis1_1(self):
        fname = 'BPD80590_C01JC6#AAA1A12606290025_UIS1.1_P262702101_20260715163358.csv'
        assert detect_phase(fname) == 'UIS1.1'

    def test_uis2_0(self):
        fname = 'BPD80590_C01JC6#AAA1A12606290025_UIS2.0_P262702101_20260717224729.csv'
        assert detect_phase(fname) == 'UIS2.0'

    def test_uis3_0(self):
        fname = 'BPD80590_C01JC6#AAA1A12606290025_UIS3.0_P262702101_20260718030135.csv'
        assert detect_phase(fname) == 'UIS3.0'

    def test_uisqa1_independent_phase(self):
        """UISQA1 保留为独立阶段，不映射为 QA1"""
        fname = 'BPD80590_C01JC6#AAA1A12606290025_UISQA1_P262702101_20260725202048.csv'
        assert detect_phase(fname) == 'UISQA1'

    def test_uisqa2_independent_phase(self):
        fname = 'BPD80590_C01JC6#AAA1A12606290025_UISQA2_P262702101_20260725210058.csv'
        assert detect_phase(fname) == 'UISQA2'


class TestCompoundPhaseFormat:
    """复合格式: EQC/FT前缀_PHASE"""

    def test_eqc_qa1(self):
        assert detect_phase('EQC1_QA1-1') == 'QA1-1'

    def test_eqc_ft1(self):
        assert detect_phase('EQC1_FT1-1') == 'FT1-1'

    def test_ft_ft1(self):
        assert detect_phase('FT1_FT1-1') == 'FT1-1'

    def test_ft_rt1(self):
        assert detect_phase('FT1_RT1-1') == 'RT1-1'

    def test_eqc_2d3d(self):
        assert detect_phase('EQC1-2D3D') == '2D3D'

    def test_qec_qa1(self):
        assert detect_phase('QEC1_QA1-1') == 'QA1-1'


class TestRealFileNames:
    """真实文件名格式"""

    def test_real_bpd60320(self):
        fname = 'BPD60320_C01QF7#AAA12605260001_EQC1_QA1-1_R2605260036_20260605_224054'
        assert detect_phase(fname) == 'QA1-1'

    def test_real_ft1(self):
        fname = 'SOMEDATA_EQC1_FT1-1_R2605260036_20260605_224054'
        assert detect_phase(fname) == 'FT1-1'

    def test_real_rt1(self):
        fname = 'SOMEDATA_EQC1_RT1-1_R2605260036_20260605_224054'
        assert detect_phase(fname) == 'RT1-1'


class TestNoFalseMatches:
    """产品码不应误匹配为阶段；无法识别时回退为短文件名"""

    def test_product_code_cp0283(self):
        """CP0283 是产品码，不是阶段 → 回退为完整短文件名"""
        assert detect_phase('BPD60320_CP0283#AAA_MORE') == 'BPD60320_CP0283#AAA_MORE'

    def test_product_code_ft_without_delimiter(self):
        """FT后面无下划线/连字符分隔符，不应匹配（如产品码中嵌入的FT）"""
        assert detect_phase('PRODUCTFT100_MORE') == 'PRODUCTFT100_MORE'

    def test_unrecognized_falls_back_to_short_filename(self):
        """无法识别时返回去扩展名的短文件名"""
        assert detect_phase('SOMEDATA_HW_20260726.csv') == 'SOMEDATA_HW_20260726'

    def test_empty_string(self):
        assert detect_phase('') == ''


class TestPhaseSortKey:
    """阶段排序: CP → UIS → FT → BF → RT → QA → 2D3D → 其他"""

    def test_cp_before_uis_before_ft(self):
        assert phase_sort_key('CP1') < phase_sort_key('UIS1.0') < phase_sort_key('FT1')

    def test_uisqa_after_uis_versions(self):
        assert phase_sort_key('UIS3.0') < phase_sort_key('UISQA1')
        assert phase_sort_key('UISQA2') < phase_sort_key('FT1')

    def test_uis_version_order(self):
        """UIS 内部按版本号排序: 1.0 < 1.1 < 1.2 < 1.3 < 2.0 < 3.0"""
        keys = ['UIS3.0', 'UIS1.2', 'UIS1.1', 'UIS1.3', 'UIS1.0', 'UIS2.0']
        sorted_keys = sorted(keys, key=phase_sort_key)
        assert sorted_keys == ['UIS1.0', 'UIS1.1', 'UIS1.2', 'UIS1.3', 'UIS2.0', 'UIS3.0']

    def test_ft_before_rt_before_qa(self):
        assert phase_sort_key('FT1') < phase_sort_key('RT1') < phase_sort_key('QA1')

    def test_unknown_last(self):
        assert phase_sort_key('BPD_HW_20260726') > phase_sort_key('QA3')

    def test_number_secondary_sort(self):
        assert phase_sort_key('QA1') < phase_sort_key('QA2')


class TestStageOf:
    """分阶段良率一级聚合：只有 CP / UIS / FT 三个流程阶段，FT 涵盖 FT/BF/RT/QA/2D3D"""

    def test_stage_mapping(self):
        assert stage_of('CP1') == 'CP'
        assert stage_of('UIS1.0') == 'UIS'
        assert stage_of('UISQA1') == 'UIS'
        assert stage_of('FT1-1') == 'FT'
        assert stage_of('BF1') == 'FT'
        assert stage_of('RT2') == 'FT'
        assert stage_of('QA3') == 'FT'
        assert stage_of('2D3D') == 'FT'

    def test_unrecognized_stage(self):
        assert stage_of('BPD80590_HW_20260726') == '其他'

    def test_stage_sort_order(self):
        """CP < UIS < FT < 其他"""
        assert stage_sort_key('CP') < stage_sort_key('UIS') < stage_sort_key('FT')
        assert stage_sort_key('FT') < stage_sort_key('其他')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
