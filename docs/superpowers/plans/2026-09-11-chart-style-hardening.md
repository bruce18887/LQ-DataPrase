# 图表风格硬伤修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复数据分析页 3 项图表硬伤——多文件箱线图补 saveAsImage、晶圆图 title 补 textStyle、统一 6 处 saveAsImage 属性。

**Architecture:** 在 `chart-bar.ts` 抽 `buildChartToolbox` 共享 helper（统一 saveAsImage 三属性 name+title+pixelRatio），7 张图表接入；纯前端 ECharts option 属性改动，无后端/数据流变更。

**Tech Stack:** Vue 3 + TypeScript + ECharts 6 + Playwright（e2e）。前端无 unit test 框架，验证走 `vue-tsc` 类型检查 + `npm run build` + e2e 读 ECharts 实例 option 断言。

**Spec:** `docs/superpowers/specs/2026-09-11-chart-style-hardening-design.md`

---

### Task 1: chart-bar.ts 新增 buildChartToolbox helper

**Files:**
- Modify: `frontend/src/utils/chart-bar.ts`（文件末尾，`mapLotColorToTheme` 之后追加）

- [ ] **Step 1: 追加 helper**

在 `chart-bar.ts` 末尾（`mapLotColorToTheme` 函数之后）追加：

```ts
/**
 * 各分析图表统一的 toolbox 构建（2026-09-11 图表风格硬伤修复）。
 *
 * saveAsImage 三属性齐备：name（下载文件名）+ title（按钮提示，统一「保存图片」）
 * + pixelRatio:2（高清导出，与晶圆图看齐）。此前柱状图家族只设 name、散点/晶圆
 * 只设 title、pixelRatio 仅晶圆设，导出体验不一致。
 *
 * extra 叠加各图特有 feature（散点 restore、晶圆 dataZoom+restore），保持现状；
 * right/top 位置各图保持现状（不传则 ECharts 默认右上角），规避 title 布局冲突。
 */
export interface ChartToolboxOptions {
  /** 下载文件名（不含扩展名），如 `${param}_分析` */
  name: string
  /** 叠加各图特有 feature（restore/dataZoom 等），与 saveAsImage 合并 */
  extra?: Record<string, unknown>
  /** toolbox 水平位置（不传则 ECharts 默认右上角） */
  right?: number | string
  /** toolbox 垂直位置 */
  top?: number | string
}

export function buildChartToolbox(opts: ChartToolboxOptions): Record<string, unknown> {
  const toolbox: Record<string, unknown> = {
    feature: {
      saveAsImage: { name: opts.name, title: '保存图片', pixelRatio: 2 },
      ...(opts.extra ?? {}),
    },
  }
  if (opts.right != null) toolbox.right = opts.right
  if (opts.top != null) toolbox.top = opts.top
  return toolbox
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend; npx vue-tsc --noEmit`
Expected: 0 错误（helper 未被消费时可能有"未使用"提示属正常，Task 2-5 消费后消失）

- [ ] **Step 3: Commit**

```bash
git add frontend/src/utils/chart-bar.ts
git commit -m "feat(chart-utils): 新增 buildChartToolbox 统一图表 toolbox"
```

---

### Task 2: 柱状图家族 4 图接入 helper

**Files:**
- Modify: `frontend/src/pages/analysis/components/HistogramChart.vue`（import L14, toolbox L293）
- Modify: `frontend/src/pages/analysis/components/MultiFileChart.vue`（import L8, toolbox L253）
- Modify: `frontend/src/pages/analysis/components/SerialChart.vue`（import L36, toolbox L171）
- Modify: `frontend/src/pages/analysis/components/QQPlotChart.vue`（import L33, toolbox L156）

- [ ] **Step 1: HistogramChart.vue**

import 行（L14）追加 `buildChartToolbox`：

```ts
// before
import { clampBarValue, formatPercent, formatAxisValue, getBarGroupPad, getMaxBarWidthPercent, getSiteColors8 } from '../../../utils/chart-bar'
// after
import { clampBarValue, formatPercent, formatAxisValue, getBarGroupPad, getMaxBarWidthPercent, getSiteColors8, buildChartToolbox } from '../../../utils/chart-bar'
```

toolbox 行（L293）替换：

```ts
// before
    toolbox: { feature: { saveAsImage: { name: `${props.selectedParam}_分析` } } },
// after
    toolbox: buildChartToolbox({ name: `${props.selectedParam}_分析` }),
```

- [ ] **Step 2: MultiFileChart.vue**

import 行（L8）追加 `buildChartToolbox`：

