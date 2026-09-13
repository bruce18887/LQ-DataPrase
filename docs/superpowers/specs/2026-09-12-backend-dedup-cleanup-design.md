# 后端重复冗余清理 · 设计文档

- 日期：2026-09-12
- 类型：技术债清理（refactor-only，无功能变更）
- 范围：`apps/`、`config/` 的 production 代码（不含 tests/migrations 的结构性重写）
- 产出约定：**本文档只定义方案与执行边界，不含任何代码改动**。执行需另行批准。

---

## 1. 背景与目标

2026-09-12 完成后端重复/冗余审计，方法为：行级重复检测脚本 + 分模块并行审计 + 逐条人工复核（每条发现的行号与调用链均已用 Read/Grep 验证）。

审计结论按性质分两类：

1. **纯冗余**：死代码、逐字节复制块、同语义多份实现 —— 消除它没有行为风险。
2. **口径分歧**：两处实现结果不同（error code、限值占位符、CPK 口径）—— 表面是重复，实质是**潜在不一致 bug**，合并前必须选定权威口径。

本方案目标：

- 消除可安全删除的重复与死代码，降低维护面与"改一处漏一处"的风险。
- 对第 2 类问题**只做不改变行为的收敛**（消除内联复制、建立单一来源），口径本身的变更另行立项。
- 全程可分批 revert，每批有明确验证门禁。

**非目标（明确不做）**：

- 不改任何前端可见的 error code 语义、不改任何数值口径（见 §6 决策 D1/D2）。
- 不统一 openpyxl 与 excelize 双库并存（`export_batch_charts_xlsx.py` 依赖 openpyxl 的 Image 嵌入，强统一风险高于收益）。
- 不搬迁 `apps/common/params.py`（已确认仅 analysis 使用，但搬迁属位置 churn，无收益）。
- 不重构 `gage_legacy_builder.py` 的 901 行（见 §6 决策 D4，另立项目）。

---

## 2. 验证门禁（每批必须全过）

| 层 | 命令 | 通过标准 |
|---|---|---|
| **L0 基线**（仅开工前一次） | `.venv/Scripts/python.exe manage.py test` | 记录真实用例总数与 OK 数，写入 `docs/tasks/todo.md` 作为后续对照基准。不依赖历史数字（记录值 888–899，可能已漂移） |
| **L1 全量** | `manage.py test`（串行） | 与 L0 同数 OK，零新增 failed/error |
| **L2 定向** | `manage.py test apps.<受影响app>` | 该 app 全绿 |
| **L3 e2e** | `cd frontend && npm run test:e2e:quick`，或按域跑对应 `.spec.ts` | 仅**触及接口行为**的批次需要：P1-2（SFTP 守卫，跑 `e2e/sftp/`）、P2-1（文件加载内联收敛，跑相关页 e2e）。P0 全部批次为纯删除，L1+L2 即可 |

**收尾要求**（CLAUDE.md 硬规则）：e2e 跑完释放全部端口（8000/3000 无监听）；每批结果记入 `docs/tasks/todo.md` 验证账目。

**判定回归的方法**（lessons R8）：出现失败先对 baseline 复跑区分存量失败与本次回归，再单文件隔离复跑排除 flake。

---

## 3. P0 —— 死代码清除（约 700 行，零行为变化）

判据：全仓库 grep（`apps/`、`config/`、`scripts/`、`test/`、`frontend/`、`electron/`）确认无生产调用者。注意 `__init__.py` re-export 与注释引用**不算**调用者。

### P0-1　删除 `apps/gage/gage_summary_builder.py`（363 行）

- **证据**：文件 1-5 行自述 `# DEAD CODE — not wired into any view ... do NOT bug-fix here`。
  `build_summary_sheet`（:26）/`build_per_file_sheets`（:196）唯一外部引用是 `apps/gage/excelize_layout.py:27-30` 的 re-export，全仓无任何调用点。
- **live 路径确认**：`apps/gage/views.py:53` → `excelize_layout.py:32` → `gage_legacy_builder.build_gage_summary_excel`。`test/backend/test_gage_builder.py:26` 亦直接 import legacy 版。
- **风险**：无。**务必不要删错一侧** —— `gage_legacy_builder.py` 是唯一 live 实现。
- **回查指引**：需要旧参考实现时用 `git show <本清理前 commit>:apps/gage/gage_summary_builder.py`，不留仓内副本。

