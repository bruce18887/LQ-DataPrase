# 3D 站点柱阵：视角记忆 + 网格线对齐直方图（设计稿）

- 日期：2026-11-05
- 状态：设计已与用户确认（视角存账号记忆、跟图表记忆开关；网格线 light 对齐直方图、night 维持淡白；动画行为不改）
- 关联：`docs/superpowers/specs/2026-11-04-3d-site-barchart-design.md`（本图上线条目的原 spec）

## 1. 背景与目标

上线后用户提出三件事：

1. **「切换测试项有时有动画、有时没有」** —— 只解释原因，不改行为（§3）。
2. **「视角改动后切换页面/测试项要保留」** —— 本轮的主功能（§4）。
3. **「加入和直方图一样的网格线」** —— 3D 网格线目前几乎看不见（§5）。

## 2. 事实与来源（写代码前先钉住）

| 事实 | 来源 / 复核方式 |
| --- | --- |
| `echarts-gl` 的 bar3D 更新动画只在**前后柱数相同**时播放（顶点级插值） | `node_modules/echarts-gl/dist/echarts-gl.js` 的 `graphicGL.updateVertexAnimation`：`previousMesh.geometry.vertexCount === currentMesh.geometry.vertexCount`（注释 "Only animate when bar count are not changed"） |
| 相机实时态不在 `getOption()` 里；交互只改 OrbitControl 内部状态 | Task 7 真机实测：拖拽后 `getOption().grid3D[0].viewControl.alpha` 不变；实时值在 `inst.getViewOfComponentModel(inst.getModel().getComponent('grid3D'))._control` 的 `getAlpha()/getBeta()/getDistance()/getOrthographicSize()/getCenter()` |
| grid3D 的 viewControl 映射：`distance` 直接生效；`orthographicSize` 生效值为**模型值 + 1**；`zoom` 不被 grid3D 读取 | `echarts-gl.js:41467` 以 `setFromViewControlModel(viewControlModel, 0)` 调用 ⇒ `extraOpts` 为假值 ⇒ `baseDistance=0, baseOrthoSize=1`（`:39002-39003`、`:39015-39016`）。`zoom` 仅在 mapbox/maptalks 路径被读 |
| gl 默认 `orthographicSize: 150`（模型值），即现状实测 151 | `echarts-gl.js` 的 `componentViewControlMixin.defaultOption.viewControl` |
| 直方图网格线 = ECharts 默认 `#dbdee4`（`neutral15`），且**不随主题变**（直方图未覆写 splitLine） | `node_modules/echarts/lib/coord/axisDefault.js` + `visual/tokens.js:56,116`；真机截图取色：直方图网格线像素 `(219,222,228)=#dbdee4`，背景 `#f3f4f6` |
| 3D 现在用 `splitLineColor`（light `#eef0f3` / night `rgba(255,255,255,0.04)`），白底上对比只有 ~5 灰阶 | `frontend/src/utils/echarts-tokens.ts` 的 `grid3DStyle`；截图取色 3D 线条 ~`(241,242,244)` |
| `analysis_chart_state` 是**整份替换**的 JSON 字段（PUT 只带该字段时，服务端用新值覆盖旧值，不做深合并） | 后端 `apps/accounts/serializers.py:96-107`（ModelSerializer，`partial=True` 只表示字段可选，不表示 JSON 内部合并） |
| 切页不销毁分析页（`<keep-alive :max="10">`），但容器 `display:none` → 恢复时会补一次 `renderOption()`（notMerge） | `frontend/src/layouts/MainLayout.vue:12`；`frontend/src/composables/useChart.ts` 的 ResizeObserver `recovering` 分支 |
| 重渲染一律 `setOption(option, { notMerge: true })`，option 里写什么机位就回什么机位 | `frontend/src/composables/useChart.ts` 的 `renderOptionNow` |

## 3. 动画行为（只解释，不改）

柱数 = 「有占比的 (bin, Site) 格子」数。不同测试项的零占比格子数不同 ⇒ 柱数常变：

- 柱数相同 → gl 顶点插值播放「长出来/变形」；
- 柱数不同 → 直接换图，无动画；
- 切文件时 `histResult` 置空 ⇒ 组件重挂 ⇒ 没有上一次网格，必然无动画。

