"""Golden characterization tests for the three ATE CSV parsers.

CTA8280F / CTA8290D / STS8200 share the same parse pipeline (locate marker,
read header/unit/min/max lines, read CSV, align columns, coerce numerics,
collect header metadata). These tests pin the observable output before the
pipeline is lifted into ``BaseAteCsvParser`` so the refactor stays behaviour
neutral.
"""
import os
import tempfile

import pandas as pd
from django.test import SimpleTestCase

from apps.datafiles.parsers.cta8280f import CTA8280FParser
from apps.datafiles.parsers.cta8290d import CTA8290DParser
from apps.datafiles.parsers.sts8200 import STS8200Parser


class _TempCsvMixin:
    def write_csv(self, text):
        fd, path = tempfile.mkstemp(suffix='.csv', text=True)
        os.close(fd)
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return path


class CTA8290DParserTests(_TempCsvMixin, SimpleTestCase):
    CONTENT = """\
TestFile,/remote/path/program.pgs
LotID,LOT-A
Operator,alice
Station,ST1
Device_Name,DEV1
Tester_Type,T1
TestType,FT
AllTestTime,12.3
HandlerName,H1
StartTime,2026-01-01 10:00:00
EndTime,2026-01-01 10:05:00
[Data]
Serial_No,Part_No,Site_No,TestA,TestB
,,,V,A
,,,0.0,0.0
,,,10.0,5.0
1,P1,1,1.0,2.0
2,P2,1,3.0,4.0
"""

    def test_parse_columns_values_and_metadata(self):
        df, meta = CTA8290DParser().parse(self.write_csv(self.CONTENT))

        self.assertEqual(
            list(df.columns),
            ['Serial_No', 'Part_No', 'Site_No', 'TestA', 'TestB'],
        )
        self.assertEqual(df['TestA'].tolist(), [1.0, 3.0])
        self.assertEqual(df['TestB'].tolist(), [2.0, 4.0])
        self.assertTrue(pd.api.types.is_numeric_dtype(df['TestA']))

        self.assertEqual(meta['format'], 'CTA8290D')
        self.assertEqual(meta['program_name'], 'program.pgs')
        self.assertEqual(meta['file_path'], os.path.abspath(meta['file_path']))
        self.assertEqual(meta['units'], {
            'Serial_No': '', 'Part_No': '', 'Site_No': '', 'TestA': 'V', 'TestB': 'A',
        })
        self.assertEqual(meta['mins']['TestA'], '0.0')
        self.assertEqual(meta['maxs']['TestB'], '5.0')
        self.assertEqual(meta['lot_id'], 'LOT-A')
        self.assertEqual(meta['operator'], 'alice')
        self.assertEqual(meta['station'], 'ST1')
        self.assertEqual(meta['device_name'], 'DEV1')
        self.assertEqual(meta['tester_type'], 'T1')
        self.assertEqual(meta['test_type'], 'FT')
        self.assertEqual(meta['total_test_time'], '12.3')
        self.assertEqual(meta['handler'], 'H1')
        self.assertEqual(meta['start_time'], '2026-01-01 10:00:00')
        self.assertEqual(meta['end_time'], '2026-01-01 10:05:00')

    def test_missing_marker_returns_none(self):
        df, meta = CTA8290DParser().parse(self.write_csv('no marker here\n'))
        self.assertIsNone(df)
        self.assertIsNone(meta)