### P0-2　删除 `apps/gage/services/rr_analysis.py`（178 行）

- **证据**：文件 1-5 行同样自述 DEAD CODE。唯一 import 者是 P0-1 删掉的 `gage_summary_builder.py:16`。
  其 `_calc_d2`/`_safe_float`/`COL_RR_PCT` 在 live 的 `gage_legacy_builder.py:66/17/61` 各有**独立的本地实现**（不依赖本文件）。
- **风险**：无。`compute_rr_statistics`/`compute_file_statistics` 全仓零调用。
- **附带**：`apps/gage/services/` 目录随文件删除而空（仅剩 `__init__.py`），一并移除。

### P0-3　收缩 `apps/gage/gage_styles.py`（57 → 约 12 行）

- **保留**：`NON_NUMERIC_KEYWORDS`（:8，从 `common.constants` 转引）、`FILL_GRAY_HEX`（:9）、`FILL_LIGHT_BLUE_HEX`（:10）—— 被 live 的 `gage_legacy_builder.py:14` 导入，并在 :47/645/654/663 使用。
- **删除**：`make_info_label_style`/`make_info_value_style`/`make_warning_style`/`make_good_rate_style`/`make_bad_rate_style`/`make_rr_pct_style`/`make_red_rr_pct_style`（:14-50）与 `_set_cell`（:54-57）—— 7 个工厂 + 1 个 helper 仅被 P0-1 的死代码消费；live 版在 `gage_legacy_builder.py` 内另有本地 `_set_cell`（:243，签名不同）。
- **净收益**：约 45 行。
- **风险**：低。`gage_styles.py` 收缩后仅存常量，可考虑直接并入 `gage_legacy_builder.py` 或 `common/constants.py`；**本轮保留文件**，避免连带改动扩大。

### P0-4　删除 `apps/gage/excelize_layout.py`（32 行）+ 改 1 行 import

- **现状**：该文件是拆分时留下的 backward-compat re-export 层（docstring 自述）。P0-1/P0-3 完成后，其中 re-export 的名字全部无人引用。
- **做法**：`apps/gage/views.py:53` 改为直接 `from apps.gage.gage_legacy_builder import build_gage_summary_excel`，随后删除整个 `excelize_layout.py`。
- **理由**：留一个纯转发 shim 本身就是"只有一层转发的冗余抽象"。
- **风险**：低。删除前需确认无 `from apps.gage.excelize_layout import`（当前仅 views.py:53 一处）。
- **替代方案**：若希望保持零 import 变更，可把文件收缩为 1 行 re-export —— 收益 −31 行，不推荐。

### P0-5　删除 `apps/datafiles/parsers/base.py:20-70`（52 行）—— 高危陈旧分叉

`BaseATEParser.get_columns_with_limits`（:20-37）与 `detect_fail_data`（:39-70）是 `apps/analysis/services/statistics/limits.py:19-40/104-165` 的**修复前旧版本**：

| 维度 | base.py（死） | limits.py（live） |
|---|---|---|
| bin NaN 判定 | `:48` `to_numeric(...) != 1` → NaN 误判为 **FAIL** | `:116-120` `notna() & (!= 1)`，修正于 2026-09-05 审查 L3（跨端点良率矛盾） |
| 限值解析 | `:50-51` 裸 `float()` → 限值 `'Min'` 时 `ValueError` → **500** | `:128-140` 走 `resolve_spec_limit` + None 守卫，注释记录该 500 为 e2e 实测事故（真实文件有 13 个系统列限值为字面 `'Min'/'Max'`） |
| 性能 | `:68` 每行重建 `set(fail_indices)` → O(n²) | `:153-155` 集合复用，注释记录 10 万行拖到数分钟的回归 |
| 调用者 | **零**（唯一引用是同文件 `:45` 自调；全仓无 `parser.detect_fail_data` / 测试引用） | 12+ 处生产调用 |

- **结论**：这不是"等价重复"而是**留着就会误导人误用的 bug 副本** —— 新代码一旦 `parser.detect_fail_data(...)` 就同时复活三个已修复的缺陷。删除是最强收敛。
- **风险**：无（零调用者已验证）。
- **保留**：同文件的 `make_column_names_unique`、`get_bin_column_name`、`fix_negative_decimal`、`convert_to_numeric`、`identify_format`、`extract_header_metadata`、`drop_tail_metadata_rows` 均 live。

### P0-6　删除 `apps/export/charts.py:32-45` 兼容 shim（14 行）+ 同步测试

