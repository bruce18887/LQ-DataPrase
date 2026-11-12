# Site 偏移山脊图（直方图 Site 模式）设计

- 日期：2026-11-03
- 状态：待评审
- 触发：用户需求「数据分析页面加 3D 柱状图看 site 差异」
- 原型：[tasks/proto-site-ridgeline/index.html](../../../tasks/proto-site-ridgeline/index.html)（真实 CP 样例，14,174 行 / 8 site / 36 参数）

## 1. 问题与判据

经澄清，用户看 site 差异要下的判断是**参数值整体偏移**（site offset）：某个 site 测出来的数值整体偏高或偏低，即使良率尚未破限。

- 良率口径已有现成实现：`SiteStatsTable.vue` 逐 site 一行（Yield / Fail / <Min / >Max），`FailCount > 0` 整行标红。
- 参数值口径是缺口：现有直方图的 `site_histograms` 把 8 个 site 并排挤在同一个 bin 里，单柱过细，读不出「谁整体挪了」。
- 3D 柱状图被否决，理由三条：
  1. 纵深轴不共基线，左边百分比刻度读不到后排柱，前排峰挡住后排尾部；
  2. `bar3D` 无 `markLine`、无多 `yAxis`、无 KDE/正态曲线、无逐系列 legend 勾选——直方图现有叠加层（[HistogramChart.vue:174-256](../../../frontend/src/pages/analysis/components/HistogramChart.vue)）在 3D 下必须重做或砍掉；
  3. 需引入 `echarts-gl` + three.js，且只支持 canvas 渲染器；全站图表默认 SVG（[echarts-theme.ts:19-26](../../../frontend/src/utils/echarts-theme.ts)），会形成渲染栈分叉，双主题需为 GL 材质重新配光。

## 2. 方案

给直方图增加**「山脊」显示模式**，默认仍为现有并排柱。`HistogramChart.vue` 一行不动（保住 `edge-clip` / `limit-line-cross` 两条回归钉），新模式由新组件承担。

山脊图：每个 site 一条脊，各有自己的基线，由远及近叠放，**共用同一条 X 值轴**。整体偏移表现为「整条脊左右挪」。

签名元素：**右侧「偏移标尺」**——与每条脊严格同行的读数轨，显示该 site 中位数相对全站中位数的偏移（单位 σ），并按阈值三档着色。

## 3. 真实数据验证

原型在 `BN281R3CYCAA_2604160006_TTTA803100.03_06_CP1_20260418161733.csv` 上跑通，三条实测结论：

1. `Idss_16V_Post2` 的 S6 偏移 **−2.73σ**，整条分布与其余 7 个 site 完全不重叠——山脊图一眼可见。
2. 真实分布是**双峰/多峰**，不是正态。只比中位数会漏掉「形状不对但中位数没挪」的 site，形状通道是选山脊图的独立理由。
3. **固定绝对阈值不可用**：`Igsspd_5V_Post` 上 8 个 site 有 5 个超过 0.6σ，整屏飘红，报警失去分辨力——那是「整批 site 之间普遍离散」，不是「某个 site 坏」。

## 4. 数据契约（后端）

位置：`apps/analysis/services/data_services/histogram.py`（`site_histograms` 现块在 274-299，响应字典在 301-335）。新增三个键，**不改动现有键**：

```python
'site_histograms_norm': {site: [pct, ...]},   # 各 site 用自己的计数作分母（每行和≈100）
'site_offsets': {
    'sites': [{'site': '1', 'n': 1750, 'median': 0.9, 'z': 0.25}, ...],  # 按 site_sort_key 排序
    'global_median': 0.88,
    'global_std': 0.31,
    'warn_threshold': 0.68,
    'err_threshold': 1.70,
},
```

理由与口径：

- **为什么另开 `site_histograms_norm`**：现有 `site_histograms` 的分母是**全站总数**（`histogram.py:294-299` 注释写明 "Use total_count (all sites) as denominator, matching Excel"）。山脊图若直接用它，die 数少的 site 整条脊都会矮，会被误读成「分布低」。并排柱依赖共享分母表达绝对占比，所以**不能改现有字段语义**，只能新增。
- **为什么偏移在后端算**：`HistogramChart.vue:116-118` 立的规矩是统计量「公式单一来源在后端」。`z = (site_median − global_median) / global_std`，`global_median` 与 `global_std` 复用同响应里已有的 `median` / `std` 口径。`global_std == 0` 时 `z` 取 0。
- **为什么阈值也在后端**：它是统计规则，不是渲染参数。见 §7。
- 无 Site 列或 site 数 < 2 时，`site_histograms_norm` / `site_offsets` 均为 `None`。

## 5. 前端

| 文件 | 改动 |
| --- | --- |
| `pages/analysis/components/SiteRidgeChart.vue` | 新增，约 230 行；ECharts `custom` series，一条 series 画出全部脊 + 参考线 + 标尺 |
| `pages/analysis/components/SingleParamTab.vue` | `histMode` 本地 ref（`'grouped' \| 'ridge'`），按模式渲染 `HistogramChart` 或 `SiteRidgeChart`（现有挂载点 :79-89）；`<template #controls-hist>` 放模式切换 |
| `ChartDock.vue` / `ChartPanel.vue` | **不改**。`ChartDock.vue:38-40` 已支持 `controls-<key>` 透传，`ChartPanel` 已有 `controls` 槽 |

