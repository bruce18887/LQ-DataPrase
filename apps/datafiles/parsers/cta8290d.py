from .base import BaseATEParser, DATA_FORMAT_CONFIG, NON_NUMERIC_COLUMNS
import pandas as pd
import os
from typing import Optional, Tuple, Dict
import logging

logger = logging.getLogger(__name__)

class CTA8290DParser(BaseATEParser):
    format_type = 'CTA8290D'
    
    def parse(self, file_path: str) -> Tuple[Optional[pd.DataFrame], Optional[Dict]]:
        import pandas as pd
        import os
        
        config = DATA_FORMAT_CONFIG.get(self.format_type)
        if not config:
            return None, None
        
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        data_start = None
        for i, line in enumerate(lines):
            if config['marker'] in line:
                data_start = i
                break
        if data_start is None:
            return None, None
        
        header_line = lines[data_start + config['header_offset']].strip()
        unit_line = lines[data_start + config['unit_offset']].strip()
        min_line = lines[data_start + config['min_offset']].strip()
        max_line = lines[data_start + config['max_offset']].strip()
        data_start_row = data_start + config['data_offset']
        
        columns = self.make_column_names_unique([col.strip().strip('"') for col in header_line.split(',')])
        units = [unit.strip().strip('"') for unit in unit_line.split(',')]
        mins = [min_val.strip().strip('"') for min_val in min_line.split(',')]
        maxs = [max_val.strip().strip('"') for max_val in max_line.split(',')]
        
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
            if 'TestFile' in line:
                parts = line.strip().split(',', 1)
                if len(parts) >= 2:
                    program_name = os.path.basename(parts[1].strip(' ,"'))
                break
        
        metadata = {
            'format': self.format_type,
            'units': dict(zip(columns, units)),
            'mins': dict(zip(columns, mins)),
            'maxs': dict(zip(columns, maxs)),
            'program_name': program_name,
            'file_path': file_path,
        }
        return df, metadata
    
    @staticmethod
    def get_bin_column_name() -> str:
        return 'SW_Bin'
