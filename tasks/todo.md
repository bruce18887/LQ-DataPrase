# [多文件分析] 功能改造计划

## 需求（来自 quest.txt）

1. 数据分析的「多Lot对比」拆分为一个独立顶层 tab —— **[多文件分析]**；**良率对比取消**。
2. [多文件分析] 把所选数据文件**提取共有测试项**（列名相同的测试项取交集），对这些测试项渲染展示。
3. [多文件分析] **不再拆分 SITE**；每个文件用不同图例；**limit 线每个数据文件用独立图例**。
4. UI 排版大致同「单参数分析」，风格随当前主题（dark/light 双主题）。

## 已确认的设计决策

- **呈现方式**：单测试项 + 上下切换（参数选择器 + prev/next），对齐单参数分析布局。
- **图形类型**：柱状图（每个文件一组柱，重叠绘制，独立颜色）。
- **共有测试项界定**：所有所选文件数值列**按列名精确取交集**。
- **自定义文件名**：每个文件的图例名可由用户编辑（默认 = 文件名）。
- **per-file limit 线**：每文件 LSL/USL 作为独立 line 系列（带 markLine），在图例中独立成项，可单独开关。
- **忽略无Limit**：左栏提供「忽略无Limit」开关；开启时**共有测试项列表只保留所有所选文件都带 limit 的项**（重新拉取 common_params）。
- **配置面板**：复用 `ChartConfigPanel`，新增 `variant='multi-file'` 阉割版——只保留 `Limit` 显示开关 + 柱宽 slider + 忽略无Limit；隐藏 3σ/4σ/6σ/正态、范围类型、自定义范围、「更多」按钮。

## 现状关键事实（已核实）

- `分布对比` tab（`DistributionComparisonTab.vue`）内含模式切换：箱线图(`BoxPlotSection`) / 多Lot对比(`MultiLotSection`)。
- `MultiLotSection.vue` 含两子页：分布对比 + 良率对比（良率走 `multi_lot` 的 `mode:'yield'`）。
- `MultiLotPanel.vue` 为**死代码**（无任何引用）。
- 后端 `multi_lot`（views.py:169）当前只处理**单参数**、**不返回 common_params**；故现状参数下拉其实为空（`AnalysisPage.commonParams` 恒为 `[]`）。
- `compute_multi_lot_distribution`（data_services.py:245）已算共享 bins + 每文件柱数据，但**未返回 per-file limit、未返回 file_id**。
- 每文件 limit 可从 `metadata['mins'/'maxs'][param]` 取，借助 `parse_limit_string` 解析。
- 图表统一走 `useChart` + `useEChartsTheme()`（自动跟随主题）。

---

## 任务清单

### A. 后端（apps/analysis）

- [x] A1. `data_services.py` 新增 `compute_common_params`（按名取交集 + ignore_no_limit 过滤）。
- [x] A2. 改 `multi_lot` 视图：无 param→common_params+file_names（带 ignore_no_limit 过滤）；有 param→lot_data 补 file_id+limit；移除 yield 分支。
- [x] A3. 改 `compute_multi_lot_distribution`：lot_data 加 file_id + per-file limit（`_resolve_param_limits`）；并修复 fail 计算对字符串 limit 的崩溃。
- [x] A4. 后端测试（tests.py `MultiFileAnalysisTests`）：共有项交集 / ignore_no_limit 过滤 / file_id+limit。全部通过（10 tests OK）。

### B. 前端 - 状态与路由（store / AnalysisPage）

- [x] B1. `stores/analysis.ts`：新增 multi-file 状态 + reset；移除 `comparisonMode`。
- [x] B2. `AnalysisPage.vue`：tab 改为 单参数 / 晶圆图 / 箱线图(直渲 BoxPlotSection) / 多文件分析 / 相关性工具；移除 `commonParams` 与 `DistributionComparisonTab`。

### C. 前端 - 新组件（均 ≤600 行）

