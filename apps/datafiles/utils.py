import os
import re

from django.conf import settings

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
    """Return the product-code token found in ``text``.

    ``text`` is split on ``_`` and each token is tested against
    ``_PRODUCT_CODE_TOKEN``. **Whole-token matches win**: a token that is
    exactly a product code (``BPD93204``) is returned immediately, before a
    prefix of it that merely *starts* like one. Without a whole-token match
    the first partial match is used — the trailing characters after the
    captured prefix are treated as unrelated (e.g. ``BPD80350XBAD`` from
    ``BPD80350XBAD-FB``, or the ``BP01`` inside ``BP01-2605220057`` when no
    real product code is present). Returns ``''`` when ``text`` is empty or
    no token matches.

    Why precedence matters (real filenames):
        ``C01Q_BP01-2605220057_BPD93204_...``  -> ``BPD93204`` (whole token),
        NOT ``BP01`` — the BP01-... token is a batch marker whose regex
        prefix would otherwise win by position.
        ``BPC61320A_FT_AAA_BPD60320XBAF_PD.cpts`` -> ``BPC61320A`` (first
        whole token), NOT the longer ``BPD60320XBAF`` suffix.

    Used for both data filenames and test-program basenames so the same
    rule applies to every source.
    """
    if not text:
        return ''
    partial = ''
    for token in text.split('_'):
        match = _PRODUCT_CODE_TOKEN.match(token)
        if not match:
            continue
        code = match.group(1)
        if code == token:
            return code  # whole-token match — unambiguous, take it
        if not partial:
            partial = code
    return partial


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


def resolve_file_path(raw: str) -> str:
    """``DataFile.file_path`` / ``ParseHistory.filepath`` → 绝对磁盘路径。

    双格式容忍：绝对路径（2026-08-21 前的遗留格式）原样透传；相对路径
    （新格式，相对 MEDIA_ROOT，如 ``data/<user>/<type>/x.csv``）按
    ``settings.MEDIA_ROOT`` 解析为绝对路径。空值原样返回。

    所有读侧消费方（存在性检查、解析、删除、mtime 缓存 key）必须先经过
    本函数，DB 中相对/绝对混存时行为一致。
    """
    if not raw:
        return raw
    if os.path.isabs(raw):
        return raw
    return os.path.normpath(os.path.join(str(settings.MEDIA_ROOT), raw))


def store_file_path(abs_path: str) -> str:
    """写库前的路径规范化：MEDIA_ROOT 之下存相对路径，之外保持绝对路径。

    相对格式为 ``data/<user>/<file_type>/...``（不带 ``media/`` 前缀），
    使数据目录（data_dir）可整体迁移而 DB 记录无需重写——2026-08-21
    起新记录一律相对化，迁移时由 system_config 自动把存量绝对路径
    重写为相对。

    边界：跨盘（``os.path.relpath`` 抛 ValueError）或位于 MEDIA_ROOT
    之外（如样例目录）的路径无法用相对路径表达，保持绝对路径原样。
    """
    norm = os.path.normpath(abs_path)
    media = os.path.normpath(str(settings.MEDIA_ROOT))
    try:
        rel = os.path.relpath(norm, media)
    except ValueError:
        return norm  # 跨盘（如 C: 与 D: 之间）
    if rel == '..' or rel.startswith('..' + os.sep):
        return norm  # 在 MEDIA_ROOT 之外
    return rel


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
        ``C01Q_BP01-2605220057_BPD93204__H0GG80#AAA12605220057__R2605230015_ETS165943_05242026.csv``
                                    -> ``BPD93204`` (the whole token wins over
                                    the ``BP01`` prefix of the batch marker)

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
