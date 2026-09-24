"""HTML 报告的内联样式（light、A4 打印友好）。

单文件自包含：无外链、无 CDN。字族取 fonts.HTML_FONT_STACK（与前端
--font-sans 同源），使「中文正文不能是裸 Arial」这条能被测试断言到。
"""

from apps.export.fonts import HTML_FONT_STACK

# 语义色（light）：与前端 success/brand/warn/error 对应，用于 CPK 分级与警报。
COLOR_OK = '#2e7d32'
COLOR_BRAND = '#1565c0'
COLOR_WARN = '#ef6c00'
COLOR_ERR = '#c62828'

REPORT_CSS = (
    "body{font-family:" + HTML_FONT_STACK + ";margin:24px;color:#212121;background:#fff}"
    "h1{color:#2c3e50;margin:0 0 4px;font-size:22px}"
    "h2{color:#2c3e50;margin:22px 0 8px;font-size:16px;border-left:4px solid #2c3e50;padding-left:8px}"
    ".report-meta{color:#607d8b;font-size:12px;margin:0 0 14px}"
    "table{border-collapse:collapse;width:100%;font-size:12px;margin:6px 0 4px}"
    "th,td{border:1px solid #ddd;padding:5px 8px;text-align:center}"
    "th{background:#2c3e50;color:#fff;font-weight:600}"
    "td.left,th.left{text-align:left}"
    "tr:nth-child(even) td{background:#fafafa}"
    ".overview{display:flex;flex-wrap:wrap;gap:0;border:1px solid #ddd;border-radius:8px;"
    "background:#fbfcfd;margin:8px 0 4px}"
    ".overview .item{padding:8px 16px;border-right:1px solid #eee}"
    ".overview .item:last-child{border-right:none}"
    ".overview .label{display:block;font-size:11px;color:#78909c}"
    ".overview .kpi-value{font-size:18px;font-weight:700}"
    ".kpi-value.pass,.yield-value.good{color:" + COLOR_OK + "}"
    ".kpi-value.fail,.yield-value.bad{color:" + COLOR_ERR + "}"
    ".yield-value.warn{color:" + COLOR_WARN + "}"
    ".alerts{margin:8px 0}"
    ".alert{padding:7px 12px;border-radius:6px;margin:4px 0;font-size:13px;border:1px solid}"
    ".alert--error{background:#fdecea;border-color:#f5c6cb;color:" + COLOR_ERR + "}"
    ".alert--warning{background:#fff8e1;border-color:#ffe082;color:#8d6e00}"
    ".chart{margin:8px 0;text-align:center}"
    ".chart img{max-width:100%;height:auto;border:1px solid #eee;border-radius:6px}"
    ".cpk-strip{display:flex;height:16px;border-radius:8px;overflow:hidden;margin:10px 0 6px}"
    ".cpk-strip span{min-width:6px}"
    ".cpk-a{background:" + COLOR_OK + "}.cpk-b{background:" + COLOR_BRAND + "}"
    ".cpk-c{background:" + COLOR_WARN + "}.cpk-d{background:" + COLOR_ERR + "}"
    ".cpk-legend{font-size:12px;color:#546e7a;margin-bottom:6px}"
    ".topfail{margin:6px 0}"
    ".chip{display:inline-block;background:#eceff1;border-radius:12px;padding:3px 10px;"
    "margin:2px 6px 2px 0;font-size:12px}"
    ".empty{color:#90a4ae;font-size:12px;padding:6px 0}"
    ".report-footer{margin-top:24px;color:#90a4ae;font-size:11px;text-align:center}"
    "@media print{body{margin:8mm}h2{page-break-after:avoid}table,img{page-break-inside:avoid}}"
)