class CTA8280FParserTests(_TempCsvMixin, SimpleTestCase):
    CONTENT = """\
TestFileName,/remote/path/program2.pgs
LotID,LOT-B
Operator,bob
Test Station,ST2
Device Name,DEV2
Tester type,T2
TestType,FT
AllTestTime,10.0
HandlerType,H2
StartTime,2026-01-02 11:00:00
EndTime,2026-01-02 11:05:00
[Data]
Index_No,Dut_No,Serial_No,Site_No,TestA,TestB
,,,,V,A
,,,,0,0
,,,,10,5
0,1,100,1,1.5,2.5
1,2,101,1,3.5,4.5
"""

    def test_parse_columns_values_and_metadata(self):
        df, meta = CTA8280FParser().parse(self.write_csv(self.CONTENT))

        self.assertEqual(
            list(df.columns),
            ['Index_No', 'Dut_No', 'Serial_No', 'Site_No', 'TestA', 'TestB'],
        )
        self.assertEqual(df['TestA'].tolist(), [1.5, 3.5])
        self.assertEqual(df['TestB'].tolist(), [2.5, 4.5])
        self.assertTrue(pd.api.types.is_numeric_dtype(df['TestB']))

        self.assertEqual(meta['format'], 'CTA8280F')
        self.assertEqual(meta['program_name'], 'program2.pgs')
        self.assertEqual(meta['units']['TestA'], 'V')
        self.assertEqual(meta['mins']['TestB'], '0')
        self.assertEqual(meta['maxs']['TestA'], '10')
        self.assertEqual(meta['lot_id'], 'LOT-B')
        self.assertEqual(meta['operator'], 'bob')
        self.assertEqual(meta['station'], 'ST2')
        self.assertEqual(meta['device_name'], 'DEV2')
        self.assertEqual(meta['tester_type'], 'T2')
        self.assertEqual(meta['test_type'], 'FT')
        self.assertEqual(meta['total_test_time'], '10.0')
        self.assertEqual(meta['handler'], 'H2')
        self.assertEqual(meta['start_time'], '2026-01-02 11:00:00')
        self.assertEqual(meta['end_time'], '2026-01-02 11:05:00')

    def test_missing_marker_returns_none(self):
        df, meta = CTA8280FParser().parse(self.write_csv('no marker here\n'))
        self.assertIsNone(df)
        self.assertIsNone(meta)


class STS8200ParserTests(_TempCsvMixin, SimpleTestCase):
    CONTENT = """\
STS8200-43 StationA
Beginning Time: 2026-01-03 09:00:00
Ending Time: 2026-01-03 09:05:00
LOT_ID: LOT-C
User: carol
Total Testing Time: 9.5
Handler: H3
Program: /remote/path/JAVBN281R3CYCAAV1.6.pgs
SITE_NUM,PART_ID,PASSFG,SOFT_BIN,T_TIME,TestA
,,,,ms,V
,,,,0,0
,,,,10,5
# end of limits
1,P1,1,1,0.1,1.5
2,P2,1,1,0.2,3.5
"""

    def test_parse_columns_values_and_metadata(self):
        df, meta = STS8200Parser().parse(self.write_csv(self.CONTENT))

        self.assertEqual(
            list(df.columns),
            ['SITE_NUM', 'PART_ID', 'PASSFG', 'SOFT_BIN', 'T_TIME', 'TestA'],
        )
        self.assertEqual(df['TestA'].tolist(), [1.5, 3.5])
        self.assertEqual(df['T_TIME'].tolist(), [0.1, 0.2])
        self.assertTrue(pd.api.types.is_numeric_dtype(df['TestA']))

        self.assertEqual(meta['format'], 'STS8200')
        self.assertEqual(meta['program_name'], 'JAVBN281R3CYCAAV1.6.pgs')
        self.assertEqual(meta['units']['TestA'], 'V')
        self.assertEqual(meta['mins']['TestA'], '0')
        self.assertEqual(meta['maxs']['TestA'], '5')
        self.assertEqual(meta['lot_id'], 'LOT-C')
        self.assertEqual(meta['operator'], 'carol')
        self.assertEqual(meta['station'], 'STS8200-43 StationA')
        self.assertEqual(meta['device_name'], 'BN281R3CYCAAV1.6')
        self.assertEqual(meta['total_test_time'], '9.5')
        self.assertEqual(meta['handler'], 'H3')
        self.assertEqual(meta['start_time'], '2026-01-03 09:00:00')
        self.assertEqual(meta['end_time'], '2026-01-03 09:05:00')

    def test_missing_marker_returns_none(self):
        df, meta = STS8200Parser().parse(self.write_csv('no marker here\n'))
        self.assertIsNone(df)
        self.assertIsNone(meta)
