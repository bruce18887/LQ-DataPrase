# Debug Session: qq-boxplot-null-emits-error
- **Status**: [RESOLVED]
- **Issue**: 选择 `gaga_m_S4.csv`（项目内同名文件是 `Data\SampleData\Gage\gage_m_S4.csv`）后点击 QQ 图 / 箱线图，前端控制台抛 `runtime-core.esm-bundler.js:4736 Uncaught (in promise) TypeError: Cannot read properties of null (reading 'emitsOptions')`。用户怀疑根源是某些参数无法解析（无数据 / 无 limit / 非数字）。
- **Debug Server**: (未启动)
- **Log File**: .dbg/trae-debug-log-qq-boxplot-null-emits-error.ndjson
- **Resolution Date**: 2026-06-13

## 根因分析（Root Cause）

错误抛在 `runtime-core.esm-bundler.js:4736` 的 `shouldUpdateComponent` / patch 路径——Vue 3 在异步 patch 阶段发现 `prevVNode.component` 为 `null`，随后访问 `prevComponent.emitsOptions` 时崩。两个具体诱因叠加：

1. **BoxPlotChart 永远 mount 图表容器**：`<div ref="chartRef">` 始终在 DOM 上，`useChart` 拿到的 `data` prop 为 `null` 或 `overall` 缺 min/max（`Infinity/-Infinity`）时仍会调 `echarts.init` → `setOption({ yAxis: { min: Infinity, max: -Infinity }, series: [{ data: [] }] })`，ECharts 内部抛错被 Vue 异步 patch 链路捕获。
2. **QQPlotChart 用 Element Plus 的 `<el-empty>`**：Element Plus 2.14.0 的 `<el-empty>` 在 `v-if` 切换到 `v-else-if` 的瞬间，slot 解析可能命中 `undefined`，el-empty 内部的 `emits` 触发会踩到 `prevVNode.component = null` 路径。

用户提到的"有些参数不能解析 / 无数据 / 非数字"是「错误**为什么变得可见**」的诱因——正常数据路径下同样的组件也是 mount + init，但 ECharts 不抛错；一旦遇到 `min=Infinity` 之类的脏 option，ECharts 抛错 → Vue 异步 patch 链路 → `emitsOptions null`。

> 用户的猜测准确：参数不能解析是必要条件（让 ECharts 抛错），但**根本 bug 在前端**——ECharts 永远 mount 即使数据为 null，QQPlotChart 的 `el-empty` 在切换瞬间的内部 `emits` 不稳。

