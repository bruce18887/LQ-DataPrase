# Debug Session: qqplot-sw-bin-bug
- **Status**: [RESOLVED]
- **Issue**: 在 `gage_m_S4.csv`（或同源 gage 文件）下选中测试项 `SW_Bin` → 勾选「显示QQ图」→ 前端报 `Cannot read properties of null (reading 'toFixed')`。
- **Debug Server**: http://127.0.0.1:7777 (started: 2026-06-13, stopped: 2026-06-13)
- **Log File**: .dbg/trae-debug-log-qqplot-sw-bin-bug.ndjson
- **Created**: 2026-06-13
- **Resolved**: 2026-06-13
- **Previous session**: debug-qq-boxplot-null-emits-error.md (RESOLVED，覆盖 BoxPlotChart + QQPlotChart 的 emitsOptions 主路径，但没覆盖到 QQPlotStatsTable 的 null r_squared)

## 用户报告

> 但是我试了下QQ图显示SW_Bin测试项还是会报错

复现路径：
1. 登录 → `/analysis`
2. 选 `gage_m_S4.csv`（其它 gage_m_S*.csv 同理）
3. 参数下拉选 `SW_Bin`
4. 勾选「显示QQ图」
5. 浏览器控制台抛 `Cannot read properties of null (reading 'toFixed')`（用户在描述里说"emitsOptions null"，实际是同一时刻 Vue 异步 patch 链上另一处冒出的症状）

