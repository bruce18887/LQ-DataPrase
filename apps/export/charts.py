"""Chart generation utilities for export."""

import io
import math

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.lines import Line2D
from matplotlib.offsetbox import AnchoredOffsetbox, HPacker, TextArea
from matplotlib.patches import Patch
from apps.analysis.services.statistics.helpers import normal_pdf_curve, site_sort_key
from apps.analysis.services.statistics.kde import GaussianKDE
from apps.export.histogram_grid import (
    bin_percentages, build_histogram_grid, finite_or_none,
)
from apps.export.fonts import apply_matplotlib_fonts

# ---- 视觉规格：对齐屏幕直方图（frontend HistogramChart.vue，light 主题）----
# 导出图恒为白底（嵌 Excel/PPT），所以只取 light 主题这一套值。
# 站点 8 色必须与前端 SITE_COLORS_8_LIGHT 逐值相同（Tol muted，CVD 安全）：
# 前端注释明确它是「直方图基准色，所有分析图表共用」。两份字面量的同步由
# apps/export/tests_histogram_style.py 的源码扫描用例钉住。
COLORS_SITE_8 = ['#0077BB', '#EE7733', '#009988', '#CC3311',
                 '#33BBEE', '#EE3377', '#BBBBBB', '#648FFF']
# All Site 系列（屏幕直方图右轴：半透明总分布柱 + 柱顶百分比）
COLOR_ALLSITE = '#90CAF9'
COLOR_ALLSITE_LABEL = '#1565C0'
# 双 Y 轴：左「百分比 (%)」蓝、右「All Site (%)」浅蓝（同屏幕 AXIS.left/allsite）
COLOR_AXIS_LEFT = '#1E88E5'
COLOR_AXIS_RIGHT = '#42A5F5'
COLOR_TEXT = '#6b7280'
COLOR_AXIS_LINE = '#e5e7eb'
COLOR_GRID = '#dbdee4'
COLOR_LIMIT = '#C62828'
COLOR_LIMIT_BADGE_TEXT = '#E65100'
COLOR_LIMIT_BADGE_BG = '#FFF3E0'
COLOR_SIGMA_3 = '#1565C0'
COLOR_SIGMA_4 = '#00838F'
COLOR_SIGMA_6 = '#E65100'
COLOR_NORMAL = '#F57F17'
COLOR_KDE = '#7B1FA2'
# report_charts.py 仍按旧名引用 LSL/USL 线色（与规格限同一红）
COLOR_LSL = COLOR_LIMIT
COLOR_USL = COLOR_LIMIT

# 柱宽/重合度 = 屏幕默认值（frontend/src/stores/analysisTabs.ts:72-74 的
# barWidthPercent=20 / barOverlapPercent=5）。导出请求目前不携带这两项，
# 固定用默认值即可与屏幕「默认视图」一致。
BAR_WIDTH_PCT = 20
BAR_OVERLAP_PCT = 5


# 导出图表 DPI：合法区间与设置页 el-input-number 的 min/max 一致
# （ChartSettingsForm.vue:30-31 = 72–600）。默认 100 的依据：Excel 嵌入图以固定
# EMU 尺寸显示（openpyxl Image 800×450px），与源分辨率无关，150→100 后清晰度不降
# 反升，PNG 体积约降 2/3（10.9MB → 4-6MB）。
EXPORT_DPI_MIN = 72
EXPORT_DPI_MAX = 600
EXPORT_DPI_DEFAULT = 100


def clamp_export_dpi(value) -> int:
    """把任意输入折成合法 DPI：非数字/越界回退默认或就近钳到端点。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return EXPORT_DPI_DEFAULT
    if num != num:  # NaN
        return EXPORT_DPI_DEFAULT
    return int(min(EXPORT_DPI_MAX, max(EXPORT_DPI_MIN, num)))


def _format_percent(value) -> str:
    """自适应精度百分比（前端 utils/chart-bar.ts formatPercent 同口径）：

    默认 2 位小数，<0.01% 时扩到 3 位，<0.001% 显示 '<0.001'，末尾零去掉。
    柱顶百分比标签必须与屏幕逐字一致，否则同一批数据在两边显示成两个精度。
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return '0'
    if not np.isfinite(v) or v <= 0:
        return '0'
    if v < 0.001:
        return '<0.001'
    decimals = 2
    while v < 10 ** -decimals and decimals < 3:
        decimals += 1
    return f'{v:.{decimals}f}'.rstrip('0').rstrip('.') or '0'


