"""Regression tests for the histogram service.

Focus: ``site_histograms`` is populated for every file that has a Site
column, including the single-site case. Previously the backend returned
``site_histograms: None`` for files with only one unique site, so the
front-end histogram had to label the lone bar as "数据分布" instead of
"Site1" — confusing the user. The 2026-06-07 fix removes the
``> 1`` guard on ``site_idx.unique()``; these tests lock in the
behaviour so a future refactor cannot silently regress it.
"""
import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.services.data_services import compute_histogram_stats


def _make_df(n: int, sites: list[int], seed: int = 0) -> pd.DataFrame:
    """Build a tiny DataFrame with a Site column and a numeric param."""
    rng = np.random.default_rng(seed)
    # Repeat the site list to get `n` rows, then take the first n.
    sites_full = (sites * (n // len(sites) + 1))[:n]
    return pd.DataFrame({
        'Site': [str(s) for s in sites_full],
        'Param1': rng.normal(0, 1, n).tolist(),
    })


def _meta(format_type: str = 'CTA8290D') -> dict:
    return {'format': format_type, 'unit': 'mV'}


class SiteHistogramsTests(SimpleTestCase):
    """``site_histograms`` must be present whenever a Site column exists."""

    def test_multi_site_populates_per_site_keys(self):
        df = _make_df(200, [1, 2, 3, 4])
        out = compute_histogram_stats(df, _meta(), 'Param1', 'Site')
        self.assertIsInstance(out['site_histograms'], dict)
        self.assertEqual(
            set(out['site_histograms'].keys()), {'1', '2', '3', '4'}
        )
        # Each site's bin list has the same length as bin_centers.
        bin_count = len(out['bin_centers'])
        for site, hist in out['site_histograms'].items():
            self.assertEqual(
                len(hist), bin_count, f'site {site} bin count mismatch'
            )

    def test_single_site_populates_one_key(self):
        # Regression: previously returned site_histograms=None and the
        # front-end mis-labelled the only site as "数据分布".
        df = _make_df(200, [1])
        out = compute_histogram_stats(df, _meta(), 'Param1', 'Site')
        self.assertIsInstance(out['site_histograms'], dict)
        self.assertEqual(set(out['site_histograms'].keys()), {'1'})
        self.assertEqual(len(out['site_histograms']['1']), len(out['bin_centers']))

    def test_no_site_column_keeps_none(self):
        # When the file has no Site column at all, site_histograms stays
        # None and the front-end falls back to the "数据分布" label — this
        # is the only legitimate "no per-site data" case.
        df = _make_df(200, [1])  # has a Site column
        df = df.drop(columns=['Site'])
        out = compute_histogram_stats(df, _meta(), 'Param1', site_col=None)
        self.assertIsNone(out['site_histograms'])

    def test_single_site_percentages_sum_to_about_100(self):
        # Same denominator (total_count = all sites) as multi-site case.
        df = _make_df(300, [1])
        out = compute_histogram_stats(df, _meta(), 'Param1', 'Site')
        site_sum = sum(out['site_histograms']['1'])
        # Allow a small tolerance for overflow/underflow bins and rounding.
        self.assertGreater(site_sum, 95.0)
        self.assertLess(site_sum, 100.05)
