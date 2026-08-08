"""PPTX builder for batch charts export.

Extracted from views.py ``_batch_charts_pptx``.  Uses matplotlib for
histogram generation and python-pptx for slide assembly.
"""

import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from pptx import Presentation
from pptx.util import Inches

from apps.analysis.services.statistics import (
    compute_cpk, compute_range_statistics, get_1d_from, filter_finite,
)
from apps.export.charts import build_histogram_bins


def build_batch_charts_pptx(datafile, df, metadata, params):
    """Build batch charts PPTX with histogram slides.

    For each parameter in *params* a matplotlib histogram is rendered
    (showing LSL/USL dashed lines and optional 6-sigma dotted lines)
    and embedded into a blank PPTX slide.

    Parameters
    ----------
    datafile : DataFile
        Used only for filename generation (by the caller).
    df : pd.DataFrame
    metadata : dict
    params : list of str
        Parameter (column) names to chart.

    Returns
    -------
    bytes
        Serialized PPTX content.
    """
    prs = Presentation()
    # blank layout
    blank_layout = prs.slide_layouts[6]

    # Chinese font support
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

    for param in params:
        if param not in df.columns:
            continue
        data_series = filter_finite(get_1d_from(df, param))
        if len(data_series) == 0:
            continue

        stats = compute_range_statistics(data_series, metadata, param)
        cpk_result = compute_cpk(
            stats['mean'], stats['std'], stats['rdl'][0], stats['rdl'][1]
        )
        cpk_val = cpk_result['cpk']
        cpk_level = cpk_result.get('cpk_color', 'gray')

        # Create matplotlib chart
        fig, ax = plt.subplots(figsize=(8, 4.5))
        rdl_min, rdl_max, _ = stats['rdl']
        # 分箱与屏幕/Excel 导出保持一致（/20），避免 PPT 图与审阅画面形状不一致
        bins, _ = build_histogram_bins(rdl_min, rdl_max)
        ax.hist(data_series.dropna(), bins=bins, color='#1E88E5', edgecolor='white', alpha=0.85)

        if rdl_min is not None:
            ax.axvline(rdl_min, color='#C62828', linestyle='--', linewidth=2, label='LSL')
        if rdl_max is not None:
            ax.axvline(rdl_max, color='#C62828', linestyle='--', linewidth=2, label='USL')
        if stats.get('s6'):
            ax.axvline(stats['s6'][0], color='#E65100', linestyle=':', linewidth=1.5, label='6σL')
            ax.axvline(stats['s6'][1], color='#E65100', linestyle=':', linewidth=1.5, label='6σU')

        ax.set_title(
            f'{param}  |  CPK={cpk_val:.4f} ({cpk_level})  |  N={len(data_series)}',
            fontsize=11,
        )
        ax.set_xlabel(stats.get('unit', ''))
        ax.set_ylabel('Frequency')
        ax.legend(loc='upper right', fontsize=8)
        fig.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=120)
        buf.seek(0)
        plt.close(fig)

        slide = prs.slides.add_slide(blank_layout)
        left = Inches(0.5)
        top = Inches(0.5)
        slide.shapes.add_picture(buf, left, top, width=Inches(9), height=Inches(5.5))

    buffer = io.BytesIO()
    prs.save(buffer)
    buffer.seek(0)
    return buffer.read()
