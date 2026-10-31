from abc import ABC, abstractmethod
from typing import Optional, Tuple, Dict, List
import os
import pandas as pd
import re

# 头部有界读取的保留行数：前 HEADER_KEEP 个物理行交给头部元数据助手
# （extract_header_metadata 的 scan_limit 默认值就是 HEADER_KEEP；
# _extract_program_name 另只扫前 50 行）。80 是助手历史上的扫描窗口，
# 有界读取保留的内容与旧实现「整文件 readlines 后各自切片」逐字一致——
# 不能缩成「marker 之前的行」，marker 之前不足 80 行时窗口会变窄。
HEADER_KEEP = 80


class BaseATEParser(ABC):
    format_type: str = ''
    
    @abstractmethod
    def parse(self, file_path: str) -> Tuple[Optional[pd.DataFrame], Optional[Dict]]:
        ...
    
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

    # ETS88 等格式在数据区块之后还会跟几行尾部元数据（如
    # ``Data Collection Start Date,<时间戳>`` / ``Data Collection Stop  Date,<时间戳>``）。
    # 这些行只有少量字段，会被 pd.read_csv(skiprows=...) 读成一行全 NaN 的假数据行；
    # 在 ag-grid 里显示在表格末尾，且 Bin=NaN != 1 被误计为 FAIL → 读取后立即丢弃。
    TAIL_META_PATTERN = re.compile(
        r'^\s*Data Collection (Start|Stop)\s+Date\s*$', re.IGNORECASE | re.UNICODE
    )

    def drop_tail_metadata_rows(self, df: 'pd.DataFrame') -> 'pd.DataFrame':
        """剔除文件尾部非数据的元数据行（如 Data Collection Start/Stop Date）。

        检测：元数据行只有 1-2 个字段（标签 + 值），被读进 DataFrame 时落在
        最靠前的列（第 0/1 列）；数据行的第 0 列是 Site #/Serial 等数值或
        数字串 → 只用最前 4 列做正则匹配即可，全列匹配对 1700 列大文件
        是浪费（1438×1728 约 250 万次字符串转换）。保序、保留原始 index
        （行被删后 index 与 fail_cells/filter 的对齐由调用方处理）。
        """
        mask = pd.Series(False, index=df.index)
        for j in range(min(4, len(df.columns))):
            mask |= df.iloc[:, j].astype(str).str.match(self.TAIL_META_PATTERN)
        return df[~mask]

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
    def extract_header_metadata(lines: List[str], mapping: Dict[str, List[str]], scan_limit: int = HEADER_KEEP) -> Dict[str, str]:
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

# 各格式数据表的「记录级列」（系统列）：数据表头部固定的一组记录身份/协议列
# （序列号/料号/槽位/过点/Bin/坐标/时间戳等）。查看数据页把它们恒显示并排在
# 测试列之前，且不参与「显示测试列」隐藏。
#
# ⚠️ 不能用列名前缀启发式判定：测试项名可能与记录级列同名前缀——
# CTA8290D/CTA8280F 的 Device_Fused_Flag、Device_Fused_Flag1/2、SITE_CHECK、
# site_check 都是**测试项**（分别位于 CSV 第 ~93/117/607/14 列），名称却以
# device_/site_ 开头（2026-08-25 用户 BPD87500 报告：Device_Fused_Flag1/2
# 被误判为系统列而跑到数据最前面）。因此按格式给出权威列表，由后端随
# /browse/ page==1 下发（system_columns），前端不再用名称猜测。
#
# 取值来源：四种格式真实样本文件 [Data] 表的开头记录块（已验证）——
# CTA8290D 0-12、CTA8280F 0-13、ETS88 解析器强制前 5 列、STS8200 0-7。
SYSTEM_COLUMNS = {
    'CTA8290D': ['Serial_No', 'Part_No', 'Dut_No', 'Site_No', 'Dut_Pass', 'SW_Bin',
                 'X_COORD', 'Y_COORD', 'QR_Code', 'Start_T', 'Test_Time', 'Alarm', 'Data_Cnt'],
    'CTA8280F': ['Index_No', 'Dut_No', 'Serial_No', 'Site_No', 'Dut_Pass', 'SW_Bin',
                 'X_COORD', 'Y_COORD', 'QR_Code', 'Start_Time', 'Test_Time',
                 'Handler_Time', 'Alarm', 'Data_Num'],
    'ETS88': ['Site #', 'Serial #', 'Bin', 'XCoord', 'YCoord'],
    'STS8200': ['SITE_NUM', 'PART_ID', 'PASSFG', 'SOFT_BIN', 'T_TIME', 'X_COORD',
                'Y_COORD', 'TEST_NUM'],
}