```ts
// before
import { clampBarValue, formatPercent, formatAxisValue, getBarGroupPad, getMaxBarWidthPercent, mapLotColorToTheme } from '../../../utils/chart-bar'
// after
import { clampBarValue, formatPercent, formatAxisValue, getBarGroupPad, getMaxBarWidthPercent, mapLotColorToTheme, buildChartToolbox } from '../../../utils/chart-bar'
```

toolbox 行（L253）替换：

```ts
// before
    toolbox: { feature: { saveAsImage: { name: `${props.selectedParam}_多文件对比` } } },
// after
    toolbox: buildChartToolbox({ name: `${props.selectedParam}_多文件对比` }),
```

- [ ] **Step 3: SerialChart.vue**

import 行（L36）追加 `buildChartToolbox`：

```ts
// before
import { formatAxisValue, getSiteColors8 } from '../../../utils/chart-bar'
// after
import { formatAxisValue, getSiteColors8, buildChartToolbox } from '../../../utils/chart-bar'
```

toolbox 行（L171）替换（保留现有 `${param}` 变量名，不动其他）：

```ts
// before
    toolbox: { feature: { saveAsImage: { name: `${param}_Serial分布` } } },
// after
    toolbox: buildChartToolbox({ name: `${param}_Serial分布` }),
```

- [ ] **Step 4: QQPlotChart.vue**

import 行（L33）追加 `buildChartToolbox`：

```ts
// before
import { formatAxisValue } from '../../../utils/chart-bar'
// after
import { formatAxisValue, buildChartToolbox } from '../../../utils/chart-bar'
```

toolbox 行（L156）替换：

```ts
// before
    toolbox: { feature: { saveAsImage: { name: `${props.param}_QQ图` } } },
// after
    toolbox: buildChartToolbox({ name: `${props.param}_QQ图` }),
```

- [ ] **Step 5: 类型检查**

Run: `cd frontend; npx vue-tsc --noEmit`
Expected: 0 错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/analysis/components/HistogramChart.vue frontend/src/pages/analysis/components/MultiFileChart.vue frontend/src/pages/analysis/components/SerialChart.vue frontend/src/pages/analysis/components/QQPlotChart.vue
git commit -m "refactor(charts): 柱状图家族 4 图接入 buildChartToolbox"
```

---

### Task 3: 散点图 scatter-option 接入 helper

**Files:**
- Modify: `frontend/src/pages/analysis/composables/scatter-option.ts`（import L8, toolbox L130）

- [ ] **Step 1: import 追加**

```ts
// before (L8)
import { formatAxisValue } from '../../../utils/chart-bar'
// after
import { formatAxisValue, buildChartToolbox } from '../../../utils/chart-bar'
```

- [ ] **Step 2: toolbox 替换（补 name，保留 restore + right:10）**

```ts
// before (L130)
    toolbox: { feature: { saveAsImage: { title: '保存图片' }, restore: { title: '还原' } }, right: 10 },
// after
    toolbox: buildChartToolbox({ name: `${d.param_x}_vs_${d.param_y}_散点`, extra: { restore: { title: '还原' } }, right: 10 }),
```

- [ ] **Step 3: 类型检查**

Run: `cd frontend; npx vue-tsc --noEmit`
Expected: 0 错误

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/analysis/composables/scatter-option.ts
git commit -m "refactor(correlation): 散点图接入 buildChartToolbox 并补下载文件名"
```

---

### Task 4: 晶圆图 WaferMapPanel 接入 helper + title textStyle

**Files:**
- Modify: `frontend/src/pages/analysis/components/WaferMapPanel.vue`（import L91, title L425, toolbox L443）

- [ ] **Step 1: import 追加**

```ts
// before (L91)
import { getSiteColors8 } from '../../../utils/chart-bar'
// after
import { getSiteColors8, buildChartToolbox } from '../../../utils/chart-bar'
```

- [ ] **Step 2: title 补 textStyle（第 2 项硬伤）**

```ts
// before (L425)
    title: { text: 'Wafer Map', subtext, left: 'center' },
// after
    title: { text: 'Wafer Map', subtext, left: 'center', textStyle: { fontSize: 15, fontWeight: 'bold', color: tc }, subtextStyle: { fontSize: 12, color: tc } },
```

（`tc` 已在同函数作用域内，L442 legend 已用 `color: tc`）

- [ ] **Step 3: toolbox 替换（补 name，保留 dataZoom+restore + right:20/top:20）**

```ts
// before (L443)
    toolbox: { feature: { saveAsImage: { title: '保存', pixelRatio: 2 }, dataZoom: { title: { zoom: '缩放', back: '还原' } }, restore: { title: '还原' } }, right: 20, top: 20 },
// after
    toolbox: buildChartToolbox({ name: 'WaferMap', extra: { dataZoom: { title: { zoom: '缩放', back: '还原' } }, restore: { title: '还原' } }, right: 20, top: 20 }),
```

