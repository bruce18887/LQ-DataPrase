# 3D 站点柱阵（单文件分析）设计

- 日期：2026-11-04
- 状态：待评审
- 触发：用户需求「数据分析页面加一个 3D 图表，看不同 Site 的差异，轴最好和直方图类似」
- 原型：[2026-11-04-3d-site-barchart-proto.html](./2026-11-04-3d-site-barchart-proto.html)（真 `echarts-gl`，非手绘 mock）
  与实测截图 [2026-11-04-3d-site-barchart-verified.png](./2026-11-04-3d-site-barchart-verified.png)
- 同族设计稿：[2026-11-03-site-ridgeline-design.md](./2026-11-03-site-ridgeline-design.md)（山脊图）。
  两者形态互斥，本稿不否决它——用户 2026-11-04 明确「保持待做」，先做 3D。

## 1. 需求与判据

要看的是 Site 之间的两类差异，且**一次编码同时给出**：

- **形状**：某个 Site 峰位偏移、峰变宽、拖尾或双峰。
- **量**：某个 Site 样本少、超规格多。

判据落在数据口径上而不是加开关：后端 `site_histograms` 的分母是**全站 `total_count`**
（[histogram.py:294-299](../../../apps/analysis/services/data_services/histogram.py)），所以柱子的**绝对高低就是量**、
**左右错位就是形状**。因此本设计**不引入任何归一化模式**，实现时不要再加一个 mode 参数。

验收判据（可执行）：8 Site × 24 bin 的样例下，峰位偏移的 Site 在**不旋转**的默认视角即可一眼辨出；
旋转与缩放过程中控制台零报错。

## 2. 技术选型

| 项 | 取值 | 依据 |
| --- | --- | --- |
| 库 | `echarts-gl@^2.1.0` | npm registry 实测：2.1.0 于 2026-05-28 发布，peerDependencies 为 `echarts: ^5.1.2 \|\| ^6.0.0`，与本项目 `echarts ^6.1.0` 匹配。GitHub README 上「GL 2.x 配 ECharts 5.x」是旧文案，以 npm 清单为准 |
| 体积 | `dist/echarts-gl.min.js` 639,846 B | 实测下载字节 |
| 形态 | `series.bar3D` + `grid3D` | 官方 12 个 bar3D 示例中 `bar3d-punch-card`（24 category × 7 category）结构最接近本场景 |
| 旋转 | `grid3D.viewControl`（拖拽转 alpha/beta、滚轮缩放） | 用户明确要求可旋转；自绘等距投影需要自己实现投影矩阵 + 每帧画家算法排序，维护成本高于收益，已否决 |
| 渲染器 | 本图强制 `canvas` | gl 只吃 canvas；`useChart` 第 4 参已有覆盖口（[useChart.ts:34](../../../frontend/src/composables/useChart.ts)），`SerialChart` / `QQPlotChart` / `WaferMapPanel` / `CorrelationToolsTab` 四处已在用同形写法 |
| 分包 | 组件 + `echarts-gl` 走 `defineAsyncComponent` 动态 import | 只有首次勾选才加载 ⇒ SPA 冷启动字节不变（`docs/reference/testing-gates.md` §2 明记冷启动是 e2e 单价主因）。Electron 下 `base: './'`（[vite.config.ts:31](../../../frontend/vite.config.ts)）相对分块可用 |

## 3. 数据契约：后端零改动

复用 `POST /analysis/histogram/` 现有响应字段，不新增端点、不改序列化：

| 字段 | 用途 |
| --- | --- |
| `site_histograms` | `{ [site]: number[26] }`，每 Site 一套 26 格占比，与 `bin_centers` 严格同网格 |
| `bin_centers` | 26 个中心值 = underflow + 24 正常 + overflow（[binning.py:12-27](../../../apps/analysis/services/binning.py)） |
| `bin_counts` | tooltip 里的 `n=` |
| `outlier_info` | §8 的 clip 过滤 |