- **现状**：docstring 自述 `.. deprecated:: 兼容 shim —— 生产路径请用 build_histogram_grid`，且明写"测试迁移那一轮应连同本 shim 一起删除"。生产代码（charts / export_ppt）已全部改走 `build_histogram_grid`。
- **阻塞点**：被 3 处测试 pin —— `apps/export/tests.py:482,490`、`test/backend/test_export_histogram_grid.py:26,177,287`。
- **做法**：删函数 + 把上述测试断言改指向 `build_histogram_grid`（或删该等价的旧几何用例）。这是 P0 中**唯一需要改测试**的条目。
- **风险**：低-中，取决于测试改写；改完以 L1 全量为准。

### P0-7　零星死代码（约 15 行）

| 位置 | 内容 | 证据 |
|---|---|---|
| `apps/analysis/services/statistics/helpers.py:104-107` | `get_1d` | 全仓零调用（live 的是 `get_1d_from`）；仅需同步移除 `statistics/__init__.py:23,95` 的 import 与 `__all__` 条目 |
| `apps/datafiles/serializers.py:147` | `FileUploadSerializer` | 全仓零引用（含前端/electron） |
| `apps/datafiles/views/_helpers.py:163-171` | `_disk_mtime` | 被 `file_views.py:33` import 但从未使用；需同删 `views/__init__.py:14` re-export 与该行 import。注意勿混淆 live 的 `services.py:115 _disk_mtime_ns` |
| `apps/export/excelize_helpers.py:12` + `apps/gage/gage_legacy_builder.py:83` | `COLOR_ALT_ROW` ×2 | 两处定义、零消费 |

### P0-8　未使用 import（12 处，逐个 grep 确认全文仅出现 1 次）

- `apps/analysis/views/analysis_views.py`：`os`(:7)、`Dict`/`Optional`/`Set`(:9)、`compute_correlation_matrix`(:20)、`compute_boxplot_stats`(:21)、`compute_range_statistics`(:22)、`compute_site_stats`(:23)、`ensure_numeric`(:34)、`compute_low_cpk_test_items`(:38)
- `apps/analysis/views/statistics_views.py`：`os`、`get_object_or_404`、`DataFile`、`get_cached_parsed_file`
- **例外，不得删**：`apps/sftp/views.py:4,6` 的 `paramiko`/`status` —— `views.py:2-3` 注释明示为 monkey-patch 目标（lessons R6③ 同款）。

### P0-9　清理仓内遗留备份文件（非 git 跟踪）

- `apps/gage/excelize_layout.py.bak`（18,438 B，5 月 31 日）—— 被 `.gitignore:172 *.bak` 忽略，属本地垃圾。
- **执行时需先向用户确认再删**（不是本次会话产生的文件，且不可用 git 恢复）。

### P0 收益汇总

约 **711 行**净删除（363+178+45+32+52+14+15+12），触及约 19 个文件，**零行为变化**；其中仅 P0-6 需要同时修改测试断言。

---

## 4. P1 —— 结构合并（约 500 行，需逐条比对行为差异）

原则：每处合并前**先列出各副本间的实际差异**，差异用参数保留；不得"取其一为准"。

### P1-1　解析器三胞胎参数化（净减约 190 行）★ 本轮最大结构收益

**实测重复**（行级检测脚本，规整化后逐行比对）：

- `cta8280f.py:12-61` ≡ `cta8290d.py:12-61` ≡ `sts8200.py:12-61` —— **40 行三方逐字节相同**
- `ets88.py:113-130` 与上述共享 15 行同构块
- `cta8280f.py:82-95` ≡ `cta8290d.py:82-95`（12 行）、≡ `sts8200.py:90-102`（11 行）
- `cta8280f.py` 与 `cta8290d.py` **整文件 diff 仅 22 行 / 5 处**：类名与 `format_type`、`'TestFileName'` vs `'TestFile'` 关键字、3 个 metadata 标签（`station`/`device_name`/`tester_type`）、`handler` 标签

**真实差异清单**（必须参数化保留，不能合并掉）：

1. 类名 / `format_type` 字符串
2. program name 提取关键字（`TestFileName` vs `TestFile` vs STS8200 的 `Program:` + `split(':')`）
3. metadata 标签映射表（`extract_header_metadata` 的 mapping dict，可作类属性）
4. STS8200 独有逻辑：`station` 取自首行、`device_name` 从 Program 路径推导（`.pgs`/`.DLL` 剥离）—— 这是 sts8200 比另两个多 8 行的原因

