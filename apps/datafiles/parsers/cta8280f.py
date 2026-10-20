from .base import BaseAteCsvParser


class CTA8280FParser(BaseAteCsvParser):
    format_type = 'CTA8280F'
    program_label = 'TestFileName'
    header_mapping = {
        'start_time': ['StartTime'],
        'end_time': ['EndTime'],
        'lot_id': ['LotID'],
        'operator': ['Operator'],
        'station': ['Test Station'],
        'device_name': ['Device Name'],
        'tester_type': ['Tester type'],
        'test_type': ['TestType'],
        'total_test_time': ['AllTestTime'],
        'handler': ['HandlerType'],
    }