def _format_axis_value(value) -> str:
    """智能轴刻度格式（前端 utils/chart-bar.ts formatAxisValue 同口径）：

    整数原样（10 → "10"），非整数最多 4 位小数并去尾零（10.5 → "10.5"、
    12.34567 → "12.3457"），避免固定 toFixed(4) 的假精度尾零。
    """
    v = float(value)
    if v.is_integer():
        return str(int(v))
    return f'{v:.4f}'.rstrip('0').rstrip('.') or '0'


def _add_rich_title(ax, param: str, unit: str, limit_text: str) -> None:
    """三段式标题：参数名（粗）+ 单位 + Limit 橙色徽标，对齐屏幕 rich-text 标题。

    ECharts 的 rich text 在 matplotlib 里没有对应物，用 TextArea/HPacker 把
    同样三段拼起来；徽标的圆角/底色用 text bbox 近似（做不到逐像素一致）。
    """
    parts = [TextArea(param, textprops={
        'fontsize': 11, 'fontweight': 'bold', 'color': COLOR_TEXT})]
    if unit:
        parts.append(TextArea(f'  ({unit})', textprops={
            'fontsize': 9, 'fontweight': 'medium', 'color': COLOR_TEXT}))
    if limit_text:
        parts.append(TextArea(f'  {limit_text}', textprops={
            'fontsize': 8, 'fontweight': 'bold', 'color': COLOR_LIMIT_BADGE_TEXT,
            'bbox': {'boxstyle': 'round,pad=0.25',
                     'facecolor': COLOR_LIMIT_BADGE_BG, 'edgecolor': 'none'}}))
    box = AnchoredOffsetbox(
        loc='lower center',
        child=HPacker(children=parts, align='center', pad=0, sep=0),
        frameon=False, pad=0, borderpad=0,
        bbox_to_anchor=(0.5, 1.01), bbox_transform=ax.transAxes)
    ax.add_artist(box)


def _align_site_series(df, site_col, data_series):
    """按 data_series 的索引对齐 Site 列，返回 (site_values, site_series)。

    屏幕侧 ``histogram.py`` 的口径：``site_idx_aligned = site_idx[data_series.index]``
    —— 只在参数值为有限数的 die 上统计站点分布。导出侧此前直接把整列 site
    喂进 ``pd.Series``，参数列含 NaN 时靠 DataFrame 索引对齐会**静默错位**
    （numpy 数组丢索引后按下标配对），这里按同一索引显式对齐。

    排序走 ``site_sort_key``：ETS88 等文件的 Site 列可能是 object dtype 混合
    int/str，旧 key 会在同一桶内比较 str<int 抛 TypeError。
    """
    if not site_col or site_col not in df.columns:
        return None, None
    site_series_raw = df[site_col]
    if isinstance(site_series_raw, pd.DataFrame):
        site_series_raw = site_series_raw.iloc[:, 0]
    aligned = (site_series_raw.loc[data_series.index]
               if isinstance(data_series, pd.Series) else site_series_raw)
    site_values = sorted(aligned.dropna().unique(), key=site_sort_key)
    return site_values, aligned.to_numpy()