不改的理由：强行补齐 0 高柱会把柱数钉死、但引入不可见的悬停目标与多余数据；关掉动画又丢掉用户明确喜欢的部分。此结论写入代码注释与 lessons。

## 4. 视角记忆

### 4.1 状态形状

```ts
export interface Site3DView {
  alpha: number          // 度，gl 限制 [-90, 90]
  beta: number           // 度，无限制
  distance: number       // 透视距离；本项目正交投影下仍参与相机位置
  orthographicSize: number // **模型值**（生效值 = 本值 + 1，见 §2）
  center: [number, number, number] // 中键平移后的观察中心
}
```

- `sanitizeSite3DView(raw: unknown): Site3DView | null`：五个量都必须是有限数（center 三项），否则整份丢弃回 null（毒状态自愈，不半信）。
- 默认值（`SITE3D_VIEW`）：`{ alpha: 28, beta: 30, distance: 245, orthographicSize: 150, center: [0,0,0] }`。
  - 现在 `SITE3D_VIEW` 里的 `zoom: 1` 删掉：gl 的 grid3D 不读它（§2），它在现有代码里是死配置；`orthographicSize: 150` 与现状（未设置 ⇒ 默认 150，生效 151）视觉完全等价。

### 4.2 捕获与回放（读真实相机）

新增 `frontend/src/pages/analysis/composables/site3dView.ts`（纯逻辑，可单测）：

- `readLiveView(chart): Site3DView | null`：走 `getViewOfComponentModel(getComponent('grid3D'))._control`，返回
  `{ alpha: getAlpha(), beta: getBeta(), distance: getDistance(), orthographicSize: getOrthographicSize() - 1, center: getCenter() }`。
  取不到（组件未就绪/私有字段改名）返回 null。
  > `_control` 是私有 API。项目已因 `axisLineCoords` 坑依赖过 gl 内部（见 tokens 注释），且 `package-lock` 钉死 2.1.0；读取失败按 null 降级，不影响出图。升级 gl 时重跑 T2 的假 control 用例与 T3 的视角保留用例即可发现。
- `saveView(view)`：经 `saveChartState({ site3dView: view })` 落账号（防抖 800ms 在记忆模块内）。

`Site3DChart.vue` 的接线：

1. **重渲染保持机位**：`buildOption()` 开头先 `const live = readLiveView(chartInstance.value)`；`live` 存在则写回组件内的 `currentView`。随后 `buildSite3DOption(..., { view: currentView.value ?? undefined })`。这样切参数/切主题/keep-alive 恢复的每次重渲染都带着当前机位，不依赖任何事件顺序。
2. **持久化触发**：容器（`chartRef`）上监听 `pointerup` 与 `wheel`，每次触发重置一个 400ms 静置定时器；到点读一次 live → `saveView`。`onDeactivated` 与 `onBeforeUnmount` 立即保存一次（keep-alive 切页/组件销毁不丢最后一下，此时实例仍可读）。页面刷新由记忆模块既有的 `pagehide` 冲刷兜底。
3. **首次加载**：`useChartMemory` 新增同步读取入口 `getCachedChartState()`（返回最近一次已解析的 `{layout,toggles,site3dView}`，未加载完为 null）。`Site3DChart` 在 setup 里优先同步取它 ⇒ 常见路径（分析页先加载记忆再挂图）首帧就是保存的机位、没有「先默认再转过去」。只有首帧之后才返回的少数路径，才用 `chart.setOption({ grid3D: { viewControl: viewControlFromView(v) } })` **合并**应用一次（gl 按 `animationDurationUpdate` 平滑转过去）。
4. **复位**：现有 ↺ 调 `applyDefaultView(chart)`，同时把 `currentView` 置为默认并 `saveView(默认)`——否则下一次重渲染会把刚复位的图又拉回旧视角。
5. **记忆开关关闭**：不读不写视角（`saveChartState` 内部已按开关拦截；读取侧在开关为 false 时忽略持久化值，用默认机位）。

