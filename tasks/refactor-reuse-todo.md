# 代码复用与去重重构计划 (Code Reuse & Dedup Refactor)

更新时间：2026-06-07
目标：审查前后端代码，复用模块、删除死代码、消除重复逻辑，预计可减少 **~2,200–2,400 行**（前端 ~1,450–1,700 + 后端 ~700–730），并顺带修复 2 处潜在 bug。

> 规则约束（来自 CLAUDE.md）：
> - 单个 Vue/TS/Django 文件不得超过 600 行。
> - 所有改动需维护 dark + light 两套主题。
> - 所有新开发/修改功能需补充或维护 e2e 测试。
> - 每步先计划、改完验证、记录 lessons。

---

## 0. 执行原则与顺序

按「高价值 + 低风险」优先。每个任务独立提交，改完跑对应测试 + 双主题视觉回归。

**前端推荐顺序**：1a（删死代码）→ 3（useChart）→ 2（useAsyncData）→ 7（主题去重）→ 1b/1c → 4/5/6
**后端推荐顺序**：B2a/B2d（样式复用）→ B4（SFTP）→ B1a/B1b（file_loading）→ B3b/B3a（统计）→ B2b/B2c（Excel 合并）

---

# 第一部分：前端 (Vue 3 + TS)

## FE-1. 重复 / 近似重复组件

### [⏸] FE-1a. 删除死代码 DataBrowser.vue + DataBrowserEnhanced.vue 【最优先・低风险・省 611 行】⏸ 用户要求暂不删除，仅标记
- **现状**：`pages/data/` 下有三个 DataBrowser，仅 `DataBrowserAgGrid.vue` 被使用（`DataManagement.vue:63,98` 导入）。
  - `DataBrowser.vue`（366 行）— 全局 grep 0 引用
  - `DataBrowserEnhanced.vue`（245 行）— 全局 grep 0 引用
  - 两者彼此 ~95% 相同：state（`DataBrowser.vue:78-90` ≡ `DataBrowserEnhanced.vue:65-76`）、computed（`92-125` ≡ `78-111`）、`loadData/exportExcel/exportCsv/downloadBlob`（`143-218` ≡ `129-205`）。
- **动作**：
  1. [ ] 再次确认无动态/字符串 import（`grep -rn "DataBrowser" frontend/src`）。
  2. [ ] 删除 `pages/data/DataBrowser.vue`。
  3. [ ] 删除 `pages/data/DataBrowserEnhanced.vue`。
  4. [ ] 跑 e2e 数据浏览相关用例，确认 DataManagement 正常。
- **省**：611 行。**风险**：低。

### [ ] FE-1b. 合并 KpiCards（dashboard vs batch）→ KpiCardGrid.vue 【中风险・省 ~70 行 + 修复 night hack】
- **现状**：
  - `pages/dashboard/components/KpiCards.vue`（106 行，`DashboardPage.vue:43,111`）— **硬编码 hex**（`52-104`：`#fff/#111827/#6b7280`），非主题感知，导致 `DashboardPage.vue:364` 存在 "global override for night" hack。
  - `pages/dashboard/components/batch/KpiCards.vue`（75 行，`BatchYieldTab.vue:17,206`）— 固定渐变背景，也非主题化。
  - 结构都是 4 卡片 grid（label/value/sub）+ `.toLocaleString()`。
- **动作**：
  1. [ ] 新建 `pages/dashboard/components/shared/KpiCardGrid.vue`，props：`items: { icon?, label, value, sub?, accent }[]`。
  2. [ ] 颜色全部走 CSS 变量（`--text-primary` 等），dark+light 自适应。
  3. [ ] 两个父组件各写 ~15 行 mapper 转换数据。
  4. [ ] 删除 `DashboardPage.vue:364` 的 night override hack。
  5. [ ] 双主题验证两个看板 + e2e。
