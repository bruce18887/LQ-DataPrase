"""Tests for ETS88 尾部元数据行过滤（查看数据 ag-grid 末尾两行 bug）.

用户报告（2026-08-27）：查看数据页用 ETS88（BPD93204）时，表格末尾会多出
两行 ``Data Collection Start Date,<时间戳>`` / ``Data Collection Stop Date``
——它们是 ETS88 文件在数据区块之后的**尾部元数据**（无数据语义），但
``pd.read_csv(skiprows=...)`` 把它们当作数据行读进 DataFrame：

* 显示：ag-grid 末尾出现两行，Bin 列为 NaN；
* 统计数据被污染：Bin=NaN != 1 → 这两行被误计为 FAIL 行
  （用户截图 TOTAL=10 / FAIL=2 / YIELD=80%，实际 8 行数据全是 Bin1）；
* 导出同样带着这两行垃圾行。

修复：``ETS88Parser.parse()`` 读取后用 ``drop_tail_metadata_rows`` 剔除
匹配 ``Data Collection (Start|Stop) Date`` 的行（正则只扫最前 4 列）。

Run directly:  python test/backend/test_ets88_tail_metadata.py
(Runs against an isolated test DB via DiscoverRunner — dev db.sqlite3 is
never touched.)
"""
import os
import shutil
import sys
import tempfile

# test/backend/ → project root (for `import config` / `from apps...`)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ETS88 fixture 需要识别为 ETS88（identify_format 要求 'ETS Datalog Reporter'）
import django  # noqa: E402

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
django.setup()

from django.test import TestCase  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.accounts.models import User  # noqa: E402
from apps.datafiles.models import DataFile  # noqa: E402
from apps.datafiles.parsers.ets88 import ETS88Parser  # noqa: E402

PASSWORD = 'x-pass-12345678'

# 数据区块：55 列（前 5 列会被解析器强制改名为 Site #/Serial #/Bin/XCoord/YCoord，
# 第 5/6 列 Date/Time —— min/max 行含「.range」无效值所以不参与 fail 判定）
N_COLS = 55


def _mkdtemp(prefix: str) -> str:
    """临时目录（不用 tempfile.mkdtemp：部分环境对 mkdtemp 目录有受限 DACL，
    makedirs + uuid 等同语义且无 ACL 副作用）。"""
    import uuid
    d = os.path.join(tempfile.gettempdir(), f'{prefix}_{os.getpid()}_{uuid.uuid4().hex[:8]}')
    os.makedirs(d, exist_ok=True)
    return d


def _make_ets88_csv() -> str:
    """构造最小 ETS88 文件：header 块（Test Name/Number + Lower/Upper Limit + Units）
    + marker（Site #,Serial #,Bin,XCoord,YCoord）+ 5 行数据 + 2 行尾部元数据。
    """
    def row(*vals):
        # 与 header 等宽（不足补空），保证 read_csv 不会按最大行宽错位
        v = list(vals)[:N_COLS]
        return ','.join(str(x) if x is not None else '' for x in v) + ',' * (N_COLS - len(v))

    header = ['Test Name'] + [''] * 3 + ['Date', 'Time', 'Active_site'] + [f'T{i}' for i in range(1, N_COLS - 6)]
    unit = ['Units'] + [''] * 3 + ['', '', ''] + ['V'] * (N_COLS - 6)
    mins = ['Lower Limit'] + [''] * 3 + ['', '', ''] + ['0.0'] * (N_COLS - 6)
    maxs = ['Upper Limit'] + [''] * 3 + ['', '', ''] + ['5.0'] * (N_COLS - 6)

    lines = [
        ','.join(header),
        ','.join(['Test Number'] + [''] * (N_COLS - 1)),
        ','.join(mins),
        ','.join(maxs),
        ','.join(unit),
        ','.join(['Site #', 'Serial #', 'Bin', 'XCoord', 'YCoord'] + [''] * (N_COLS - 5)),
    ]
    # 5 行 Bin=1 数据
    for i in range(1, 6):
        lines.append(row(1, i, 1, 100 + i, 200 + i, 20260524, 100000 + i, 4) + ',' + ','.join(['1.0'] * (N_COLS - 8)))
    # 尾部元数据（bug 本体）
    lines.append(row('Data Collection Start Date', '05/24/2026 16:53:46'))
    lines.append('Data Collection Stop  Date,05/24/2026 16:59:06' + ',' * (N_COLS - 2))
    return '\n'.join(lines) + '\n'


class Ets88TailMetadataParserTests(TestCase):
    """解析器层：尾部元数据行不进 DataFrame，但 start/end_time 仍正常提取。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmpdir = _mkdtemp('ets88_tail_meta_test')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.path = os.path.join(self.tmpdir, 'ets88_fixture.csv')
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(_make_ets88_csv())

    def test_tail_metadata_rows_are_dropped(self):
        df, meta = ETS88Parser().parse(self.path)
        self.assertIsNotNone(df)
        # 5 行真实数据，2 行 Data Collection 元数据被剔除
        self.assertEqual(df.shape[0], 5)
        # 元数据行内容不得出现在任何列
        for col in df.columns[:4]:
            vals = df[col].astype(str)
            self.assertFalse(
                vals.str.contains('Data Collection', case=False, na=False, regex=False).any(),
                f'列 {col} 不应含 Data Collection 元数据',
            )
        # Bin 全部为 1（不再有 NaN Bin 假数据行）
        self.assertEqual(set(df['Bin'].tolist()), {1.0})

    def test_tail_metadata_still_extracted_as_metadata(self):
        """尾部元数据虽然不进 DataFrame，仍要被提取为文件的 start_time/end_time。"""
        _df, meta = ETS88Parser().parse(self.path)
        self.assertEqual(meta['start_time'], '05/24/2026 16:53:46')
        self.assertEqual(meta['end_time'], '05/24/2026 16:59:06')


class Ets88TailMetadataBrowseApiTests(TestCase):
    """API 层：/browse/ 响应不含 Data Collection 行，total 为真实数据行数。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmpdir = _mkdtemp('ets88_tail_meta_api')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user('ets88_tester', 'ets88@localhost', PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.path = os.path.join(self.tmpdir, 'ets88_api_fixture.csv')
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(_make_ets88_csv())
        self.datafile = DataFile.objects.create(
            owner=self.user,
            filename=os.path.basename(self.path),
            file_path=self.path,
            file_size=os.path.getsize(self.path),
            format_type='ETS88',
            status='ready',
        )

    def test_browse_total_excludes_tail_metadata(self):
        resp = self.client.get('/api/v1/browse/', {'datafile_id': self.datafile.id, 'page_size': 99999})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # 5 行数据 + 2 行元数据 —— total 只应含真实数据行
        self.assertEqual(body['total'], 5)
        self.assertEqual(len(body['data']), 5)
        # 任何数据行的最前 4 列都不含 Data Collection
        for row_vals in body['data']:
            head = ' | '.join(str(v) for v in row_vals[:4])
            self.assertNotIn('Data Collection', head)
        # fail_row_count 应反映真实 fail（本 fixture 全 Bin1 → 0）
        self.assertEqual(body['fail_row_count'], 0)


if __name__ == '__main__':
    # Isolated test DB (never touches dev db.sqlite3) + transaction rollback.
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=1)
    failures = runner.run_tests(['test.backend.test_ets88_tail_metadata'])
    sys.exit(1 if failures else 0)