**做法**：在 `base.py` 增加 CTA 家族的中间基类（或 `_parse_cta_like(config)` 模板方法），差异下沉为类属性（`HEADER_LABELS`、`PROGRAM_KEYWORD`），STS8200 保留自己的 `parse` 覆写只复用公共骨架。

**同时消除双份事实源**：4 处 `get_bin_column_name` 覆写（`cta8280f:94`/`cta8290d:94`→`'SW_Bin'`、`ets88:169`→`'Bin'`、`sts8200:102`→`'SOFT_BIN'`）与 `apps/analysis/services/statistics/helpers.py:14-20` 的 `BIN_COLUMN_MAPPING` 是**同一知识的两份记录**（逐项核对：完全一致）。
→ 把映射表移到 `apps/common/constants.py`（中性位置），`helpers.get_bin_column_name` 与 parser 侧共读一处。
→ **不能**让 parser 直接 import analysis 的 helper（analysis 已被 datafiles 依赖，反向 import 成环）。
→ 注意 parser 覆写**是 live 的**（`browse_views.py:316` 用 `parser.get_bin_column_name()` 下发 bin 列），不能直接删。

**验证**：L1 + `manage.py test apps.datafiles`；**额外**用四格式真实样本文件做对拍（解析前后 `metadata` 全字段与 `df` 形状/dtype/前若干行逐字节相等），样本取自 `Data/`。这是本轮唯一建议加样本对拍的条目 —— 解析器改动的影响面是全链路。

### P1-2　SFTP 下载端点守卫链抽取（净减约 55 行）★ R3 高危

**现状**（`apps/sftp/views.py`，6 个下载相关端点，257-531）：
`not_connected` 守卫 ×7、`缺少 path 参数` ×3、`_is_csv` 校验 ×6、`_user_upload_dir → resolve_local_path → sftp.get → _register_file → remove_partial → pool.invalidate` 落盘链 ×5 份。

**必须保留的差异**（这是重点，不是可忽略的细节）：

| 端点 | 位置 | 守卫顺序 | `_is_csv` |
|---|---|---|---|
| `download` | :257-295 | 先 `not remote_path` 后 `_is_csv` | 有 |
| `download_file_stream` | :297-338 | 同上 | 有 |
| `download_dir` | :344-383 | **完全无 `_is_csv`** | 无 |
| `download_batch` | :389-433 | 同 download | 有 |
| `_single_download_parse` | :457-484 | 走 `elif remote_path` 分支 | 有 |
| `_batch_download_parse` | :486-531 | 同上 | 有 |

`views.py:261` 注释已记录一次真实事故：`os.path.splitext(None)` → 500。抽取时任何一处守卫遗漏或顺序调换，都会把 400 变成 500。

**做法**：抽 `_prepare_download(request, remote_path, *, require_csv: bool)` 返回 `(sftp, file_path)` 或错误 Response；`require_csv` 显式表达差异（`download_dir` 传 `False`），让守卫差异成为**签名上可见的意图**而非散落的遗漏。

**验证**：L1 + L2 + **L3 `e2e/sftp/`**（守卫改动影响状态码，必须跑 e2e）。

### P1-3　Excel 样式构造复用共享 helper（净减约 130 行）

**现状**：`gage_legacy_builder.py` 内联 14 个样式定义、**56 处手写 `excelize.Border(...)`**（对比：`excelize_helpers.py` 18 处、`buyoff/excelize_layout.py` 8 处）。

**逐字段等价性核对**（已实际比对）：

| legacy 内联 | 共享等价物 | 等价？ |
|---|---|---|
| `header_style`（:90-100） | `excelize_helpers.make_header_style(f, 12)`（:34-45） | ✅ 逐字段一致（含 4 条 `style=2` 边框） |
| `data_style`（:117-127） | `make_data_style(f)`（:48-59） | ✅ 一致（4 条 `style=1`） |
| `title_style`（:101-106） | `make_title_style(f)`（:95-101） | ✅ 一致 |
| `info_label_style`/`info_value_style`/`warning_style` | P0-3 删掉的 `gage_styles.make_*` 同名工厂 | ✅ 一致 → 应改指向共享 helper 而非重建 |
| `thick_top_style`（:128-138）、`thick_top_mid_style` | **无对应共享版本**（`left/top=2`、`bottom/right=1` 混搭） | ❌ 需给 `thin_border` 加参数或新增工厂 |

