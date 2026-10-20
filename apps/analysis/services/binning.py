"""Shared histogram bin grid.

Both the single-file histogram and the multi-file distribution chart must use
the same 25 inner edges / 24 normal bins / underflow+overflow layout. The grid
is centred on ``[bin_min, bin_max]`` (two sub-bins on each side) so the two
endpoints stay pixel-aligned.
"""

from apps.analysis.services.statistics.helpers import safe_gap


def build_bin_grid(bin_min, bin_max, *, round_centers=False):
    """Return ``(inner_edges, bin_centers, data_gap)`` for a histogram.

    ``round_centers=True`` is used by multi-lot because its ``bar_data`` is
    paired with ``bin_centers`` in the same array; the single-file histogram
    rounds only when serialising the response.
    """
    data_gap = safe_gap(bin_min, bin_max)
    bin_start = bin_min - 2 * data_gap
    inner_edges = [bin_start + j * data_gap for j in range(25)]
    bin_centers = [inner_edges[0] - data_gap]
    bin_centers += [(inner_edges[i] + inner_edges[i + 1]) / 2 for i in range(24)]
    bin_centers.append(inner_edges[-1] + data_gap)
    if round_centers:
        bin_centers = [round(c, 6) for c in bin_centers]
    return inner_edges, bin_centers, data_gap
