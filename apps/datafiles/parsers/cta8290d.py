from .base import BaseAteCsvParser


class CTA8290DParser(BaseAteCsvParser):
    format_type = 'CTA8290D'
    program_label = 'TestFile'
    header_mapping = {
        'start_time': ['StartTime'],
        'end_time': ['EndTime'],
        'lot_id': ['LotID'],
        'operator': ['Operator'],
        'station': ['Station'],
        'device_name': ['Device_Name'],
        'tester_type': ['Tester_Type'],
        'test_type': ['TestType'],
        'total_test_time': ['AllTestTime'],
        'handler': ['HandlerName'],
    }