`lower_limit` / `upper_limit` 本图**不消费**（§7）。

无 Site 列时 `site_histograms` 为 `null`（后端仅在检测不到 Site 列时留空）⇒ 前端走 §9 的提示分支。

## 4. 前端接入点

| 文件 | 改动 | 要点 |
| --- | --- | --- |
| `frontend/package.json`、`package-lock.json` | 新增依赖 | 见 §2 |
| `pages/analysis/composables/site3dOption.ts` | **新增**（纯函数，无 DOM） | `buildSite3DOption(result, theme, mode)`：轴、色键、`barSize` 换算、clip 过滤全在此。照 `dockGeometry.ts` 的先例——纯模型放 `composables/`，便于 T2 直测 |
| `pages/analysis/composables/histogramBins.ts` | **新增**（纯函数） | 从 [HistogramChart.vue:105-112](../../../frontend/src/pages/analysis/components/HistogramChart.vue) 原样抽出「按 clip 边界算 activeIndices」，2D 与 3D 共用（§8） |
| `pages/analysis/components/Site3DChart.vue` | **新增**（薄壳，目标 <200 行） | 容器 + `useChart` + 图下提示条 + 降级 `el-alert`；不写业务计算 |
| `pages/analysis/components/HistogramChart.vue` | 内联 clip 过滤改调 `histogramBins.ts` | 行为逐字节不变，由 T2 钉住（§8） |
| `utils/echarts-theme.ts` | 新增 `grid3DTheme` computed | 与 `getBaseOption` 同一个 `colors` 源，不散写（§5） |
| `pages/analysis/composables/useChartDock.ts` | `ChartKey` 加 `'site3d'`、`ALL_KEYS`、`defaultLayout`、`isValidLayout`，**并升 `VERSION`** | 不升 `VERSION` 的话，用户存过的 4 图布局会被 `isValidLayout` 判非法整表丢弃（[useChartDock.ts:73-83](../../../frontend/src/pages/analysis/composables/useChartDock.ts)） |
| `pages/analysis/components/ChartDock.vue` | `TITLES` 加 `site3d` | 标题「3D柱状图」（[ChartDock.vue:124](../../../frontend/src/pages/analysis/components/ChartDock.vue)） |
| `pages/analysis/components/SingleParamTab.vue` | 复选框「显示3D柱状图」+ `#site3d` slot + 异步组件 | 前缀「显示」沿用现有四个复选框的写法（[SingleParamTab.vue:19-22](../../../frontend/src/pages/analysis/components/SingleParamTab.vue)）；**默认不勾**，避免 dock 从 4 格挤成 6 格 |

## 5. 风格：逐项映射回项目 token

官方示例的观感来自它自己覆盖掉的 gl 默认值，不是 3D 的固有长相。以下默认值全部从
`echarts-gl@2.1.0/lib/**` 源码实测取得，逐项改回项目 token（R7②：ECharts 不解析 CSS 变量，
`setOption` 里的颜色必须取 `useEChartsTheme()` 的 JS 语义色）。

