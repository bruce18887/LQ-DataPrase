"""自包含 HTML 报告（内联 CSS + base64 图表，零外链，可离线打开）。"""

from .single import build_single_html_report
from .batch import build_batch_html_report

__all__ = ['build_single_html_report', 'build_batch_html_report']
