"""
Limit resolution service for analysis views.

Resolves lower/upper limits from a range_type string and a stats dict.
This replaces duplicated switch-case logic that previously appeared in
histogram, serial_distribution, site_stats, etc.
"""


def resolve_limits(range_type: str, stats: dict) -> tuple:
    """Resolve lower/upper limits based on range_type.

    Args:
        range_type: One of 'RDL', 'DR', 'CL', 'S3', 'S4', 'S6'.
        stats: Dict with keys 'rdl', 'dr', 'cl', 's3', 's4', 's6',
               each a (lower, upper, gap) tuple from compute_range_statistics.

    Returns:
        (lower, upper) float tuple. Either value may be None if
        range_type is unrecognised.
    """
    if range_type == 'RDL':
        return stats['rdl'][0], stats['rdl'][1]
    elif range_type == 'DR':
        return stats['dr'][0], stats['dr'][1]
    elif range_type == 'CL':
        return stats['cl'][0], stats['cl'][1]
    elif range_type == 'S3':
        return stats['s3'][0], stats['s3'][1]
    elif range_type == 'S4':
        return stats['s4'][0], stats['s4'][1]
    elif range_type == 'S6':
        return stats['s6'][0], stats['s6'][1]
    return None, None