## 关键代码位置
- QQ 组件：[QQPlotChart.vue](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/src/pages/analysis/components/QQPlotChart.vue)
- QQ 计算后端：[apps/analysis/services/statistics/computations.py:303-350](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/apps/analysis/services/statistics/computations.py#L303-L350)
- QQ API 视图：[apps/analysis/views.py:354-386](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/apps/analysis/views.py#L354-L386)
- **Stats Table 组件（**根因**）**：[frontend/src/pages/analysis/components/QQPlotStatsTable.vue:32](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/src/pages/analysis/components/QQPlotStatsTable.vue#L32)

## 假设与验证

| ID | 假设 | 可能性 | 验证手段 | 证据状态 |
|----|------|--------|----------|----------|
| A | 后端 qqplot/boxplot 对 `SW_Bin` 抛 500 | 中 | curl + Django 日志 | ✗ 后端 200 OK，response 形态见下 |
| B | `SW_Bin` 是 soft-bin 列（soft_bin / pass_fail 类离散整型），不是连续数值列。`pd.to_numeric(errors='coerce')` 转 float 后 `scipy.stats.probplot` 在所有 y 值相同时返回 NaN r → JSON null。前端 `r_squared.toFixed(4)` 崩 | **高** | 看后端响应（r_squared=null, observed_quantiles 100 个 1.0）；看前端调用栈 | ✓ **确证** |
| C | `SW_Bin` 没有 limit（LSL/USL） | 中 | 看后端 logic | ✓ 确认无 limit，但与本 bug 无关——QQ 图不需要 limit |
| D | 上次 fix 在 `QQPlotChart` 加的 `v-else-if` + `useChart` 重建守卫仍有 race | 中 | 复现时观察 | ✗ QQ plot 本身不崩；只是同一时刻 Vue 异步 patch 上另一处也冒头 |
| E | ParamSelector 切到 `SW_Bin` 时，`localSelectedParam` 短暂变 `''` 又 set 回，触发 `prevVNode.component = null` | 低 | 在 `localSelectedParam` watcher 前后打 log | ✗ D-SPT 日志显示 watcher 仅触发一次 |

## 根因分析（Root Cause）

**`SW_Bin` 是 soft-bin 分类列，在 `gage_m_S4.csv` 中所有 100 行值均为 1.0**——这是量具 R&R 数据里"软分类"列的典型特征（pass = 1）。

后端 `compute_qqplot` 把所有 y 值排序后跑 `scipy.stats.probplot(clean, dist='norm', fit=True)`。当 y 全部相同时，相关系数 r 是 NaN（变量方差为 0 → 协方差 = 0 → 0/0）；后端 `clean_data` 把 NaN 序列化成 JSON `null`，于是响应是：

```json
{
  "theoretical_quantiles": [-2.46, ..., 2.46],   // 100 个
  "observed_quantiles": [1.0, 1.0, ..., 1.0],     // 100 个全 1.0
  "r_squared": null,                              // ← 关键
  "is_normal": false,
  "n": 100
}
```

前端拿到 `qqResult`（非 null），SingleParamTab 同时挂载 [QQPlotChart](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/src/pages/analysis/components/QQPlotChart.vue) 和 [QQPlotStatsTable](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/src/pages/analysis/components/QQPlotStatsTable.vue)。**QQPlotStatsTable 的 `tableData` computed 在第一行**：

```typescript
{ label: 'R²', value: props.result.r_squared.toFixed(4) },
//                                       ^^^^^^^^^^ 炸了
```

`r_squared` 是 `null`，`.toFixed(4)` 抛 `TypeError: Cannot read properties of null (reading 'toFixed')`。

错误是同步抛在 Vue 的渲染函数里，污染了 Vue 的 patch 链；同一个 microtask 里 `QQPlotChart` 的 `v-else` 分支刚换上 chart container，`prevVNode.component` 还来不及挂上，于是用户看到的是上一次会话出现的同款 `Cannot read properties of null (reading 'emitsOptions')` 错误——但**根因是 `QQPlotStatsTable` 的 `toFixed`**，emitsOptions 是它引发 Vue 异步链崩坏后的次级症状。

> 用户原始判断的修正：用户说"QQ图显示SW_Bin测试项还是会报错"，并猜测"参数不能解析"。参数脏数据仍然必要（让 `r_squared` 变 null），但**根因在前端展示组件的 `toFixed` 守卫缺失**——不是 chart 渲染，是 stats table。修复必须从"`r_squared` 可能为 null，加 `Number.isFinite` 守卫"入手。

## 修复实施（Fix Implementation）

### Fix 1 — QQPlotStatsTable 加 null/NaN 守卫（**根因**）
[QQPlotStatsTable.vue:18-41](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/src/pages/analysis/components/QQPlotStatsTable.vue#L18-L41)

```typescript
interface QQPlotResult {
  r_squared: number | null          // ← 改类型
  is_normal: boolean
  n: number
}

const tableData = computed(() => {
  if (!props.result) return []
  // r_squared may be null when all observed values are identical (e.g. soft-bin
  // columns like SW_Bin with constant value 1.0) — scipy.stats.probplot returns
  // NaN for the correlation coefficient, which JSON-serializes to null.
  const r2 = props.result.r_squared
  const r2Text = typeof r2 === 'number' && Number.isFinite(r2) ? r2.toFixed(4) : 'N/A'
  return [
    { label: 'R²', value: r2Text },
    { label: '正态性', value: props.result.is_normal ? '正态' : '非正态' },
    { label: '样本量', value: props.result.n },
  ]
})
```

QQPlotChart 里的 `rSquared.toFixed(4)` 已经在 `if (rSquared != null)` 守卫下，**无需修改**。

## 日志证据

### 修复前（pre-fix log）
- 后端响应：r_squared = null
- 前端：第一次 sw-bin-qqplot-repro e2e 报
  ```
  [pageerror] Cannot access 'props' before initialization  ← instrumentation bug, 噪音
  [pageerror] Cannot read properties of null (reading 'toFixed')  ← 真正 bug
  ```
- Debug Server D-QR 日志显示 `rSquaredIsNull: true, observedAllSame: true`，loadQQPlot:ok 拿到 100 理论点
- chart canvas count = 0（QQPlotChart 还没渲染就被 stats table 抛错打断）

### 修复后（post-fix log）
- 后端响应：同上
- 前端：4 passed (41.7s)，无 pageerror
- Debug Server D-QR 日志（修复时）：
  ```
  D-SPT loadQQPlot:ok param=SW_Bin rSquaredNull=true n=100 theoreticalCount=100
  D-QR render-state hasResult=true rSquaredIsNull=true observedAllSame=true
  D-UC ensureInit:new-instance chartRefIs="<div ... class=\"qqplot-container\">" hasChart=true
  D-UR renderOption seriesType=scatter seriesDataCount=100 xMin=-2.462038 yMin=1
  ```
  ← **QQ plot 成功渲染 100 个 scatter 点**

### 清理后验证（最终 e2e）
- 6 passed (54.9s) —— sw-bin-qqplot-repro.spec.ts (2) + gage-qqbox-repro.spec.ts (4) 全部通过
- 零 pageerror

## 验证结论

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 选 SW_Bin → 显示 QQ → pageerror | 1 条 `null.toFixed` | 0 |
| QQ plot 是否渲染 | 否（被 stats table 抛错打断） | 是，100 scatter points |
| 既有 gage-qqbox-repro 测试 | 已过（无关 SW_Bin 路径） | 仍过 |

## Lesson Learned（已追加到 [lessons.md](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/tasks/lessons.md)）

- **JSON 序列化的 NaN = null**——后端 `scipy.stats` / `numpy` 返回的 `NaN` 经 DRF 序列化成 JSON `null`，前端所有"展示用"的 `.toFixed()` / `.toLocaleString()` 都**必须**用 `Number.isFinite` 守卫，不能写 `value.toFixed(4)`。
- **TypeScript `number` 类型不是"运行时安全"**——`interface { r_squared: number }` 在编译期不会拒绝 `null`，运行时 `.toFixed()` 必崩。模式：所有来自后端 JSON 的数值字段类型用 `number | null`，渲染时用 `typeof x === 'number' && Number.isFinite(x)` 守卫。
- **用户报告的"emitsOptions null"是次级症状**——同一时刻 Vue 异步 patch 链崩坏可能让多个错误一起冒头。**先抓 `pageerror` 里最早抛的那个**，再顺着找根因；不要被"上一次会话修过的同款症状"误导。
- **e2e 必须覆盖"脏数据 + 正常数据"两条路径**——上一会话的 `gage-qqbox-repro.spec.ts` 只用 5 个"好"参数，没覆盖 soft-bin / 离散 / 全同值路径，结果 SW_Bin 这条用户常选路径成了盲点。**回归测试套件要包含至少一个"脏数据"用例**。
