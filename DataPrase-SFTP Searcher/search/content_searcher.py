from typing import List, Dict, Optional
from config.sftp_connection import SFTPConnection


class ContentSearcher:
    def __init__(self, connection: SFTPConnection, chunk_size: int = 8192):
        self.connection = connection
        self.chunk_size = chunk_size

    def search_in_files(
        self,
        files: List[Dict],
        search_string: str,
        case_sensitive: bool = False,
        fuzzy_match: bool = False,
        cancel_event=None,
    ) -> List[Dict]:
        matched_files = []
        total_searched = 0

        for file_info in files:
            if cancel_event is not None and cancel_event.is_set():
                break
            total_searched += 1
            matches = self._search_single_file(
                file_info, search_string, case_sensitive, fuzzy_match
            )
            if matches:
                matched_files.append(
                    {
                        "path": file_info["path"],
                        "filename": file_info["filename"],
                        "size": file_info["size"],
                        "matches": matches,
                        "match_count": len(matches),
                    }
                )

        return matched_files, total_searched

    def _search_single_file(
        self,
        file_info: Dict,
        search_string: str,
        case_sensitive: bool,
        fuzzy_match: bool,
    ) -> List[Dict]:
        matches = []
        line_number = 0
        content_buffer = ""

        try:
            with self.connection.sftp.open(file_info["path"], "rb") as remote_file:
                while True:
                    chunk = remote_file.read(self.chunk_size)
                    if not chunk:
                        if content_buffer:
                            remaining_matches = self._process_line(
                                content_buffer,
                                line_number,
                                search_string,
                                case_sensitive,
                                fuzzy_match,
                            )
                            matches.extend(remaining_matches)
                        break

                    try:
                        chunk_str = chunk.decode("utf-8")
                    except UnicodeDecodeError:
                        try:
                            chunk_str = chunk.decode("gbk")
                        except UnicodeDecodeError:
                            chunk_str = chunk.decode("utf-8", errors="ignore")

                    content_buffer += chunk_str
                    while "\n" in content_buffer:
                        line, content_buffer = content_buffer.split("\n", 1)
                        line_number += 1
                        line_matches = self._process_line(
                            line, line_number, search_string, case_sensitive, fuzzy_match
                        )
                        matches.extend(line_matches)

        except Exception as e:
            print(f"Warning: Could not read file '{file_info['path']}' - {str(e)}")

        return matches[:50]

    def _process_line(
        self,
        line: str,
        line_number: int,
        search_string: str,
        case_sensitive: bool,
        fuzzy_match: bool,
    ) -> List[Dict]:
        search_line = line if case_sensitive else line.lower()
        search_term = search_string if case_sensitive else search_string.lower()

        match_results = []

        if fuzzy_match:
            if self._fuzzy_match(search_term, search_line):
                match_results.append(
                    {
                        "line_number": line_number,
                        "content": line.strip()[:200],
                        "position": 0,
                    }
                )
        else:
            start = 0
            while True:
                pos = search_line.find(search_term, start)
                if pos == -1:
                    break
                match_results.append(
                    {
                        "line_number": line_number,
                        "content": line.strip()[:200],
                        "position": pos,
                    }
                )
                start = pos + 1

        return match_results

    def _fuzzy_match(self, pattern: str, text: str) -> bool:
        pattern_idx = 0
        pattern_len = len(pattern)

        for char in text:
            if pattern_idx < pattern_len and char == pattern[pattern_idx]:
                pattern_idx += 1
            if pattern_idx == pattern_len:
                return True

        return False
