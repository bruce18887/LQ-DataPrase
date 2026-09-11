# 图表风格硬伤修复设计

> 日期：2026-09-11
> 范围：严格 3 项（多文件箱线补 saveAsImage / 晶圆 title 补 textStyle / 统一 6 处 saveAsImage 属性）
> 方式：chart-bar.ts 抽 buildChartToolbox 共享 helper
> 状态：待审核

## 1. 背景与动机

数据分析页 9 张图表缺乏统一基础模板——`echarts-theme.ts` 的 `getBaseOption`（统一 title/legend/tooltip/轴系字号）定义后**从未被任何图表接入**，各图只取了 `colors` 配色对象，title/tooltip/legend/toolbox 全部手写，导致排版层风格漂移。配色层是统一的（所有 tooltip 都用 `colors.tooltipBg/Border/Text`），漂移集中在排版与工具栏。

本次聚焦其中 3 项最突出的**硬伤**，均为低风险、纯前端 ECharts option 属性改动，不涉及后端与数据流。

### 三项硬伤

1. **多文件箱线图不能保存图片**：`MultiFileBoxPlot.vue` 的 option 完全没有 `toolbox`，是全站唯一没有 saveAsImage 的图；且它是本次多文件增强新建的组件，本应对齐既有风格却漏了。
2. **晶圆图标题不跟随主题**：`WaferMapPanel.vue` 的 `title` 未设 `textStyle`，用 ECharts 默认 18px + 默认色，既比其他图的 15px bold 大，颜色也不吃主题文字色 `tc`。
3. **saveAsImage 属性混用**：柱状图家族（直方图/多文件柱/序列/QQ）只设 `name`（下载文件名），散点/晶圆只设 `title`（按钮提示），`pixelRatio:2` 仅晶圆设了——三个属性各设一半，导出体验不一致。

## 2. 范围

### 做

- 在 `chart-bar.ts` 新增 `buildChartToolbox` helper，统一 saveAsImage 三属性（`name` + `title:'保存图片'` + `pixelRatio:2`）。
- 7 处接入：6 处现有 toolbox 改用 helper（保留各自 name / extra feature / 位置），`MultiFileBoxPlot` 新增 toolbox（加 `param` prop）。
- 晶圆 `title` 补 `textStyle`（15 bold tc）+ `subtextStyle`（12 tc）。

### 不做

- 不动 `BoxPlotChart`（单文件箱线）、`matrix-option`（相关性矩阵）的 toolbox：二者现状无 saveAsImage，但不在本次点名范围，留待后续。
- 不统一 legend 底部定位（`top:'bottom'` vs `bottom:5` vs `bottom:10`）。
- 不统一 axisLabel 字号、正态/KDE 线型、大数据关动画（评估里的中/低优先级项，非本次硬伤）。
- 不接入 `getBaseOption`（那是覆盖 9 图的较大重构，本次不碰）。
- 不统一 toolbox 位置（保持各图现状，规避 title 与 toolbox 布局冲突风险）。

## 3. 设计

### 3.1 共享 helper

在 `chart-bar.ts`（顶部注释已声明"所有分析图表共用同一套视觉 token"）新增：

```ts
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

export function buildChartToolbox(opts: ChartToolboxOptions) {
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

- `saveAsImage.name`：下载文件名，各图沿用/新增有意义命名。
- `saveAsImage.title`：按钮 hover 提示，统一 `'保存图片'`。
- `saveAsImage.pixelRatio`：导出分辨率，统一 `2`（高清，与晶圆看齐）。
- `extra`：叠加各图特有 feature（散点的 restore、晶圆的 dataZoom+restore），保持现状。
- `right`/`top`：位置，各图保持现状。

### 3.2 接入清单

| 图表 | 文件 | name | extra | 位置 |
|---|---|---|---|---|
| 直方图 | HistogramChart.vue | `${selectedParam}_分析` | — | 默认 |
| 多文件柱 | MultiFileChart.vue | `${selectedParam}_多文件对比` | — | 默认 |
| 序列 | SerialChart.vue | `${param}_Serial分布` | — | 默认 |
| QQ | QQPlotChart.vue | `${param}_QQ图` | — | 默认 |
| 散点 | scatter-option.ts | `${param_x}_vs_${param_y}_散点` | `restore:{title:'还原'}` | `right:10` |
| 晶圆 | WaferMapPanel.vue | `WaferMap` | `dataZoom`+`restore`（现状） | `right:20, top:20` |
| 多文件箱线 | MultiFileBoxPlot.vue | `${param}_箱线图对比` | — | 默认 |

- `MultiFileBoxPlot` 加 `param?: string` prop，父组件 `MultiFileTab` 传 `:param="selectedParam"`（`MultiFileChart` 已是同款 prop）。
- 散点 name 用 `d.param_x`/`d.param_y` 构造；scatter-option.ts 已 import chart-bar 的 `formatAxisValue`，追加 `buildChartToolbox` 即可。
- 晶圆 name 用固定 `'WaferMap'`（buildOption 作用域无便捷文件名标识，保持简单——已与用户确认）。

### 3.3 晶圆 title

`WaferMapPanel.vue` buildOption 的 title：

```
title: { text:'Wafer Map', subtext, left:'center' }
→
title: { text:'Wafer Map', subtext, left:'center',
         textStyle:{ fontSize:15, fontWeight:'bold', color:tc },
         subtextStyle:{ fontSize:12, color:tc } }
```

`tc` 已在作用域内（同函数 legend 已用 `color: tc`）。

## 4. 数据流与影响

- 纯前端 ECharts option 属性改动，无后端 / API / 数据流变更。
- 无新增依赖。
- 影响面：9 个前端文件（chart-bar.ts + 6 图表 + MultiFileBoxPlot + MultiFileTab）。

## 5. 验证

1. `cd frontend; npx vue-tsc --noEmit` → 0 类型错误。
2. `cd frontend; npm run build` → 构建成功。
3. 现有 e2e `frontend/e2e/analysis/multi-file.spec.ts` 不回归（含本次多文件增强新加的 3 条用例）。
4. 视觉抽查：多文件箱线图右上角出现保存按钮；晶圆图标题字号/颜色与其他图一致；各图保存按钮 hover 提示统一为"保存图片"，导出图为 2x 清晰度。

## 6. 文件变更清单

| 文件 | 变更 |
|---|---|
| frontend/src/utils/chart-bar.ts | 新增 `ChartToolboxOptions` + `buildChartToolbox` |
| frontend/src/pages/analysis/components/HistogramChart.vue | toolbox 改用 helper |
| frontend/src/pages/analysis/components/MultiFileChart.vue | toolbox 改用 helper |
| frontend/src/pages/analysis/components/SerialChart.vue | toolbox 改用 helper |
| frontend/src/pages/analysis/components/QQPlotChart.vue | toolbox 改用 helper |
| frontend/src/pages/analysis/composables/scatter-option.ts | toolbox 改用 helper + 补 name |
| frontend/src/pages/analysis/components/WaferMapPanel.vue | toolbox 改用 helper + 补 name + title textStyle |
| frontend/src/pages/analysis/components/MultiFileBoxPlot.vue | 加 `param` prop + 新增 toolbox |
| frontend/src/pages/analysis/components/MultiFileTab.vue | 给 MultiFileBoxPlot 传 `:param` |