- **省**：~70 行。**风险**：中（视觉差异需 accent/variant prop）。

### [ ] FE-1c. 两个 YieldTrendChart 重命名 + 走 useChart 【中风险・省 ~40 行】
- **现状**：同名但是两种不同图：
  - `dashboard/components/YieldTrendChart.vue`（247 行）— 自取数（`analysisApi.getYieldTrend`），单线 + SPC + 异常；手写 `echarts.init` + `_tc()/_ts()`。
  - `dashboard/components/batch/YieldTrendChart.vue`（135 行）— props 驱动多系列 bar+line；已用 `initEchartsWhenReady`（好范例）。
- **动作**：
  1. [ ] `dashboard/components/YieldTrendChart.vue` 重命名为 `FileYieldTrendChart.vue`，更新导入。
  2. [ ] 两者都改用 FE-3 的 `useChart` composable。
  3. [ ] dashboard 版采用 `initEchartsWhenReady` util。
- **省**：~40 行。**风险**：中（依赖 FE-3 先落地）。

## [x] FE-2. 统一异步数据 composable useAsyncData 【高优先・低中风险・省 ~120 行】✅ 7/9 composable 已迁移
- **现状**：`pages/analysis/composables/` 下 9 个 use*.ts 形状几乎一致：`loading=ref(false)` + `data=ref(null)` + `try{...}catch(e){console.error + ElMessage.error(e.response?.data?.error||'…')}finally{loading=false}`。
  - 参考：`useBoxPlot.ts:9-33`、`useCorrelationMatrix.ts:6-32`、`useFileCorrelation.ts:6-31`、`useMultiLot.ts:12-46`、`useParameterTrend.ts:11-44`。
  - 校验前缀 `ElMessage.warning('请…')` 也重复：`useBoxPlot.ts:13-16`、`useMultiLot.ts:17-25`、`useCorrelationMatrix.ts:11-14`。
- **动作**：
  1. [ ] 新建 `composables/useAsyncData.ts`：`useAsyncData<T>(fetcher, opts?:{successMsg?,errorMsg?,silent?})` → `{ loading, data, error, run }`，内部统一 try/catch/finally + ElMessage。
  2. [ ] 9 个 composable 逐个改写为「一行 guard + run(fetcher)」。
  3. [ ] 顺手统一 API 入口：部分用 `api.post(...)`（`useCorrelation.ts`/`useSiteStats.ts`/`useSerialDistribution.ts`），部分用 `analysisApi`（`useBoxPlot.ts`/`useParameterTrend.ts`）→ 统一到 `api/analysis.ts`。
  4. [ ] **注意**：`usePareto.ts:18-46` 仍返回 mock 数据（`// TODO 替换为实际API调用`）—— 此次顺便接真实 API。
- **省**：~120–150 行。**风险**：低中（机械替换）。

## [x] FE-3. 统一 ECharts 生命周期 composable useChart 【高优先・中风险・省 ~1,547 行・最大结构收益】✅ 全部 11/11 图表已迁移
- **现状**：~21 个组件用 echarts，11 个逐字节重复同样的样板：
  - 文件：`HistogramChart`、`BoxPlotChart`、`ParetoChart`、`QQPlotChart`、`SerialChart`、`ParameterTrendChart`、`CorrelationPanel`、`CorrelationMatrixPanel`、`MultiLotPanel`、`WaferMapPanel`、`distribution/MultiLotSection`、`dashboard/YieldTrendChart`。
  - 重复点：`_tc()` 取色行（11 文件，如 `HistogramChart.vue:10`）、`echarts.init`（`HistogramChart.vue:22-31`/`BoxPlotChart.vue:36-43`/`ParetoChart.vue:25-32`）、`resize`（`HistogramChart.vue:309-311` 等）、`onMounted/onUnmounted` 四钩子（`HistogramChart.vue:334-346`）、主题 watcher（`HistogramChart.vue:329-332`）。
  - **已有资产但大多没用**：`utils/echarts-init.ts`（`initEchartsWhenReady`，处理零尺寸 + ResizeObserver + dispose）、`utils/echarts-theme.ts`（`useEChartsTheme`，含 base option + 调色板 `:69-104`）。目前只有 `batch/YieldTrendChart.vue` 用了 init util。
