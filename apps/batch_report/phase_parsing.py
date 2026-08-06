"""批次文件名阶段解析与排序。

从批次文件名识别测试阶段（CP/UIS/FT/BF/RT/QA/2D3D），集中管理：
- PHASE_ORDER：阶段标识排序（CP → UIS → FT → BF → RT → QA → 2D3D）
- detect_phase：文件名 → 阶段名；无法识别时回退为去扩展名的短文件名
- phase_sort_key：阶段排序键（UISQA* 排在 UIS 版本号之后）
- STAGE_ORDER / stage_of：阶段名 → 流程阶段一级聚合（分阶段良率/过滤用）
  流程阶段只有 CP → UIS → FT 三个：FT/BF/RT/QA/2D3D 同属 FT 终测全流程，不再细分
- stage_sort_key：流程阶段排序键
"""
import os
import re

# 阶段标识排序（明细粒度）：CP(晶圆测试) → UIS → FT(终测) → BF(老化) → RT(复测) → QA(质量) → 2D3D
PHASE_ORDER = {'CP': 0, 'UIS': 1, 'FT': 2, 'BF': 3, 'RT': 4, 'QA': 5, '2D3D': 6}

# 流程阶段一级聚合顺序（分阶段良率/阶段过滤）：
# FT 涵盖 FT/BF/RT/QA/2D3D（终测全流程），与用户确认的阶段模型一致
STAGE_ORDER = {'CP': 0, 'UIS': 1, 'FT': 2}

# 标准格式: _CP1_ / _FT1-1_ / _QA1-2_ / _UIS1.0_ / _UISQA1_
# 下划线/连字符定界避免误匹配产品码（如 CP0283）；[.-] 兼容版本号 UIS1.0 与序号 FT1-2
_PHASE_PATTERN = re.compile(r'_((?:UIS(?:QA)?|CP|FT|QA|RT|BF)\d+(?:[.-]\d+)?)[_-]')

# 复合格式: EQC1_QA1-1 → QA1-1, FT1_FT1-1 → FT1-1, FT1_RT1-1 → RT1-1, EQC1-2D3D → 2D3D
# 前缀_EQC/QEC/FT/UIS 与主阶段之间用 _ 或 - 分隔，捕获主阶段标识（含序号）
_COMPOUND_PATTERN = re.compile(
    r'(?:EQC\d+|QEC\d+|FT\d+|UIS\d+(?:\.\d+)?)[_-]'
    r'((?:CP|FT|QA|RT|BF|UIS)\d+(?:[.-]\d+)?|2D3D)'
)


def detect_phase(filename: str) -> str:
    """从批次文件名解析测试阶段。

    优先级: 复合格式 > 标准格式。均无法识别时回退为去扩展名的短文件名
    （不再返回 'UNKNOWN'，保证每个文件都有可区分的阶段标识）。
    """
    fname_upper = filename.upper()

    m = _COMPOUND_PATTERN.search(fname_upper)
    if m:
        return m.group(1)

    m = _PHASE_PATTERN.search(fname_upper)
    if m:
        return m.group(1)

    return os.path.splitext(filename)[0]


def phase_sort_key(phase_name: str):
    """按半导体测试流程排序: CP → UIS → FT → BF → RT → QA → 2D3D → 其他(99)。

    次级: CP1 < CP2（首数字）；UIS 按版本号（UIS1.0 < UIS1.1 < UIS2.0）；
    UISQA* 在 UIS 组内排末尾（主版本=99）。
    """
    for prefix, order in PHASE_ORDER.items():
        if phase_name.startswith(prefix):
            if prefix == 'UIS':
                upper = phase_name.upper()
                if upper.startswith('UISQA'):
                    return (order, 99, 0)
                m = re.match(r'UIS(\d+)(?:\.(\d+))?', upper)
                return (order, int(m.group(1)) if m else 0,
                        int(m.group(2)) if m and m.group(2) else 0)
            m = re.search(r'(\d+)', phase_name)
            return (order, int(m.group(1)) if m else 0, 0)
    return (99, 0, 0)


def stage_of(phase_name: str) -> str:
    """阶段名 → 流程阶段一级聚合名（分阶段良率/过滤用）。

    CP1 → CP, UIS1.0/UISQA1 → UIS, FT1-1/RT1/QA1/BF1/2D3D → FT, 未识别 → 其他。
    """
    if phase_name.startswith('CP'):
        return 'CP'
    if phase_name.startswith('UIS'):
        return 'UIS'
    for prefix in ('FT', 'BF', 'RT', 'QA', '2D3D'):
        if phase_name.startswith(prefix):
            return 'FT'
    return '其他'


def stage_sort_key(stage_name: str):
    """流程阶段排序键: CP(0) < UIS(1) < FT(2) < 其他(99)。"""
    return (STAGE_ORDER.get(stage_name, 99),)
