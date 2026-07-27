# 后端代码审查报告

**审查日期**: 2026-06-13
**审查范围**: 全部后端 Python 代码（130 个文件，17,937 行）

---

## 一、项目概览

| 指标 | 数值 |
|------|------|
| Python 文件总数 | 130 个 |
| 代码总行数 | 17,937 行 |
| Django 应用数 | 11 个 |
| 超过 600 行的文件 | 6 个（违规） |
| 无测试覆盖的模块 | 4 个 |
| 死代码函数 | 12+ 个 |
| 重复代码模式 | 8 种 |

---

## 二、违反项目规则的文件（超过 600 行）

| 文件路径 | 行数 | 严重程度 | 建议拆分方案 |
|----------|------|----------|-------------|
| `apps/datafiles/views.py` | **859** | 🔴 高 | 拆分为 `services/upload.py` + `services/file_management.py` + 多个 view 文件 |
| `apps/gage/gage_legacy_builder.py` | **857** | 🔴 高 | 已有重构版本 `gage_summary_builder.py`，应激活并删除旧版 |
| `apps/analysis/services/data_services.py` | **825** | 🟡 中 | 按功能拆分为 `data_loading.py` + `data_transform.py` + `data_validation.py` |
| `apps/analysis/views.py` | **751** | 🟡 中 | 拆分为 `analysis_views.py` + `statistics_views.py`，工具函数移入 common |
| `apps/analysis/services/statistics/analytics.py` | **709** | 🟡 中 | 按分析类型拆分：`histogram.py` + `qqplot.py` + `boxplot.py` + `uph.py` |
| `apps/datafiles/tests.py` | **655** | 🟢 低 | 拆分为 `tests/test_upload.py` + `tests/test_crud.py` + `tests/test_parsers.py` |

---

## 三、死代码清单

### 3.1 未使用的函数/类（高置信度，可安全删除）

| 函数/类 | 文件 | 原因 |
|---------|------|------|
| `parse_and_save_datafile()` | `apps/datafiles/services.py:93` | 从未被调用，与 `_register_file()` 功能重复 |
| `parse_data_file_task` | `apps/datafiles/tasks.py:10` | Celery 任务已导入但从未调度执行 |
| `build_summary_sheet()` | `apps/gage/gage_summary_builder.py:21` | 已导入但未激活，legacy 版本仍在使用 |
| `build_per_file_sheets()` | `apps/gage/gage_summary_builder.py:191` | 同上 |
| `check_feature_permission()` | `apps/accounts/permissions.py:34` | 与 `FeaturePermission.has_permission()` 重复 |
| `load_user_files()` | `apps/common/file_loading.py:50` | 从未被导入或调用 |
| `_apply_bin1_filter()` | `apps/common/file_loading.py:91` | 仅被 `load_user_files()` 调用 |
| `compute_zonal_yield()` | `apps/analysis/services/statistics/analytics.py:470` | 导出在 `__all__` 但从未被导入 |
| `make_cpk_style()` | `apps/export/excelize_helpers.py:109` | 从未被调用 |
| `make_cpk_fill()` | `apps/export/excelize_helpers.py:97` | 仅被 `make_cpk_style()` 调用 |
| `medium_border()` | `apps/export/excelize_helpers.py:134` | 从未被调用 |
| `auto_widths()` | `apps/export/excelize_helpers.py:186` | 从未被调用 |

### 3.2 未使用的导入

| 模块 | 未使用的导入 | 行号 |
|------|-------------|------|
| `apps/accounts/views.py` | `PasswordChangeSerializer` | 16 |
| `apps/datafiles/views.py` | `parse_data_file_task` | 33 |
| `apps/data_correlation/views.py` | `get_parser` | 13 |
| `apps/analysis/views.py` | `get_parser` | 14 |
| `apps/buyoff/views.py` | `get_parser` | 12 |
| `apps/dashboard/views.py` | `get_parser` | 11 |
| `apps/batch_report/views.py` | `is_pass_bin` | 18 |
| `apps/dashboard/views.py` | `is_pass_bin` | 20 |

### 3.3 遗留/一次性脚本（可归档或删除）