- 模式切换只在 `site_histograms` 存在且 site 数 ≥ 2 时出现；否则不渲染该控件。
- 切换状态**不持久化**（本地 ref），避免 R5 那条「跨上下文状态泄漏」。
- 渲染器/主题走既有 `useChart` + `useEChartsTheme`，不新增依赖。

## 6. 视觉规格

全部取自 `styles/design-tokens.css` 与 `utils/echarts-theme.ts`，不新增色值。

| 元素 | Light | Night |
| --- | --- | --- |
| 面板体 / 边框 | `--bg-2` `#f3f4f6` / `--border-2` `#d1d5db` | `#16213e` / `rgba(255,255,255,.18)` |
| 标题栏 | `--bg-3` `#e5e7eb`，12px/600 | `rgba(255,255,255,.05)` |
| 脊体 | `rgba(71,85,105,.90)` | `rgba(255,255,255,.62)`（= `--chart-8`） |
| 脊描边（切开相邻脊） | 面板底色 `#f3f4f6`，1.1px | `#16213e` |
| 网格线 | `#eef0f3`（`--bar-grid`） | `rgba(255,255,255,.04)` |
| 正常波动 `|z| < warn` | `--text-3` `#9ca3af` | `rgba(255,255,255,.55)` |
| 需关注 | `--warn` `#92400e` | `#f9a825` |
| 超标 | `--error` `#b91c1c` | `#f5576c` |
| LSL/USL | `--error` 虚线 6-3 | 同色系 |
| 全站中位数 | `--text-2` 虚线 4-4 | `rgba(255,255,255,.5)` |
| 超标行底纹 | `rgba(185,28,28,.075)` | `rgba(245,87,108,.13)` |

- 字号只用 `micro 11` / `dense 12` / `base 14` 三档，对齐 `chartFontSize`。
- 数值全部 `tabular-nums`。
- **山脊图不画共用 Y 轴**：每条脊有自己的基线，再画百分比轴是误导。高度只在同一行内可比，跨行比较靠 X 轴位置与右侧标尺。该说明写进图注。
- 超标行底纹沿用 `SiteStatsTable` 的 `site-fail-row` 语言（`color-mix(in srgb, var(--error) 12%, transparent)`），不另造一套。

## 7. 阈值规则

```
med_abs = median(|z| over all sites)
warn_threshold = max(0.3, 1.5 × med_abs)
err_threshold  = max(0.6, 2.5 × med_abs)
```

- 绝对值下限保证「site 之间几乎没差」时不会误报；倍数项保证「整批普遍离散」时不会整屏飘红。
- 两个阈值随响应下发（§4），前端只渲染，并把 `err_threshold` 印在标尺表头（`超标 ≥ 0.68σ`），不让用户猜。
- 实测：`Idss_16V_Post2` → 0.68σ（只有 S6 报红）；`Igsspd_5V_Post` → 2.17σ（无 site 报红，如实表达「无离群 site，但 site 间整体发散」）。

## 8. 边界与降级

| 情况 | 行为 |
| --- | --- |
| 无 Site 列 / site 数 < 2 | 不渲染切换控件，仅并排柱 |
| 单 site | 同上（不提供山脊模式） |
| `global_std == 0` | `z` 全 0，标尺全灰 |
| 某 site 样本过少 | 仍绘制；`n` 进 tooltip |
| LSL/USL 在数据范围外 | 不画该线（现有直方图同规则） |
| `site_histograms_norm` 缺失 | 回退并排柱，不报错 |
| 布局尺寸变化 | `useChart` 的 ResizeObserver 复用；标尺在像素空间绘制，随 `api.getWidth()` 自适应 |

## 9. 测试

按 `docs/reference/testing-gates.md` 选层。

- **T1 后端单测**（紧随 `apps/analysis/tests_param_guards.py` 现有 `site_histograms` 断言）：
  - `site_histograms_norm` 每个 site 行和≈100；分母是各 site 自己的计数（构造计数不等的 fixture 才能区分）；
  - `site_offsets` z 公式；`std=0` 守卫；单 site；无 Site 列 → `None`；
  - 阈值公式在 `med_abs=0` 时取绝对下限。
- **T2 前端单测**：把 option 构造抽成纯函数，快照断言脊点列、参考线、标尺三档；`npx vitest run`，不开浏览器。
- **T3 e2e**：`frontend/e2e/analysis/` 新增一条——有 site 数据时切换控件可见、点后出现山脊、标尺文本存在；无 site 数据时不出现。收口跑 `node scripts/e2e_pool.mjs --slots=4`。

## 10. 不做的事

- 不做真 3D、不引入 `echarts-gl` / `three.js`。
- 不替换现有并排柱，只加模式。
- 不做按 site 上色（那会撞 `getSiteColors8` 的 8 色上限；山脊图里 site 是行，颜色留给判据）。
- 不做排序开关（标尺已按颜色给出强弱，再加排序是多余控制）。
- 不改 `HistogramChart.vue` 的任何既有逻辑。

## 11. 开放问题

1. **异常值处理（clip / exclude）在山脊模式下的口径**。现有直方图会按 IQR 边界隐藏 bin（`HistogramChart.vue:89-112`），但裁剪会改变分布形状，而形状正是山脊模式的判读依据。建议 v1 山脊模式**始终用全量数据**，并在该模式下隐藏异常值提示条——需用户确认是否接受这一口径差异。
