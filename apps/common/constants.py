"""跨应用共享常量（无 Django 依赖，可被解析器/统计/导出安全引用）。"""

# 限值字符串中的非数值占位（'min'/'max' 类关键字按数据边界解析，不在此列）
NON_NUMERIC_KEYWORDS = ['min', 'max', 'lower limit', 'upper limit', 'n/a', 'na', '-', 'none']