| 目录/文件 | 文件数 | 状态 |
|-----------|--------|------|
| `tasks/` 目录 | 10 个 | 一次性诊断/修复脚本，非生产代码 |
| `scripts/update_sub_batch.py` | 1 个 | 一次性迁移脚本 |
| `apps/datafiles/management/commands/backfill_product_code.py` | 1 个 | 一次性迁移命令 |
| `apps/datafiles/management/commands/fix_moved_project_paths.py` | 1 个 | 一次性迁移命令 |
| `apps/datafiles/management/commands/migrate_user_paths.py` | 1 个 | 一次性迁移命令 |
| `test/archive/` 目录 | 15 个 | 旧调试脚本，应清理 |

---

## 四、可复用模块分析

### 4.1 代码重复问题

#### 问题 1：文件加载模式重复（最严重）

`get_object_or_404(DataFile) + get_cached_parsed_file()` 组合在 **10 个文件**中重复实现，仅 1 个使用了 `common/file_loading.py`。

**重复位置**：
- `apps/analysis/views.py` - 自定义 `_load_df_from_request()`
- `apps/batch_report/views.py` - 直接调用
- `apps/buyoff/views.py` - 循环内重复加载
- `apps/dashboard/views.py` - 直接调用
- `apps/data_correlation/views.py` - 直接调用
- `apps/gage/views.py` - 直接调用
- `apps/export/views.py` - **唯一使用 common 模块**

**建议**：统一使用 `common/file_loading.load_user_file()`，消除 7 处重复实现。

#### 问题 2：Only-Bin1 过滤逻辑重复

```python
if only_bin1:
    bin_col = get_bin_column_name(df_obj.format_type)
    if bin_col in df.columns:
        bin_numeric = pd.to_numeric(df[bin_col], errors='coerce')
        df = df[bin_numeric == 1].copy()
```

**重复位置**：`gage/views.py`, `buyoff/views.py`, `common/file_loading.py`

**建议**：统一使用 `common/file_loading.load_user_files(only_bin1=True)`。

#### 问题 3：常量重复定义

`NON_NUMERIC_KEYWORDS` 在 3 个文件中独立定义：
- `apps/analysis/services/statistics/helpers.py`
- `apps/gage/gage_styles.py`
- `apps/datafiles/parsers/base.py`

**建议**：统一从 `common/constants.py` 导入。

#### 问题 4：其他重复模式

| 重复模式 | 出现次数 | 涉及模块 |
|----------|----------|----------|
| `file_id` 参数获取 | 8+ 次 | analysis, export, dashboard |
| 数值列过滤 | 5 次 | analysis, buyoff, dashboard, data_correlation, export |
| `permission_classes = [IsAuthenticated]` | 22 次 | 所有 views |
| Excel Content-Type 字符串 | 6 次 | batch_report, buyoff, export, gage |
| `PHASE_ORDER` 常量 | 2 次 | batch_report/views.py 内部重复 |

### 4.2 应抽取到 common 的函数

| 函数 | 当前位置 | 建议位置 |
|------|----------|----------|
| `clean_data()` | `analysis/views.py:49` | `common/serialization.py` |
| `_filter_blank_params()` | `analysis/views.py:62` | `common/params.py` |
| `_sanitize_numeric_params()` | `analysis/views.py:76` | `common/params.py` |
| `_load_df_from_request()` | `analysis/views.py:102` | 删除，使用 `common/file_loading.py` |

---

## 五、架构问题

### 5.1 views.py 职责过重

| 文件 | 行数 | 问题 |
|------|------|------|
| `apps/datafiles/views.py` | 859 | 10 个 View 类 + 6 个模块级函数，混合上传、解压、注册、浏览、一致性检查 |
| `apps/analysis/views.py` | 751 | 2 个 ViewSet + 工具函数，混合数据加载、验证、业务逻辑 |
| `apps/batch_report/views.py` | 375 | 单个 action 方法 200 行，包含全部 Phase 检测和 KPI 计算 |

### 5.2 跨模块不健康依赖

`apps/sftp/views.py` 直接导入 `apps/datafiles/views.py` 中的私有函数：
```python
from apps.datafiles.views import _register_file, _user_upload_dir
```