- **动作**：
  1. [ ] 新建 `composables/useChart.ts`：`useChart(buildOption:()=>EChartsOption, watchSources:WatchSource[]) => { chartRef }`。内部：mount 时 `initEchartsWhenReady`、resize 监听、unmount dispose、watchSources + `themeStore.currentTheme` 变化重渲染。
  2. [ ] **先迁移 1 个**（建议 `ParetoChart`）作为样板，dark+light + tab 懒挂载验证。
  3. [ ] 逐个迁移其余 10 个图；用 `useEChartsTheme().colors.value.textColor` 替换 `_tc()`。
  4. [ ] 注意多坐标轴 / `chartInstance.clear()` 再 setOption 的图需特殊处理。
  5. [ ] 每迁移一个跑对应 e2e + 双主题。
- **省**：~450–600 行（约 40–55 行/图 × 11）。**风险**：中（分批迁移降险）。

## [ ] FE-4. 抽取格式化工具 utils/format.ts 【低风险・省 ~25 行】
- **现状**：`SftpFileTable.vue:113-137` 有 `formatSize/formatDate/getFileExt/isCsv`；`:row-class-name` fail 高亮在 `SiteStatsTable.vue:43-45`、`RangeComparisonTable.vue:39-53`、`DataBrowserAgGrid.vue:205-217` 重复。
- **动作**：
  1. [ ] 新建 `utils/format.ts`：`formatBytes/formatTimestamp/getFileExt/isCsv`。
  2. [ ] `SftpFileTable` 等改用。
  3. [ ] （可选）抽一个 fail-row class 工具。
- **省**：~25 行。**风险**：低。
- **注意（非去重，合规问题）**：`FileListTab.vue` **975 行，超 600 限制**，应拆分（toolbar / table / dialogs）—— 见已有 `tasks/todo.md` 文件管理整合计划，可一并处理。

## [ ] FE-5.（可选）API 层共享 cleanParams 【低风险・省 ~10 行】
- **现状**：API 层整体已很干净（`api/index.ts:3-30` 集中 axios 实例 + 401 拦截）。仅 `datafiles.ts:23-30` 有本地 `cleanParams`，`analysis.ts:23-26,33-35,51-53` 内联重复「有值才加参数」。
- **动作**：[ ] 抽 `api/utils.ts::cleanParams`，`analysis.ts` 复用。
- **省**：~10 行。**风险**：低。

## [ ] FE-6.（低优先）补全 components/common 桶导出 【低风险】
- **现状**：`components/common/index.ts` 仅导出 `Card/Button/Badge/Loading/Empty`；`CircularProgress/GridBackground/ThemeToggle` 未进 barrel，难以发现 → 易被重复造轮子。
- **动作**：[ ] 把这 3 个加入 `index.ts`；审查是否有手写 spinner/empty 应改用 `Loading/Empty`。
- **风险**：低。

