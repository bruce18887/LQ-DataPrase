"""Gage Summary 的输入形状夹具（被 ``test_gage_sheet_shape`` 与列宽平价判据共用）。

文件名不以 ``test`` 开头 ⇒ Django ``DiscoverRunner`` 的 ``test*.py`` 发现规则不会把它当用例
收集（同 ``test/backend/sheet_readback.py``、``test/backend/excel_cf.py`` 的先例）。
之所以抽出来而不是两处各写一份：这两组判据必须跑在**同一批形状**上（一份钉产物字节，
一份钉「列宽与整表回读算出的一致」），各自造数据就等于各算各的列宽。

形状是自足的（固定 seed 的合成帧，不读 ``Data/SampleData`` 的真实样例）：真实样例不入库，
CI 的干净检出里拿不到，判据就会退化成 skip。测试项名用 ``PAR0001..`` 这种假名，规格限
是 ``0`` / ``6×(位次+1)`` 的十进制串，文件名是 ``pin<i>.csv_S<i>``——都不含真实料号、
机台主机名或本地路径。
"""
import numpy as np
import pandas as pd

from apps.gage.gage_legacy_builder import build_gage_summary_excel

#: 超长参数名：51 个窄字符 ⇒ 显示宽度 51 + 2.5 = 53.5 ⇒ 钳到上界 42.0
LONG_PARAM = 'PARA_TEST_MEASUREMENT_CHANNEL_EXTENDED_ID_000128'
#: 东亚宽字符参数名：6 个汉字 ⇒ 显示宽度 12 ⇒ 12 + 2.5 = 14.5；按 1 计会得 8.5
WIDE_PARAM = '漏电流阈值名'

SHAPES = {
    # 窄表：4 文件 ⇒ 每组 4 行、组内**有中间行**（下发形状判据的靶形），列号留在单字母区
    'narrow': dict(n_params=6, n_rows=12, n_files=4, seed=20261028),
    # 宽表：40 参数 + 3 系统列 = 43 列 ⇒ 文件表列区间 1..51（A..AY），双字母区从
    # 第 27 列（AA）起、占 27..51；100 行 ⇒ 触达数据行写入上限（last_col = 列数 + 8）
    'wide': dict(n_params=40, n_rows=100, n_files=2, seed=20261029),
}


def frame_and_meta(seed, n_params, n_rows):
    rng = np.random.default_rng(seed)
    cols = {
        'Site_No': ['1'] * n_rows,
        'SW_Bin': [1] * n_rows,
        'Serial_No': [str(i) for i in range(n_rows)],
    }
    params = [f'PAR{ci:04d}' for ci in range(1, n_params + 1)]
    for ci, name in enumerate(params, start=1):
        cols[name] = rng.normal(5 + ci, 1.0, n_rows).round(4)
    meta = {
        'format': 'CTA8290D', 'tester_id': 'T-PIN', 'program_name': 'pin.dll',
        'start_time': '2026-01-01 00:00:00',
        'units': {name: 'V' for name in params},
        'mins': {name: '0' for name in params},
        'maxs': {name: str(6 * (ci + 1)) for ci, name in enumerate(params)},
    }
    return pd.DataFrame(cols), meta


def file_info(shape, idx=1, n_rows=None, n_params=None):
    cfg = SHAPES[shape]
    df, meta = frame_and_meta(
        cfg['seed'] + idx,
        cfg['n_params'] if n_params is None else n_params,
        cfg['n_rows'] if n_rows is None else n_rows)
    return {'filename': f'pin{idx}.csv_S{idx}', 'sheet_name': f'pin{idx}_S{idx}',
            'df': df, 'metadata': meta}


def datasets(shape):
    cfg = SHAPES[shape]
    return [file_info(shape, idx) for idx in range(1, cfg['n_files'] + 1)]


_BUILD_CACHE = {}


def build_shape(shape):
    """同一形状只建一次（产物字节只由输入决定；缓存与逐例重建由字节判据自己钉住等价）。"""
    if shape not in _BUILD_CACHE:
        _BUILD_CACHE[shape] = build_gage_summary_excel(datasets(shape))
    return _BUILD_CACHE[shape]


def synthetic_dataset(filename, columns, mins=None, maxs=None, units=None):
    """按「测试列名 → 值列表」造一份 ``file_datasets`` 条目（列宽对抗形状用）。

    系统列按 CTA8290D 的口径补齐，规格限缺省是 ``'0'``/``'10'`` 的十进制串 ——
    平价判据要变的只有测试列名与数值本身。列名别撞 ``SYSTEM_COLUMNS`` 与
    ``NON_NUMERIC_KEYWORDS``（'min'/'max'/'na'/'-'/'none' 子串），否则该项会被筛掉。
    """
    n = len(next(iter(columns.values())))
    frame_cols = {'Site_No': ['1'] * n, 'SW_Bin': [1] * n,
                  'Serial_No': [str(i) for i in range(n)]}
    frame_cols.update(columns)
    return {
        'filename': filename,
        'sheet_name': filename.split('.')[0],
        'df': pd.DataFrame(frame_cols),
        'metadata': {
            'format': 'CTA8290D', 'tester_id': 'T-PIN', 'program_name': 'pin.dll',
            'start_time': '2026-01-01 00:00:00',
            'units': units if units is not None else {c: 'V' for c in columns},
            'mins': mins if mins is not None else {c: '0' for c in columns},
            'maxs': maxs if maxs is not None else {c: '10' for c in columns},
        },
    }


def group_rows(shape):
    """``(组首行集合, 组末行集合, 组内中间行集合)``；每组 n_files 行，自 DATA_FIRST_ROW 起。"""
    from apps.gage.gage_summary_sheet import DATA_FIRST_ROW
    cfg = SHAPES[shape]
    n_files, n_params = cfg['n_files'], cfg['n_params']
    starts, ends, middles = set(), set(), set()
    for gi in range(n_params):
        start = DATA_FIRST_ROW + gi * n_files
        end = start + n_files - 1
        starts.add(start)
        ends.add(end)
        middles.update(range(start + 1, end))
    return starts, ends, middles