| gl 默认值 | 改成 | 为什么 |
| --- | --- | --- |
| `bar3D.shading: 'color'`（默认即此，**是示例改成了 `lambert`**） | 保持 `'color'` | 不打光 ⇒ `#0077BB` 渲染出来就是 `#0077BB`，`getSiteColors8` 的色盲校验才有效 |
| `viewControl.projection: 'perspective'` | `'orthographic'` | 去掉近大远小，柱高才可跨 Site 比 |
| `axisLine.lineStyle.color: '#333'`、宽 2 | `colors.axisLineColor`、宽 1，**且不能 `show:false`**（§6 坑 2） | light `#e5e7eb` / night `rgba(255,255,255,.10)` |
| `splitLine.lineStyle.color: ['#ccc']` | `colors.splitLineColor` | 深底上 `#ccc` 会糊成一片 |
| `axisLabel.textStyle.fontSize: 12`（无字色） | `chartFontSize.micro` + `colors.axisLabelColor` + `fontFamily.sans` | 字号/字族/字色三件都要归 token |
| `axisPointer.label.textStyle`：14px 白字黑胶囊 | `colors.tooltipBg / tooltipBorder / tooltipText` | gl 的黑胶囊与项目 tooltip 的玻璃底不同源 |
| 示例里的 `light.main.shadow: true` | 不写 | 阴影是「demo 感」主要来源，且 `shading:'color'` 下根本不吃光 |
| `visualMap` 按 z 上色的蓝→红色阶 | 按 **Site 维度**上色，喂 `getSiteColors8(isDark)` | 要的是「Site 颜色和直方图对得上」 |
| `itemStyle.opacity: 1` | **默认不动**（渐隐关掉） | 见 §6.5：按行降 opacity 会吃掉 Site 色的饱和度，而 Site 身份在这张图里就靠颜色 |

- **GL 图层本身是 `transparent: true` 创建的**（`lib/component/grid3D/Grid3DView.js:35`）⇒ 场景不铺自己的底色，
  `ChartPanel` 的 CSS 背景直接透出，双主题不必为 3D 单开背景处理。
- 主题切换不必自己挂：`useChart` 已 watch `themeStore.currentTheme` 重渲染（[useChart.ts:321](../../../frontend/src/composables/useChart.ts)）。
- 默认机位与箱体：`alpha 28 / beta 30 / distance 245`，`boxWidth 132 / boxHeight 74 / boxDepth 120`。
  这组数是「Site 分辨度」实测出来的（§6.5）：`beta` 取负值会把值轴甩到左后方；`alpha` 低于 25 时后排被前排整根挡住；
  `boxDepth` 从 64 拉到 120 才让 8 个 Site 各自成一条可辨的色带。

## 6. 实测踩到的五个坑（实现时必撞，先写死）

1. **`visualMap` 用 `categories` + `inRange.color` 时，192 根柱一根都不画。** 必须写成
   `pieces: [{ value: i, label: siteName, color: pal[i % 8] }]`。副作用是好的：piecewise 的 `label` 正好显示成
   Site 名，而 **gl 系列不进 ECharts legend**，所以这个 visualMap 就是本图唯一的色键。
2. **`grid3D.axisLine.show = false` 会让 `_updateAxisLabelAlign` 读到 `null.axisLineCoords`，每次相机更新抛一次
   `TypeError`**（原型页修前实测一次渲染 194 条）。⇒「收掉 gl 那套 #333 硬轴线」只能做成**弱化到接近底色**，不能真隐藏。
