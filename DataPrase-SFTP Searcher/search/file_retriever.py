import stat
import fnmatch
from datetime import datetime
from typing import List, Dict, Optional
from config.sftp_connection import SFTPConnection


class FileRetriever:
    def __init__(self, connection: SFTPConnection):
        self.connection = connection

    def list_files(
        self,
        remote_path: str = "/",
        extensions: Optional[List[str]] = None,
        filename_pattern: Optional[str] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        after_date: Optional[datetime] = None,
        before_date: Optional[datetime] = None,
        recursive: bool = True,
    ) -> List[Dict]:
        return self.list_files_from_paths(
            [remote_path], extensions, filename_pattern,
            min_size, max_size, after_date, before_date, recursive,
        )

    def list_files_from_paths(
        self,
        remote_paths: List[str],
        extensions: Optional[List[str]] = None,
        filename_pattern: Optional[str] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        after_date: Optional[datetime] = None,
        before_date: Optional[datetime] = None,
        recursive: bool = True,
    ) -> List[Dict]:
        seen_paths = set()
        all_files = []

        for path in remote_paths:
            files = []
            self._traverse_directory(
                path,
                extensions,
                filename_pattern,
                min_size,
                max_size,
                after_date,
                before_date,
                recursive,
                files,
            )
            for f in files:
                if f["path"] not in seen_paths:
                    seen_paths.add(f["path"])
                    all_files.append(f)

        return all_files

    def _traverse_directory(
        self,
        current_path: str,
        extensions: Optional[List[str]],
        filename_pattern: Optional[str],
        min_size: Optional[int],
        max_size: Optional[int],
        after_date: Optional[datetime],
        before_date: Optional[datetime],
        recursive: bool,
        files: List[Dict],
    ):
        try:
            entries = self.connection.sftp.listdir_attr(current_path)
        except Exception as e:
            print(f"Warning: Cannot access directory '{current_path}' - {str(e)}")
            return

        for entry in entries:
            full_path = f"{current_path.rstrip('/')}/{entry.filename}"

            if stat.S_ISDIR(entry.st_mode):
                if recursive:
                    self._traverse_directory(
                        full_path,
                        extensions,
                        filename_pattern,
                        min_size,
                        max_size,
                        after_date,
                        before_date,
                        recursive,
                        files,
                    )
            elif stat.S_ISREG(entry.st_mode):
                if self._matches_filters(
                    entry, extensions, filename_pattern, min_size, max_size, after_date, before_date
                ):
                    files.append(
                        {
                            "path": full_path,
                            "filename": entry.filename,
                            "size": entry.st_size,
                            "modified_time": datetime.fromtimestamp(entry.st_mtime),
                            "permissions": stat.filemode(entry.st_mode),
                        }
                    )

    def _matches_filters(
        self,
        entry,
        extensions: Optional[List[str]],
        filename_pattern: Optional[str],
        min_size: Optional[int],
        max_size: Optional[int],
        after_date: Optional[datetime],
        before_date: Optional[datetime],
    ) -> bool:
        if extensions:
            ext = "." + entry.filename.rsplit(".", 1)[-1].lower() if "." in entry.filename else ""
            if ext not in extensions:
                return False

        if filename_pattern and not fnmatch.fnmatch(entry.filename, filename_pattern):
            return False

        if min_size is not None and entry.st_size < min_size:
            return False

        if max_size is not None and entry.st_size > max_size:
            return False

        file_time = datetime.fromtimestamp(entry.st_mtime)
        if after_date is not None and file_time < after_date:
            return False

        if before_date is not None and file_time > before_date:
            return False

        return True

    def format_size(self, size_bytes: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"
