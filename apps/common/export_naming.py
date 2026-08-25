"""Export filename template rendering.

Templates NEVER include the extension — the extension is appended based on the
export_type (and format, e.g. batch_charts xlsx/pptx). Each user configures
per-export-type templates in System Settings (UserSetting.export_filename_templates).

Rules:
- Missing/empty template → built-in default for the type.
- Known variables are replaced; unknown/misspelled placeholders are kept as-is
  (visible self-diagnosis in the filename).
- Windows-invalid characters are sanitized to "_".
- Rendered-empty results fall back to the default template.
"""

import re

from django.utils import timezone

EXPORT_TEMPLATE_DEFAULTS: dict[str, str] = {
    'to_excel': '{filename}_analysis',
    'to_csv': '{filename}_data',
    'sigma_limit': '{filename}_{sigma}sigma_Limit',
    'html_report': '{filename}_report',
    'batch_charts': '{filename}_batch_charts',
    'batch_report': 'Batch_Report_{datetime}',
    'buyoff': 'Buyoff_Form_{datetime}',
    'gage': 'Gage_Summary_{datetime}',
    'file_correlation': '{file1}_vs_{file2}_correlation',
}

# Variables available per export type (mirrored in frontend/src/constants/export-templates.ts)
EXPORT_TEMPLATE_VARIABLES: dict[str, tuple[str, ...]] = {
    'to_excel': ('filename', 'date', 'time', 'datetime', 'user'),
    'to_csv': ('filename', 'date', 'time', 'datetime', 'user'),
    'sigma_limit': ('filename', 'sigma', 'date', 'time', 'datetime', 'user'),
    'html_report': ('filename', 'date', 'time', 'datetime', 'user'),
    'batch_charts': ('filename', 'date', 'time', 'datetime', 'user'),
    'batch_report': ('batch_name', 'file_count', 'date', 'time', 'datetime', 'user'),
    'buyoff': ('file_count', 'date', 'time', 'datetime', 'user'),
    'gage': ('file_count', 'date', 'time', 'datetime', 'user'),
    'file_correlation': ('file1', 'file2', 'date', 'time', 'datetime', 'user'),
}

MAX_TEMPLATE_LENGTH = 200

# Windows-invalid filename chars + control chars; must stay in sync with
# frontend/src/utils/download.ts sanitizeFilename().
_INVALID_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_VAR_RE = re.compile(r'\{(\w+)\}')


def sanitize_filename_part(value: str, replacement: str = '_') -> str:
    """Clean a filename part: replace Windows-invalid/control chars, strip
    whitespace and trailing dots/spaces."""
    return _INVALID_CHARS_RE.sub(replacement, value).strip().rstrip('. ')


def resolve_template(template: str, context: dict[str, object],
                     allowed_vars: tuple[str, ...] = ()) -> str:
    """Lenient variable replacement:
    - variable in allowed_vars and in context → value
    - variable in allowed_vars but missing from context → '' (e.g. {sigma}
      used in a type whose view didn't provide sigma)
    - unknown/misspelled placeholders → kept as-is (visible self-diagnosis)
    """
    allowed = set(allowed_vars)

    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name in allowed:
            return str(context[name]) if name in context else ''
        return m.group(0)

    return _VAR_RE.sub(repl, template)


def base_export_context(user, now=None) -> dict[str, str]:
    """Common variables: username + date(YYYYMMDD) + time(HHMMSS) +
    datetime(YYYYMMDD_HHMMSS), in Asia/Shanghai local time."""
    local = timezone.localtime(now or timezone.now())
    return {
        'user': user.username,
        'date': local.strftime('%Y%m%d'),
        'time': local.strftime('%H%M%S'),
        'datetime': local.strftime('%Y%m%d_%H%M%S'),
    }


def render_export_filename(user, export_type: str, extension: str,
                           context: dict[str, object]) -> str:
    """Single entry point: user template (or default) rendered + sanitized,
    with extension appended (deduped if the template already ends with it)."""
    from apps.accounts.models import UserSetting  # local import avoids cycles

    settings, _ = UserSetting.objects.get_or_create(user=user)
    templates = settings.export_filename_templates or {}
    template = templates.get(export_type) or EXPORT_TEMPLATE_DEFAULTS.get(export_type, 'export')

    allowed = EXPORT_TEMPLATE_VARIABLES.get(export_type, ())
    rendered = sanitize_filename_part(resolve_template(template, context, allowed))
    if not rendered:
        default = EXPORT_TEMPLATE_DEFAULTS.get(export_type, 'export')
        rendered = sanitize_filename_part(resolve_template(default, context, allowed))

    ext = extension.lstrip('.')
    if not rendered.lower().endswith('.' + ext):
        rendered = f'{rendered}.{ext}'
    return rendered