3. **`barSize` 是绝对世界单位，两个分量各管一个方向——「太细」和「看着歪」都出在这里。** 源码
   [`lib/chart/bar3D/cartesian3DLayout.js:19-39`](https://cdn.jsdelivr.net/npm/echarts-gl@2.1.0/lib/chart/bar3D/cartesian3DLayout.js)
   写明：不传时自动取 `bandWidth × 0.7`；传了就直接当尺寸用（不是「占一格的百分比」）。两个坑各踩一次：
   - 原型第一版按分数填 `0.88`，柱子缩到自动值的四分之一 ⇒ 用户反馈「太细」。
   - x 方向 band 只有 `132/24 = 5.5`、y 方向有 `120/8 = 15`，所以**自动值本身就是「3.85 宽 × 10.5 厚」的板状**，
     在 `beta 30` 的方位角下每根柱斜着摊开、相邻 bin 糊成一条斜带 ⇒ 用户反馈「看着歪」。**与机位无关、
     与倒角无关**（`bevelSize` 归 0 做过对照，画面无变化）。
   本设计因此**分开给两个分量**：宽取 `bandX × 0.85`（≈4.7）、厚取 `bandY × 0.30`（≈4.5），截面近正方，
   柱子立起来且行间距留白最大。箱体尺寸取 §5 那一组（`132 / 74 / 120`）——两个 fill 只有和这组尺寸绑在一起
   才等价，换尺寸必须同步重算。
4. **平涂下色板第 7 格 `#BBBBBB` 在白底几乎不可辨**（截图里 S7 那排）。用户 2026-11-04 拍板：
   **只在 `site3dOption.ts` 的取色函数里把这一格换成深灰，不动 `SITE_COLORS_8_LIGHT`**，注释写明原因与影响面。
5. **「纵深渐隐」是 Site 分辨度的减分项，不是加分项。** 它原本是照 `transparent-bar3d` 抄来解遮挡的
   （按行 0.82→0.50），但平涂配色 + 降 opacity 直接把 Site 之间唯一的身份通道（色相饱和度）吃掉了。
   四档对照实测（渐隐 / alpha / boxDepth 各切一刀）结论：**遮挡要靠机位几何解决**——
   `alpha 14 → 28` 让前排不再整根盖住后排，`boxDepth 64 → 120` 让 8 行各自成带，两者到位后
   **关掉渐隐反而最清楚**。所以渐隐默认关，只作为可选项保留在原型上，不进产品开关。

## 7. LSL/USL：3D 图不画（已收口）

`bar3D` 的 x 轴是 `category`（官方两个结构型示例都用 category，柱宽由 category 轴自动等分），
规格限只能吸附到最近的 bin，画出来是**误导性的精确**。因此：

- 3D 图**不画** LSL/USL，规格限继续由同屏 2D 直方图的 `markLine` 承担（value 轴，落位准确）。
- 图下方挂一行说明：「规格限（LSL/USL）不在 3D 图中绘制，请看同屏直方图」。
  样式复用 `OutlierHintBar` 那条「图下信息条」的位置与 CSS 族，DOM 侧用 `var(--token)`（R7①），不新造按钮。

## 8. 异常值口径必须与 2D 同源

现有 2D 直方图在 `clip` 模式下会隐藏 bin 中心落在 IQR 边界外的柱子
（[HistogramChart.vue:105-112](../../../frontend/src/pages/analysis/components/HistogramChart.vue)）。
3D 若不做同样过滤，同屏两图口径矛盾——这是本项目反复修过的同类问题（同文件 :92 的注释即为一例）。

做法：把那段 `activeIndices` 计算原样抽成 `histogramBins.ts` 纯函数，两图共用；
`HistogramChart.vue` 只改为调用它，行为逐字节不变，由 T2 断言钉住。

## 9. 边界与降级

| 情况 | 行为 |
| --- | --- |
| 无 Site 列（`site_histograms === null`） | 出 `el-alert`「该文件没有 Site 列，无法进行站点统计」，与 `serialError` 同形（[SingleParamTab.vue:94-101](../../../frontend/src/pages/analysis/components/SingleParamTab.vue)） |
| 单 Site 文件 | 照常渲染一行（后端单站点也会填 `site_histograms`） |
| Site 数 > 8 | 按 `% 8` 循环取色，与 2D 直方图同规则；y 轴标签全列 |
| WebGL 不可用 | 模块级一次性探测 `canvas.getContext('webgl2' \|\| 'webgl')`；探不到**不建图**，出 `el-alert` 说明当前环境不支持。用户 2026-11-04 拍板：不做「退化成 2D 分组柱」的第二条渲染路径 |
| 全零 / `total_count` 为 0 | 后端返回 `None` ⇒ `histResult` 为空，走已有 `el-empty` 分支 |
| 容器从隐藏恢复、v-if 重建 | 全部由 `useChart` 现有能力承担，本图不自己挂 observer |

## 10. 测试分层与门禁成本

按 `docs/reference/testing-gates.md` 选层。

- **T1（后端）**：无。后端零改动。
- **T2（vitest，`frontend/test/unit/`）**：新增 `site3dOption.spec.ts`，断言
  ① 轴型 `category/category/value` 与 `bin_centers` 逐格对齐；
  ② `shading === 'color'`、`projection === 'orthographic'`；
  ③ 色键取 `getSiteColors8(isDark)`，且第 7 格被 3D 专用值覆盖、其余 7 格逐字相等；
  ④ light/night 两个分支的 token 键集对称（R7①）；
  ⑤ `barSize` 两个分量分别等于 `boxWidth/NB × 0.85` 与 `boxDepth/NS × 0.30`，且**断言两者不相等**
  （钉住 §6.3：写成单一 `fill` 同时乘两个方向，就会退回板状截面，用户看到的「歪」会复现）；
  ⑥ 无 Site 列返回 `null` 而非空 option；
  ⑦ **同一 `result` 下 3D 取用的 bin 集合 === `histogramBins.ts` 给 2D 的 `activeIndices`**（钉 §8）。
  另加 `histogramBins.spec.ts` 覆盖 clip/exclude/off 三档与「边界病态导致全排除时回退全部 bin」的守卫。
- **T3（Playwright，`frontend/e2e/analysis/site3d.spec.ts`）** 只留两条不可替代的，标 `@p1`：
  ① 勾选后 dock 内出现 `data-site3d-canvas`，且 canvas 实测盒宽/盒高非零（真 WebGL 出图，按 R2⑤ 先 `count()` 再取 `boundingBox()`）；
  ② night 主题下轴线与标签取 night token（双主题对比度）。
  布局存档回归：勾上再取消后，`lqdp-analysis-chart-layout` 里用户原有的 4 图布局不丢（钉 `VERSION` 升档）。
- **门禁**：`package.json` / `package-lock.json` 与 `frontend/src/utils/` 都是 GLOBAL
  （[affected-rules.mjs:177](../../../scripts/affected-rules.mjs)、194-195）⇒ **这批必然升级全量池**，
  实测 6–8min + 后端全套，不是可选项。收口按 `node scripts/e2e_pool.mjs --slots=4` 跑。
- **600 行约束**：新文件都在限内；`echarts-theme.ts` 现 258 行，加 `grid3DTheme` 后约 300。
  `lineLimit.spec.ts` 会把新文件自动纳入断言，无需登记豁免。

## 11. 不做的事

- 不改后端任何端点、序列化或分箱逻辑。
- 不进导出报告（导出是 `apps/export/charts.py` 的 matplotlib Agg 服务端重绘，前端 ECharts 图本来都不进导出）。用户 2026-11-04：「后期再说」。
- 不做 3D 专属设置面板（`fill`、机位、渐隐先固定为实测值；后续要调再说）。
- 不做多文件分析 / 相关性 tab 的 3D。
- 不做归一化开关（§1 已说明单一编码同时承载量与形状）。
- 不做「WebGL 不可用时退化成 2D 分组柱」。

## 12. 风险与留观

| 风险 | 处置 |
| --- | --- |
| 遮挡：前排柱挡住后排，转到低角度时读数困难 | 已用机位几何解决（`alpha 28` + `boxDepth 120`，§6.5），**不用渐隐**——降 opacity 会吃掉 Site 色饱和。用户把视角转到低处时仍会遮挡，这是 3D 形态的固有代价，不是可修的缺陷；读数兜底是同屏 2D 直方图与 Site 统计表 |
| 低配机器 WebGL 退到 SwiftShader 软件渲染 | 192 根柱的量级可承受；上线后按 §9 的探测分支观察是否真有人走到提示分支 |
| `echarts-gl` 2.1.0 发布不足半年 | 原型已用本项目实际 `echarts 6.1.0` 构建产物跑通、控制台零报错；升级 echarts 时把该页回归纳入 T2 |
