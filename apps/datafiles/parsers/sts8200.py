from .base import BaseAteCsvParser


class STS8200Parser(BaseAteCsvParser):
    format_type = 'STS8200'
    program_label = 'Program:'
    program_sep = ':'
    header_mapping = {
        'start_time': ['Beginning Time'],
        'end_time': ['Ending Time'],
        'lot_id': ['LOT_ID'],
        'operator': ['User'],
        'station': ['Tester ID'],
        'tester_type': ['Tester ID'],
        'total_test_time': ['Total Testing Time'],
        'handler': ['Handler'],
    }

    def postprocess_header_meta(self, lines, program_name, header_meta):
        if lines and 'station' not in header_meta:
            header_meta['station'] = lines[0].strip()
        if program_name and 'device_name' not in header_meta:
            dev = program_name.replace('.pgs', '').replace('.DLL', '').replace('.dll', '')
            if dev.upper().startswith('JAV'):
                dev = dev[3:]
            header_meta['device_name'] = dev
        return header_meta