> **实现补充（2026-11-05 复审，已落地）**：`pointerup` 在单击 tooltip 时也会触发，直接把它当
> 「用户改了视角」会挡掉迟到加载、并在切页/卸载时把未动过的默认机位写进账号。最终接线用两个
> 显式标记：`viewDecided`（交互处理器里**立即**置位，迟到加载据此跳过）与 `userTouched`（只在
> `isSameSite3DView(live, currentView)` 为假时置位，flush 保存后清掉）。`currentView` 只作渲染
> 回退值，不再兼任「用户已决定」判据。e2e 等落库也据此改为解析 postData 比 alpha 值（基底合并后
> 每份 PUT 都带 site3dView，只判键存在会误命中）。
>
> 另一处时序差异：滚轮只写 gl 的 `_zoomSpeed`，阻尼在后续帧才落到 `getOrthographicSize()`，
> 事件当刻读相机仍是旧值。因此 `wheel` 走独立处理器：**无条件**排静置并置 `viewDecided`，
> 「有没有真变化」的判等推迟到 400ms 静置后的 `flushView`（比较后再决定是否 PUT）。

### 4.3 记忆载荷（防整份冲洗）

`analysis_chart_state` 现有形状 `{ layout, toggles }`，新增可选 `site3dView`。

**必须修的隐患**：现在 `saveChartState(patch)` 的 `latest` 只累积「本次防抖窗口内的改动」，`flush` 时整份 PUT。视角是高频触发，若某次只带 `{ site3dView }`，服务端会把布局与勾选整份覆盖掉（§2 的整份替换事实）。修法：

```ts
// useChartMemory.ts
// knownState = 服务端最近一次确认/加载到的完整状态（省略 null 字段）
// 每次 saveChartState：latest = { ...knownState, ...(latest ?? {}), ...patch }
// 每次成功 flush：knownState = { ...knownState, ...payload }
// flush 失败保持现状（静默、下次再试）；下一次 saveChartState 仍以 knownState 为基底
```

- `parseState` 增加 `site3dView: sanitizeSite3DView(o.site3dView)`；坏值 → null。
- `clearChartMemoryState()` 已发 `analysis_chart_state: {}` ⇒ 视角一并清掉（符合「清空记忆」语义）。
- `analysis_chart_memory === false`：`saveChartState` 现有早退不动；`clearChartMemoryState({disableMemory:true})` 行为不变。
- 本机 localStorage 仅继续镜像布局（现状），不镜像视角——账号是视角唯一事实来源；GET 失败时视角回默认（与布局「失败回默认」同口径）。

### 4.4 与现有行为的关系

- 视角是**账号级全局一个**，不按测试项/文件分开（用户确认）。
- 切测试项、切主题、最大化/还原、切页回来：机位保持。
- 切文件：`histResult` 清空导致组件重挂，重挂时从记忆读回同一机位（全局），表现仍是「保持」。
- 新账号/无记录：默认机位（现状）。

## 5. 网格线

- `EChartsColors` 新增 `gridLineColor`：
  - light：`#dbdee4`（= ECharts 默认 `neutral15`，直方图实际线色）；
  - night：`rgba(255, 255, 255, 0.04)`（维持 3D 现在的夜间观感，避免深底上一片亮灰线）。
- `GRID3D_TOKEN_KEYS` 增加 `'gridLineColor'`（T2 的「3D 用到的键两分支都存在」一起管）。
- `grid3DStyle.splitLine.lineStyle.color` 改取 `colors.gridLineColor`；轴线（axisLine）仍取 `splitLineColor`，不动。
- 密度与方向不变：x 每 bin、y 每 Site、z 每刻度（gl 在 box 面绘制，`Grid3DFace._updateSplitLines`）。
- 直方图本身不改（它本来就是 `#dbdee4`）。

## 6. 不做的事

- 不改 2D 直方图的 splitLine（已经是要对齐的目标）。
- 不为「动画一致」改数据形状或关动画（§3）。
- 不按参数/文件分别记视角（用户明确选全局）。
- 不把视角写 localStorage 镜像（账号唯一来源）。
- 不动后端代码（`analysis_chart_state` 是哑 JSON 字段，客户端加键即可）。

## 7. 文件影响面