**做法**：`header/data/title` 三个改调 `apps/export/excelize_helpers`；40 处纯四边同构 border 改用现成的 `thin_border()`（:186）；`thick_top*` 混搭款先在 `excelize_helpers` 补一个可指定各边 style 的工厂，再替换。
`save_excelize`（`excelize_helpers.py:198-209`）与 legacy 本地版（`gage_legacy_builder.py:887-901`）合并 —— **必须保留 legacy 的 `finally: f.close()` 语义**（helpers 版是先 `close()` 后读，legacy 版读取成功才在 finally 关闭，且注释记录为 defect #10 修复）。legacy 版 `:885` 注释自述"kept local to avoid cross-module dependency"，该顾虑在 `apps/gage/views.py:12` 已经 import `save_excelize` 后不再成立。

**风险**：中。`f.new_style()` 每次调用返回新 style id，改用共享 helper 会**减少 style id 数量**（更好）。
**已验证**：`test/backend/test_gage_builder.py` 与 `apps/gage/tests.py` 对 style / fill / border / color **零断言**（只用 openpyxl 读单元格值），故 style id 数量变化不会破测试。剩余风险仅为导出外观回归，靠人工比对兜底。
**验证**：L1 + `manage.py test apps.gage apps.export` + 人工比对导出 xlsx 外观（建议导出一次前后对拍单元格样式）。

### P1-4　`serial_distribution.py` 有/无 Site 双分支合并（约 28 行）

`:71-96`（有 site）与 `:97-124`（无 site）逐句镜像：cols 组装 → `pd.to_numeric(errors='coerce')` → `isfinite | isna` 掩码 → `reset_index` → `groupby(...).last()` → `expected` 列名去重重命名。
→ 抽 `_group_last(df, keys, cols)`，site 有无作为 keys 长度差异。
**验证**：L1 + `manage.py test apps.analysis`（已有 `tests_serial_column.py` 覆盖两条路径）。

### P1-5　文件名碰撞后缀算法统一（约 15 行）

4 份：`datafiles/views/file_views.py:312-317`、`:413-418`、`:567-571`、`sftp/local_paths.py:23-34`。
`sftp/local_paths.py` 是最完备实现（含同秒 `_seq` 兜底），datafiles 三处未复用。
→ datafiles 侧改调 `local_paths.resolve_local_path` 或抽 `common` 层公共函数。
**风险**：合并后"同秒双碰撞"的产物文件名会变（多了序号段）—— 执行前必须 grep e2e 是否断言精确文件名（lessons R2③ 提示 DB 状态/文件名污染风险）。
**验证**：L1 + `manage.py test apps.datafiles apps.sftp`。

### P1-6　`charts.py` sigma 带循环收敛（约 12 行）

`:122-129` 与 `:174-181` 是同一 `[(3, show_3sigma, COLOR_SIGMA_3, '3σ'), (4, ...), (6, ...)]` + `mean±σ*std`（仅一处画线一处加标签），`export_ppt.py:91-97` 是第三份简化副本。
→ 抽 `_sigma_bands(mean, std, flags)` 返回 `(sigma, lower, upper, color, label)` 列表，三处消费。

### P1-7　"已注册批量路径集合"单一来源（约 18 行）

4 份同构：`datafiles/views/batch_views.py:38-60`、`:157-162`（`:156` 注释自述 "Mirrors … above"）、`views/_helpers.py:399-403`、`:462-467`。
均为 `set(os.path.normpath(resolve_file_path(p)) for p in DataFile.filter(owner, file_type='batch')[...])`。
→ 抽 `_registered_batch_paths(user, batch_name=None)`。
**历史风险**：注释记录过漏 `normpath` 导致重复导入/误报未注册 —— 合并正是为消除"再次漏改"。注意 4 处的 `batch_name` 过滤条件不一致（:38/:399 带 batch_name，:157/:462 不带），参数化时必须保留。

### P1-8　视图层小重复（约 50 行）

- **param 守卫 11 行全等**：`analysis_views.py:630-641` ≡ `statistics_views.py:99-110`（`param_required` → `param not in df.columns` → `param_not_found` + detail）。
  → 抽 `require_param(request, df)`。这直接服务 lessons **R3①**（相似端点守卫必须对齐，grep 对比即可发现差异）。