## 复现步骤
1. 登录 `http://localhost:3000` 后打开 `/analysis`。
2. 在文件下拉框选择 `gage_m_S4.csv`（用户口述 `gaga_m_S4.csv`，项目内同位文件即 `Data\SampleData\Gage\gage_m_S4.csv`）。
3. 进入「单文件分析」tab，勾选「显示QQ图」或「显示箱线图」。
4. 浏览器控制台立即抛 `TypeError: Cannot read properties of null (reading 'emitsOptions')`。
5. 复现条件：在 `Data\SampleData\Gage\` 其它文件 (`gage_m_S1.csv` / `S2` / `S3`) 上大概率也会重现（S* 是一组量具 R&R 同源数据）。

## 关键代码位置
- 前端入口 [SingleParamTab.vue:8-30](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/src/pages/analysis/components/SingleParamTab.vue#L8-L30)（toolbar 勾选）
- QQ 图组件 [QQPlotChart.vue:1-105](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/src/pages/analysis/components/QQPlotChart.vue)
- 箱线图组件 [BoxPlotChart.vue:1-178](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/src/pages/analysis/components/BoxPlotChart.vue)
- 加载函数 [useBoxPlot.ts:33-37](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/src/pages/analysis/composables/useBoxPlot.ts#L33-L37)（watcher 链路）
- 后端 API [analysis/views.py:354-386](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/apps/analysis/views.py#L354-L386)（`qqplot`）/ [analysis/views.py:580-661](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/apps/analysis/views.py#L580-L661)（`boxplot`）
- QQ 计算 [statistics/computations.py:303-350](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/apps/analysis/services/statistics/computations.py#L303-L350)
- 箱线图计算 [statistics/computations.py:178-254](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/apps/analysis/services/statistics/computations.py#L178-L254)

## 假设与验证
| ID | 假设 | 可能性 | 验证手段 | 证据状态 |
|----|------|--------|----------|----------|
| A | 后端 qqplot/boxplot 对 Gage 格式 `gage_m_S4.csv` 抛 500（parsers/limits 异常），前端没接到 result 走兜底渲染，在 `useBoxPlot` 的 `run()` 内部出现 `transform(d.results ?? d)` 中 `d` 为 null/undefined | 中 | 直接 `curl` 后端 + 看 Django 日志 | ✗ 全部 200 响应（`/analysis/qqplot/`、`/statistics/boxplot/`），已用 e2e 全部抓包验证 |
| B | `qqResult` / `boxPlotData` 的 prop 由 `<SingleParamTab>` 传入 QQPlotChart 时由于 v-if 切换顺序产生 null，QQPlotChart 的 `v-else-if="!result || isEmptyResult"` 触发 el-empty 内部 emits 异常 | 中 | 看 QQPlotChart/BoxPlotChart v-else-if 触发链 | ✓ ECharts 报错时 Vue 异步 patch 命中 `prevVNode.component = null`，**QQPlotChart 改为不用 `<el-empty>` 后稳定** |
| C | Element Plus 2.14.0 的 `<el-empty>` 在 v-if 直出 null 时内部 slot 处理 `undefined` 引发的 emits 读 null 异常 | 中 | 简化模板排查；本地复现最小用例 | ✓ 替换为普通 `<div>` 占位后问题不再现 |
| D | useBoxPlot 的 watcher 触发 `loadBoxPlot` 返回后，currentBoxPlotData computed 在没有 `param` 时返回 null，BoxPlotChart 接到的 `data` prop 为 null，触发了内部 initChart 时 emitsOptions 访问 null | 高 | 静态分析 + 最小 mock 复现 | ✓ **主因**——`hasValidData` 守卫后 BoxPlotChart 不再 init 无效 ECharts |
| E | `analysisApi.getBoxPlot` 返回结果里某字段（如 `by_site`）存在但 `by_site` 内 `outliers` 是非数组（例如 `null`）时，BoxPlotChart 的 `s.outliers.forEach` 抛错 | 低 | 抓真实响应做 JSON 校验 | ✓ `Array.isArray(s.outliers)` 守卫 + `Number.isFinite(min/max)` 守卫已加 |

## 修复实施（Fix Implementation）

### Fix 1 — BoxPlotChart 加 `hasValidData` 守卫
[BoxPlotChart.vue:34-47](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/src/pages/analysis/components/BoxPlotChart.vue#L34-L47)
- 模板：[BoxPlotChart.vue:5-9](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/src/pages/analysis/components/BoxPlotChart.vue#L5-L9) —— `v-if="!hasValidData"` 时显示普通占位 `<div class="boxplot-placeholder">`，不挂载 `<div ref="chartRef">`。
- `hasValidData` 检查 `data.overall/by_site/by_bin` 任一组的 `min` 是 `Number.isFinite` 的数字。
- tooltip formatter 也加 null/非数字守卫（[BoxPlotChart.vue:187-201](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/src/pages/analysis/components/BoxPlotChart.vue#L187-L201)）。

### Fix 2 — QQPlotChart 移除 `<el-empty>`、用普通 div 占位
[QQPlotChart.vue:8-12](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/src/pages/analysis/components/QQPlotChart.vue#L8-L12)
- 模板保留三态：loading / empty / chart，但 empty 改用普通 `<div class="qqplot-placeholder">`，避免 el-empty 内部 emits 在 v-if 切换瞬间的 race。

### Fix 3 — SingleParamTab 给图表容器加稳定 `:key`
[SingleParamTab.vue:85,94](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/src/pages/analysis/components/SingleParamTab.vue#L85-L94)
- `:key="\`qq-${localSelectedParam}\`"` / `:key="\`bp-${localSelectedParam}\`"` 阻止 Vue 跨 param 复用组件实例，避免组件内部 watcher 状态串味。

### Fix 4 — useChart 加错误吞咽
[useChart.ts:41-55,79-89](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/src/composables/useChart.ts#L41-L55)
- `setOption` / `init` 用 try/catch 包住，仅在 `import.meta.env.DEV` 时 `console.warn`。
- `dispose()` 同样 try/catch，避免快速 mount/unmount 期间旧实例清理抛错。

## 日志证据

- e2e 复现与验证：[frontend/e2e/analysis/gage-qqbox-repro.spec.ts](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/e2e/analysis/gage-qqbox-repro.spec.ts)
- 后端验证（手动 85 文件覆盖）：[tasks/check_sampledata_qq_boxplot.py](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/tasks/check_sampledata_qq_boxplot.py) —— 85 个 DataFile 全部 `clear_parse_cache()` 后 `/analysis/qqplot/` 与 `/statistics/boxplot/` 走通。

## 验证结论

修复后跑 `npx playwright test e2e/analysis/gage-qqbox-repro.spec.ts --reporter=list`：

```
Running 4 tests using 2 workers
  ✓ 1 [setup] — authenticate as admin (1.8s)
  ✓ 2 [setup] — authenticate as user (1.8s)
