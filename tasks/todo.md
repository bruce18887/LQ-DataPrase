# Django 性能审计修复计划

## 问题 1: DataBrowserView 全表扫描 + bug
- **Bug:** 第 215 行 `parser.get_bin_column_name()` 引用了未定义的变量 `parser`，调用时抛 NameError
- **性能:** 全部加载 df → detect_fail_data → 全部 to_dict → 过滤 → 分页。应改为：pandas 级别过滤 → iloc 切片 → 按页转字典
- **修复:** 用 `get_parser(datafile.format_type).get_bin_column_name()` 修复 bug；重写分页流程

## 问题 2: 废弃代码 — views.py 重复方法
- 4 个方法被后面的同名方法覆盖，移除第一组: `correlation_matrix`, `bin_trend`, `boxplot`, `param_trend`
- 连带更新 import 语句（移除不再被旧方法使用的导入）

## 问题 3: 废弃代码 — statistics.py 重复函数
- 4 个函数被后面的同名函数覆盖，移除第一组: `compute_correlation_matrix`, `compute_bin_trend`, `compute_boxplot_stats`, `compute_param_trend`

## 问题 4: clean_data 递归 NaN 序列化
- 在 21 个地方调用，递归遍历整个响应树
- 改为在每个端点源头做 `.replace({np.nan: None})`，然后移除 `clean_data()`

## 问题 5: POST → GET 幂等端点
- 15+ 个 @action 端点改为 methods=['get']，前端使用 query_params
- 需要确认前端已适配或暂时标记兼容

## 验证
- 运行测试
- 检查语法