- [ ] **Step 4: 类型检查**

Run: `cd frontend; npx vue-tsc --noEmit`
Expected: 0 错误

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/analysis/components/WaferMapPanel.vue
git commit -m "fix(wafer): title 补主题 textStyle + toolbox 接入 buildChartToolbox"
```

---

### Task 5: 多文件箱线图补 toolbox + param prop（第 1 项硬伤）

**Files:**
- Modify: `frontend/src/pages/analysis/components/MultiFileBoxPlot.vue`（import L8, props L10-13, option 加 toolbox）
- Modify: `frontend/src/pages/analysis/components/MultiFileTab.vue`（L156 传 :param）

- [ ] **Step 1: MultiFileBoxPlot import 追加**

```ts
// before (L8)
import { mapLotColorToTheme } from '../../../utils/chart-bar'
// after
import { mapLotColorToTheme, buildChartToolbox } from '../../../utils/chart-bar'
```

- [ ] **Step 2: props 加 param**

```ts
// before
const props = defineProps<{
  lotData: any
  fileNames: Record<number, string>
}>()
// after
const props = defineProps<{
  lotData: any
  fileNames: Record<number, string>
  param?: string
}>()
```

- [ ] **Step 3: option 加 toolbox**

在 `buildOption()` 的 return 对象里，`tooltip: {...}` 之后、`grid: {...}` 之前插入一行：

```ts
    toolbox: buildChartToolbox({ name: `${props.param ?? '多文件'}_箱线图对比` }),
```

插入后 return 对象结构为：`{ tooltip, toolbox, grid, xAxis, yAxis, series }`。

- [ ] **Step 4: MultiFileTab 传 :param**

```html
<!-- before (L156) -->
            <MultiFileBoxPlot :lot-data="lotData" :file-names="resolvedNames" />
<!-- after -->
            <MultiFileBoxPlot :lot-data="lotData" :file-names="resolvedNames" :param="selectedParam" />
```

- [ ] **Step 5: 类型检查**

Run: `cd frontend; npx vue-tsc --noEmit`
Expected: 0 错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/analysis/components/MultiFileBoxPlot.vue frontend/src/pages/analysis/components/MultiFileTab.vue
git commit -m "feat(multi-file-boxplot): 补 saveAsImage 工具栏 + param prop"
```

---

### Task 6: 构建验证 + e2e 断言

**Files:**
- Modify: `frontend/e2e/analysis/multi-file.spec.ts`（在现有"箱线图显隐"用例追加 saveAsImage 断言）

- [ ] **Step 1: 前端构建**

Run: `cd frontend; npm run build`
Expected: 构建成功，0 错误（build 脚本含 `vue-tsc -b`，类型一并校验）

- [ ] **Step 2: e2e 追加断言**

先读 `frontend/e2e/analysis/multi-file.spec.ts`，定位现有的箱线图显隐用例（上个迭代新增，用 `page.locator(TAB).getByRole('checkbox', { name: '显示箱线图' }).check()` 勾选后断言 `boxCard` 可见）。在"勾选后 boxCard 可见"断言之后，追加对箱线图 ECharts 实例 option 含 saveAsImage 的断言：

```ts
    // 箱线图 ECharts 实例 option 应含统一 saveAsImage（第 1 项硬伤修复证据）
    await page.waitForFunction(() => {
      const el = document.querySelector('.boxplot-card .chart-container') as any
      const inst = el?.__echartsInstance__
      const opt = inst?.getOption?.()
      const tb = Array.isArray(opt?.toolbox) ? opt.toolbox[0] : opt?.toolbox
      const sai = tb?.feature?.saveAsImage
      return !!sai && sai.pixelRatio === 2
    }, null, { timeout: 5_000 })
```

（`__echartsInstance__` 由 `useChart` 挂在容器 DOM 上；SVG 渲染下 toolbox 图标无稳定 accessible name，故读实例 option 断言比 DOM 定位可靠）

- [ ] **Step 3: 跑 e2e**

Run: `cd frontend; npx playwright test e2e/analysis/multi-file.spec.ts --project=Edge`
Expected: 全部用例通过（含新断言与上个迭代的 3 条多文件用例，无回归）

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/analysis/multi-file.spec.ts
git commit -m "test(multi-file): 断言箱线图 saveAsImage 工具栏存在"
```

---

## 完成后验证清单

- [ ] `npx vue-tsc --noEmit` 0 错误
- [ ] `npm run build` 成功
- [ ] `multi-file.spec.ts` e2e 全绿
- [ ] 视觉抽查：多文件箱线图右上角有保存按钮；晶圆图标题 15px bold 且跟随主题色；各图保存按钮 hover 提示统一"保存图片"