## [ ] FE-7. 清理重复的 Element Plus 主题 :deep() 覆盖 【结论：跨文件 day-mode CSS 重复，非真正冗余，暂跳过】
- **调研结论**：`element-plus-theme.css` 只覆盖 night-mode（`:root[data-theme="night"]`），组件内 `:deep()` 管 day-mode。**无真正与主题文件重复的样式**。但 card/table/input 等 day-mode 样式在 4-7 个文件间复制（~126 行），可提取为共享 CSS 文件。净节省有限（~50 行），暂不执行。
- **现状**：全局 `styles/element-plus-theme.css`（669 行）已主题化 `.el-input/.el-select/.el-table/.el-pagination`（`:407-488`/`:443-466`），但组件内仍重复声明同样的 `:deep()` 覆盖：
  - `:deep(.el-input){--el-input-bg-color:...}`：`DataBrowser.vue:272-298`、`DataBrowserEnhanced.vue:215-231`、`DataBrowserAgGrid.vue:406-422`、`Topbar.vue`（4 文件）。
  - `--el-table-*`/`--el-pagination-*` 覆盖块：`FileListTab/SingleFileTable/BatchYieldTab/SftpBrowser/UserManagement/SettingsPage/DataBrowser/DataBrowserEnhanced`（9 文件）。
  - JS 侧 `themeStore.currentTheme==='night'` 散落各图，应改用 `useEChartsTheme().isDark`；内联 `isDark?'#hex':'#hex'`（`DataBrowserAgGrid.vue:209-212`、`dashboard/YieldTrendChart.vue:94,173,195`）应用 `echarts-theme.ts:69-104` 调色板。
- **动作**（FE-1a 删完后只剩 DataBrowserAgGrid + Topbar + 表格消费方）：
  1. [ ] 删除组件内冗余 `:deep(.el-input/.el-select/.el-table/.el-pagination)` 块。
  2. [ ] `_tc()/_ts()` → `useEChartsTheme()`（与 FE-3 合并做）。
  3. [ ] 内联 hex → 调色板。
  4. [ ] **逐组件**删 CSS 后做 dark+light 视觉回归。
- **省**：~120–180 行。**风险**：中。

---

# 第二部分：后端 (Django REST)

> 建议新增 `apps/common/` 包，存放 `file_loading.py` / `params.py` / `responses.py`；Excel 助手留在 `apps/export/excelize_helpers.py`；纯统计助手留在 `apps/analysis/services/statistics/`。

## BE-1. 重复的 view 模式（最大重复源）

### [x] BE-1a. 抽取「按 id 取文件 + 解析」样板 → apps/common/file_loading.py 【中风险・省 ~120–150 行】✅
- **现状**：`get_object_or_404(DataFile, pk=fid, owner=request.user)` + `get_cached_parsed_file(int(fid), request.user.pk)` + `if df is None` 出现 ~18 次：
  - `analysis/views.py:77-92`（好版本 `_load_df_from_request`，但私有未复用），又裸写于 `178-193`/`453-471`/`579-597`
  - `buyoff/views.py:30-37,69-84`、`gage/views.py:33-48`、`data_correlation/views.py:31-39`
  - `export/views.py:36-39,78-81,105-108,124-127,168-171`（5×）
  - `batch_report/views.py:100-101,332-335`、`dashboard/views.py:182-198`
- **动作**：
  1. [ ] 新建 `apps/common/file_loading.py`。
  2. [ ] `load_user_file(request, file_id) -> (df, datafile, metadata)`（泛化 `_load_df_from_request`）。
  3. [ ] `load_user_files(request, file_ids, *, only_bin1=False, min_count=None) -> list[dataset_dict]`（多文件循环，返回 `{'df','metadata','file_id','filename','timestamp'}`，统一 `analysis/views.py:463-469` 与 `581-595`）。
  4. [ ] 7 个 viewset 逐个替换，**注意各处 error 契约不同**（`'parse_failed'` vs `'file_not_found'`）需保持。
- **省**：~120–150 行。**风险**：中。

### [ ] BE-1b. only_bin1 过滤去重 【低风险・省 ~10 行】
- **现状**：`buyoff/views.py:74-79` 与 `gage/views.py:38-43` 逐字节相同（`get_bin_column_name` → `pd.to_numeric` → `df[bin==1]`）。
- **动作**：[ ] `file_loading.py::filter_bin1(df, format_type)` 或 `load_user_files(only_bin1=True)`。
- **省**：~10 行。**风险**：低。

