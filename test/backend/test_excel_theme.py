"""Excel 输出配色的对比度守门测试。

用户反馈两个模板"对比度不清晰"，根因是白字压在淡彩底上——buyoff 的
``red_result_style`` 用 ``FFFFFF`` 压 ``F5B7B1``，Gage 的 ``warning_style``
干脆把 ``F5B7B1`` 当字体色。这里把 WCAG 相对亮度对比度固化成断言：
配色表里任何"底色 + 字体色"搭配都必须 ≥ 4.5:1（AA 正文阈值）。

纯函数测试，不需要 excelize 句柄。

runner: ``manage.py test test.backend.test_excel_theme``
"""

from django.test import SimpleTestCase

from apps.export import excel_theme as theme

MIN_CONTRAST = 4.5
WHITE = "FFFFFF"


def _channel(value):
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color):
    h = hex_color.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(fg, bg):
    """WCAG 对比度（1.0 ~ 21.0）。"""
    low, high = sorted((_luminance(fg), _luminance(bg)))
    return (high + 0.05) / (low + 0.05)


class ContrastTests(SimpleTestCase):
    def _assert_pair(self, fg, bg, label):
        ratio = contrast(fg, bg)
        self.assertGreaterEqual(
            round(ratio, 2), MIN_CONTRAST,
            f'{label}：字色 #{fg} 压底色 #{bg} 只有 {ratio:.2f}:1，低于 {MIN_CONTRAST}:1')

    def test_header_band(self):
        self._assert_pair(theme.COLOR_HEADER_FONT, theme.COLOR_HEADER_BG, '表头带')

    def test_title_band(self):
        # 标题带是浅灰底 + 深字（不是深底白字）
        self._assert_pair(theme.COLOR_FONT, theme.COLOR_TITLE_BG, '标题带')

    def test_body_text_on_its_backgrounds(self):
        self._assert_pair(theme.COLOR_FONT, theme.COLOR_DATA_BG, '数据格')
        self._assert_pair(theme.COLOR_FONT, theme.COLOR_LABEL_BG, '行名格')
        self._assert_pair(theme.COLOR_FONT_MUTED, theme.COLOR_DATA_BG, '单位行')

    def test_verdict_text_on_white(self):
        # 不铺底时用的语义字色（Gage 表头区的计数/警示）
        for name in ('FONT_PASS', 'FONT_WARN', 'FONT_FAIL', 'FONT_NA'):
            self._assert_pair(getattr(theme, name), WHITE, name)

    def test_verdict_text_on_its_fill(self):
        # 铺底时用的搭配（Buyoff Result 区的条件格式配色）
        self._assert_pair(theme.FONT_ON_PASS, theme.FILL_PASS, '通过底')
        self._assert_pair(theme.FONT_ON_WARN, theme.FILL_WARN, '警示底')
        self._assert_pair(theme.FONT_ON_FAIL, theme.FILL_FAIL, '失败底')
        self._assert_pair(theme.FONT_NA, theme.FILL_NA, 'N/A 底')
