"""HTML 报告用的图表构建器（matplotlib Agg）。

约束（与 chart_workers 同族）：本模块**不得 import Django/DB**，入参全为
可 pickle 的标量/列表；字族统一走 ``fonts.apply_matplotlib_fonts()``，本模块
不自设 sans-serif 候选列表（源码扫描测试会红，见 test_export_fonts）。

每个 render_* 返回 PNG ``bytes``（无数据时返回 ``b''``，调用方据此跳过）。
"""

import io

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

from apps.export.charts import (
    COLORS_SITE_8, COLOR_LSL, COLOR_NORMAL, EXPORT_DPI_DEFAULT,
)
from apps.export.fonts import apply_matplotlib_fonts

_COLOR_BAR = '#1E88E5'


def _save(fig, dpi):
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=dpi, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()


def render_bin_pareto_payload(labels, counts, dpi=EXPORT_DPI_DEFAULT) -> bytes:
    """Bin Pareto：降序柱 + 累计百分比折线。"""
    if not counts:
        return b''
    apply_matplotlib_fonts()
    pairs = sorted(zip(labels, counts), key=lambda x: x[1], reverse=True)
    xs = [str(lbl) for lbl, _ in pairs]
    ys = [float(c) for _, c in pairs]
    total = float(sum(ys)) or 1.0
    cum = np.cumsum(ys) / total * 100.0

    fig, ax = plt.subplots(figsize=(8, 3.6))
    fig.patch.set_facecolor('white')
    ax.bar(xs, ys, color=_COLOR_BAR, alpha=0.8, edgecolor='white')
    ax.set_ylabel('数量', fontsize=10)
    ax.grid(True, axis='y', alpha=0.3)
    ax.tick_params(labelsize=8)

    ax2 = ax.twinx()
    ax2.plot(xs, cum, color=COLOR_LSL, marker='o', linewidth=2, markersize=4, label='累计%')
    ax2.set_ylim(0, 105)
    ax2.yaxis.set_major_formatter(ticker.FormatStrFormatter('%.0f%%'))
    ax2.tick_params(labelsize=8)
    ax2.legend(fontsize=8, loc='lower right')
    plt.tight_layout()
    return _save(fig, dpi)


def render_site_yield_payload(sites, yields, overall=None,
                             dpi=EXPORT_DPI_DEFAULT) -> bytes:
    """Site 良率：柱 + 整体良率参考线。"""
    if not sites:
        return b''
    apply_matplotlib_fonts()
    fig, ax = plt.subplots(figsize=(8, 3.4))
    fig.patch.set_facecolor('white')
    xs = [str(s) for s in sites]
    ys = [float(y) for y in yields]
    ax.bar(xs, ys, color=COLORS_SITE_8[:len(xs)] or _COLOR_BAR, alpha=0.8, edgecolor='white')
    if overall is not None:
        ax.axhline(float(overall), color=COLOR_NORMAL, linewidth=1.8, linestyle='--',
                   label=f'整体 {float(overall):.2f}%')
        ax.legend(fontsize=8, loc='lower right')
    ax.set_ylabel('良率 (%)', fontsize=10)
    ax.set_ylim(0, 105)
    ax.grid(True, axis='y', alpha=0.3)
    ax.tick_params(labelsize=8)
    plt.tight_layout()
    return _save(fig, dpi)


def render_bin_site_heatmap_payload(row_labels, col_labels, matrix,
                                    dpi=EXPORT_DPI_DEFAULT) -> bytes:
    """Bin×Site 热力图（仅 Fail Bin）：色深 = 该行内的集中度。

    matrix[i][j] = 第 i 行第 j 列计数；行内占比决定色深。
    """
    if not row_labels or not col_labels:
        return b''
    apply_matplotlib_fonts()
    data = np.array(matrix, dtype=float)
    row_sums = data.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    intensity = data / row_sums

    fig, ax = plt.subplots(figsize=(1.1 + 0.8 * len(col_labels),
                                    0.9 + 0.5 * len(row_labels)))
    fig.patch.set_facecolor('white')
    im = ax.imshow(intensity, cmap='Reds', aspect='auto', vmin=0, vmax=1)
    ax.set_xticks(range(len(col_labels)))
    ax.set_xticklabels([str(c) for c in col_labels], fontsize=8)
    ax.set_yticks(range(len(row_labels)))
    ax.set_yticklabels([str(r) for r in row_labels], fontsize=8)
    for i in range(len(row_labels)):
        for j in range(len(col_labels)):
            ax.text(j, i, f'{int(data[i, j])}', ha='center', va='center',
                    fontsize=7, color='#212121')
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02).ax.tick_params(labelsize=7)
    plt.tight_layout()
    return _save(fig, dpi)


def render_yield_trend_payload(labels, yields, dpi=EXPORT_DPI_DEFAULT) -> bytes:
    """批次良率趋势折线。"""
    if not labels:
        return b''
    apply_matplotlib_fonts()
    fig, ax = plt.subplots(figsize=(8, 3.2))
    fig.patch.set_facecolor('white')
    xs = [str(x) for x in labels]
    ys = [float(y) for y in yields]
    ax.plot(xs, ys, color=COLOR_NORMAL, marker='o', linewidth=2, markersize=4)
    ax.set_ylabel('良率 (%)', fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.tick_params(axis='x', rotation=45, labelsize=7)
    ax.tick_params(axis='y', labelsize=8)
    plt.tight_layout()
    return _save(fig, dpi)