### [x] BE-1c. col_meta / fail_mask 构建去重 【低风险・省 ~20 行】✅
- **现状**：`datafiles/views.py:595-604` 与 `analysis/views.py:326-335` 构建相同 `col_meta`（unit/min/max）；fail_mask（`detect_fail_data`→`{str(idx):cols}`）也重复（`datafiles/views.py:590-593`、`analysis/views.py:322-324`）。
- **动作**：[ ] 在 statistics 层加 `build_col_meta(df, metadata)` 与 `build_fail_mask(fail_cells)`。
- **省**：~20 行。**风险**：低。

### [ ] BE-1d.（可选）统一错误响应装饰器 【中风险・省 ~30 行】
- **现状**：大量手写 `return Response({'error':'x'}, status=400)`；仅 `dashboard/views.py:275-277` 有 try/except 包裹。
- **动作**：[ ] `apps/common/responses.py`：`@api_errors` 装饰器（异常→500）+ `err(code, status=400)` 快捷。
- **省**：~30 行。**风险**：中（改变失败语义，需谨慎）。

### [x] BE-1e. 提升参数助手到 common 【低风险・省 ~25 行】✅
- **现状**：`analysis/views.py` 有 `_getlist(55-64)`/`_to_float(67-74)`，但 `request.data.get(x) or request.query_params.get(x)` 在该文件内联 ~30 次。
- **动作**：[ ] 抽到 `apps/common/params.py`，各 view 复用。
- **省**：~25 行。**风险**：低。

## BE-2. Excel / openpyxl + excelize 导出去重

> `excelize_helpers.py` 已是良好共享模块（`gage_styles/buyoff/excel_builders/gage_summary_builder` 均导入 `make_header_style/make_data_style/save_excelize/to_native`）。剩余问题：

### [x] BE-2a. export_xlsx_optimized 复用共享样式 【低风险・省 ~60 行】✅
- **现状**：`export/export_xlsx_optimized.py:26-80` **重新内联定义**调色板 + `header/data/red/red_bin` 样式（应 import）；其中 `red_bin_style_id(70-80)` 与 `red_style_id(58-68)` **完全相同**，重复了 `excelize_helpers.py:28-70`。
- **动作**：[ ] 26-80 行替换为从 `excelize_helpers` import。
- **省**：~55 行。**风险**：低（输出一致）。

### [ ] BE-2b. 抽取共享 write_stats_block 【中风险・省 ~80 行】
- **现状**：Min/Avg/Max/Range/STD/CPK 统计块写 3 次：`excel_builders.py:90-120`、`export_xlsx_optimized.py:99-148`、`gage_summary_builder.py:308-357`，且都内联手算 CPK（又与 `compute_cpk` 重复，见 BE-3a）。
- **动作**：[ ] `excelize_helpers.py::write_stats_block(f, sheet, df, metadata, cols, start_row, layout=...)`，内部调 `compute_range_statistics` + `compute_cpk`；三处复用（layout 参数兼容行差异：export 5-10 行 / gage 115-128 行带 ±σ）。
- **省**：~80 行。**风险**：中。

### [ ] BE-2c. 合并重复的 data sheet builder 【中风险・省 ~150 行】
- **现状**：`excel_builders.build_to_excel_sheet(23-173)` 与 `export_xlsx_optimized.export_to_xlsx_optimized(14-217)` 产出**相同 sheet**（header/units/min-max/stats/data/红色 fail 高亮/冻结窗格/自动筛选），仅「外部 f 句柄 vs 自建自存」不同。`export/views.py:62` 用 optimized；`build_to_excel_sheet` 疑为死代码（`views.py:18` 导入但 `to_excel` 未调）。
- **动作**：
  1. [ ] 保留 `build_to_excel_sheet(f,...)` 为唯一实现。
  2. [ ] `export_to_xlsx_optimized` 改为薄包装（`f=new_file(); build_to_excel_sheet(f,...); return save_excelize(f)`）。
  3. [ ] **改前后跑 e2e 导出测试，比对字节级一致**（CLAUDE.md 规则）。
