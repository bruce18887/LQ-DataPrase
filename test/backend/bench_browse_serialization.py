"""Benchmark: browse row serialization — records vs values (orient) 格式对比.

查看数据（browse）性能优化基准：对真实 CTA8280F 种子文件（10000×188）计时
两种 rows 序列化路径，并断言两种路径的 JSON 输出语义逐值相等（NaN/inf→null）。

结果（pandas 3.0.3, 10000×188, 1289 fail 行）：
* records（旧，对象数组）:    to_json ~0.15s / 45.4MB；前端 parse 实测 1299ms(266MB)
* values（新，行值数组）:     to_json ~0.05s / 15.2MB；前端 parse 实测  281ms(176MB)
* 62.7MB 真实大文件（68006×142）：records 208.9MB / values 68.0MB

Node 实测参考（同规模 mock）：JSON.parse records 1299ms vs values 281ms（4.6x）。

Run directly:  python test/backend/bench_browse_serialization.py
（bench_* 命名不会被 DiscoverRunner 收集，`manage.py test` 不会误跑。）
"""
import json
import os
import sys
import time

# test/backend/ → project root (for `import config` / `from apps...`)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

import pandas as pd  # noqa: E402

from apps.analysis.services.statistics import detect_fail_data  # noqa: E402
from apps.datafiles.parsers import get_parser  # noqa: E402

SAMPLE_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'Data', 'SampleData', 'CTA8280F',
    'DA35_BPC50338_CL08D4.01#AEA3_414A07_2604140567_FT_20260420_164504.csv',
)


def _timed(fn, min_of=3):
    best = float('inf')
    for _ in range(min_of):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


def main():
    assert os.path.exists(SAMPLE_CSV), f'missing seed file: {SAMPLE_CSV}'
    parser = get_parser('CTA8280F')
    df, metadata = parser.parse(SAMPLE_CSV)
    assert df is not None
    fail_indices, _fail_columns, fail_cells = detect_fail_data(df, metadata)
    print(f'file: {os.path.basename(SAMPLE_CSV)}  rows={len(df)}  cols={len(df.columns)}  fail_rows={len(set(fail_indices))}')

    # 旧路径：records 对象数组（__fail_cells__ 附加在行对象上）
    def old_path():
        paged = df.copy()
        paged['__fail_cells__'] = [fail_cells.get(i, []) for i in paged.index]
        return paged.to_json(orient='records', date_format='iso')

    # 新路径：values 行值数组 + 并行 fail_cells
    def new_data_path():
        return df.to_json(orient='values', date_format='iso')

    def new_fail_path():
        return json.dumps([fail_cells.get(i, []) for i in df.index], ensure_ascii=False)

    old_str = old_path()
    data_str = new_data_path()
    fail_str = new_fail_path()

    # 语义逐值相等：旧 records 行对象 == 新 values+zip 行对象
    cols = list(df.columns)
    vals = json.loads(data_str)
    fails = json.loads(fail_str)
    new_rows = []
    for i in range(len(vals)):
        o = {'__fail_cells__': fails[i]}
        for j in range(len(cols)):
            o[cols[j]] = vals[i][j]
        new_rows.append(o)
    assert json.loads(old_str) == new_rows, 'records 与 values+zip 两种路径 JSON 语义不一致！'
    print('语义等价验证: PASS (records == values+zip 逐值相等)')

    total_old = len(old_str)
    total_new = len(data_str) + len(fail_str) + len(json.dumps(cols, ensure_ascii=False))
    print(f'payload: old records={total_old/1e6:.1f}MB  new values+fail_cells={total_new/1e6:.1f}MB')

    t_old = _timed(old_path)
    t_data = _timed(new_data_path)
    t_fail = _timed(new_fail_path)
    print(f'old records to_json:  {t_old*1000:6.0f} ms')
    print(f'new values  to_json:  {t_data*1000:6.0f} ms + fail_cells {t_fail*1000:6.0f} ms')


if __name__ == '__main__':
    main()
