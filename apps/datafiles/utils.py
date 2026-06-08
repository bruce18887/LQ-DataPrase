import os
import re

# Matches a product-code token: 'B' + 1-2 uppercase letters + a run of digits,
# optionally followed by an alphanumeric suffix that continues the product
# code (e.g. the 'R3CYCAA' in 'BN281R3CYCAA'). The whole token is captured
# because the trailing characters are still part of the canonical product
# code — tester programs reuse the same suffix across runs.
_PRODUCT_CODE_TOKEN = re.compile(r'^(B[A-Z]{1,2}\d+[A-Z0-9]*)')

# Test program file extensions. The CSV header for every supported tester
# exposes a "test program name" (TestFile / TestFileName / Data Sheet File /
# Program:) that always points at a file with one of these extensions.
# ``.cpts`` is the Chroma compound test-program spec emitted by CTA-series
# testers (e.g. ``BPC61320A_FT_AAA_BPD60320XBAF_PD.cpts``); without it the
# product code in such headers (``BPC61320A``) was silently dropped.
_TEST_PROGRAM_EXTS = ('.pts', '.pgs', '.pds', '.cpts')


def _match_product_code(text: str) -> str:
    """Return the first B-prefix product-code token found in ``text``.

    ``text`` is split on ``_`` and each token is tested against
    ``_PRODUCT_CODE_TOKEN``. Returns ``''`` when ``text`` is empty or no
    token matches. Used for both data filenames and test-program basenames
    so the same rule applies to every source.
    """
    if not text:
        return ''
    for token in text.split('_'):
        match = _PRODUCT_CODE_TOKEN.match(token)
        if match:
            return match.group(1)
    return ''


def _program_basename(program_name: str) -> str:
    """Return the basename of ``program_name`` if it ends in a recognised
    test-program extension (.pts/.pgs/.pds), otherwise ``''``.

    The caller is expected to feed the result back into
    ``_match_product_code`` to extract the actual product code — this
    function only normalises the path and strips the extension.
    """
    if not program_name:
        return ''
    base = os.path.basename(program_name.strip())
    if not base:
        return ''
    lower = base.lower()
    for ext in _TEST_PROGRAM_EXTS:
        if lower.endswith(ext):
            return os.path.splitext(base)[0]
    return ''


def extract_product_code(filename: str, program_name: str = '') -> str:
    """Extract the product-code token from a data filename or its CSV header.

    Preferred source: the **data filename**. The B-prefix token regex
    handles the common shapes directly:
        ``BPD60320_FT.csv``         -> ``BPD60320``
        ``BPD60320_QA1.csv``        -> ``BPD60320``
        ``DA35_BPC50338_...csv``    -> ``BPC50338``
        ``BPD93204_FT1_...csv``     -> ``BPD93204``
        ``BN281R3CYCAA_...csv``     -> ``BN281R3CYCAA`` (full token, including
                                                    alphanumeric suffix)

    Fallback: if the data filename does **not** expose a B-prefix token
    (e.g. STS8200 device data named ``2604160006_x.csv``), the function
    scans the CSV test-program name (``.pts``/``.pgs``/``.pds`` basename)
    for the same pattern. Examples:
        ``2604160006_x.csv`` + ``BN281.pts``        -> ``BN281``
        ``2604160006_x.csv`` + ``BN281.pgs``        -> ``BN281``

    If neither source yields a match the function returns ``''``. We never
    return the raw program-name basename (``BPC50338_FT_SAB_BPC50338XBAC_EN``)
    because that string concatenates the product code with the test stage /
    handler / hardware suffix and is not a stable product identifier.

    Examples (from real seeded filenames + parsed program names):
        filename='BPD60320_FT.csv',  program_name='BPD60320.pts'           -> 'BPD60320'
        filename='BPD60320_QA1.csv', program_name='BPD60320.pgs'           -> 'BPD60320'
        filename='DA35_BPC50338_...',
            program_name='BPC50338_FT_SAB_BPC50338XBAC_EN.pts'              -> 'BPC50338'
        filename='BN281R3CYCAA_2604160006_...',
            program_name='JAVBN281R3CYCAAV1.6.pgs'                         -> 'BN281R3CYCAA'
        filename='BPD93204_FT1_ETS163550.csv',
            program_name='BPD93204.pts'                                    -> 'BPD93204'
        filename='BPD60320_FT.csv', program_name=''                        -> 'BPD60320'
        filename='2604160006_x.csv', program_name='BN281.pts'              -> 'BN281'
        filename='random.csv', program_name=''                             -> ''
        filename='BPD60320_FT.csv', program_name='nope.csv'                -> 'BPD60320' (ext mismatch → filename wins)
    """
    # 1. The data filename is the primary source — the B-prefix regex
    #    already covers every shape we see in production data.
    code = _match_product_code(filename)
    if code:
        return code

    # 2. Fall back to the CSV test-program name (only recognised
    #    .pts/.pgs/.pds extensions — any other string is treated as
    #    "no program name available"). The same B-prefix regex is then
    #    applied to the basename so trailing suffixes
    #    (e.g. ``_FT_SAB_BPC50338XBAC_EN``) collapse to the leading
    #    product code.
    base = _program_basename(program_name)
    if base:
        return _match_product_code(base)
    return ''