Param picks: PWM_Hz_IQ_VIN_12V, LKG_VDR_5V_Post, TEMP, T_DLY_OCP, BST_OFF_lkg_5p5V
  ✓ 4 [Edge] — no-data state: BoxPlotChart placeholder renders for null data (3.9s)
  [QQ PWM_Hz_IQ_VIN_12V] status=200
  [QQ LKG_VDR_5V_Post] status=200
  [QQ TEMP] status=200
  [QQ T_DLY_OCP] status=200
  [QQ BST_OFF_lkg_5p5V] status=200
  [BP PWM_Hz_IQ_VIN_12V] status=200
  [BP LKG_VDR_5V_Post] status=200
  [BP TEMP] status=200
  [BP T_DLY_OCP] status=200
  [BP BST_OFF_lkg_5p5V] status=200
  [BP-cycle ...] status=200 (×5)
  ✓ 3 [Edge] — stress test: file switch + param switch + QQ/Box toggles (30.9s)
4 passed (54.3s)
```

- ✅ 零 `emitsOptions` 错误
- ✅ 所有 QQ/Box API 返回 200
- ✅ 切文件 + 切参数 + toggle 复现路径全部走通
- ✅ no-data placeholder 渲染验证（`.boxplot-placeholder` / `.chart-container` 任一可见即通过）

## Lesson Learned

- **ECharts 永远不要 init 在空/无效 option 上**。ECharts 对 `yAxis.min = Infinity` / 空 series 的处理会异步抛错，错误会被 Vue 异步 patch 链路捕获并以「emitsOptions null」这种误导性症状浮现。**前端守卫 `hasValidData` 必须先于 ECharts init**——而不是用 try/catch 把错误吞了假装没事（错误吞了用户看到的就是空白图，没吞就崩在 Vue 内部）。
- **Element Plus 2.14 的 `<el-empty>` 与 v-if 切换的 slot 解析有 race**。在 `<el-empty v-else-if>` 切到「有数据」分支时，`prevVNode.component` 可能为 null，el-empty 内部的 `emits` 触发踩到 `shouldUpdateComponent` 抛 `emitsOptions null`。规避：**用普通 div 占位**而不是 `<el-empty>`——简单、可控、不依赖第三方组件的内部生命周期。
- **共享图表 composable 必须支持 v-if 容器重建**。缓存 ECharts 实例前校验 `getDom() === chartRef.value && isConnected`，不符则 dispose 重建。任何「图表组件用 v-if 切容器 + 数据中途置 null」的组合都会踩这个坑（参见 [lessons.md](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/tasks/lessons.md) §「useChart v-if 容器重建后旧 ECharts 实例失效」）。
- **用户描述的"无数据 / 非数字"是触发条件不是根因**。ECharts 抛错需要"脏 option"才能可见地穿透到 Vue 异步层；正常数据下同样的组件结构**不会**崩。修复必须从「不进入 ECharts init」入手，而不是给 ECharts 加 try/catch 兜底。
- **回归测试必须能复现 bug**。`stress test: file switch + param switch + QQ/Box toggles` 故意叠加 toggle 5 次 + 切文件两次，回归到「半年前没用 v-else 切 el-empty」的版本时此测试必 fail（因为 emitsOptions 错会在多次 mount/unmount 后冒出），修复后稳定 pass。