- **省**：~150 行。**风险**：中。

### [x] BE-2d. 边框工厂助手 【低风险・省 ~30 行】✅
- **现状**：`[excelize.Border(type=t,color=COLOR_BORDER,style=1) for t in (...)]` 在 `buyoff/excelize_layout.py:105,111,117`、`gage_summary_builder.py:237,241,244,249`、`excelize_helpers.py`（×5）、`export_xlsx_optimized.py`（×4）重复。
- **动作**：[ ] `excelize_helpers.thin_border(color=...)/medium_border()` 工厂。
- **省**：~30 行。**风险**：低。

## BE-3. 统计计算去重

### [x] BE-3a. Excel 内联 CPK 改走 compute_cpk 【低中风险・省 ~15 行 + 一致性】✅
- **现状**：`compute_cpk`（`computations.py:16-93`）为正典，但手算 CPK `min((max-avg)/(3*std),(avg-min)/(3*std))` 重现于 `excel_builders.py:110-112`、`export_xlsx_optimized.py:120-124`、`gage_summary_builder.py:352-357`。（`dashboard/views.py:101` 已正确用 `compute_cpk`。）
- **动作**：[ ] 三处 Excel builder 改用 `compute_cpk`（内联版忽略了 cpk_a/b/c 分级逻辑）。
- **省**：~15 行。**风险**：低中。

### [x] BE-3b. compute_pass_yield 助手 【低中风险・省 ~40 行 + 修 bug】✅
- **现状**：「Bin1 计数→pass，yield=pass/total*100」算 5 次：`dashboard/views.py:204-219`、`batch_report/views.py:108-125` 与 `338-349`、`export/views.py:131-139`、`analytics.py:142-153`（正典）。Bin1 判定 `int(float(bv))==1` vs `bn in ('1','Bin1')` 不一致 → **潜在 bug**。
- **动作**：[ ] `apps/analysis/services/statistics/limits.py::compute_pass_yield(bin_stats, total_rows) -> {pass_count,fail_count,yield_pct}`，统一一种 Bin1 判定，各处复用。
- **省**：~40 行。**风险**：低中（需测试确认判定正确）。

### [ ] BE-3c. 共享 bin label / sort 助手 【低风险・省 ~15 行】
- **现状**：`dashboard/views.py:25-67`（pandas crosstab）与 `batch_report/aggregation.py:42-90`（手动 dict）产出同形 Bin×Site 表（同服务 `BinSiteCrossTable.vue`），输入不同无法全并，但 `_format_bin_label`（`aggregation.py:33-39`≈`dashboard/views.py:51-54`）与 bin 排序键重复。
- **动作**：[ ] 共享 `format_bin_label()` / `bin_sort_key()`。
- **省**：~15 行。**风险**：低。

### [ ] BE-3d.（跟进）拆分 data_services.py（614 行，超限）
- **动作**：[ ] 审查 `analysis/services/data_services.py` 与 statistics 包重叠；按 histogram/wafer/multi-lot/cpk 子模块拆分至 600 行内。

## [x] BE-4. SFTP 复用 _register_file 【中风险・省 ~90 行 + 修 2 处缺字段 bug・高价值】✅
- **现状**：`sftp/views.py` 两处复制了 `datafiles/views.py:90-147 _register_file` 的整段逻辑（读头→`identify_format`→`parse`→`DataFile.create`→`ParseHistory.create`）：
  - `sftp/views.py:351-390`（`_single_download_parse`）
  - `sftp/views.py:429-469`（`_batch_download_parse`）
  - **缺陷**：两副本省略了 `_register_file` 的 `product_code`（`extract_product_code` line 132）与 `source_mtime` → 数据质量 bug。（`sftp/views.py:233 download_dir` 已正确调用 `_register_file`。）
