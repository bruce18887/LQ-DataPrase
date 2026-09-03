"""Chart generation utilities for export."""

import io
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from apps.analysis.services.statistics.helpers import normal_pdf_curve
from apps.analysis.services.statistics.kde import GaussianKDE
from apps.export.histogram_grid import (
    bin_percentages, build_histogram_grid, finite_or_none,
)

COLORS_SITE_8 = ['#E53935', '#1E88E5', '#43A047', '#F9A825', '#8E24AA', '#00ACC1', '#F57C00', '#D81B60']
COLOR_LSL = '#C62828'
COLOR_USL = '#C62828'
COLOR_SIGMA_3 = '#1565C0'
COLOR_SIGMA_4 = '#00838F'
COLOR_SIGMA_6 = '#E65100'
COLOR_NORMAL = '#F57F17'
COLOR_KDE = '#7B1FA2'


def _get_export_dpi():
    # Excel 嵌入图以固定 EMU 尺寸显示（openpyxl Image 800×450px），与源分辨率
    # 无关；150→100 后清晰度不降反升，PNG 体积约降 2/3（10.9MB → 4-6MB）。
    return 100


def build_histogram_bins(low: float, high: float):
    """.. deprecated:: 兼容 shim —— 生产路径请用 ``build_histogram_grid``。

    旧几何（26 条有限边界、两端各外扩 2.5 gap、无 ±inf 兜底）与屏幕侧
    ``histogram.compute_histogram_stats`` 平移了 0.5·gap，且超范围值被
    ``np.histogram`` 静默丢弃、限值退化时整张图空白（缺陷 #4/#5）。
    本函数只为 ``apps/export/tests.py::BuildHistogramBinsTests`` 保留原几何，
    导出侧（charts / export_ppt）已全部改走 ``build_histogram_grid``；
    测试迁移那一轮应连同本 shim 一起删除。
    """
    data_gap = (high - low) / 20 if (high - low) > 0 else 1.0
    bin_start = low - 2.5 * data_gap
    bins = np.array([bin_start + j * data_gap for j in range(26)])
    return bins, data_gap


