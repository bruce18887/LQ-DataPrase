import os
import csv
from datetime import datetime
from typing import List, Dict


class ReportGenerator:
    def __init__(self):
        self.search_stats = {}

    def display_results(
        self,
        matched_files: List[Dict],
        total_searched: int,
        search_string: str,
        elapsed_time: float,
        show_details: bool = True,
    ):
        self.search_stats = {
            "search_string": search_string,
            "total_searched": total_searched,
            "matched_files": len(matched_files),
            "elapsed_time": elapsed_time,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        print("\n" + "=" * 80)
        print("SEARCH RESULTS")
        print("=" * 80)
        print(f"Search string: {search_string}")
        print(f"Total files searched: {total_searched}")
        print(f"Files with matches: {len(matched_files)}")
        print(f"Search time: {elapsed_time:.2f} seconds")
        print("=" * 80)

        if not matched_files:
            print("\nNo matches found.")
            return

        for idx, file_info in enumerate(matched_files, 1):
            print(f"\n[{idx}] {file_info['path']}")
            print(f"    Size: {self._format_size(file_info['size'])}")
            print(f"    Matches: {file_info['match_count']}")

            if show_details and file_info["matches"]:
                print("    Sample matches:")
                for match in file_info["matches"][:3]:
                    print(f"      Line {match['line_number']}: {match['content'][:100]}")
                    if len(file_info["matches"]) > 3:
                        print(f"      ... and {len(file_info['matches']) - 3} more matches")
                        break

        print("\n" + "=" * 80)
        print("SEARCH STATISTICS")
        print("=" * 80)
        print(f"Search completed at: {self.search_stats['timestamp']}")
        print(f"Total files scanned: {total_searched}")
        print(f"Matching files: {len(matched_files)}")
        print(f"Search duration: {elapsed_time:.2f}s")
        print("=" * 80)

    def export_to_csv(self, matched_files: List[Dict], output_file: str) -> bool:
        try:
            with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(
                    [
                        "File Path",
                        "File Name",
                        "File Size (bytes)",
                        "Match Count",
                        "Line Number",
                        "Match Position",
                        "Content Preview",
                    ]
                )

                for file_info in matched_files:
                    for match in file_info["matches"]:
                        writer.writerow(
                            [
                                file_info["path"],
                                file_info["filename"],
                                file_info["size"],
                                file_info["match_count"],
                                match["line_number"],
                                match["position"],
                                match["content"],
                            ]
                        )

            print(f"Results exported to: {output_file}")
            return True
        except Exception as e:
            print(f"Error exporting to CSV: {str(e)}")
            return False

    def export_to_text(self, matched_files: List[Dict], output_file: str) -> bool:
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("SFTP File Search Results\n")
                f.write("=" * 80 + "\n")
                f.write(f"Search string: {self.search_stats.get('search_string', 'N/A')}\n")
                f.write(
                    f"Total files searched: {self.search_stats.get('total_searched', 0)}\n"
                )
                f.write(
                    f"Files with matches: {self.search_stats.get('matched_files', 0)}\n"
                )
                f.write(
                    f"Search time: {self.search_stats.get('elapsed_time', 0):.2f} seconds\n"
                )
                f.write(f"Timestamp: {self.search_stats.get('timestamp', 'N/A')}\n")
                f.write("=" * 80 + "\n\n")

                for idx, file_info in enumerate(matched_files, 1):
                    f.write(f"\n[{idx}] {file_info['path']}\n")
                    f.write(f"    Size: {self._format_size(file_info['size'])}\n")
                    f.write(f"    Matches: {file_info['match_count']}\n")

                    for match in file_info["matches"]:
                        f.write(
                            f"      Line {match['line_number']}, Position {match['position']}: {match['content']}\n"
                        )

                f.write("\n" + "=" * 80 + "\n")
                f.write("End of report\n")

            print(f"Results exported to: {output_file}")
            return True
        except Exception as e:
            print(f"Error exporting to text file: {str(e)}")
            return False

    def display_column_results(
        self,
        result_files: List[Dict],
        column_name: str,
        elapsed_time: float,
    ):
        print("\n" + "=" * 80)
        print(f"COLUMN EXTRACTION RESULTS - Column: {column_name}")
        print("=" * 80)
        print(f"Files processed: {len(result_files)}")
        print(f"Search time: {elapsed_time:.2f} seconds")
        print("=" * 80)

        if not result_files:
            print("\nNo data found.")
            return

        for idx, file_info in enumerate(result_files, 1):
            print(f"\n[{idx}] {file_info['path']}")
            print(f"    Size: {self._format_size(file_info['size'])}")
            print(f"    TestFile: {file_info.get('test_file', 'N/A')}")
            print(f"    StartTime: {file_info.get('start_time', 'N/A')}")
            print(f"    PtsModifyTime: {file_info.get('pts_modify_time', 'N/A')}")
            print(f"    Valid values found: {file_info['value_count']}")
            print(f"    Values:")
            for vi, val in enumerate(file_info["values"], 1):
                print(f"      [{vi}] {val}")

        print("\n" + "=" * 80)
        print("EXTRACTION COMPLETE")
        print("=" * 80)

    def export_column_results_to_csv(self, result_files: List[Dict], output_file: str) -> bool:
        try:
            with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["File Path", "File Name", "TestFile", "StartTime", "PtsModifyTime", "Value Index", "Value"])

                for file_info in result_files:
                    for vi, val in enumerate(file_info["values"], 1):
                        writer.writerow([
                            file_info["path"],
                            file_info["filename"],
                            file_info.get("test_file", ""),
                            file_info.get("start_time", ""),
                            file_info.get("pts_modify_time", ""),
                            vi,
                            val,
                        ])

            print(f"Results exported to: {output_file}")
            return True
        except Exception as e:
            print(f"Error exporting to CSV: {str(e)}")
            return False

    def export_csv_search_results_to_csv(self, matched_files: List[Dict], output_file: str) -> bool:
        try:
            with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(
                    [
                        "File Path",
                        "File Name",
                        "File Size (bytes)",
                        "TestFile",
                        "StartTime",
                        "PtsModifyTime",
                        "Line Number",
                        "Matched Content",
                    ]
                )

                for file_info in matched_files:
                    match = file_info.get("match") or {}
                    writer.writerow(
                        [
                            file_info["path"],
                            file_info["filename"],
                            file_info["size"],
                            file_info.get("test_file", ""),
                            file_info.get("start_time", ""),
                            file_info.get("pts_modify_time", ""),
                            match.get("line_number", ""),
                            match.get("content", ""),
                        ]
                    )

            print(f"Results exported to: {output_file}")
            return True
        except Exception as e:
            print(f"Error exporting to CSV: {str(e)}")
            return False

    def export_csv_search_results_to_txt(self, matched_files: List[Dict], output_file: str) -> bool:
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                for file_info in matched_files:
                    f.write(f"File: {file_info['path']}\n")
                    f.write(f"Size: {self._format_size(file_info['size'])}\n")
                    if file_info.get("modified_time"):
                        f.write(
                            f"Modified: {file_info['modified_time'].strftime('%Y-%m-%d %H:%M')}\n"
                        )
                    f.write(f"TestFile: {file_info.get('test_file', '') or 'N/A'}\n")
                    f.write(f"StartTime: {file_info.get('start_time', '') or 'N/A'}\n")
                    f.write(f"PtsModifyTime: {file_info.get('pts_modify_time', '') or 'N/A'}\n")
                    match = file_info.get("match") or {}
                    f.write(f"First match: Line {match.get('line_number', '')}: {match.get('content', '')}\n")
                    f.write("-" * 60 + "\n\n")

            print(f"Results exported to: {output_file}")
            return True
        except Exception as e:
            print(f"Error exporting to text file: {str(e)}")
            return False

    def export_column_results_to_txt(self, result_files: List[Dict], output_file: str) -> bool:
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                for file_info in result_files:
                    f.write(f"File: {file_info['path']}\n")
                    f.write(f"Column: {file_info['column_name']}\n")
                    f.write(f"TestFile: {file_info.get('test_file', 'N/A')}\n")
                    f.write(f"StartTime: {file_info.get('start_time', 'N/A')}\n")
                    f.write(f"PtsModifyTime: {file_info.get('pts_modify_time', 'N/A')}\n")
                    f.write(f"Valid values: {file_info['value_count']}\n")
                    f.write("-" * 60 + "\n")
                    for vi, val in enumerate(file_info["values"], 1):
                        f.write(f"  [{vi}] {val}\n")
                    f.write("\n")

            print(f"Results exported to: {output_file}")
            return True
        except Exception as e:
            print(f"Error exporting to text file: {str(e)}")
            return False

    def export_file_list_to_csv(self, files: List[Dict], output_file: str) -> bool:
        try:
            with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(["File Path", "File Name", "File Size (bytes)", "Modified Time"])
                for f in files:
                    modified = (
                        f["modified_time"].strftime("%Y-%m-%d %H:%M")
                        if f.get("modified_time") else ""
                    )
                    writer.writerow([f["path"], f["filename"], f["size"], modified])
            print(f"Results exported to: {output_file}")
            return True
        except Exception as e:
            print(f"Error exporting to CSV: {str(e)}")
            return False

    def export_file_list_to_txt(self, files: List[Dict], output_file: str) -> bool:
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                for idx, fi in enumerate(files, 1):
                    modified = (
                        fi["modified_time"].strftime("%Y-%m-%d %H:%M")
                        if fi.get("modified_time") else ""
                    )
                    f.write(
                        f"[{idx}] {fi['path']} "
                        f"({self._format_size(fi['size'])}, {modified})\n"
                    )
            print(f"Results exported to: {output_file}")
            return True
        except Exception as e:
            print(f"Error exporting to text file: {str(e)}")
            return False

    def _format_size(self, size_bytes: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"
