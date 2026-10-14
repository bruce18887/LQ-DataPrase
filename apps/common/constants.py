"""跨应用共享常量（无 Django 依赖，可被解析器/统计/导出安全引用）。"""

# 限值字符串中的非数值占位（'min'/'max' 类关键字按数据边界解析，不在此列）
NON_NUMERIC_KEYWORDS = ['min', 'max', 'lower limit', 'upper limit', 'n/a', 'na', '-', 'none']

# 「默认每页行数」= 查看数据表格的 ag-grid IRM 块大小。这是**唯一事实源**，四方引用它：
# 账号写入侧校验（apps/accounts/serializers.py）、查看数据执行侧钳位
# （apps/datafiles/views/browse_views.py）、设置页下拉端点（TableSettingsForm.vue）、
# 前端块大小上下界（DataBrowserAgGrid.vue）。上下界必须一致 —— 校验域与执行域脱钩
# 曾让 browse 自钳到 100000（比合法设置域宽 200 倍）。
# 前端两份是 TS 字面量、无法 import 本模块，由 test/backend/test_page_size_bounds.py
# 的源码扫描用例钉住（先例 apps/export/tests_chart_dpi.py）。
# 过小会把滚动变成请求风暴；过大在百兆局域网上一屏传不完。
PAGE_SIZE_MIN = 50
PAGE_SIZE_MAX = 500
