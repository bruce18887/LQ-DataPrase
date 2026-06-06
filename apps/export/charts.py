"""Chart generation utilities for export."""

import io
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

COLORS_SITE_8 = ['#E53935', '#1E88E5', '#43A047', '#F9A825', '#8E24AA', '#00ACC1', '#F57C00', '#D81B60']
COLOR_LSL = '#C62828'
COLOR_USL = '#C62828'
COLOR_SIGMA_3 = '#1565C0'
COLOR_SIGMA_4 = '#00838F'
COLOR_SIGMA_6 = '#E65100'
COLOR_NORMAL = '#F57F17'


def _get_export_dpi():
    return 150


def _create_histogram_chart(
    df, metadata, selected_param, data_series, mean_val, std_val,
    rdl_min, rdl_max, show_limit=True, show_3sigma=False,
    show_4sigma=False, show_6sigma=False, show_normal=False, site_col=None
):
    """Ported from old project: create matplotlib histogram with site grouping."""
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False

    if len(data_series) == 0:
        return io.BytesIO()

    param_low_limit = rdl_min if rdl_min is not None else float(data_series.min())
    param_high_limit = rdl_max if rdl_max is not None else float(data_series.max())

    data_gap = (param_high_limit - param_low_limit) / 20 if (param_high_limit - param_low_limit) > 0 else 1.0
    x_labels = [param_low_limit + (i - 2) * data_gap for i in range(25)]
    bin_start = param_low_limit - 2.5 * data_gap
    all_bins = np.array([bin_start + j * data_gap for j in range(26)])

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

    if site_col and site_col in df.columns:
        site_values = sorted(df[site_col].dropna().unique(), key=lambda x: (isinstance(x, float), x))
        n_sites = len(site_values)
        bar_width = data_gap * 0.8 / n_sites
        site_df = df[[site_col, selected_param]].copy()
        site_col_1d = site_df[site_col]
        if isinstance(site_col_1d, pd.DataFrame):
            site_col_1d = site_col_1d.iloc[:, 0]
        site_df[selected_param] = pd.to_numeric(site_df[selected_param], errors='coerce')
        grouped = site_df.groupby(site_col_1d)

        for idx, site in enumerate(site_values):
            if site in grouped.groups:
                sdata = grouped.get_group(site)[selected_param].dropna()
            else:
                sdata = pd.Series(dtype=float)
            total = len(sdata)
            hist, _ = np.histogram(sdata, bins=all_bins)
            hist_percent = [round((count / total) * 100, 2) if total > 0 else 0 for count in hist]
            bar_data = [hist_percent[i] if i < len(hist_percent) else 0 for i in range(25)]
            offset = (idx - n_sites / 2 + 0.5) * bar_width
            bar_x = [x_labels[i] + offset for i in range(25)]

            ax.bar(
                bar_x, bar_data, width=bar_width * 0.9,
                color=colors[idx % len(colors)], alpha=0.7,
                label=f'Site{site}%', edgecolor='white', linewidth=0.5
            )
    else:
        data_clean = data_series
        hist, _ = np.histogram(data_clean, bins=all_bins)
        total = len(data_clean)
        hist_percent = [round((count / total) * 100, 2) if total > 0 else 0 for count in hist]
        bar_data = [hist_percent[i] if i < len(hist_percent) else 0 for i in range(25)]
        ax.bar(x_labels, bar_data, width=data_gap * 0.9, color='#1E88E5', alpha=0.7, label='数据分布', edgecolor='white', linewidth=0.5)

    if show_limit and rdl_min is not None:
        ax.axvline(x=param_low_limit, color=COLOR_LSL, linewidth=2.5, linestyle='--')
    if show_limit and rdl_max is not None:
        ax.axvline(x=param_high_limit, color=COLOR_USL, linewidth=2.5, linestyle='--')

    for sigma, flag, color, label_prefix in [
        (3, show_3sigma, COLOR_SIGMA_3, '3σ'), (4, show_4sigma, COLOR_SIGMA_4, '4σ'), (6, show_6sigma, COLOR_SIGMA_6, '6σ')
    ]:
        if flag and std_val > 0:
            lower = mean_val - sigma * std_val
            upper = mean_val + sigma * std_val
            ax.axvline(x=lower, color=color, linewidth=2, linestyle=':')
            ax.axvline(x=upper, color=color, linewidth=2, linestyle=':')

    if show_normal and std_val > 0:
        x_pdf = np.linspace(x_labels[0], x_labels[-1], 200)
        pdf_values = (1 / (std_val * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x_pdf - mean_val) / std_val) ** 2)
        max_pdf = np.max(pdf_values)
        if max_pdf > 0:
            normal_scaled = pdf_values / max_pdf * y_max_plot
            ax.plot(x_pdf, normal_scaled, color=COLOR_NORMAL, linewidth=3, label='正态分布')

    ax.set_ylabel('百分比 (%)', fontsize=12)
    ax.set_ylim(0, y_max_plot)
    ax.set_xlim(float(x_labels[0]), float(x_labels[-1]))
    ax.set_xticks(x_labels)
    ax.xaxis.set_major_formatter(ticker.FormatStrFormatter('%.4f'))
    ax.tick_params(axis='x', rotation=45, labelsize=6)
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter('%.0f%%'))
    ax.grid(True, alpha=0.3)

    if show_limit and rdl_min is not None:
        _add_vline_label(ax, param_low_limit, 'LSL', COLOR_LSL)
    if show_limit and rdl_max is not None:
        _add_vline_label(ax, param_high_limit, 'USL', COLOR_USL)

    for sigma, flag, color, label_prefix in [
        (3, show_3sigma, COLOR_SIGMA_3, '3σ'), (4, show_4sigma, COLOR_SIGMA_4, '4σ'), (6, show_6sigma, COLOR_SIGMA_6, '6σ')
    ]:
        if flag and std_val > 0:
            lower = mean_val - sigma * std_val
            upper = mean_val + sigma * std_val
            _add_vline_label(ax, lower, f'{label_prefix}下限', color)
            _add_vline_label(ax, upper, f'{label_prefix}上限', color)

    ax.legend(fontsize=8, loc='upper center', bbox_to_anchor=(0.5, -0.2), ncol=4)
    ax.set_title(selected_param, fontsize=14, fontweight='bold', color='#0066cc', pad=15)
    plt.tight_layout()

    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', dpi=_get_export_dpi(), bbox_inches='tight')
    plt.close(fig)
    img_buffer.seek(0)
    return img_buffer
