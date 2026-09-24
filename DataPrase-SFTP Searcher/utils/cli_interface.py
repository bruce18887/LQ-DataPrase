import os
import sys
from datetime import datetime
from typing import Optional, Tuple, List
from config.sftp_connection import SFTPConnection
from config.config_manager import ConfigManager
from search.file_retriever import FileRetriever
from search.content_searcher import ContentSearcher
from search.csv_column_reader import CsvColumnReader
from search.csv_content_searcher import CsvContentSearcher
from utils.report import ReportGenerator


class CLIInterface:
    def __init__(self):
        self.config_manager = ConfigManager()
        self.connection: Optional[SFTPConnection] = None
        self.report_generator = ReportGenerator()

    def run(self):
        self._show_banner()

        while True:
            print("\n" + "=" * 60)
            print("MAIN MENU")
            print("=" * 60)
            print("1. Connect to SFTP Server")
            print("2. Search Files")
            print("3. Extract Column from CSV Files")
            print("4. Search CSV Files for String")
            print("5. Manage Saved Connections")
            print("6. Exit")

            choice = input("\nSelect an option (1-6): ").strip()

            if choice == "1":
                self._handle_connect()
            elif choice == "2":
                self._handle_search()
            elif choice == "3":
                self._handle_extract_column()
            elif choice == "4":
                self._handle_csv_search()
            elif choice == "5":
                self._handle_manage_connections()
            elif choice == "6":
                self._disconnect()
                print("Goodbye!")
                sys.exit(0)
            else:
                print("Invalid option. Please try again.")

    def _show_banner(self):
        print("\n" + "=" * 60)
        print("       SFTP File Search Tool")
        print("       Version 1.0")
        print("=" * 60)
        print("A powerful tool for searching files on SFTP servers")
        print("=" * 60)

    def _handle_connect(self):
        print("\n--- Connect to SFTP Server ---")

        saved_connections = self.config_manager.list_connections()
        if saved_connections:
            print("\nSaved connections:")
            for idx, name in enumerate(saved_connections, 1):
                print(f"  {idx}. {name}")
            print(f"  {len(saved_connections) + 1}. New connection")

            choice = input("\nSelect a connection or create new (number): ").strip()

            try:
                choice_num = int(choice)
                if 1 <= choice_num <= len(saved_connections):
                    self._connect_to_saved(saved_connections[choice_num - 1])
                    return
            except ValueError:
                pass

        self._connect_new()

    def _connect_to_saved(self, name: str):
        conn_info = self.config_manager.load_connection(name)
        if not conn_info:
            print("Error: Could not load saved connection.")
            return

        self.connection = SFTPConnection(
            host=conn_info["host"],
            port=conn_info["port"],
            username=conn_info["username"],
            password=conn_info["password"],
        )

        if self.connection.connect():
            print(f"Connected using saved configuration: {name}")

    def _connect_new(self):
        print("\nEnter SFTP connection details:")
        host = input("  Host/IP: ").strip()
        if not host:
            print("Error: Host is required.")
            return

        port_str = input("  Port (default: 22): ").strip()
        port = int(port_str) if port_str else 22

        username = input("  Username: ").strip()
        if not username:
            print("Error: Username is required.")
            return

        password = input("  Password: ").strip()
        if not password:
            print("Error: Password is required.")
            return

        timeout_str = input("  Timeout in seconds (default: 30): ").strip()
        timeout = int(timeout_str) if timeout_str else 30

        self.connection = SFTPConnection(
            host=host, port=port, username=username, password=password, timeout=timeout
        )

        if self.connection.connect():
            save = input("\nSave this connection? (y/n): ").strip().lower()
            if save == "y":
                name = input("  Connection name: ").strip()
                if name:
                    self.config_manager.save_connection(name, host, port, username, password)
                    default = input("  Set as default connection? (y/n): ").strip().lower()
                    if default == "y":
                        self.config_manager.set_default_connection(name)

    def _handle_search(self):
        if not self.connection or not self.connection.is_connected():
            print("Error: Not connected to SFTP server. Please connect first.")
            return

        print("\n--- File Search ---")

        search_path = input("  Remote directory to search (default: /): ").strip()
        if not search_path:
            search_path = "/"

        ext_input = input("  File extensions to search (comma-separated, e.g., .txt,.csv): ").strip()
        extensions = None
        if ext_input:
            extensions = [ext.strip() if ext.strip().startswith(".") else f".{ext.strip()}" for ext in ext_input.split(",")]

        # --- File content search prompt: moved BEFORE file retrieval ---
        search_string = input("\n  Search file contents for a string (press Enter to skip): ").strip()

        case_sensitive = False
        fuzzy = False
        if search_string:
            case_sensitive = input("  Case sensitive? (y/n, default: n): ").strip().lower() == "y"
            fuzzy = input("  Enable fuzzy matching? (y/n, default: n): ").strip().lower() == "y"

        print("\nFilter options (press Enter to skip):")
        min_size = self._parse_size_input("  Minimum file size (e.g., 100, 1KB, 5MB): ")
        max_size = self._parse_size_input("  Maximum file size (e.g., 100, 1KB, 5MB): ")

        recursive = input("  Recursive search? (y/n, default: y): ").strip().lower()
        recursive = recursive != "n"

        print("\nRetrieving files...")
        retriever = FileRetriever(self.connection)
        files = retriever.list_files(
            remote_path=search_path,
            extensions=extensions,
            min_size=min_size,
            max_size=max_size,
            recursive=recursive,
        )

        print(f"\nFound {len(files)} files matching criteria.")

        if not files:
            return

        if search_string:
            print("\nSearching file contents...")
            searcher = ContentSearcher(self.connection)
            start_time = datetime.now()

            matched_files, total_searched = searcher.search_in_files(
                files, search_string, case_sensitive, fuzzy
            )

            elapsed_time = (datetime.now() - start_time).total_seconds()

            self.report_generator.display_results(
                matched_files, total_searched, search_string, elapsed_time
            )

            export = input("\nExport results? (csv/txt/n, default: n): ").strip().lower()
            if export in ["csv", "txt"]:
                filename = self._ask_export_filename("search_results", export)

                if export == "csv":
                    self.report_generator.export_to_csv(matched_files, filename)
                else:
                    self.report_generator.export_to_text(matched_files, filename)
        else:
            print("\nMatching files:")
            for idx, file_info in enumerate(files, 1):
                print(
                    f"  {idx}. {file_info['path']} "
                    f"({retriever.format_size(file_info['size'])}, "
                    f"{file_info['modified_time'].strftime('%Y-%m-%d %H:%M')})"
                )

    def _handle_extract_column(self):
        if not self.connection or not self.connection.is_connected():
            print("Error: Not connected to SFTP server. Please connect first.")
            return

        print("\n--- Extract Column from CSV Files ---")
        print("This feature finds CSV files matching a pattern and extracts data from a specific column.")

        print("  Multiple paths supported - separate with commas or semicolons")
        search_paths_input = input("  Remote directories to search (default: /): ").strip()
        if not search_paths_input:
            search_paths = ["/"]
        else:
            search_paths = [p.strip() for p in search_paths_input.replace(";", ",").split(",") if p.strip()]
            if not search_paths:
                search_paths = ["/"]

        file_pattern = input("  File name pattern (default: *RT*.csv): ").strip()
        if not file_pattern:
            file_pattern = "*RT*.csv"

        column_name = input("  Column name to extract (default: ShadowReg2): ").strip()
        if not column_name:
            column_name = "ShadowReg2"

        max_rows_str = input("  Number of valid rows to extract per file (default: 10): ").strip()
        max_rows = int(max_rows_str) if max_rows_str else 10

        recursive = input("  Recursive search? (y/n, default: y): ").strip().lower()
        recursive = recursive != "n"

        print(f"\nSearching for files matching '{file_pattern}' in {len(search_paths)} path(s)...")
        for p in search_paths:
            print(f"  - {p}")

        retriever = FileRetriever(self.connection)
        files = retriever.list_files_from_paths(
            search_paths,
            filename_pattern=file_pattern,
            recursive=recursive,
        )

        print(f"Found {len(files)} matching files.")

        if not files:
            return

        print(f"\nExtracting column '{column_name}' from each file...")
        reader = CsvColumnReader(self.connection)
        start_time = datetime.now()

        result_files = reader.extract_column(files, column_name, max_rows)

        elapsed_time = (datetime.now() - start_time).total_seconds()

        self.report_generator.display_column_results(result_files, column_name, elapsed_time)

        if result_files:
            export = input("\nExport results? (csv/txt/n, default: n): ").strip().lower()
            if export in ["csv", "txt"]:
                filename = self._ask_export_filename("column_extract", export)

                if export == "csv":
                    self.report_generator.export_column_results_to_csv(result_files, filename)
                else:
                    self.report_generator.export_column_results_to_txt(result_files, filename)

    def _handle_csv_search(self):
        if not self.connection or not self.connection.is_connected():
            print("Error: Not connected to SFTP server. Please connect first.")
            return

        print("\n--- Search CSV Files for String ---")
        print("This feature finds CSV files containing a given string (e.g., a test item). One match per file is enough.")

        print("  Multiple paths supported - separate with commas or semicolons")
        search_paths_input = input("  Remote directories to search (default: /): ").strip()
        if not search_paths_input:
            search_paths = ["/"]
        else:
            search_paths = [p.strip() for p in search_paths_input.replace(";", ",").split(",") if p.strip()]
            if not search_paths:
                search_paths = ["/"]

        file_pattern = input("  File name pattern (default: *FT*.csv): ").strip()
        if not file_pattern:
            file_pattern = "*FT*.csv"

        search_string = input("  String to search for (test item): ").strip()
        if not search_string:
            print("No search string entered. Returning to menu.")
            return

        case_sensitive = input("  Case sensitive? (y/n, default: n): ").strip().lower() == "y"

        recursive = input("  Recursive search? (y/n, default: y): ").strip().lower()
        recursive = recursive != "n"

        print("  Time filter (Enter = all files):")
        after_date = self._ask_datetime("    Modified after (e.g. 2026-06-01 or 2026-06-01 12:30): ")
        before_date = self._ask_datetime("    Modified before (e.g. 2026-06-30 23:59): ")

        one_per_folder = input("  Search only one file per folder? (y/n, default: n): ").strip().lower() == "y"

        workers_str = input("  Number of parallel threads (default: 8): ").strip()
        try:
            max_workers = int(workers_str) if workers_str else 8
        except ValueError:
            max_workers = 8
        max_workers = max(1, min(max_workers, 8))

        default_summary = "csv_search_summary_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".txt"
        summary_input = input(f"  Real-time summary file (Enter = {default_summary}, n = off): ").strip()
        summary_path = None
        if summary_input and summary_input.lower() != "n":
            summary_path = summary_input
            if not summary_path.endswith((".txt", ".log")):
                summary_path += ".txt"
        elif not summary_input:
            summary_path = default_summary

        searcher = CsvContentSearcher(self.connection)

        use_grep = False
        if one_per_folder:
            print("\nOne-file-per-folder mode uses the parallel download search.")
        elif not recursive:
            print("\nNon-recursive search uses the parallel download search.")
        else:
            print("\nChecking for server-side grep search (no downloads, fastest)...")
            use_grep = searcher.server_grep_supported(search_paths)
            if use_grep:
                print("Server-side grep available - files will be scanned on the server.")
            else:
                print("Server-side grep not available -> using parallel download search.")

        summary_file = None
        if summary_path:
            try:
                summary_file = open(summary_path, "w", encoding="utf-8")
                summary_file.write("SFTP CSV SEARCH SUMMARY\n")
                summary_file.write(f"Search string: {search_string}\n")
                summary_file.write(f"File pattern: {file_pattern}\n")
                summary_file.write(f"Paths: {', '.join(search_paths)}\n")
                if use_grep:
                    summary_file.write("Mode: server-side grep\n")
                elif one_per_folder:
                    summary_file.write("Mode: one file per folder, download search\n")
                else:
                    summary_file.write(f"Mode: all files, {max_workers} thread(s), download search\n")
                time_filter_text = self._format_time_filter(after_date, before_date)
                if time_filter_text:
                    summary_file.write(f"Time filter: modified {time_filter_text}\n")
                summary_file.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                summary_file.write("-" * 60 + "\n\n")
                summary_file.flush()
                print(f"Real-time summary file: {summary_path}")
            except Exception as e:
                print(f"Warning: cannot write summary file: {str(e)}")
                summary_file = None

        print(f"\nSearching for '{search_string}'...")
        print("-" * 80)

        match_counter = {"count": 0}

        def format_match(file_info: Dict) -> str:
            lines = [f"[MATCH #{match_counter['count']}] {file_info['path']}"]
            lines.append(
                f"    Size: {retriever.format_size(file_info['size'])}"
                + (
                    f" | Modified: {file_info['modified_time'].strftime('%Y-%m-%d %H:%M')}"
                    if file_info.get("modified_time")
                    else ""
                )
            )
            lines.append(
                f"    TestFile: {file_info.get('test_file', '') or 'N/A'}"
                f" | StartTime: {file_info.get('start_time', '') or 'N/A'}"
                f" | PtsModifyTime: {file_info.get('pts_modify_time', '') or 'N/A'}"
            )
            match = file_info.get("match") or {}
            lines.append(f"    First match: Line {match.get('line_number', '')}: {match.get('content', '')}")
            return "\n".join(lines)

        def on_match(file_info: Dict):
            match_counter["count"] += 1
            text = format_match(file_info)
            print(f"\r{text}")
            if summary_file:
                summary_file.write(text + "\n\n")
                summary_file.flush()

        def on_progress(done: int, total: int):
            pct = done * 100.0 / total if total else 100.0
            sys.stdout.write(f"\rProgress: {pct:.1f}% ({done}/{total})")
            sys.stdout.flush()

        retriever = FileRetriever(self.connection)
        start_time = datetime.now()
        matched_files: List[Dict] = []
        total_searched = 0

        try:
            if use_grep:
                try:
                    matched_files, total_searched = searcher.search_via_server(
                        search_paths,
                        file_pattern,
                        search_string,
                        case_sensitive,
                        after_date=after_date,
                        before_date=before_date,
                        on_match=on_match,
                    )
                except Exception as e:
                    print(f"\nServer-side search failed ({str(e)}); falling back to download search.")
                    use_grep = False

            if not use_grep:
                time_filter_text = self._format_time_filter(after_date, before_date)
                print(f"\nListing files matching '{file_pattern}' in {len(search_paths)} path(s)...")
                if time_filter_text:
                    print(f"Time filter: modified {time_filter_text}")
                for p in search_paths:
                    print(f"  - {p}")

                files = retriever.list_files_from_paths(
                    search_paths,
                    filename_pattern=file_pattern,
                    min_size=None,
                    max_size=None,
                    after_date=after_date,
                    before_date=before_date,
                    recursive=recursive,
                )

                print(f"Found {len(files)} file(s).")
                if one_per_folder and files:
                    print("Mode: only the first file in each folder will be searched.")

                if not files:
                    return

                print(f"Searching file contents ({max_workers} thread(s))...")
                matched_files, total_searched = searcher.search_in_files(
                    files,
                    search_string,
                    case_sensitive,
                    max_workers=max_workers,
                    one_file_per_folder=one_per_folder,
                    on_match=on_match,
                    on_progress=on_progress,
                )
        finally:
            elapsed_time = (datetime.now() - start_time).total_seconds()
            if summary_file:
                try:
                    summary_file.write("-" * 60 + "\n")
                    if total_searched is None:
                        summary_file.write(
                            f"Done: {len(matched_files)} file(s) matched "
                            f"(server-side search) in {elapsed_time:.2f}s\n"
                        )
                    else:
                        summary_file.write(
                            f"Done: {len(matched_files)} file(s) matched, "
                            f"{total_searched} file(s) searched in {elapsed_time:.2f}s\n"
                        )
                finally:
                    summary_file.close()
                    summary_file = None

        print()
        print("-" * 80)
        if total_searched is None:
            print(f"Done: {len(matched_files)} file(s) matched (server-side search) in {elapsed_time:.2f}s")
        else:
            print(f"Done: {len(matched_files)} file(s) matched, {total_searched} file(s) searched in {elapsed_time:.2f}s")

        if matched_files:
            export = input("\nExport results? (csv/txt/n, default: n): ").strip().lower()
            if export in ["csv", "txt"]:
                filename = self._ask_export_filename("csv_search_results", export)

                if export == "csv":
                    self.report_generator.export_csv_search_results_to_csv(matched_files, filename)
                else:
                    self.report_generator.export_csv_search_results_to_txt(matched_files, filename)

    def _handle_manage_connections(self):
        print("\n--- Manage Saved Connections ---")

        connections = self.config_manager.list_connections()
        if not connections:
            print("No saved connections.")
            return

        print("\nSaved connections:")
        for idx, name in enumerate(connections, 1):
            default_marker = " (default)" if self.config_manager.get_default_connection() == name else ""
            print(f"  {idx}. {name}{default_marker}")

        print("\nOptions:")
        print("  1. Delete a connection")
        print("  2. Set default connection")
        print("  3. Back to main menu")

        choice = input("\nSelect an option (1-3): ").strip()

        if choice == "1":
            conn_idx = input("  Enter connection number to delete: ").strip()
            try:
                idx = int(conn_idx) - 1
                if 0 <= idx < len(connections):
                    self.config_manager.delete_connection(connections[idx])
            except ValueError:
                print("Invalid number.")
        elif choice == "2":
            conn_idx = input("  Enter connection number to set as default: ").strip()
            try:
                idx = int(conn_idx) - 1
                if 0 <= idx < len(connections):
                    self.config_manager.set_default_connection(connections[idx])
            except ValueError:
                print("Invalid number.")

    def _disconnect(self):
        if self.connection and self.connection.is_connected():
            self.connection.disconnect()

    def _ask_datetime(self, prompt: str) -> Optional[datetime]:
        """Ask for a date/time; empty input returns None (no filter)."""
        formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]
        while True:
            text = input(prompt).strip()
            if not text:
                return None
            for fmt in formats:
                try:
                    return datetime.strptime(text, fmt)
                except ValueError:
                    continue
            print("  Invalid date format. Use YYYY-MM-DD or YYYY-MM-DD HH:MM (Enter = skip).")

    def _format_time_filter(self, after_date: Optional[datetime], before_date: Optional[datetime]) -> str:
        parts = []
        if after_date:
            parts.append("after " + after_date.strftime("%Y-%m-%d %H:%M:%S"))
        if before_date:
            parts.append("before " + before_date.strftime("%Y-%m-%d %H:%M:%S"))
        return ", ".join(parts)

    def _ask_export_filename(self, default: str, ext: str) -> str:
        """Ask for an export filename, re-prompting until it is valid."""
        while True:
            filename = input(f"  Output filename (default: {default}): ").strip()
            if not filename:
                filename = default
            if not filename.lower().endswith("." + ext):
                filename += "." + ext
            problem = self._invalid_filename_reason(filename)
            if problem:
                print(f"  Invalid filename: {problem}. Please try again (Enter = {default}).")
                continue
            return filename

    @staticmethod
    def _invalid_filename_reason(filename: str) -> Optional[str]:
        """Return a reason string if the filename is invalid on Windows, else None."""
        if not filename.strip():
            return "name is empty"
        final = filename.replace("/", "\\").split("\\")[-1]
        bad = [c for c in final if c in '<>:"|?*' or ord(c) < 32]
        if bad:
            return f"cannot contain the character '{bad[0]}'"
        base = final.rsplit(".", 1)[0]
        reserved = {"CON", "PRN", "AUX", "NUL"}
        reserved |= {f"COM{i}" for i in range(1, 10)}
        reserved |= {f"LPT{i}" for i in range(1, 10)}
        if base.upper() in reserved:
            return f"'{base}' is a reserved Windows device name"
        return None

    def _parse_size_input(self, prompt: str) -> Optional[int]:
        size_input = input(prompt).strip()
        if not size_input:
            return None

        try:
            if size_input.upper().endswith("KB"):
                return int(float(size_input[:-2]) * 1024)
            elif size_input.upper().endswith("MB"):
                return int(float(size_input[:-2]) * 1024 * 1024)
            elif size_input.upper().endswith("GB"):
                return int(float(size_input[:-2]) * 1024 * 1024 * 1024)
            else:
                return int(size_input)
        except ValueError:
            print("  Warning: Invalid size format, ignoring filter.")
            return None
