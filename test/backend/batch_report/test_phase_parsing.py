"""
测试阶段解析逻辑 (Phase Detection)

覆盖：
- 标准格式: _CP1_, _FT1-1_, _QA1-2_
- 复合格式: EQC1_QA1-1, FT1_FT1-1, FT1_RT1-1, EQC1-2D3D
- 边界情况: UNKNOWN, 产品码不误匹配
"""
import re
import pytest


def detect_phase(fname_upper: str) -> str:
    """从 batch_report/views.py 提取的阶段检测逻辑"""
    phase_type = None

    # 1) Compound: EQC1_QA1-1 → QA1-1, FT1_FT1-1 → FT1-1, FT1_RT1-1 → RT1-1, EQC1-2D3D → 2D3D
    m = re.search(r'(?:EQC\d+|QEC\d+|FT\d+)[_-]((?:CP|FT|QA|RT|BF)\d+(?:-\d+)?|2D3D)', fname_upper)
    if m:
        phase_type = m.group(1)
    else:
        # 2) Standard: _CP1_, _FT1-1_, _QA1-2_ — use underscore/hyphen delimiter to avoid CP0283 (program code)
        m = re.search(r'_((?:CP|FT|QA|RT|BF)\d+(?:-\d+)?)[_-]', fname_upper)
        if m:
            phase_type = m.group(1)
    if not phase_type:
        phase_type = 'UNKNOWN'

    return phase_type


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
    """产品码不应误匹配为阶段"""

    def test_product_code_cp0283(self):
        """CP0283 是产品码，不是阶段"""
        assert detect_phase('BPD60320_CP0283#AAA_MORE') == 'UNKNOWN'

    def test_product_code_ft_without_delimiter(self):
        """FT后面无下划线/连字符分隔符，不应匹配（如产品码中嵌入的FT）"""
        # FT100 本身是有效阶段格式，但 PRODUCTFT100 不应匹配
        assert detect_phase('PRODUCTFT100_MORE') == 'UNKNOWN'

    def test_unknown_phase(self):
        """无法识别时返回 UNKNOWN"""
        assert detect_phase('RANDOM_TEXT_NO_PHASE') == 'UNKNOWN'

    def test_empty_string(self):
        assert detect_phase('') == 'UNKNOWN'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
