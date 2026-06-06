"""CSV export functions."""

import pandas as pd
from typing import Dict
from apps.analysis.services.statistics import (
    ensure_numeric, get_bin_column_name, get_site_column,
)
from apps.datafiles.parsers.base import DATA_FORMAT_CONFIG


def _convert_to_native_type(val):
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (ValueError, TypeError):
        pass
    if isinstance(val, (bool,)):
        return val
    if isinstance(val, (int,)):
        return int(val) if hasattr(val, 'item') else val
    if isinstance(val, (float,)):
        if hasattr(val, 'item'):
            native = val.item()
        else:
            native = val
        if pd.isna(native):
            return ""
        return native
    if hasattr(val, 'item'):
        native = val.item()
        try:
            if pd.isna(native):
                return ""
        except (ValueError, TypeError):
            pass
        return native
    return str(val) if val is not None else ""



# 导出DataFrame为CSV，支持Site过滤、Pass/Fail过滤和原始格式匹配
def export_to_csv(df: pd.DataFrame, metadata: Dict, site_filter=None, passfail_filter=None,
                  keep_header=False, match_original_format=False, raw_lines=None) -> bytes:
    try:

        export_df = df.copy()

        if site_filter and site_filter != "全部":
            site_col = get_site_column(df)
            if site_col:
                export_df = export_df[export_df[site_col].astype(str) == str(site_filter)]

        if passfail_filter and passfail_filter != "全部":

            format_type = metadata.get('format', 'CTA8290D')
            bin_col = get_bin_column_name(format_type)

            if bin_col in export_df.columns:
                if passfail_filter == "Pass":
                    export_df = export_df[ensure_numeric(export_df, bin_col) == 1]
                elif passfail_filter == "Fail":
                    export_df = export_df[ensure_numeric(export_df, bin_col) != 1]

        if keep_header and raw_lines:

            format_type = metadata.get('format', 'CTA8290D')
            config = DATA_FORMAT_CONFIG.get(format_type)

            if config and raw_lines:
                data_marker_line = None
                for i, line in enumerate(raw_lines):
                    if config['marker'] in line:
                        data_marker_line = i
                        break

                if data_marker_line is not None:
                    if format_type in ['CTA8290D', 'CTA8280F']:
                        header_end_line = data_marker_line + config['max_offset']
                    elif format_type == 'ETS88':
                        header_end_line = data_marker_line + 3
                    else:
                        header_end_line = data_marker_line

                    header_lines = []
                    for i in range(header_end_line + 1):
                        header_lines.append(raw_lines[i].rstrip('\n').rstrip('\r'))

                    header_content = '\n'.join(header_lines)

                    if len(export_df) > 0:
                        if match_original_format:
                            if format_type == 'ETS88':
                                export_bin_col = get_bin_column_name(format_type)
                                coord_x_col = 'XCoord'
                                coord_y_col = 'YCoord'

                                meta_cols = ['Site #', 'Serial #', export_bin_col, coord_x_col, coord_y_col]
                                existing_meta_cols = [c for c in meta_cols if c in export_df.columns]
                                other_cols = [c for c in export_df.columns if c not in meta_cols]
                                ordered_cols = existing_meta_cols + other_cols
                                export_df = export_df[ordered_cols]

                            data_csv = export_df.to_csv(index=False, header=False)
                            csv_content = header_content + '\n' + data_csv
                        else:
                            data_csv = export_df.to_csv(index=False)
                            csv_content = header_content + '\n' + data_csv
                    else:
                        csv_content = header_content
                else:
                    csv_content = export_df.to_csv(index=False)
            else:
                csv_content = export_df.to_csv(index=False)
        elif match_original_format and raw_lines:

            format_type = metadata.get('format', 'CTA8290D')
            config = DATA_FORMAT_CONFIG.get(format_type)

            if config and raw_lines:
                data_start = None
                for i, line in enumerate(raw_lines):
                    if config['marker'] in line:
                        data_start = i
                        break

                if data_start is not None:
                    marker_line = raw_lines[data_start].strip()

                    if len(export_df) > 0:
                        if format_type == 'ETS88':
                            export_bin_col = get_bin_column_name(format_type)
                            coord_x_col = 'XCoord'
                            coord_y_col = 'YCoord'

                            meta_cols = ['Site #', 'Serial #', export_bin_col, coord_x_col, coord_y_col]
                            existing_meta_cols = [c for c in meta_cols if c in export_df.columns]
                            other_cols = [c for c in export_df.columns if c not in meta_cols]
                            ordered_cols = existing_meta_cols + other_cols
                            export_df = export_df[ordered_cols]

                        data_csv = export_df.to_csv(index=False, header=False)
                        csv_content = marker_line + '\n' + data_csv
                    else:
                        csv_content = marker_line
                else:
                    csv_content = export_df.to_csv(index=False)
            else:
                csv_content = export_df.to_csv(index=False)
        else:
            csv_content = export_df.to_csv(index=False)

        return csv_content.encode('utf-8-sig')
    except ImportError:
        # Fallback when app module is not available
        export_df = df.copy()
        if site_filter and site_filter != "全部":
            # Simplified site filtering without get_site_column
            site_cols = [col for col in df.columns if 'Site' in col or 'site' in col]
            if site_cols:
                export_df = export_df[export_df[site_cols[0]].astype(str) == str(site_filter)]
        if passfail_filter and passfail_filter != "全部":
            # Simplified pass/fail filtering
            bin_cols = [col for col in df.columns if 'Bin' in col or 'bin' in col]
            if bin_cols:
                if passfail_filter == "Pass":
                    export_df = export_df[pd.to_numeric(export_df[bin_cols[0]], errors='coerce') == 1]
                elif passfail_filter == "Fail":
                    export_df = export_df[pd.to_numeric(export_df[bin_cols[0]], errors='coerce') != 1]
        return export_df.to_csv(index=False).encode('utf-8-sig')
