import logging
from pathlib import Path
from apps.datafiles.models import DataFile, ParseHistory
from apps.datafiles.parsers import get_parser, BaseATEParser

logger = logging.getLogger(__name__)


def parse_and_save_datafile(file_path: str, user, filename: str, file_size: int) -> DataFile:
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        file_head = f.read(4096)
    
    format_type = BaseATEParser.identify_format(file_head)
    if format_type == 'Unknown':
        raise ValueError("无法识别的数据格式")
    
    parser = get_parser(format_type)
    df, metadata = parser.parse(file_path)
    
    if df is None:
        raise ValueError("数据解析失败")
    
    datafile = DataFile.objects.create(
        owner=user,
        filename=filename,
        file_path=file_path,
        file_size=file_size,
        format_type=format_type,
        row_count=df.shape[0],
        col_count=df.shape[1],
        program_name=metadata.get('program_name', ''),
        metadata=metadata,
        status='ready',
    )
    
    ParseHistory.objects.create(
        user=user,
        datafile=datafile,
        filename=filename,
        filepath=file_path,
        format_type=format_type,
        rows=df.shape[0],
        cols=df.shape[1],
    )
    
    return datafile