- **同文件双份**：`file_correlation_views.py:71-85` ≡ `:105-119`（load pair → compute → `NoCommonParamsError` → 400）。
- **boxplot 双分支**：`statistics_views.py:351-365`（by_site）≡ `:367-390`（by_bin），差异仅分组索引列 → `_group_series(series, idx)`。
- **数值列候选判定 5 处**：`analysis_views.py:119-123`、`views/_helpers.py:130-142`、`multi_lot.py:36-41`、`file_correlation.py:80-83`、`site_yield.py:207`（`is_numeric_dtype and not is_bool_dtype` + blank 过滤）。
  → 抽 `numeric_param_columns(df, *, exclude=..., strip=..., drop_dup_all_nan=...)`。
  **注意真实差异**：`multi_lot` 额外 `str(c).strip()`，`_helpers` 额外查重名列/全 NaN —— 差异须以参数保留，不能取其一为准。

---

## 5. P2 —— 契约与口径（依 §6 决策执行，净减约 88 行）

### P2-1　文件加载：消除内联复制，**不合并两套 error code**（决策 D1=B，约 50 行）

两套实现并存且语义不同：

| | `apps/analysis/views/_helpers.py:147-172` `_load_df_from_request` | `apps/common/file_loading.py:16-52` `load_user_file` |
|---|---|---|
| 返回 | `(df, datafile, metadata, err)` 元组 | 抛 `FileLoadError` |
| 重名列 | **去重**（:166-167） | 不去重 |
| 错误码 | 合成 `file_not_found_or_parse_failed` | 区分 `file_not_found` / `parse_failed` |
| 消费者 | analysis 全部端点 | 仅 `apps/export/views.py:119,150,185,213,263` |

→ **保持两套不动**（改 error code 属功能变更，会波及前端错误分支）。
→ 只把 7 处内联复制改为调用**其所在 app 已有的那套**：`dashboard/views.py:246-252`、`buyoff/views.py:32-40`/`:71-90`、`gage/views.py:32`、`batch_report/views.py:101`/`:343`、`browse_views.py:203-220`。
→ 附带：在两文件头 docstring 互指，并修正 `common/file_loading.py` 现在"声称覆盖 analysis/dashboard 但实际只有 export 用"的失真描述。
**验证**：L1 + L2 + 触及页面的 e2e（dashboard / buyoff / batch 各一次）。

### P2-2　CL 自定义限守卫收敛（约 20 行）

8 处重复 `range_type == 'CL' and custom_low is not None and custom_high is not None`：`histogram.py:90,162,313,314`、`multi_lot.py:98,190`、`serial_distribution.py:184`、`statistics_views.py:133`、`analysis_views.py:180`。
各处注释已自述"与 histogram 同口径"，说明意图是单一来源。
→ 抽 `resolve_custom_limits(range_type, low, high, stats)`。
**唯一实质差异**：`analysis_views.py:180` 多一个 `low > high` 校验，未下沉 —— 收敛时决定是否推广到全部端点（推广会新增 400 拒绝路径，属行为变更 → **本轮只做等价收敛，把该校验原样保留在 analysis 侧**，并加 TODO 记录待产品确认）。

### P2-3　`filtered_cpk` 单一来源（决策 D3=A，约 18 行）

`histogram.py:112-139`（IQR 边界 → normal 子集 → filtered mean/std → `compute_cpk`）与 `statistics/filters.py:90-105` `_display_cpk` 是同一口径的两份手抄，后者注释自认 "mirrors histogram.py"。
→ 抽 `filtered_cpk(series, rdl, iqr_multiplier)` 供两处调用。
**理由**：纯计算、无对外契约影响，而漂移会让同一页面的「低CPK筛选」与统计卡自相矛盾 —— 属真实 bug 温床，应立即收敛。
**验证**：L1 + `manage.py test apps.analysis`（`tests_param_guards.py`、`tests_chart_config.py` 覆盖 CPK 路径）。

### P2-4　限值占位符判定：**保持现状 + 文档标注**（决策 D2=B）

三份占位符集合：`dashboard/views.py:74-79`（仅排除 `''/nan/none/n/a`）、`statistics/limits.py:44-73`（用 `NON_NUMERIC_KEYWORDS`，排除 `'Min'/'Max'`）、`file_correlation.py:35-36`（额外处理 `'·'`/`'—'`/去引号）。
`dashboard/views.py:130-137` 注释**自认**与 `NON_NUMERIC_KEYWORDS` 不一致。
→ 本轮**不改行为**（改会让 dashboard「有规格限参数个数」数字变化，可能破 e2e 断言且需产品定夺哪个口径正确）。
→ 只补一处交叉引用注释，并**另立条目**：待产品确认权威口径后再统一。风险留档。

