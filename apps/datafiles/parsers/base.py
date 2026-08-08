from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple, Dict, List
import pandas as pd
import numpy as np
import re
import logging

logger = logging.getLogger(__name__)

from apps.common.constants import NON_NUMERIC_KEYWORDS

class BaseATEParser(ABC):
    format_type: str = ''
    
    @abstractmethod
    def parse(self, file_path: str) -> Tuple[Optional[pd.DataFrame], Optional[Dict]]:
        ...
    
    def get_columns_with_limits(self, df: pd.DataFrame, metadata: Dict) -> List[str]:
        cols_with_limits = []
        for col in df.columns:
            if col not in metadata.get('mins', {}) or col not in metadata.get('maxs', {}):
                continue
            min_str = str(metadata['mins'][col]).strip()
            max_str = str(metadata['maxs'][col]).strip()
            if not min_str or not max_str:
                continue
            if min_str.lower() in NON_NUMERIC_KEYWORDS or max_str.lower() in NON_NUMERIC_KEYWORDS:
                continue
            try:
                float(min_str)
                float(max_str)
                cols_with_limits.append(col)
            except (ValueError, TypeError):
                continue
        return cols_with_limits
    
    def detect_fail_data(self, df: pd.DataFrame, metadata: Dict):
        fail_indices = []
        fail_columns = []
        fail_cells = {}
        format_type = metadata.get('format', self.format_type)
        target_bin_col = self.get_bin_column_name()
        cols_with_limits = self.get_columns_with_limits(df, metadata)
        fail_row_mask = pd.Series([False] * len(df), index=df.index)
        if target_bin_col in df.columns:
            fail_row_mask = pd.to_numeric(df[target_bin_col], errors='coerce') != 1
        for col in cols_with_limits:
            min_val = float(str(metadata['mins'][col]).strip())
            max_val = float(str(metadata['maxs'][col]).strip())
            col_data = pd.to_numeric(df[col], errors='coerce')
            fail_mask = fail_row_mask & ((col_data < min_val) | (col_data > max_val))
            fail_rows = df.index[fail_mask].tolist()
            for idx in fail_rows:
                fail_indices.append(idx)
                fail_columns.append(col)
                if idx not in fail_cells:
                    fail_cells[idx] = []
                fail_cells[idx].append(col)
        if target_bin_col in df.columns:
            fail_bin_indices = df.index[fail_row_mask].tolist()
            for idx in fail_bin_indices:
                if idx not in fail_cells:
                    fail_cells[idx] = []
                if target_bin_col not in fail_cells[idx]:
                    fail_cells[idx].append(target_bin_col)
                if idx not in set(fail_indices):
                    fail_indices.append(idx)
        return fail_indices, fail_columns, fail_cells
    
    @staticmethod
    def make_column_names_unique(columns: List[str]) -> List[str]:
        seen = {}
        unique = []
        for col in columns:
            # Clean column name: remove newlines and normalize whitespace
            cleaned = col.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')
            cleaned = ' '.join(cleaned.split())  # normalize multiple spaces
            if cleaned in seen:
                seen[cleaned] += 1
                unique.append(f"{cleaned}.{seen[cleaned]}")
            else:
                seen[cleaned] = 0
                unique.append(cleaned)
        return unique
    
    @staticmethod
    def get_bin_column_name() -> str:
        return 'SW_Bin'
    
    @staticmethod
    def fix_negative_decimal(value):
        if isinstance(value, str):
            if value.endswith('-') and value.rstrip('-').replace('.', '', 1).lstrip('-').replace('E', '').replace('e', '').isdigit():
                return '-' + value.rstrip('-')
            if value.startswith('-') and '.' in value:
                try:
                    return str(float(value))
                except ValueError:
                    return value
        return value

    def convert_to_numeric(self, series: pd.Series) -> pd.Series:
        if series.dtype == object:
            series = series.astype(str).apply(self.fix_negative_decimal)
        return pd.to_numeric(series, errors='coerce')

    @staticmethod
    def identify_format(file_content: str) -> str:
        content = file_content.lower()
        if 'cta8290d' in content:
            return 'CTA8290D'
        elif 'cta8280f' in content:
            return 'CTA8280F'
        elif 'sts8200' in content:
            return 'STS8200'
        elif 'ets datalog reporter' in content:
            return 'ETS88'
        return 'Unknown'

    @staticmethod
    def extract_header_metadata(lines: List[str], mapping: Dict[str, List[str]], scan_limit: int = 80) -> Dict[str, str]:
        """Extract key-value metadata from header lines using flexible matching.

        ``mapping`` maps canonical keys (e.g. 'start_time') to a list of
        possible header labels (e.g. ['StartTime', 'Beginning Time']).
        Matching is case-insensitive and ignores whitespace/underscores.
        Returns a dict of canonical_key -> value.
        """
        result = {}
        # Build a lookup: normalized_label -> canonical_key
        label_to_key = {}
        for canonical, labels in mapping.items():
            for label in labels:
                norm = re.sub(r'[\s_]+', '', label.lower())
                label_to_key[norm] = canonical

        for line in lines[:scan_limit]:
            stripped = line.strip().rstrip(',')
            if not stripped or stripped.startswith('['):
                continue
            # Try splitting on first comma or colon
            for sep in [',', ':']:
                if sep in stripped:
                    parts = stripped.split(sep, 1)
                    key_part = parts[0].strip()
                    val_part = parts[1].strip() if len(parts) > 1 else ''
                    # Remove trailing commas from value (CTA8280F padded format)
                    val_part = val_part.rstrip(',').strip()
                    norm_key = re.sub(r'[\s_]+', '', key_part.lower())
                    if norm_key in label_to_key and val_part:
                        canon = label_to_key[norm_key]
                        if canon not in result:  # first match wins
                            result[canon] = val_part
                    break
        return result

NON_NUMERIC_COLUMNS = {
    'CTA8290D': ['Serial_No', 'Part_No', 'Dut_No', 'Site_No', 'SW_Bin', 'X_COORD', 'Y_COORD', 'QR_Code', 'Start_T', 'Alarm'],
    'CTA8280F': ['Index_No', 'Dut_No', 'Serial_No', 'Site_No', 'SW_Bin', 'X_COORD', 'Y_COORD', 'QR_Code', 'Start_Time', 'Alarm'],
    'ETS88': ['Site #', 'Serial #', 'Bin', 'XCoord', 'YCoord'],
    'STS8200': ['SITE_NUM', 'PART_ID', 'PASSFG', 'SOFT_BIN', 'X_COORD', 'Y_COORD'],
}

DATA_FORMAT_CONFIG = {
    'CTA8290D': {'marker': '[Data]', 'header_offset': 1, 'unit_offset': 2, 'min_offset': 3, 'max_offset': 4, 'data_offset': 5},
    'CTA8280F': {'marker': '[Data]', 'header_offset': 1, 'unit_offset': 2, 'min_offset': 3, 'max_offset': 4, 'data_offset': 5},
    'ETS88': {'marker': 'Site #,Serial #,Bin,XCoord,YCoord', 'header_offset': 0, 'unit_offset': 3, 'min_offset': 1, 'max_offset': 2, 'data_offset': 2, 'special_headers': True, 'header_line': 68, 'min_line': 70, 'max_line': 71, 'unit_line': 72},
    'STS8200': {'marker': 'SITE_NUM,PART_ID,PASSFG,SOFT_BIN', 'header_offset': 0, 'unit_offset': 1, 'min_offset': 2, 'max_offset': 3, 'data_offset': 5},
}