**建议**：将这些函数移至 `apps/datafiles/services.py`，提供正式的公共接口。

### 5.3 models.py 缺乏业务方法

**`DataFile` 模型建议添加**：
- `get_numeric_columns()` - 获取数值列
- `is_batch` property - 判断是否为批次文件
- `display_format` property - 格式显示名
- `delete_from_disk()` - 删除磁盘文件

**`User` 模型建议添加**：
- `is_locked_out` property
- `record_failed_login()` 方法
- `reset_login_attempts()` 方法

### 5.4 文件加载 API 风格不统一

| 风格 | 使用模块 |
|------|----------|
| 返回元组 + error code | analysis |
| 抛异常 | export, common |
| 内联直接调用 | batch_report, buyoff, dashboard, data_correlation, gage |

**建议**：统一使用异常风格（common 模块已实现）。

---

## 六、测试覆盖率

### 6.1 测试覆盖情况

| 模块 | 测试状态 | 测试行数 | 风险等级 |
|------|----------|----------|----------|
| accounts | ✅ 完整 | 312 | 低 |
| analysis | ✅ 完整 | 441 | 低 |
| batch_report | ✅ 完整 | 183 | 低 |
| datafiles | ✅ 完整 | 656 | 低 |
| sftp | ✅ 完整 | 444 | 低 |
| **buyoff** | ❌ 无测试 | 3 | 🟡 中 |
| **dashboard** | ❌ 无测试 | 3 | 🔴 高 |
| **export** | ❌ 无测试 | 3 | 🔴 高 |
| **gage** | ❌ 无测试 | 3 | 🟡 中 |

### 6.2 测试文件位置问题

| 文件 | 当前位置 | 问题 |
|------|----------|------|
| `test_sftp_pool.py` | `test/` | 独立脚本，不被 `manage.py test` 发现 |
| `test_histogram_range_type.py` | `test/` | 同上 |
| `test_phase_parsing.py` | `test/backend/` | pytest 风格，目录不规范 |
| 15 个调试脚本 | `test/archive/` | 应清理 |

---

## 七、改进建议（按优先级）

### 🔴 高优先级

1. **拆分超大文件** - 6 个超过 600 行的文件必须拆分
2. **统一文件加载模式** - 所有模块使用 `common/file_loading.py`
3. **补充 dashboard 和 export 测试** - 核心业务逻辑零覆盖
4. **提取 datafiles service 层** - 消除 sftp 对 views 的不健康依赖
5. **清理死代码** - 删除 12+ 个未使用的函数

### 🟡 中优先级

6. **统一常量定义** - `NON_NUMERIC_KEYWORDS` 等常量去重
7. **添加模型业务方法** - DataFile 和 User 模型
8. **设置全局权限配置** - 消除 22 处重复声明
9. **统一 Excel Content-Type** - 定义为常量
10. **清理遗留脚本** - tasks/ 和 test/archive/ 目录

### 🟢 低优先级

11. **统一文件加载 API 风格** - 全部使用异常方式
12. **PHASE_ORDER 常量去重** - batch_report 内部重复
13. **迁移散落的测试文件** - 统一到 app tests 目录

---

## 八、总结

### 代码健康度评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 文件大小合规 | ⭐⭐⭐☆☆ | 6 个文件违规，集中在核心模块 |
| 代码复用 | ⭐⭐☆☆☆ | 大量重复模式，common 模块推广不足 |
| 死代码控制 | ⭐⭐☆☆☆ | 12+ 个未使用函数，多个遗留脚本 |
| 测试覆盖 | ⭐⭐⭐☆☆ | 核心模块有测试，但 4 个模块零覆盖 |
| 架构清晰度 | ⭐⭐⭐☆☆ | 存在职责混乱和不健康依赖 |

**总体评分：2.4/5 - 需要改进**

### 关键发现

1. **最严重问题**：文件加载逻辑在 10 个文件中重复实现，common 模块形同虚设
2. **最高风险**：dashboard 和 export 模块零测试覆盖
3. **最大技术债**：`gage_legacy_builder.py`（857 行）已有重构版本但未激活
4. **最需立即行动**：拆分 6 个超大文件，清理 12+ 个死代码函数