- **实际结果**：`sftp/views.py` 517→432 行（-85），修复 2 个 `product_code` 丢失 bug。移除 `DataFile`/`ParseHistory`/`get_parser`/`BaseATEParser` 导入。
- [x] 1. 两个 `_*_download_parse` 改为调用 `_register_file`（已导入于 `sftp/views.py:9`）
- [x] 2. 移除不再需要的导入
- [x] 3. Python 语法验证通过

## [ ] BE-5. DataFileBaseSerializer 【低风险・省 ~20 行】
- **现状**：`datafiles/serializers.py:48-74 DataFileSerializer` 与 `77-101 DataFileListSerializer` 重复 4 个 `*_display = CharField(source='get_*_display')` + `validate_tags`，仅 `Meta.fields` 不同。
- **动作**：[ ] 抽 `DataFileBaseSerializer`（display 字段 + validate_tags），两者继承只声明 `Meta.fields`。
- **省**：~20 行。**风险**：低。

## [ ] BE-6. 杂项清理（非去重，合规/安全）
- [ ] 删除 `apps/gage/excelize_layout.py.bak`（18KB 死备份）。
- [ ] 拆分超 600 行文件：`gage_legacy_builder.py`（857）、`analytics.py`（720）、`data_services.py`（614）、`datafiles/views.py`（653）、`analysis/views.py`（604）—— BE-1/BE-2 的去重会直接帮助降行。
- [ ] 安全：`config/settings/base.py:90-99` Postgres 密码硬编码，应移至 `os.environ`（与已有的 SECRET_KEY/SFTP_CONFIG_KEY 一致）。

---

## 汇总优先级表

| 区域 | 任务 | 省行 | 风险 | 优先级 |
|---|---|---|---|---|
| FE-1a | 删死代码 DataBrowser×2 | 611 | 低 | **最优先** |
| FE-3 | useChart composable (~11 图) | 450–600 | 中 | 高 |
| FE-7 | 删冗余 EP 主题 :deep() | 120–180 | 中 | 高 |
| FE-2 | useAsyncData (9 composable) | 120–150 | 低中 | 高 |
| FE-1b | KpiCardGrid 合并 (+修 night hack) | ~70 | 中 | 中 |
| FE-1c | 两 YieldTrendChart 走 useChart | ~40 | 中 | 中 |
| FE-4 | utils/format.ts | ~25 | 低 | 低 |
| FE-5 | API cleanParams | ~10 | 低 | 低 |
| FE-6 | 补全 common barrel | — | 低 | 低 |
| BE-4 | SFTP 复用 _register_file (+修 bug) | 90(+25) | 中 | **高** |
| BE-1a | file_loading.py | 120–150 | 中 | 高 |
| BE-2c | 合并 data sheet builder | 150 | 中 | 中 |
| BE-2b | write_stats_block | 80 | 中 | 中 |
| BE-2a | optimized 复用样式 | 55 | 低 | 高(易) |
| BE-3b | compute_pass_yield (+修 bug) | 40 | 低中 | 高 |
| BE-2d | 边框工厂 | 30 | 低 | 低 |
| BE-1d | 错误响应装饰器 | 30 | 中 | 低 |
| BE-1e | params 助手提升 | 25 | 低 | 中 |
| BE-1c | col_meta/fail_mask | 20 | 低 | 中 |
| BE-5 | DataFileBaseSerializer | 20 | 低 | 中 |
| BE-3a | Excel CPK 走 compute_cpk | 15 | 低中 | 中 |
| BE-3c | bin label/sort 助手 | 15 | 低 | 低 |
| BE-1b | only_bin1 去重 | 10 | 低 | 中 |

**前端合计 ~1,450–1,700 行；后端合计 ~700–730 行；总计 ~2,150–2,430 行。**
**附带修复**：SFTP 缺 product_code/source_mtime（BE-4）、Bin1 判定不一致（BE-3b）。

