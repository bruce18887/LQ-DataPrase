"""导出物的字族单一来源：Excel 工作簿、图表 PNG、HTML 报告共用一份口径。

刻意与配色模块分开存放：``excel_theme``（buyoff/Gage）与 ``excelize_helpers``
（batch_report/sigma-limit/数据导出）两家的配色被明确要求不得混用，字族却是
**三套通道共同**的问题 —— 改动前同一份报告里同时出现 Calibri、等线、Arial。
"""

# 拉丁/数字用 Calibri：Excel 表格里数字宽窄最紧凑，中文字符交给 Excel 的
# 主题回退（原生行为）。等线与 Arial 属于历史上的就地字面量，已收敛到这里。
EXCEL_FONT_FAMILY = "Calibri"

# 按**可用性**排序，不按设计偏好：SimHei 居首是为了让已生成的 PNG 观感不变
# （提到雅黑前面会改变既有报告的字形）。SimSun 垫在 DejaVu 之前兜底 ——
# Win10/11 把黑体改成了「按需功能」，缺字时至少还有宋体，不至于渲染成方块。
MATPLOTLIB_SANS_SERIF = ['SimHei', 'Microsoft YaHei', 'SimSun', 'DejaVu Sans']

# 与 frontend/src/styles/design-tokens.css 的 --font-sans 同值（那份是唯一事实
# 来源，改那边要同步这边；e2e 的 fonts.spec.ts 断言的是前端那份）。
# HTML 报告正文曾写裸 Arial，中文没有 CJK 回退。
HTML_FONT_STACK = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', "
    "'Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans CJK SC', "
    "'Source Han Sans SC', 'Helvetica Neue', Arial, sans-serif"
)


def apply_matplotlib_fonts():
    """把统一字族应用到 matplotlib。幂等，供各图表渲染入口调用。

    matplotlib 在函数内就地改全局 rcParams 是这个项目的既有写法；这里把
    两份互不相同的候选列表收成一份，调用点只留一行。
    """
    from matplotlib import pyplot as plt

    plt.rcParams['font.sans-serif'] = list(MATPLOTLIB_SANS_SERIF)
    plt.rcParams['axes.unicode_minus'] = False