- [x] C1. `composables/useMultiFile.ts`：`loadCommonParams(ids, ignoreNoLimit)` + `loadDistribution(ids, param)`。
- [x] C2. `components/MultiFileTab.vue`（~210 行，仿 SingleParamTab）。
- [x] C3. `components/MultiFileChart.vue`（~140 行，柱状图 + per-file 独立 limit 图例）。
- [x] C4. 改 `ChartConfigPanel.vue`：新增 `variant`（默认 `full` 不变），`multi-file` 阉割版。

### D. 清理死代码 / 移除良率

- [x] D1. 删除 `MultiLotPanel.vue`。
- [x] D2. 删除 `MultiLotSection.vue` / `DistributionComparisonTab.vue` / `useMultiLot.ts`（良率对比随之移除）。
- [x] D3. grep 校验无引用残留。

### E. E2E 测试（frontend/e2e/analysis/）

- [x] E1. 新增 `multi-file.spec.ts`：选 ≥2 文件→共有项非空→柱状图渲染（含独立 Limit 图例 + 断言无「良率对比」）/ 自定义图例名生效 / 忽略无Limit 重新拉取。**5 passed**。
- [x] E1b. 更新 `analysis.spec.ts` 的 TABS（分布对比→箱线图/多文件分析），**6 passed**。
- [x] E2. 双主题：新组件全用 CSS 变量 + 图表主题 textColor；series/limit 用调色板色（主题无关）。

### F. 验证（完成前）

- [x] F1. 后端 `python manage.py test apps.analysis` → 10 passed（含新 `MultiFileAnalysisTests` 3 例）。
- [x] F2. 前端 `vue-tsc -b` 总报错 33→31（仅剩全仓固有的 ECharts `EChartsOption` 推断噪声，我的文件仅贡献与 HistogramChart 同款 2 条）；e2e 全绿。
- [x] F3. 主题：组件用主题 token，dark/light 均适配（截图确认 light 渲染正常）。
- [x] F4. 行数：MultiFileTab ~210 / MultiFileChart ~140 / ChartConfigPanel ~150 / useMultiFile ~55，均 ≤600。

---

## 待定细节（已定）

- 共有测试项默认**不过滤**（全数值列交集）；开启「忽略无Limit」时过滤为各文件都带 limit 的项。
- 自定义文件名用左栏行内 `el-input` 列表（占位符=文件名，留空回退文件名）。

## Review

### 交付内容
- **后端**：`multi_lot` 改为双模式——无 `param` 返回 `common_params`(按列名交集，可选 ignore_no_limit 过滤) + `file_names`；有 `param` 时 `lot_data` 每项补 `file_id` / `lower_limit` / `upper_limit`。新增 `compute_common_params` / `_resolve_param_limits`。
- **顺手修复**：原 `compute_multi_lot_distribution` 的 fail 计算用 `series < 原始字符串limit` 直接比较，遇真实数据（mins/maxs 是字符串）必崩。因旧版参数下拉恒空、该路径从未真正跑通而未暴露；现改用解析后的数值 limit，并 ±inf 兜底。
- **前端**：新增 `多文件分析` 顶层 tab（`MultiFileTab` + `MultiFileChart` + `useMultiFile`）；`分布对比` tab 收敛为 `箱线图`(直渲 BoxPlotSection)；删除多Lot/良率相关死代码。`ChartConfigPanel` 加 `variant` 复用为阉割版。
- **测试**：后端 3 例 + 前端 `multi-file.spec.ts` 3 例 + 修正既有 TABS 例，全部通过。

### 关键决策与取舍
- 单测试项 + prev/next（对齐单参数页），而非一次性渲染全部，兼顾性能与组件行数上限。
- limit 线以独立 `line+markLine` 系列承载，从而获得独立图例项，满足「limit 每文件独立图例」。
- common params 与 distribution 分两次请求（仿单参数页 per-param 拉取），payload 小、导航流畅。

### 已知限制
- `vue-tsc -b` 仍有 31 条**既有**报错（全仓 ECharts 选项类型推断问题，非本次引入；master 本就 33 条）。运行/构建走 Vite(esbuild)与 e2e 不受影响；如需根治需全仓统一给 `buildOption` 标注返回类型，超出本任务范围。