---

## Review（进度记录）

### 2026-06-07 批次 1

| 任务 | 改了什么 | 实际省行 | 验证 |
|---|---|---|---|
| BE-2a | `export_xlsx_optimized.py` 内联样式+save 替换为 `excelize_helpers` import | 217→157（省60） | `python -c "import"` OK |
| BE-2d | `gage_summary_builder.py`(4处) + `buyoff/excelize_layout.py`(3处) border 改用 `thin_border()` | ~30 | import OK |
| BE-3a | `excel_builders.py` + `export_xlsx_optimized.py` + `gage_summary_builder.py` CPK 改用 `compute_cpk()` | ~15 | import OK |
| BE-3b | 5处 yield 计算统一为 `compute_pass_yield()`（dashboard/batch_report×2/analytics/export），修复 batch_report `sum(1 for...)` bug | ~40 | import OK |
| BE-1c | `datafiles/views.py` + `analysis/views.py` fail_mask/col_meta 改用 `build_fail_mask()`/`build_col_meta()` | ~20 | import OK |
| FE-3 | `useChart` composable 创建 + 6/11 图表迁移（Pareto/QQPlot/BoxPlot/Serial/ParamTrend/Histogram） | ~550（原~1810→~1260，含新 composable 83行） | `vue-tsc --noEmit` 通过 |

**本批次实际节省**：后端 ~165 行，前端 ~467 行（含新文件），**合计 ~632 行**。
**新文件**：`apps/analysis/services/statistics/limits.py` 新增 ~70 行 helper；`frontend/src/composables/useChart.ts` 新增 83 行。
| FE-3续 | 完成剩余 5 图表迁移（CorrelationMatrix/Correlation/MultiLot/WaferMap/YieldTrend） | ~988 行（含之前共 ~1,547 行净省） | `vue-tsc --noEmit` 通过 |

| FE-2 | `useAsyncData` composable 创建 + 7/9 composable 迁移 | ~120 行（含新文件 64 行） | `vue-tsc --noEmit` 通过 |

**累计节省**：后端 ~165 行 + 前端 ~1,667 行 = **~1,832 行**。
**待继续**：FE-7（主题去重）、FE-1b（KpiCards 合并）、BE-4（SFTP）、BE-1a（file_loading）等。

### 2026-06-07 批次 2

| 任务 | 改了什么 | 实际省行 | 验证 |
|---|---|---|---|
| BE-4 | `sftp/views.py` `_single_download_parse` + `_batch_download_parse` 内联注册替换为 `_register_file()`，修复 2 个 `product_code` 丢失 bug | 517→432（-85） | Python syntax OK |
| BE-1a | 创建 `apps/common/` 包（`file_loading.py` + `params.py`），`export/views.py` 5 处文件加载改用 `load_user_file()` | 191→184（-7）+ 新增 ~120 行共享代码 | Python syntax OK |
| BE-1e | `analysis/views.py` 移除 `_getlist`/`_to_float`，~20 处内联参数提取改用 `get_param()`/`get_param_float()`/`get_param_list()` | 595→573（-22） | Python syntax OK |

**本批次实际节省**：后端 ~114 行（sftp -85, analysis -22, export -7），新增共享代码 ~120 行。
**新文件**：`apps/common/__init__.py`、`apps/common/file_loading.py`（66 行）、`apps/common/params.py`（46 行）。

**累计节省**：后端 ~279 行 + 前端 ~1,667 行 = **~1,946 行**。
**附带修复**：SFTP `product_code` 丢失 bug ×2（BE-4）、Bin1 判定不一致（BE-3b，批次 1）。
**待继续**：FE-1b（KpiCards 合并）、BE-1b（only_bin1）、BE-2b/2c（Excel 合并）、BE-5（Serializer）等。
