from .base import BaseATEParser, DATA_FORMAT_CONFIG, NON_NUMERIC_COLUMNS
import pandas as pd
import os
from collections import deque
from typing import Optional, Tuple, Dict
import logging

logger = logging.getLogger(__name__)

# 有界读取的两个保留量（见 parse() 里的注释）：
# HEADER_KEEP 对齐 base.extract_header_metadata 的 scan_limit=80；
# TAIL_KEEP 对齐「时间字段在文件尾，扫最后 20 行」的既有口径。
HEADER_KEEP = 80
TAIL_KEEP = 20

class ETS88Parser(BaseATEParser):
    format_type = 'ETS88'
    
    def parse(self, file_path: str) -> Tuple[Optional[pd.DataFrame], Optional[Dict]]:
        import pandas as pd
        import os
        
        config = DATA_FORMAT_CONFIG.get(self.format_type)
        if not config:
            return None, None
        
        # 只保留解析真正会读的行：头部（读到 marker 行为止，且至少 HEADER_KEEP 行，
        # 让下面 `head[:80]`/`head[:50]` 看到的与整读时逐字一致）+ 尾部 TAIL_KEEP 行
        # （ETS88 的时间字段在文件尾）。旧写法 `f.readlines()` 把整只 288MB 文件读成
        # 35,339 条 Python 字符串（实测驻留 ≈275MB）；时间只省 0.07s（0.31s→0.24s），
        # 省的是**峰值**——解析缓存预算抬到 4096MB 后，这种瞬时叠加才是要紧的。
        marker = config['marker']
        head = []
        tail = deque(maxlen=TAIL_KEEP)
        marker_idx = None
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for i, line in enumerate(f):
                if marker_idx is None:
                    head.append(line)
                    if marker in line:
                        marker_idx = i
                elif len(head) < HEADER_KEEP:
                    # marker 很靠前时仍要把前 80 行收齐，否则头部元数据扫描范围会变
                    head.append(line)
                tail.append(line)
        if marker_idx is None:
            return None, None
        
        search_keywords = {
            'header': ['Test Name', 'Test Number', 'Date', 'Time'],
            'min': ['Lower Limit'],
            'max': ['Upper Limit'],
            'unit': ['Units'],
        }
        
        header_line_idx = None
        min_line_idx = None
        max_line_idx = None
        unit_line_idx = None
        
        for i in range(max(0, marker_idx - 20), marker_idx):
            line_lower = head[i].lower()
            
            if header_line_idx is None:
                if any(kw.lower() in line_lower for kw in search_keywords['header']):
                    parts = head[i].split(',')
                    if len(parts) > 50:
                        header_line_idx = i
                        continue
            
            if min_line_idx is None and any(kw.lower() in line_lower for kw in search_keywords['min']):
                min_line_idx = i
                continue
            
            if max_line_idx is None and any(kw.lower() in line_lower for kw in search_keywords['max']):
                max_line_idx = i
                continue
            
            if unit_line_idx is None and any(kw.lower() in line_lower for kw in search_keywords['unit']):
                unit_line_idx = i
                continue
        
        if header_line_idx is None:
            header_line_idx = config.get('header_line', marker_idx - 5)
        if min_line_idx is None:
            min_line_idx = config.get('min_line', marker_idx - 3)
        if max_line_idx is None:
            max_line_idx = config.get('max_line', marker_idx - 2)
        if unit_line_idx is None:
            unit_line_idx = config.get('unit_line', marker_idx - 1)
        
        header_line = head[header_line_idx].strip()
        min_line = head[min_line_idx].strip()
        max_line = head[max_line_idx].strip()
        unit_line = head[unit_line_idx].strip()
        
        header_columns = [col.strip().strip('"') for col in header_line.split(',')]
        ets88_meta_cols = ['Site #', 'Serial #', 'Bin', 'XCoord', 'YCoord']
        for i in range(min(len(ets88_meta_cols), len(header_columns))):
            header_columns[i] = ets88_meta_cols[i]
        
        unit_columns = [unit.strip().strip('"') for unit in unit_line.split(',')]
        min_columns = [min_val.strip().strip('"') for min_val in min_line.split(',')]
        max_columns = [max_val.strip().strip('"') for max_val in max_line.split(',')]
        
        # Skip keyword labels in first column for min/max lines
        if min_columns and min_columns[0].lower() in ['lower limit', 'min']:
            min_columns[0] = ''
        if max_columns and max_columns[0].lower() in ['upper limit', 'max']:
            max_columns[0] = ''
        
        if len(unit_columns) < len(header_columns):
            unit_columns.extend([''] * (len(header_columns) - len(unit_columns)))
        if len(min_columns) < len(header_columns):
            min_columns.extend([''] * (len(header_columns) - len(min_columns)))
        if len(max_columns) < len(header_columns):
            max_columns.extend([''] * (len(header_columns) - len(max_columns)))
        
        columns = self.make_column_names_unique(header_columns)
        data_start_row = marker_idx + 1

        # ETS88 文件的**数据区块之后**还跟着两行尾部元数据（无数据语义）：
        #   Data Collection Start Date,12/25/2024 12:30:39
        #   Data Collection Stop  Date,12/25/2024 16:33:01
        # 这些行只有少量字段（8 列），会被 pd.read_csv 当作数据行读进 DataFrame
        # （其余列 NaN）→ 显示在查看数据 ag-grid 末尾、SampleData 列值被算进
        # Bin 统计（Bin=NaN != 1 被误判为 FAIL 行）→ 在读取时就丢弃。
        df = pd.read_csv(file_path, skiprows=data_start_row, header=None,
                        on_bad_lines='skip', encoding='utf-8')
        df = self.drop_tail_metadata_rows(df)
        if len(df.columns) == len(columns):
            df.columns = columns
        elif len(df.columns) > len(columns):
            df = df.iloc[:, :len(columns)]
            df.columns = columns
        else:
            cols_to_pad = len(columns) - len(df.columns)
            for _ in range(cols_to_pad):
                df[len(df.columns)] = None
            df.columns = columns
        
        non_numeric = NON_NUMERIC_COLUMNS.get(self.format_type, [])
        for col in df.columns:
            if col not in non_numeric and df[col].dtype == object:
                df[col] = self.convert_to_numeric(df[col])
        
        program_name = ''
        for line in head[:50]:
            if 'Data Sheet File' in line:
                parts = line.strip().split(',', 1)
                if len(parts) >= 2:
                    program_name = os.path.basename(parts[1].strip(' ,"'))
                break
        
        # Extract header metadata (ETS88 header ~70 lines, time fields at file tail)
        header_meta = self.extract_header_metadata(head, {
            'start_time': ['Data Collection Start Date', 'On'],
            'end_time': ['Data Collection Stop  Date', 'Data Collection Stop Date'],
            'lot_id': ['Datalog for Lot Number'],
            'operator': ['Data collected by operator', 'Reporting Operator'],
            'station': ['Data collected on station', 'Reporting Station'],
            'device_name': ['Test Name'],
            'tester_type': ['Tester_ID'],
            'test_type': ['Data collection type'],
            'handler': ['Handler/Prober ID', 'Handler_ID'],
        }, scan_limit=80)
        # ETS88 puts time fields at file tail — scan last 20 lines too (higher priority)
        tail_meta = self.extract_header_metadata(list(tail), {
            'start_time': ['Data Collection Start Date'],
            'end_time': ['Data Collection Stop  Date', 'Data Collection Stop Date'],
        })
        for k, v in tail_meta.items():
            header_meta[k] = v  # tail values override header (e.g. On → Data Collection Start Date)

        metadata = {
            'format': self.format_type,
            'units': dict(zip(columns, unit_columns)),
            'mins': dict(zip(columns, min_columns)),
            'maxs': dict(zip(columns, max_columns)),
            'program_name': program_name,
            'file_path': file_path,
            **header_meta,
        }
        return df, metadata
