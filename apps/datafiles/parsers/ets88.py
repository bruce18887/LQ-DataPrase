from .base import BaseATEParser, DATA_FORMAT_CONFIG, NON_NUMERIC_COLUMNS
import pandas as pd
import os
from typing import Optional, Tuple, Dict
import logging

logger = logging.getLogger(__name__)

class ETS88Parser(BaseATEParser):
    format_type = 'ETS88'
    
    def parse(self, file_path: str) -> Tuple[Optional[pd.DataFrame], Optional[Dict]]:
        import pandas as pd
        import os
        
        config = DATA_FORMAT_CONFIG.get(self.format_type)
        if not config:
            return None, None
        
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        marker_idx = None
        for i, line in enumerate(lines):
            if config['marker'] in line:
                marker_idx = i
                break
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
            line_lower = lines[i].lower()
            
            if header_line_idx is None:
                if any(kw.lower() in line_lower for kw in search_keywords['header']):
                    parts = lines[i].split(',')
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
        
        header_line = lines[header_line_idx].strip()
        min_line = lines[min_line_idx].strip()
        max_line = lines[max_line_idx].strip()
        unit_line = lines[unit_line_idx].strip()
        
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
        
        df = pd.read_csv(file_path, skiprows=data_start_row, header=None,
                        on_bad_lines='skip', encoding='utf-8')
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
        for line in lines[:50]:
            if 'Data Sheet File' in line:
                parts = line.strip().split(',', 1)
                if len(parts) >= 2:
                    program_name = os.path.basename(parts[1].strip(' ,"'))
                break
        
        # Extract header metadata (ETS88 header ~70 lines, time fields at file tail)
        header_meta = self.extract_header_metadata(lines, {
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
        tail_meta = self.extract_header_metadata(lines[-20:], {
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
    
    @staticmethod
    def get_bin_column_name() -> str:
        return 'Bin'