### P2-5　600 行硬规则（CLAUDE.md）：只拆 `analysis_views.py`（决策 D4=B）

| 文件 | 行数 | 处置 |
|---|---|---|
| `apps/analysis/views/analysis_views.py` | 689 | **本轮拆**：按端点族分 `histogram_views.py` / `multi_lot_views.py` / `wafer_views.py`（+ 保留 `analysis_views.py` 作其余）。成本已被摊平：`_load_df_from_request` 已公共化，且 P1-8 会先抽出 `require_param`。需同步 `views/__init__.py` re-export 与 `urls.py` 导入路径 |
| `apps/gage/gage_legacy_builder.py` | 901 | **另立项目**：它是**单个 866 行函数 + 内部嵌套闭包**（`_set_cell`@:243、`_calc_d2`@:66 被闭包捕获），拆文件要先解开闭包与局部样式变量作用域，风险显著高于"文件太长"的收益。P0+P1-3 完成后它已能降到约 750 行。自然三段：样式(:78-240)/Summary(:242-680)/分文件表(:682-881) |
| 临界预警 | — | `file_views.py` 587、`browse_views.py` 573、`sftp/views.py` 561 —— P1-2/P1-5 完成后三者均回落至 600 以下，无需额外拆分 |

### P2-6　`common/` 目录归属（仅记录，不改代码）

`common/params.py` 实际仅 analysis 使用、`common/file_loading.py` 仅 export 使用。
→ 不搬迁（churn 无收益）。建议在 `apps/common/` 加一条准入约定："跨 app 共享工具须 ≥2 个消费者"，防止继续堆积。

---

## 6. 决策记录（本会话已确认）

| # | 分歧点 | 决定 | 理由 |
|---|---|---|---|
| **D1** | 文件加载两套 error code 是否统一 | **B：不统一**，只消除 7 处内联复制 | error code 是前后端契约，改它属功能变更而非清理；本轮只治重复不治口径 |
| **D2** | dashboard 与 analysis 限值占位符口径 | **B：保持现状**，补交叉引用注释 + 另立待决条目 | 改口径会让 dashboard 计数变化并可能破 e2e 断言；哪个权威需产品定夺 |
| **D3** | `filtered_cpk` 两份手抄是否立即抽单一来源 | **A：立即抽**（P2-3） | 纯计算逻辑无契约影响，漂移直接造成同页数值自相矛盾 |
| **D4** | 600 行超限文件拆分范围 | **B：只拆 `analysis_views.py`**，`gage_legacy_builder.py` 另立项目 | 后者是单函数+闭包捕获，属结构重构而非机械拆分，风险不对称 |
| D5 | 带 DEAD CODE 头注释的参考实现去留 | **删除**，靠 `git show` 回查 | 文件头已明写 "do NOT bug-fix here"，留仓会持续误导后来人 |
| D6 | 分批策略 | **按风险分层** P0→P1→P2 | 每批独立可 revert，第一批即拿到最大收益 |
| D7 | commit 粒度 | **每批一个 commit** | 出问题可单批回滚，不牵连其他 |
| D8 | 验证门禁 | **L1 全量 + L2 定向**，仅触及接口行为的批次加 L3 e2e | 与 lessons R1/R8 一致 |

---

## 7. 执行顺序与 commit 计划

```
前置  [L0] 跑全量测试，记录真实基线到 docs/tasks/todo.md
─────────────────────────────────────────────────────────────
c1  refactor(gage):  删除 gage 死代码链                P0-1~P0-4  ~618 行
c2  refactor(parsers): 删除 base.py 修复前陈旧分叉      P0-5        52 行
c3  chore:  零星死代码 + 未使用 import + .bak           P0-6~P0-9   ~40 行
    └─ P0 完成，L1+L2 全绿即形成第一个稳定交付点
c4  refactor(parsers): CTA/STS 家族参数化 + bin 列单源   P1-1       ~190 行  ← 加样本对拍
c5  refactor(sftp): 下载端点守卫链抽取                  P1-2        ~55 行  ← 加 e2e/sftp
c6  refactor(excel): 样式与 save_excelize 复用共享层     P1-3       ~130 行
c7  refactor: 视图与服务层小重复抽取                     P1-4~P1-8   ~123 行
c8  refactor(analysis): 拆分 analysis_views 端点族       P2-5(D4)    行数不减，解 600 线
c9  refactor: filtered_cpk 单一来源 + CL 守卫收敛        P2-3,P2-2(D3) ~38 行
c10 refactor: 文件加载内联复制收敛                       P2-1(D1)    ~50 行  ← 加 e2e
```

