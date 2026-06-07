import re

# Matches a product-code token: 'B' + 1-2 uppercase letters + a run of digits.
# Only the 'B<letters><digits>' prefix is captured, so trailing suffixes such as
# the 'R3CYCAA' in 'BN281R3CYCAA' are dropped.
_PRODUCT_CODE_TOKEN = re.compile(r'^(B[A-Z]{1,2}\d+)')


def extract_product_code(filename: str) -> str:
    """Extract the product-code prefix from a data filename.

    The product code looks like 'B' + one or two uppercase letters + digits.
    It is usually (but not always) the first underscore-separated token; some
    files prefix it with an unrelated token (e.g. 'DA35_'), so we scan every
    underscore-separated token and return the first one that matches.

    Examples (from real seeded filenames):
        'BPD60320_FT.csv'                                 -> 'BPD60320'
        'BPD60320_C01F40#AAA12603030006_FT1-...'          -> 'BPD60320'
        'DA35_BPC50338_CL08D4.01#AEA3_414A07_...'         -> 'BPC50338'
        'BN281R3CYCAA_2604160006_TTTA803100.03_...'       -> 'BN281'
        'BPD93204_FT1_ETS163550_12252024.csv'             -> 'BPD93204'
        'gage_m_S1.csv'                                   -> ''  (no match)
    """
    if not filename:
        return ''
    for token in filename.split('_'):
        match = _PRODUCT_CODE_TOKEN.match(token)
        if match:
            return match.group(1)
    return ''