DATA_FORMAT_CONFIG = {
    'CTA8290D': {'marker': '[Data]', 'header_offset': 1, 'unit_offset': 2, 'min_offset': 3, 'max_offset': 4, 'data_offset': 5},
    'CTA8280F': {'marker': '[Data]', 'header_offset': 1, 'unit_offset': 2, 'min_offset': 3, 'max_offset': 4, 'data_offset': 5},
    'ETS88': {'marker': 'Site #,Serial #,Bin,XCoord,YCoord', 'header_offset': 0, 'unit_offset': 3, 'min_offset': 1, 'max_offset': 2, 'data_offset': 2, 'special_headers': True, 'header_line': 68, 'min_line': 70, 'max_line': 71, 'unit_line': 72},
    'STS8200': {'marker': 'SITE_NUM,PART_ID,PASSFG,SOFT_BIN', 'header_offset': 0, 'unit_offset': 1, 'min_offset': 2, 'max_offset': 3, 'data_offset': 5},
}


class BaseAteCsvParser(BaseATEParser):
    """Template for ATE CSVs whose header/unit/min/max sit on fixed lines.

    Subclasses declare the program-name label and header-label mapping; the
    marker scan, CSV read, column alignment and numeric coercion stay here.
    """

    program_label: str = ''
    program_sep: str = ','
    header_mapping: Dict[str, List[str]] = {}

    def parse(self, file_path: str) -> Tuple[Optional[pd.DataFrame], Optional[Dict]]:
        config = DATA_FORMAT_CONFIG.get(self.format_type)
        if not config:
            return None, None

        # 有界读取：只留头部前 HEADER_KEEP 行（给元数据助手）与 marker 行及其后
        # max(offset) 行（给 header/unit/min/max）。旧写法 readlines() 把整文件
        # 读成字符串列表，随后 read_csv 再整读一遍；大文件上两份全量同时驻留。
        marker = config['marker']
        max_offset = max(config['header_offset'], config['unit_offset'],
                         config['min_offset'], config['max_offset'])
        head = []
        block = []
        marker_idx = None
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for i, line in enumerate(f):
                if len(head) < HEADER_KEEP:
                    head.append(line)
                if marker_idx is None:
                    if marker in line:
                        marker_idx = i
                        block.append(line)
                elif len(block) <= max_offset:
                    block.append(line)
                if (marker_idx is not None and len(head) >= HEADER_KEEP
                        and len(block) > max_offset):
                    break
        if marker_idx is None:
            return None, None

        header_line = block[config['header_offset']].strip()
        unit_line = block[config['unit_offset']].strip()
        min_line = block[config['min_offset']].strip()
        max_line = block[config['max_offset']].strip()
        data_start_row = marker_idx + config['data_offset']

        columns = self.make_column_names_unique(
            [col.strip().strip('"') for col in header_line.split(',')]
        )
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
            for _ in range(len(columns) - len(df.columns)):
                df[len(df.columns)] = None
            df.columns = columns

        non_numeric = NON_NUMERIC_COLUMNS.get(self.format_type, [])
        for col in df.columns:
            if col not in non_numeric and df[col].dtype == object:
                df[col] = self.convert_to_numeric(df[col])

        program_name = self._extract_program_name(head)
        header_meta = self.extract_header_metadata(head, self.header_mapping)
        header_meta = self.postprocess_header_meta(head, program_name, header_meta)

        metadata = {
            'format': self.format_type,
            'units': dict(zip(columns, units)),
            'mins': dict(zip(columns, mins)),
            'maxs': dict(zip(columns, maxs)),
            'program_name': program_name,
            'file_path': file_path,
            **header_meta,
        }
        return df, metadata

    def _extract_program_name(self, lines: List[str]) -> str:
        if not self.program_label:
            return ''
        for line in lines[:50]:
            if self.program_label in line:
                parts = line.strip().split(self.program_sep, 1)
                if len(parts) >= 2:
                    return os.path.basename(parts[1].strip(' ,"'))
                break
        return ''

    def postprocess_header_meta(self, lines: List[str], program_name: str,
                                header_meta: Dict[str, str]) -> Dict[str, str]:
        """钩子：``lines`` 至多 HEADER_KEEP 个物理行（旧实现是整文件），覆写方
        不得假设能拿到更多；STS8200 只用 ``lines[0]``。"""
        return header_meta