def _render_histogram_payload(
    param, data_series, site_values, site_series,
    mean_val, std_val, rdl_min, rdl_max,
    show_limit=True, show_3sigma=False, show_4sigma=False,
    show_6sigma=False, show_normal=False, show_kde=False,
    dpi=EXPORT_DPI_DEFAULT, unit='',
):
    """渲染单个参数直方图 PNG，返回 io.BytesIO。

    与 _create_histogram_chart 同逻辑，但入参全部为可 pickle 的标量/ndarray
    （data_series/site_series 为 ndarray，site_values 为标量列表）——
    供 chart_workers 多进程渲染调用，不依赖 DataFrame。

    版式对齐屏幕 HistogramChart.vue（light 主题口径）：三段式标题、双 Y 轴
    （左「百分比 (%)」/ 右「All Site (%)」）、All Site 半透明柱 + 柱顶百分比、
    横向网格、底部图例。matplotlib 与 ECharts 是两套引擎，做不到逐像素一致，
    但颜色、轴、系列构成与信息层级保持同源。
    """
    apply_matplotlib_fonts()

    if len(data_series) == 0:
        return io.BytesIO()

    # 限值可能缺失/退化：parse_limit_string 新语义下缺失返回 None，旧语义回退
    # 0.0 造成幻影 (0, 0) —— 两种都由 resolve_bin_range 统一回退到数据范围，
    # 否则 TEMP 型数据（25~33）会全部落在 bin 外 → 导出图空白（缺陷 #5）。
    low_limit = finite_or_none(rdl_min)
    high_limit = finite_or_none(rdl_max)
    all_bins, bin_centers, data_gap = build_histogram_grid(rdl_min, rdl_max, data_series)
    # x 轴刻度唯一来源 = bin 中心（缺陷 #3：不要再另算一套公式）
    x_labels = [float(c) for c in bin_centers]

    has_site = site_series is not None and len(site_values or []) > 0
    site_list = list(site_values) if has_site else []
    series_count = len(site_list) + 1 if has_site else 1
    # 柱组几何对齐屏幕的 barWidth/barGap 语义：单系列 20% of bin，多系列被
    # getMaxBarWidthPercent 压到 87%/N；组内相邻柱按 5% 重合度错位。
    bar_w = data_gap * min(BAR_WIDTH_PCT / 100, 0.87 / series_count)
    step = bar_w * (1 - BAR_OVERLAP_PCT / 100)

    def slot_offset(idx: int) -> float:
        return (idx - (series_count - 1) / 2) * step

    # 轴范围向两端扩展柱组偏移量，避免首/末 bin 的外侧柱被裁掉
    pad = (series_count - 1) / 2 * step + bar_w / 2
    x_lo = x_labels[0] - pad
    x_hi = x_labels[-1] + pad

    # —— 各系列百分比（与屏幕同源：histogram_grid.bin_percentages 6 位口径）——
    # 分母 = 全量有限值数（屏幕 histogram.py 的 total_count 口径），不是各
    # site 内部归一：屏幕图里各 Site 柱合计 = 该 site 占比，全部 site 合计 100%。
    total_count = len(data_series)
    site_percents: dict = {}
    if has_site:
        param_ser = pd.to_numeric(pd.Series(data_series), errors='coerce')
        grouped = pd.DataFrame({'site': pd.Series(site_series), 'val': param_ser}).groupby('site')
        for site in site_list:
            sdata = (grouped.get_group(site)['val'].dropna()
                     if site in grouped.groups else pd.Series(dtype=float))
            hist, _ = np.histogram(sdata, bins=all_bins)
            site_percents[site] = bin_percentages(hist, total_count)
    hist_all, _ = np.histogram(np.asarray(data_series, dtype=float), bins=all_bins)
    all_percents = bin_percentages(hist_all, total_count)

    # 左轴上限：有站点数据时按站点直方图最大百分比向上取整留顶部空间
    # （屏幕 HistogramChart.vue 同公式）；无站点数据时保持 0–100。
    left_y_max = 100
    if has_site:
        max_site_pct = max((max(v) if v else 0.0 for v in site_percents.values()), default=0.0)
        left_y_max = math.ceil(max_site_pct / 5) * 5 + 5

    fig, ax = plt.subplots(figsize=(10, 5.5))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    if has_site:
        for idx, site in enumerate(site_list):
            ax.bar([x + slot_offset(idx) for x in x_labels], site_percents[site],
                   width=bar_w, color=COLORS_SITE_8[idx % len(COLORS_SITE_8)],
                   linewidth=0, zorder=2)
    else:
        ax.bar(x_labels, all_percents, width=bar_w, color=COLOR_AXIS_LEFT,
               linewidth=0, zorder=2)

    # All Site：半透明柱 + 柱顶百分比，挂在右轴（屏幕同款信息层级）。
    # 柱高用真实百分比，不做屏幕的 0.5% 最小可见高度钳制 —— 导出图是数据
    # 文档，柱高即百分比；这条口径由 test_export_histogram_grid 的求和断言钉住。
    ax_right = None
    if has_site:
        ax_right = ax.twinx()
        ax_right.patch.set_visible(False)
        allsite_offset = slot_offset(len(site_list))
        ax_right.bar([x + allsite_offset for x in x_labels], all_percents,
                     width=bar_w, color=COLOR_ALLSITE, alpha=0.5,
                     linewidth=0, zorder=2)
        for x, pct in zip(x_labels, all_percents):
            if pct > 0:
                ax_right.annotate(
                    f'{_format_percent(pct)}%', (x + allsite_offset, pct),
                    xytext=(0, 1.5), textcoords='offset points',
                    ha='center', va='bottom', fontsize=6.5,
                    color=COLOR_ALLSITE_LABEL, fontweight='bold',
                    clip_on=False, zorder=4)

    def add_vline(x, color, linestyle, label):
        """参考线 + 线端标签。出界线只画线不标字：标注 clip_on=False 落在轴外
        会把 bbox_inches='tight' 撑出大片空白（屏幕侧同样只显示框内的标签）。"""
        ax.axvline(x=x, color=color, linewidth=3, linestyle=linestyle, zorder=5)
        if x_lo <= x <= x_hi:
            ax.annotate(label, xy=(x, left_y_max * 0.98), fontsize=7, color=color,
                        fontweight='bold', ha='center', va='top',
                        bbox=dict(boxstyle='round,pad=0.15', facecolor='white',
                                  edgecolor=color, alpha=0.85),
                        clip_on=False, zorder=6)

    if show_limit and low_limit is not None:
        add_vline(low_limit, COLOR_LIMIT, '--', 'LSL')
    if show_limit and high_limit is not None:
        add_vline(high_limit, COLOR_LIMIT, '--', 'USL')

    sigma_specs = (
        (3, show_3sigma, COLOR_SIGMA_3, '3σ'),
        (4, show_4sigma, COLOR_SIGMA_4, '4σ'),
        (6, show_6sigma, COLOR_SIGMA_6, '6σ'),
    )
    for sigma, flag, color, prefix in sigma_specs:
        if flag and std_val > 0:
            add_vline(mean_val - sigma * std_val, color, ':', f'{prefix}下限')
            add_vline(mean_val + sigma * std_val, color, ':', f'{prefix}上限')

    # 曲线各自归一化到左轴满高 —— 屏幕侧两条曲线各挂一条隐藏密度轴，
    # 视觉上同样是「各自顶满绘图区」。
    normal_drawn = False
    if show_normal and std_val > 0:
        # 公式单一来源 normal_pdf_curve（与屏幕 ECharts / histogram 响应同源）
        curve = normal_pdf_curve(mean_val, std_val, x_lo, x_hi)
        if curve:
            x_pdf = np.array([x for x, _ in curve])
            pdf_values = np.array([y for _, y in curve])
            max_pdf = np.max(pdf_values)
            if max_pdf > 0:
                ax.plot(x_pdf, pdf_values / max_pdf * left_y_max,
                        color=COLOR_NORMAL, linewidth=3, label='正态分布', zorder=3)
                normal_drawn = True

    kde_drawn = False
    if show_kde:
        # Non-parametric density overlay: adapts to bimodal / skewed shapes
        # that the normal curve cannot represent.  Best-effort — a failed fit
        # (degenerate data) just omits the curve instead of failing the export.
        try:
            kde_vals = np.asarray(data_series, dtype=float)
            if len(kde_vals) >= 3 and np.ptp(kde_vals) > 0:
                kde = GaussianKDE(kde_vals, bw_method='silverman')
                x_kde = np.linspace(x_lo, x_hi, 200)
                kde_values = kde(x_kde)
                max_kde = np.max(kde_values)
                if max_kde > 0:
                    ax.plot(x_kde, kde_values / max_kde * left_y_max,
                            color=COLOR_KDE, linewidth=3, label='KDE曲线', zorder=3)
                    kde_drawn = True
        except Exception:
            pass

    # 图例：系列构成与屏幕一致（Site1..N、All Site、规格限、σ 线、曲线），
    # 参考线/曲线用 Line2D 代理，颜色与画出来的线严格同值。
    handles = []
    if has_site:
        for idx, site in enumerate(site_list):
            handles.append(Patch(facecolor=COLORS_SITE_8[idx % len(COLORS_SITE_8)],
                                 label=f'Site{site}'))
        handles.append(Patch(facecolor=COLOR_ALLSITE, alpha=0.5, label='All Site'))
    else:
        handles.append(Patch(facecolor=COLOR_AXIS_LEFT, label='数据分布'))
    if show_limit and (low_limit is not None or high_limit is not None):
        handles.append(Line2D([], [], color=COLOR_LIMIT, linewidth=3,
                              linestyle='--', label='规格限'))
    for _sigma, flag, color, prefix in sigma_specs:
        if flag and std_val > 0:
            handles.append(Line2D([], [], color=color, linewidth=3,
                                  linestyle=':', label=f'{prefix}线'))
    if normal_drawn:
        handles.append(Line2D([], [], color=COLOR_NORMAL, linewidth=3, label='正态分布'))
    if kde_drawn:
        handles.append(Line2D([], [], color=COLOR_KDE, linewidth=3, label='KDE曲线'))
    if handles:
        ax.legend(handles=handles, loc='upper center', bbox_to_anchor=(0.5, -0.18),
                  ncol=min(len(handles), 6), fontsize=8, frameon=False,
                  labelcolor=COLOR_TEXT, handlelength=1.6, columnspacing=1.2)

    ax.set_ylim(0, left_y_max)
    ax.set_xlim(x_lo, x_hi)
    ax.set_xticks(x_labels)
    ax.set_xticklabels([_format_axis_value(v) for v in x_labels], rotation=45,
                       ha='right', rotation_mode='anchor', fontsize=7,
                       color=COLOR_TEXT)
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter('%.0f%%'))
    ax.tick_params(axis='y', labelsize=7, colors=COLOR_AXIS_LEFT)
    ax.set_ylabel('百分比 (%)', fontsize=9, fontweight='bold', color=COLOR_AXIS_LEFT)
    ax.grid(True, axis='y', color=COLOR_GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color(COLOR_AXIS_LEFT)
    ax.spines['bottom'].set_color(COLOR_AXIS_LINE)

    if ax_right is not None:
        ax_right.yaxis.set_major_formatter(ticker.FormatStrFormatter('%.0f%%'))
        ax_right.tick_params(axis='y', labelsize=7, colors=COLOR_AXIS_RIGHT)
        ax_right.set_ylabel('All Site (%)', fontsize=9, fontweight='bold',
                            color=COLOR_AXIS_RIGHT)
        ax_right.spines['top'].set_visible(False)
        ax_right.spines['left'].set_visible(False)
        ax_right.spines['bottom'].set_visible(False)
        ax_right.spines['right'].set_color(COLOR_AXIS_RIGHT)
        ax_right.grid(False)

    limit_text = ''
    if low_limit is not None and high_limit is not None:
        limit_text = f'Limit [{low_limit:.4f}, {high_limit:.4f}]'
    _add_rich_title(ax, param, unit or '', limit_text)

    # 顶部预留标题块（offsetbox 不参与 tight_layout）；图例在轴外，由
    # savefig(bbox_inches='tight') 收进画布。
    fig.tight_layout(rect=(0, 0, 1, 0.94))

    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', dpi=dpi, bbox_inches='tight')
    plt.close(fig)
    img_buffer.seek(0)
    return img_buffer


def _create_histogram_chart(
    df, metadata, selected_param, data_series, mean_val, std_val,
    rdl_min, rdl_max, show_limit=True, show_3sigma=False,
    show_4sigma=False, show_6sigma=False, show_normal=False,
    show_kde=False, site_col=None, dpi=EXPORT_DPI_DEFAULT, unit=''
):
    """薄包装：从 DataFrame 提取 site 数据后委托 _render_histogram_payload。

    （主进程串行兜底路径保留此签名；并行路径直接用 _render_histogram_payload。）
    """
    site_values, site_series = _align_site_series(df, site_col, data_series)
    return _render_histogram_payload(
        selected_param, data_series.to_numpy(), site_values, site_series,
        mean_val, std_val, rdl_min, rdl_max,
        show_limit=show_limit, show_3sigma=show_3sigma,
        show_4sigma=show_4sigma, show_6sigma=show_6sigma,
        show_normal=show_normal, show_kde=show_kde,
        dpi=dpi, unit=unit,
    )