def _render_histogram_payload(
    param, data_series, site_values, site_series,
    mean_val, std_val, rdl_min, rdl_max,
    show_limit=True, show_3sigma=False, show_4sigma=False,
    show_6sigma=False, show_normal=False, show_kde=False,
):
    """渲染单个参数直方图 PNG，返回 io.BytesIO。

    与 _create_histogram_chart 同逻辑，但入参全部为可 pickle 的标量/ndarray
    （data_series/site_series 为 ndarray，site_values 为标量列表）——
    供 chart_workers 多进程渲染调用，不依赖 DataFrame。
    """
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False

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
    n_bins = len(x_labels)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('#fafafa')

    colors = COLORS_SITE_8
    y_max_plot = 100

    def _add_vline_label(exp_ax, x, label, exp_color):
        label_y = y_max_plot - y_max_plot * 0.02
        exp_ax.annotate(label, xy=(x, label_y), fontsize=8, color=exp_color,
                        fontweight='bold', ha='center',
                        bbox=dict(boxstyle='round,pad=0.15', facecolor='white', edgecolor=exp_color, alpha=0.85),
                        clip_on=False)

    if site_series is not None:
        param_ser = pd.to_numeric(pd.Series(data_series), errors='coerce')
        grouped = pd.DataFrame({'site': pd.Series(site_series), 'val': param_ser}).groupby('site')
        bar_width = data_gap * 0.8 / len(site_values) if site_values else data_gap * 0.8

        for idx, site in enumerate(site_values):
            if site in grouped.groups:
                sdata = grouped.get_group(site)['val'].dropna()
            else:
                sdata = pd.Series(dtype=float)
            total = len(sdata)
            hist, _ = np.histogram(sdata, bins=all_bins)
            # 6 位口径（bin_percentages）：1/50000 = 0.002% 不得被归零（缺陷 #12）
            bar_data = bin_percentages(hist, total)
            offset = (idx - len(site_values) / 2 + 0.5) * bar_width
            bar_x = [x_labels[i] + offset for i in range(n_bins)]

            ax.bar(
                bar_x, bar_data, width=bar_width * 0.9,
                color=colors[idx % len(colors)], alpha=0.7,
                label=f'Site{site}%', edgecolor='white', linewidth=0.5
            )
    else:
        hist, _ = np.histogram(data_series, bins=all_bins)
        bar_data = bin_percentages(hist, len(data_series))
        ax.bar(x_labels, bar_data, width=data_gap * 0.9, color='#1E88E5', alpha=0.7, label='数据分布', edgecolor='white', linewidth=0.5)

    if show_limit and low_limit is not None:
        ax.axvline(x=low_limit, color=COLOR_LSL, linewidth=2.5, linestyle='--')
    if show_limit and high_limit is not None:
        ax.axvline(x=high_limit, color=COLOR_USL, linewidth=2.5, linestyle='--')

    for sigma, flag, color, label_prefix in [
        (3, show_3sigma, COLOR_SIGMA_3, '3σ'), (4, show_4sigma, COLOR_SIGMA_4, '4σ'), (6, show_6sigma, COLOR_SIGMA_6, '6σ')
    ]:
        if flag and std_val > 0:
            lower = mean_val - sigma * std_val
            upper = mean_val + sigma * std_val
            ax.axvline(x=lower, color=color, linewidth=2, linestyle=':')
            ax.axvline(x=upper, color=color, linewidth=2, linestyle=':')

    if show_normal and std_val > 0:
        # 公式单一来源 normal_pdf_curve（与屏幕 ECharts / histogram 响应同源），
        # 此处仅做导出图的 max-normalize 缩放
        curve = normal_pdf_curve(mean_val, std_val, x_labels[0], x_labels[-1])
        if curve:
            x_pdf = np.array([x for x, _ in curve])
            pdf_values = np.array([y for _, y in curve])
            max_pdf = np.max(pdf_values)
            if max_pdf > 0:
                normal_scaled = pdf_values / max_pdf * y_max_plot
                ax.plot(x_pdf, normal_scaled, color=COLOR_NORMAL, linewidth=3, label='正态分布')

    if show_kde:
        # Non-parametric density overlay: adapts to bimodal / skewed shapes
        # that the normal curve cannot represent.  Best-effort — a failed fit
        # (degenerate data) just omits the curve instead of failing the export.
        try:
            kde_vals = np.asarray(data_series, dtype=float)
            if len(kde_vals) >= 3 and np.ptp(kde_vals) > 0:
                kde = GaussianKDE(kde_vals, bw_method='silverman')
                x_kde = np.linspace(x_labels[0], x_labels[-1], 200)
                kde_values = kde(x_kde)
                max_kde = np.max(kde_values)
                if max_kde > 0:
                    kde_scaled = kde_values / max_kde * y_max_plot
                    ax.plot(x_kde, kde_scaled, color=COLOR_KDE, linewidth=3, label='KDE曲线')
        except Exception:
            pass

    ax.set_ylabel('百分比 (%)', fontsize=12)
    ax.set_ylim(0, y_max_plot)
    ax.set_xlim(float(x_labels[0]), float(x_labels[-1]))
    ax.set_xticks(x_labels)
    ax.xaxis.set_major_formatter(ticker.FormatStrFormatter('%.4f'))
    ax.tick_params(axis='x', rotation=45, labelsize=6)
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter('%.0f%%'))
    ax.grid(True, alpha=0.3)

    if show_limit and low_limit is not None:
        _add_vline_label(ax, low_limit, 'LSL', COLOR_LSL)
    if show_limit and high_limit is not None:
        _add_vline_label(ax, high_limit, 'USL', COLOR_USL)

    for sigma, flag, color, label_prefix in [
        (3, show_3sigma, COLOR_SIGMA_3, '3σ'), (4, show_4sigma, COLOR_SIGMA_4, '4σ'), (6, show_6sigma, COLOR_SIGMA_6, '6σ')
    ]:
        if flag and std_val > 0:
            lower = mean_val - sigma * std_val
            upper = mean_val + sigma * std_val
            _add_vline_label(ax, lower, f'{label_prefix}下限', color)
            _add_vline_label(ax, upper, f'{label_prefix}上限', color)

    ax.legend(fontsize=8, loc='upper center', bbox_to_anchor=(0.5, -0.2), ncol=4)
    ax.set_title(param, fontsize=14, fontweight='bold', color='#0066cc', pad=15)
    plt.tight_layout()

    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', dpi=_get_export_dpi(), bbox_inches='tight')
    plt.close(fig)
    img_buffer.seek(0)
    return img_buffer


def _create_histogram_chart(
    df, metadata, selected_param, data_series, mean_val, std_val,
    rdl_min, rdl_max, show_limit=True, show_3sigma=False,
    show_4sigma=False, show_6sigma=False, show_normal=False,
    show_kde=False, site_col=None
):
    """薄包装：从 DataFrame 提取 site 数据后委托 _render_histogram_payload。

    （主进程串行兜底路径保留此签名；并行路径直接用 _render_histogram_payload。）
    """
    site_values = None
    site_series = None
    if site_col and site_col in df.columns:
        site_series_raw = df[site_col]
        if isinstance(site_series_raw, pd.DataFrame):
            site_series_raw = site_series_raw.iloc[:, 0]
        site_values = sorted(site_series_raw.dropna().unique(), key=lambda x: (isinstance(x, float), x))
        site_series = site_series_raw.to_numpy()
    return _render_histogram_payload(
        selected_param, data_series.to_numpy(), site_values, site_series,
        mean_val, std_val, rdl_min, rdl_max,
        show_limit=show_limit, show_3sigma=show_3sigma,
        show_4sigma=show_4sigma, show_6sigma=show_6sigma,
        show_normal=show_normal, show_kde=show_kde,
    )
