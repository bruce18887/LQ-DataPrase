import posixpath
import queue
import shlex
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Callable

import paramiko

from config.sftp_connection import SFTPConnection


class CsvContentSearcher:
    """Searches CSV files for a string. One match per file is enough.

    Speed strategy:
    - files are read in large chunks instead of line by line
    - paramiko prefetch pipelines the download so reads never wait per chunk
    - matching runs on raw bytes (utf-8 / gbk / utf-16 needle variants)
    - metadata (TestFile/StartTime/PtsModifyTime) is parsed only for matched files

    Parallel strategy:
    - every worker thread uses its own independent SSH connection; sharing a
      single SFTP channel across threads desyncs the protocol stream and
      causes "Garbage packet received" errors
    - a broken connection is re-opened and the failed file is retried once
    """

    CHUNK_SIZE = 1024 * 1024  # 1 MB per read
    HEAD_SIZE = 64 * 1024  # metadata region kept from file start
    MAX_INFLIGHT = 64  # prefetch requests in flight per file (~2 MB)
    LINE_CONTEXT = 4096  # trailing bytes kept so line starts stay in the buffer
    CONNECTION_ERRORS = (paramiko.SSHException, paramiko.SFTPError, EOFError, OSError)

    def __init__(self, connection: SFTPConnection):
        self.connection = connection

    def search_in_files(
        self,
        files: List[Dict],
        search_string: str,
        case_sensitive: bool = False,
        max_workers: int = 1,
        one_file_per_folder: bool = False,
        on_match: Optional[Callable[[Dict], None]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
        cancel_event=None,
    ) -> Tuple[List[Dict], int]:
        """Search files and return (matched_files, total_searched).

        on_match and on_progress callbacks are invoked under an internal lock,
        so they are safe to call print() without extra locking. If cancel_event
        is set, remaining files are skipped and the search finishes early.
        """
        if one_file_per_folder:
            files = self._first_file_per_folder(files)

        total = len(files)
        matched_files: List[Dict] = []
        lock = threading.Lock()
        progress = {"done": 0}

        def record(file_info: Dict, result: Optional[Dict]):
            with lock:
                progress["done"] += 1
                if result:
                    matched_files.append(result)
                    if on_match:
                        on_match(result)
                if on_progress:
                    on_progress(progress["done"], total)

        if max_workers <= 1:
            for file_info in files:
                if cancel_event is not None and cancel_event.is_set():
                    record(file_info, None)
                    continue
                try:
                    result = self._search_single_file(
                        file_info, search_string, case_sensitive
                    )
                except self.CONNECTION_ERRORS as e:
                    print(
                        f"Warning: Could not process file '{file_info['path']}' - {str(e)}"
                    )
                    result = None
                record(file_info, result)
            return matched_files, total

        # Build a pool of independent SSH connections (one per worker).
        pool: "queue.Queue[Tuple]" = queue.Queue()
        opened = 0
        print(f"Opening {max_workers} parallel connection(s)...")
        for i in range(max_workers):
            try:
                pool.put(self._open_connection())
                opened += 1
            except Exception as e:
                print(f"Warning: could not open connection {i + 1}: {str(e)}")
                break

        if opened == 0:
            print("No parallel connection available; searching on the current connection.")
            for file_info in files:
                if cancel_event is not None and cancel_event.is_set():
                    record(file_info, None)
                    continue
                try:
                    result = self._search_single_file(
                        file_info, search_string, case_sensitive
                    )
                except self.CONNECTION_ERRORS as e:
                    print(
                        f"Warning: Could not process file '{file_info['path']}' - {str(e)}"
                    )
                    result = None
                record(file_info, result)
            return matched_files, total

        def worker(file_info: Dict):
            if cancel_event is not None and cancel_event.is_set():
                record(file_info, None)
                return
            ssh_client, client = pool.get()
            try:
                result = None
                if client is None:
                    print(f"Warning: no connection available, skipped '{file_info['path']}'")
                else:
                    try:
                        result = self._search_single_file(
                            file_info, search_string, case_sensitive, client=client
                        )
                    except self.CONNECTION_ERRORS as e:
                        print(
                            f"\nWarning: connection error on '{file_info['path']}' "
                            f"({str(e)}); reconnecting..."
                        )
                        ssh_client, client = self._recycle(ssh_client)
                        if client is not None:
                            try:
                                result = self._search_single_file(
                                    file_info, search_string, case_sensitive, client=client
                                )
                            except Exception as e2:
                                print(
                                    f"Warning: Could not process file "
                                    f"'{file_info['path']}' - {str(e2)}"
                                )
                                result = None
                        else:
                            print(
                                f"Warning: could not reopen connection, "
                                f"skipped '{file_info['path']}'"
                            )
                record(file_info, result)
            finally:
                pool.put((ssh_client, client))

        try:
            with ThreadPoolExecutor(max_workers=opened) as executor:
                futures = [executor.submit(worker, f) for f in files]
                for future in as_completed(futures):
                    future.result()
        finally:
            while True:
                try:
                    ssh_client, _ = pool.get_nowait()
                except queue.Empty:
                    break
                if ssh_client is not None:
                    try:
                        ssh_client.close()
                    except Exception:
                        pass

        return matched_files, total

    def _open_connection(self):
        """Open an independent SSH + SFTP connection for one worker thread."""
        conn = self.connection
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh_client.connect(
            hostname=conn.host,
            port=conn.port,
            username=conn.username,
            password=conn.password,
            timeout=conn.timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        sftp_client = ssh_client.open_sftp()
        return ssh_client, sftp_client

    def _recycle(self, ssh_client):
        """Close a broken connection and open a fresh one."""
        if ssh_client is not None:
            try:
                ssh_client.close()
            except Exception:
                pass
        for _ in range(2):
            try:
                return self._open_connection()
            except Exception:
                continue
        return None, None

    # ---- server-side (grep) search ----

    def server_grep_supported(self, search_paths: List[str]) -> bool:
        """True if the server shell has grep and shell paths match SFTP paths
        (SFTP servers sometimes run chrooted, making shell paths differ)."""
        try:
            _, stdout, _ = self.connection.client.exec_command("grep --version")
            if b"grep" not in stdout.read().lower():
                return False
        except Exception:
            return False

        for path in search_paths:
            try:
                entries = self.connection.sftp.listdir(path)
            except Exception:
                continue
            if not entries:
                continue
            probe = f"{path.rstrip('/')}/{entries[0]}"
            try:
                _, stdout, _ = self.connection.client.exec_command(
                    f"[ -e {shlex.quote(probe)} ] && echo MAPPING_OK"
                )
                return b"MAPPING_OK" in stdout.read()
            except Exception:
                return False
        return True

    def search_via_server(
        self,
        search_paths: List[str],
        file_pattern: str,
        search_string: str,
        case_sensitive: bool = False,
        after_date: Optional[datetime] = None,
        before_date: Optional[datetime] = None,
        on_match: Optional[Callable[[Dict], None]] = None,
        cancel_event=None,
    ) -> Tuple[List[Dict], Optional[int]]:
        """Run grep on the server: no file downloads, stops each file after
        its first match. Returns (matched_files, None) - the number of files
        examined is unknown server-side."""
        cmd = self._build_grep_command(
            search_string, case_sensitive, file_pattern, search_paths,
            after_date, before_date,
        )
        _, stdout, stderr = self.connection.client.exec_command(cmd)

        matched_files: List[Dict] = []
        cancelled = False
        for raw in iter(stdout.readline, b""):
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                try:
                    stdout.channel.close()
                except Exception:
                    pass
                break
            parsed = self._parse_grep_line(raw.rstrip(b"\r\n"))
            if parsed is None:
                continue
            path, line_number, content_bytes = parsed
            info = self._build_match_info(path, line_number, content_bytes)
            if info is None:
                continue
            matched_files.append(info)
            if on_match:
                on_match(info)

        if not cancelled:
            exit_code = stdout.channel.recv_exit_status()
            err = stderr.read()
            if exit_code >= 2:
                err_text = err.decode("utf-8", errors="ignore").strip()
                if not matched_files and err_text:
                    # probably a bad grep invocation -> let the caller fall back
                    raise RuntimeError(f"grep failed: {err_text[:300]}")
                if err_text:
                    print(f"grep warnings: {err_text[:300]}")
        return matched_files, None

    def _build_grep_command(
        self,
        search_string: str,
        case_sensitive: bool,
        file_pattern: str,
        search_paths: List[str],
        after_date: Optional[datetime] = None,
        before_date: Optional[datetime] = None,
    ) -> str:
        needle_args = ["-e " + shlex.quote(search_string)]
        if not search_string.isascii():
            # also match GBK-encoded bytes; harmless if the shell is not bash
            try:
                gbk_bytes = search_string.encode("gbk")
                raw = "$'" + "".join(f"\\x{b:02x}" for b in gbk_bytes) + "'"
                needle_args.append("-e " + raw)
            except (UnicodeEncodeError, LookupError):
                pass

        case_arg = [] if case_sensitive else ["-i"]

        if after_date is None and before_date is None:
            parts = ["LC_ALL=C", "grep", "-a", "-H", "-F", "-m", "1", "-n"]
            parts.extend(case_arg)
            parts.extend(needle_args)
            parts.append("--include=" + shlex.quote(file_pattern))
            parts.append("--")
            parts.extend(shlex.quote(p) for p in search_paths)
            return " ".join(parts)

        # time-filtered file selection via find, then grep the result
        grep_parts = ["env", "LC_ALL=C", "grep", "-a", "-H", "-F", "-m", "1", "-n"]
        grep_parts.extend(case_arg)
        grep_parts.extend(needle_args)
        find_parts = ["find"]
        find_parts.extend(shlex.quote(p) for p in search_paths)
        find_parts.append("-type f")
        find_parts.append("-name " + shlex.quote(file_pattern))
        if after_date is not None:
            find_parts.append(
                "-newermt " + shlex.quote(after_date.strftime("%Y-%m-%d %H:%M:%S"))
            )
        if before_date is not None:
            find_parts.append(
                shlex.quote("!") + " -newermt "
                + shlex.quote(before_date.strftime("%Y-%m-%d %H:%M:%S"))
            )
        find_parts.append("-print0")
        find_parts.append("2>/dev/null")
        return (
            " ".join(find_parts)
            + " | xargs -0 -r "
            + " ".join(grep_parts)
        )

    @staticmethod
    def _parse_grep_line(raw: bytes) -> Optional[Tuple[str, int, bytes]]:
        parts = raw.split(b":", 2)
        if len(parts) < 3:
            return None
        try:
            line_number = int(parts[1])
        except ValueError:
            return None
        return parts[0].decode("utf-8", errors="ignore"), line_number, parts[2]

    def _build_match_info(
        self, path: str, line_number: int, content_bytes: bytes
    ) -> Optional[Dict]:
        try:
            size = 0
            modified_time = None
            try:
                st = self.connection.sftp.stat(path)
                size = st.st_size
                modified_time = datetime.fromtimestamp(st.st_mtime)
            except Exception:
                pass

            head = b""
            try:
                with self.connection.sftp.open(path, "rb") as f:
                    head = f.read(self.HEAD_SIZE)
            except Exception:
                pass

            test_file, start_time, pts_modify_time = self._parse_head(head)
            detected = self._detect_encoding(head.split(b"\n", 1)[0]) if head else None
            content = self._decode_line(content_bytes, detected).strip()[:200]
            return {
                "path": path,
                "filename": path.rsplit("/", 1)[-1],
                "size": size,
                "modified_time": modified_time,
                "test_file": test_file,
                "start_time": start_time,
                "pts_modify_time": pts_modify_time,
                "match": {"line_number": line_number, "content": content},
            }
        except Exception as e:
            print(f"Warning: could not read info for '{path}' - {str(e)}")
            return None

    @staticmethod
    def _first_file_per_folder(files: List[Dict]) -> List[Dict]:
        seen_folders = set()
        result = []
        for file_info in files:
            folder = posixpath.dirname(file_info["path"])
            if folder not in seen_folders:
                seen_folders.add(folder)
                result.append(file_info)
        return result

    def _search_single_file(
        self,
        file_info: Dict,
        search_string: str,
        case_sensitive: bool,
        client=None,
    ) -> Optional[Dict]:
        if client is None:
            client = self.connection.sftp
        try:
            needles, fold = self._build_needles(search_string, case_sensitive)
            if not needles:
                return None
            overlap = max(len(n) for n in needles) - 1
            keep = max(overlap, self.LINE_CONTEXT)

            size = file_info.get("size") or 0
            head = b""
            buf = b""
            newlines_before = 0
            detected = None
            matched = False
            match = None

            with client.open(file_info["path"], "rb") as f:
                prefetch = getattr(f, "prefetch", None)
                if prefetch is not None and size > 0:
                    try:
                        prefetch(size, self.MAX_INFLIGHT)
                    except TypeError:
                        # older paramiko without max_concurrent_requests
                        prefetch(size)
                    except Exception:
                        pass

                while not matched:
                    chunk = f.read(self.CHUNK_SIZE)
                    if not chunk:
                        break
                    if len(head) < self.HEAD_SIZE:
                        head += chunk[: self.HEAD_SIZE - len(head)]
                    buf += chunk

                    idx = self._find(buf, needles, fold)
                    if idx >= 0:
                        # pull more data if the matched line end is not in buf yet
                        while buf.find(b"\n", idx) == -1 and len(buf) < idx + 400:
                            more = f.read(self.CHUNK_SIZE)
                            if not more:
                                break
                            buf += more
                        matched = True
                        line_number = newlines_before + buf.count(b"\n", 0, idx) + 1
                        if detected is None and head:
                            detected = self._detect_encoding(head.split(b"\n", 1)[0])
                        line_bytes = self._extract_line(buf, idx)
                        content = self._decode_line(line_bytes, detected).strip()[:200]
                        match = {"line_number": line_number, "content": content}
                        break

                    if len(buf) > keep:
                        consumed = len(buf) - keep
                        newlines_before += buf.count(b"\n", 0, consumed)
                        buf = buf[consumed:]
                    # else: chunk smaller than keep window, keep accumulating

            if not matched:
                return None

            test_file, start_time, pts_modify_time = self._parse_head(head)
            return {
                "path": file_info["path"],
                "filename": file_info["filename"],
                "size": file_info["size"],
                "modified_time": file_info.get("modified_time"),
                "test_file": test_file,
                "start_time": start_time,
                "pts_modify_time": pts_modify_time,
                "match": match,
            }

        except self.CONNECTION_ERRORS:
            # connection-level failure: let the caller recycle the connection
            raise
        except Exception as e:
            print(f"Warning: Could not process file '{file_info['path']}' - {str(e)}")
            return None

    @staticmethod
    def _build_needles(search_string: str, case_sensitive: bool) -> Tuple[List[bytes], bool]:
        """Build byte needles to search for. Returns (needles, fold_case).

        ASCII strings use a single utf-8 needle with optional byte folding.
        Non-ASCII strings (e.g. Chinese test items) are encoded with the
        common CSV encodings since the file bytes are never decoded.
        """
        if search_string.isascii():
            term = search_string if case_sensitive else search_string.lower()
            return [term.encode("utf-8")], not case_sensitive

        needles = []
        for enc in ("utf-8", "gbk", "utf-16-le", "utf-16-be"):
            try:
                b = search_string.encode(enc)
            except (UnicodeEncodeError, LookupError):
                continue
            if b not in needles:
                needles.append(b)
        return needles, False

    @staticmethod
    def _find(buf: bytes, needles: List[bytes], fold: bool) -> int:
        region = buf.lower() if fold else buf
        idx = -1
        for needle in needles:
            pos = region.find(needle)
            if pos != -1 and (idx == -1 or pos < idx):
                idx = pos
        return idx

    @staticmethod
    def _extract_line(buf: bytes, idx: int) -> bytes:
        start = buf.rfind(b"\n", 0, idx) + 1
        end = buf.find(b"\n", idx)
        if end == -1:
            end = len(buf)
        return buf[start:end].rstrip(b"\r")

    def _parse_head(self, head: bytes) -> Tuple[str, str, str]:
        """Extract TestFile/StartTime/PtsModifyTime from the file head bytes."""
        test_file = ""
        start_time = ""
        pts_modify_time = ""
        if not head:
            return test_file, start_time, pts_modify_time

        detected = None
        raw_lines = head.split(b"\n")
        # a head truncated mid-line would corrupt the last value -> drop it
        if raw_lines and not head.endswith(b"\n"):
            raw_lines = raw_lines[:-1]
        for raw in raw_lines:
            line = self._decode_line(raw, detected)
            if detected is None:
                detected = self._detect_encoding(raw)
            stripped = line.rstrip("\r")

            if stripped.startswith("["):
                section = stripped[1:].split("]")[0].strip()
                if section.upper() == "DATA":
                    break
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

        return test_file, start_time, pts_modify_time

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