- 每个 commit 独立自洽、可单独 `git revert`，不依赖后续 commit。
- P0 的 c1-c3 为纯删除，可连续完成；P1/P2 每批做完即验证，不攒批。
- **顺序依赖**：P1-8 的 `require_param` 应在 P2-5 拆 `analysis_views.py` **之前**完成（先公共化再拆，避免拆分后两处重复）。
- 预计总净减：P0 711 行 + P1 498 行 + P2 88 行 ≈ **1300 行**，另解除 1 个文件的 600 行违规（`gage_legacy_builder.py` 那处另立项目）。

**实施计划拆分建议**：本方案共 10 个 commit，建议落成**两份**实施计划 —— 计划 A = P0（c1-c3，纯删除，一轮可完成）、计划 B = P1+P2（c4-c10，每批需独立比对与验证）。理由：计划 B 任一条目的差异清单若被证伪（如样本对拍不等），按 lessons 的"出现偏差立即停下重规划"只影响该条，不会把已稳定的 P0 交付点一起推翻。

---

## 8. 风险登记与既有约束对照

| 风险 | 触及的 lessons 规则 | 缓解 |
|---|---|---|
| 删 gage 时删错一侧（legacy 是 live） | — | §3 P0-1 已用调用链证据钉死方向；删前跑 `test_gage_builder` 确认绿 |
| SFTP 守卫合并漏一个 → 400 变 500 | **R3①** 相似端点守卫必须对齐 | §4 P1-2 用 `require_csv` 参数把差异显式化 + 必跑 e2e |
| 文件加载 error code 被顺手统一 | **R3②③** 前端已过滤≠后端不用管；哨兵判断先做真值守卫 | 决策 D1 明确不改；P2-1 只做内联替换 |
| 数值口径合并造成统计值漂移 | **R4①③** | 抽函数时参数保留差异（P1-8 数值列候选、P2-2 CL 校验），改完跑脆弱数据回归 |
| 解析器参数化改变解析结果 | R4 | 四格式真实样本前后对拍（唯一加此门禁的条目） |
| 4+ 步重构中途丢工 | **R1** 完成即提交，磁盘才是事实 | 每批一 commit；批间 `git status` + `git diff --stat` |
| 改测试时把 pin 住的旧行为断言一起删 | **R6** | P0-6 明确"改指向新实现"而非"删断言" |

---

## 9. 完成定义（Definition of Done）

1. L0 基线数字已入 `docs/tasks/todo.md`，且每批后 L1 结果与之可比。
2. P0 全部完成：`apps/gage/` 死代码链、`parsers/base.py` 分叉、shim、零星死代码、未使用 import 均消失；全量测试绿。
3. P1 完成项各自通过其门禁；SFTP/解析器批有额外交付证据（e2e 绿 / 样本对拍零差异）。
4. 未做项（D1/D2 的口径统一、D4 的 gage 拆分）在 `docs/tasks/todo.md` 留有明确待办条目，不静默遗忘。
5. `grep` 复核：`gage_summary_builder`、`rr_analysis`、`build_histogram_bins`、`get_1d`（非 `get_1d_from`）、`FileUploadSerializer`、`_disk_mtime`（非 `_ns`）在仓内均无残留引用。
6. 端口全部释放，无前端主题影响（纯后端，不触及 dark/light 双主题规则 R7）。

---

## 10. 附：本方案的事实核验说明

- 本文档所有行号在 2026-09-12 主代理亲自 Read/Grep 复核（三份子代理审计报告中的每条高价值发现均经主代理二次验证）。
- 审计过程中曾出现一次**方向性误判**：token 级扫描器把唯一 live 的 `gage_legacy_builder.py` 报成"陈旧副本"。若照该线索执行会直接下线 Gage 导出。教训：重复检测工具的输出必须经调用链复核才能定"删哪一侧"。
- 审计用的临时脚本（`tasks/dup_scan.py`、`tasks/dup_scan_lines.py`）已按项目约定用完清理，未留在仓内。
