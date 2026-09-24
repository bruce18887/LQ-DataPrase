import csv
import io
from typing import List, Dict, Optional, Tuple
from config.sftp_connection import SFTPConnection


class CsvColumnReader:
    def __init__(self, connection: SFTPConnection, chunk_size: int = 8192):
        self.connection = connection
        self.chunk_size = chunk_size

    def extract_column(
        self,
        files: List[Dict],
        column_name: str,
        max_rows: int = 10,
        cancel_event=None,
    ) -> List[Dict]:
        result_files = []

        for file_info in files:
            if cancel_event is not None and cancel_event.is_set():
                break
            values, test_file, start_time, pts_modify_time = self._extract_from_file(
                file_info, column_name, max_rows
            )
            if values:
                result_files.append({
                    "path": file_info["path"],
                    "filename": file_info["filename"],
                    "size": file_info["size"],
                    "column_name": column_name,
                    "values": values,
                    "value_count": len(values),
                    "test_file": test_file,
                    "start_time": start_time,
                    "pts_modify_time": pts_modify_time,
                })

        return result_files

    def _extract_from_file(
        self,
        file_info: Dict,
        column_name: str,
        max_rows: int,
    ) -> Tuple[List[str], str, str, str]:
        try:
            test_file = ""
            start_time = ""
            pts_modify_time = ""
            in_data = False
            headers_read = False
            col_idx = -1
            values = []
            detected_encoding = None

            with self.connection.sftp.open(file_info["path"], "rb") as f:
                for line_bytes in f:
                    line_text = self._decode_line(line_bytes, detected_encoding)
                    if detected_encoding is None:
                        detected_encoding = self._detect_encoding(line_bytes)

                    stripped = line_text.rstrip("\r\n")

                    if not in_data:
                        if stripped.startswith("["):
                            section = stripped[1:].split("]")[0].strip()
                            if section.upper() == "DATA":
                                in_data = True
                            continue

                        parts = stripped.split(",", 1)
                        if len(parts) == 2:
                            key = parts[0].strip()
                            val = parts[1].strip().rstrip(",")
                            if key == "TestFile" and not test_file:
                                test_file = val.split("\\")[-1]
                            elif key == "StartTime" and not start_time:
                                start_time = val
                            elif key == "PtsModifyTime" and not pts_modify_time:
                                pts_modify_time = val
                    else:
                        if not headers_read:
                            headers = [h.strip() for h in stripped.split(",")]
                            if column_name not in headers:
                                return [], test_file, start_time, pts_modify_time
                            col_idx = headers.index(column_name)
                            headers_read = True
                        else:
                            row = stripped.split(",")
                            if col_idx < len(row):
                                val = row[col_idx].strip()
                                if val:
                                    values.append(val)
                                    if len(values) >= max_rows:
                                        break

            return values, test_file, start_time, pts_modify_time

        except Exception as e:
            print(f"Warning: Could not process file '{file_info['path']}' - {str(e)}")
            return [], "", "", ""

    def _decode_line(self, line_bytes: bytes, detected_encoding: Optional[str]) -> str:
        if detected_encoding:
            try:
                return line_bytes.decode(detected_encoding)
            except (UnicodeDecodeError, UnicodeError):
                pass
        for enc in ["utf-8", "gbk", "gb2312", "utf-16"]:
            try:
                return line_bytes.decode(enc)
            except (UnicodeDecodeError, UnicodeError):
                continue
        return line_bytes.decode("utf-8", errors="ignore")

    def _detect_encoding(self, first_line: bytes) -> str:
        for enc in ["utf-8", "gbk", "gb2312", "utf-16"]:
            try:
                first_line.decode(enc)
                return enc
            except (UnicodeDecodeError, UnicodeError):
                continue
        return "utf-8"