| 文件 | 改动 |
| --- | --- |
| `frontend/src/pages/analysis/composables/site3dView.ts`（新） | `Site3DView`、`sanitizeSite3DView`、`readLiveView`、`saveView`、默认常量引用 |
| `frontend/src/pages/analysis/composables/site3dOption.ts` | `SITE3D_VIEW` 换 `orthographicSize`；`defaultViewControl` 同步；`buildSite3DOption` 新增 `view?` 并用它构造 viewControl |
| `frontend/src/composables/useChartMemory.ts` | snapshot 增 `site3dView`；`parseState` 校验；`knownState` 基底合并；新增 `getCachedChartState()` 同步读 |
| `frontend/src/pages/analysis/components/Site3DChart.vue` | 读 live→currentView；pointerup/wheel/onDeactivated/onBeforeUnmount 保存；挂载加载与迟到应用；复位写默认 |
| `frontend/src/utils/echarts-tokens.ts` | 两主题加 `gridLineColor`；`GRID3D_TOKEN_KEYS` 加一项；`grid3DStyle.splitLine` 取新 token |
| `frontend/test/unit/site3dView.spec.ts`（新） | 纯函数与假 control |
| `frontend/test/unit/site3dOption.spec.ts` | `SITE3D_VIEW` 形状、`view` 参数生效 |
| `frontend/test/unit/chartLayout.spec.ts` | parseState 视角字段、视角单键上报仍带 layout+toggles |
| `frontend/test/unit/echartsTokens.spec.ts` | 新 token 对称/取值、splitLine 取 gridLineColor |
| `frontend/test/unit/site3dWiring.spec.ts` | 组件接线（读 live、保存触发、复位写默认） |
| `frontend/e2e/analysis/site3d.spec.ts` | 新增 1 条：拖拽 → 切参数 → 机位保持；刷新 → 仍保持 |

行数预算：`Site3DChart.vue` 现 140 行，预计 ≤ 200；`site3dView.ts` ≤ 90；`useChartMemory.ts` 181 → ≤ 200。硬闸仍是 600 行。

## 8. 测试判据

T2（纯函数/接线，全部可变异复核）：

1. `sanitizeSite3DView`：合法对象原样返回；缺字段/`NaN`/字符串/center 长度非 3 → null。
2. `readLiveView`：假 control 的四个 getter + center，`orthographicSize` **减 1**；control 缺失 → null。变异：去掉 `-1` 必须红。
3. `buildSite3DOption`：给 `view` 时 viewControl 逐字段等于它；不给时等于默认。变异：忽略 `view` 必须红。
4. 记忆：`parseState` 接受 `site3dView`、拒绝坏值；**视角单键上报后 flush 的 payload 仍包含加载时的 layout 与 toggles**。变异：去掉 knownState 基底必须红。
5. tokens：两主题键集相等且含 `gridLineColor`；light `#dbdee4`、night `rgba(255,255,255,0.04)`；`grid3DStyle` 的 splitLine 取该 token（写死或不跟随主题必须红）。
6. 接线：`Site3DChart.vue` 的 `buildOption` 先读 live 再构造；`pointerup`/`wheel`/`onDeactivated`/`onBeforeUnmount` 有保存；复位路径写默认。

T3（不可替代，1 条）：

- 打开 3D → 拖拽旋转（读 live 记录 alpha/beta）→ 切换参数 → 轮询读回的 alpha/beta 与拖拽后一致（容差 0.5°，damping 余量）→ 等 `PUT /auth/settings/` 响应落地（**不用固定 sleep**：组件 400ms 静置 + 记忆 800ms 防抖）→ 刷新页面并重选文件/参数 → 机位仍一致。
- 只在 Edge 项目跑一次，成本 ≈ 5s。

## 9. 已知风险

1. 依赖 gl 私有 `_control`（读取失败按 null 降级；升级 gl 需重跑 §8 的 2/6 与 T3）。
2. 「切参数保持机位」意味着不同量级的参数共用同一机位（用户已确认要全局一个）。极端情况下新参数柱高变化大，需要手动缩放——与「每次都跳回默认」相比这是用户明确选择的代价。
3. 视角按账号同步；同账号多机（LAN 部署）会互相覆盖，遵循「最后写入者赢」，与布局记忆一致。
