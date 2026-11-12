# 图表区域框选 → 子集直方图 设计

日期：2026-11-11
状态：设计已获用户批准（含 D1–D5 决策点），待实现
范围：单文件分析 tab 的直方图与 serial 散点图

## 1. 目标与已确认口径

在直方图/serial 散点图上框选一批芯片（按 serial 圈定），右键新建一张**子集直方图面板**，
单独看这批芯片在同一参数上的分布。

用户已逐项确认：

| 问题 | 结论 |
|---|---|
| 新图表内容 | 子集直方图（同参数），不做散点/跨参数切换 |
| 直方图选择手势 | 横向拖拽框选值域（ECharts brush lineX） |
| 散点图选择手势 | 矩形框选（brush rect） |
| CPK 口径 | **原参数规格限（RDL）+ 子集 mean/std** |
| 面板生命周期 | 会话级多面板并存；切文件/切参数清空；不持久化 |

## 2. 方案选型

**采用方案 A：扩展 `/analysis/histogram/` 加可选 `selection` 字段 + 独立子集面板区。**

- 方案 B（独立 `/analysis/subset_histogram/` 端点）：收益与 A 几乎相同，但多一个相似端点
  多一份守卫漂移风险（lessons R3：histogram/qqplot/boxplot 守卫不齐是状态码雪崩温床），
  前端 `useHistogram` 也无法直接复用。否。
- 方案 C（纯前端算子集）：直方图响应只有聚合计数、**没有 bin→serial 映射**，前端无法自行
  把值域选区解析成 serial 集合；且 CPK/KDE/正态公式单一来源在后端是既定原则。否。

A 的核心：选区 = 现有统计管线的一个前置行级过滤步骤，前后端各加一层薄壳。
`compute_histogram_stats` 的 CPK 本来就始终锚定 RDL 规格限（不随 range_type 变），
「CPK 根据原来的数据」零改动天然成立。

## 3. 端到端交互流

1. 直方图按住左键横拖 → 高亮值域区间；serial 散点拖矩形 → 圈内点高亮、其余淡化。
2. 图上右键 → 自绘菜单：「新建子集直方图」「清除选择」；无选区时不弹菜单。
3. 点新建 → ChartDock **下方**的子集面板区出现新面板：
   标题 `{param} 子集 · n={count}` + 选区摘要（值域 [lo, hi] 或 serial 颗数），
   内容复用 HistogramChart 渲染 + 统计卡（n / mean / std / CPK / 原规格限数值）。
4. 可继续框选再建，多面板并存（网格每行最多 2 张），× 关闭；
   切文件/切参数/换账号全部清空。

## 4. 后端设计

### 4.1 selection 请求字段

`/analysis/histogram/`（POST）计算路径新增可选字段，两种形态：

```jsonc
// 直方图框选：值域（不需要序列列）。lo/hi 各为有限数或 null，null = 该侧无界，
// 至少一个非 null。框住 underflow/overflow 兜底柱时对应侧置 null（见 D6）。
{ "kind": "value_range", "lo": 1.23, "hi": null }
// 散点框选：serial 集合；serial_col 可选，缺省自动检测
{ "kind": "serials", "serials": [1, 2, 3], "serial_col": "Serial_No" }
```

### 4.2 过滤位置

视图 `AnalysisViewSet.histogram`（apps/analysis/views/analysis_views.py）：
在现有过滤链（`filter_bin1_rows` / `filter_test_items`）**之后**、per-param 循环
**之前**对 df 做行级过滤，然后照常走 `compute_histogram_stats`：

- `value_range`：`pd.to_numeric(df[param], errors='coerce')` 后 `.between(lo, hi)`
  过滤行（R4：coerce + 向量化，不用 apply；pandas 3.x 的 `between(None)` 全 False，
  None 边界先映射 ±inf 再 between）。
- `serials`：序列列解析复用 `get_serial_column(df)`（serial_distribution 同款）；
  请求带 `serial_col` 时校验该列存在于 df，否则 400。匹配双方做类型容错
  （数值列 coerce 后 isin；字符串列直接 isin）；未匹配的 serial 静默忽略，
  实际颗数以响应 n 为准。

### 4.3 守卫表（全部 400，结构化 error code）

| 情形 | code |
|---|---|
| kind 不在白名单 / selection 非 dict | `invalid_selection` |
| value_range 的 lo/hi 非「有限数或 null」、两者皆 null、或双非 null 时 lo > hi | `invalid_selection` |
| serials 空 / 非 list / 元素非 number\|string / 长度 > 100000 | `invalid_selection` |
| selection 存在但请求参数数 ≠ 1 | `invalid_selection`（选区只对单参数有定义） |
| serial_col 不在 df 列 | `invalid_selection` |
| 选区过滤后无有效数据 | `empty_selection`（不走 500，也不复用 no_valid_params 的误导文案） |

fast path（无 params 的参数列表发现）忽略 selection。stale param 守卫
（`guard_all_missing`）维持不变，在选区过滤之前生效。

### 4.4 三个口径决策（已批准）

- **D1 子集分箱强制 `range_type='DR'`**（子集自身值域）。沿用 RDL 时，选「USL 之外」
  的子集值全在规格限外，会被压成边缘一根柱，看不到分布形状。CPK 不受影响
  （始终锚定 RDL）。子集请求不带 custom_low/high。
- **D2 子集不做 IQR 异常值再剔除**：面板按 outlierHandling=off 展示全量子集统计。
  用户显式圈的就是「异常」群体，再剔一次会把要看的对象剔没。行级筛选（Bin1 等）
  仍沿用当前 tab 上下文（请求照带现有过滤参数）。
- **D3 规格限线落在子集轴范围内才画**；在范围外时统计卡照常显示原规格限数值 + CPK，
  不强行扩轴（否则子集被压成一小簇）。响应里的 lower_limit/upper_limit 仍是原规格限。
- **D6 兜底柱无界语义（计划阶段发现，2026-11-11 补）**：直方图「limit 边缘外」的柱是
  underflow/overflow 兜底柱，柱内芯片真实值远在轴范围之外——若按框选的轴值域过滤会选空
  （恰是用户主场景）。规则：框选区间触达 underflow 柱中心（`bin_centers[0]`）→ `lo=null`；
  触达 overflow 柱中心（`bin_centers[-1]`）→ `hi=null`；两侧都触达 = 全选，前端视为无选区。
  判定在前端（持有父图 bin_centers），后端只消费 null 边界。

## 5. 前端设计

### 5.1 新文件（600 行约束驱动）

SingleParamTab.vue 已 578 行（上限 600），新逻辑全部进新文件，
SingleParamTab 只加约 3 行（挂 `<SubsetPanelArea/>` + 两图各一个 `enable-selection` prop）。

| 新文件（frontend/src/pages/analysis/ 下） | 职责 |
|---|---|
| `composables/useChartBrushSelect.ts` | 两图共用：zrender 拖拽 → 选区、DOM 高亮浮层、右键菜单状态（机制见 §5.3）。直方图 value-range / 散点 rect |
| `composables/selectionGeometry.ts` | 纯函数：矩形归一/求交、点集命中取 serial、跨 lane 去重、兜底柱无界判定、面板标题 |
| `composables/useSubsetPanels.ts` | 模块单例（仿 useChartDock 模式）：面板列表 {id, selection, result, loading, error}；create 读 useSingleTabStore 拼请求（现有过滤参数 + selection + range_type='DR'）；remove；watch fileId/selectedParam 清空 |
| `components/SubsetPanelArea.vue` | ChartDock 下方独立区域：网格（每行 ≤2）渲染面板、标题/×关闭/loading/ErrorBanner，内嵌复用 HistogramChart（outlier-handling 固定 'off'）+ 统计卡 |
| `components/ChartContextMenu.vue` | 自绘右键浮层（Teleport to body，CSS 主题变量，dark/light 双维护） |

HistogramChart / SerialChart 各加约 20 行：接 `enable-selection` prop，
调 useChartBrushSelect，把 brush 配置合并进 buildOption、菜单事件接到 composable。

### 5.2 关键决策（已批准）

- **D4 子集面板不进 ChartDock**：dock 的 `ChartKey` 联合类型 / `isValidLayout` /
  账号记忆是固定集合契约（T2 钉死「旧 v:1 存档回读逐字不丢」），临时 key 混入
  有泄漏进账号 PUT 的风险（R5 族）。独立区域零侵入；代价是不能拖进主拼格、
  不能用分隔条调大小（固定网格 + 固定面板高度）。
- **D5 散点命中语义 = 按绘制坐标（WYSIWYG）**：含 jitter 微移与锚定到轴边缘的
  超界点，圈住即选中，收集 `realSerial`。框选常驻：左键拖=选择，滚轮缩放保留，
  散点图拖拽平移让位（brush 与 inside dataZoom 的左键冲突；直方图无 dataZoom 无冲突）。

### 5.3 框选技术要点（计划阶段定型：zrender 指针事件 + DOM 浮层）

不用 ECharts brush 组件，改用 zrender `mousedown` + window `mousemove/mouseup` +
`convertFromPixel`，选区高亮是容器内的绝对定位 DOM 浮层。原因：useChart 每次渲染
`setOption(notMerge:true)` 会清掉 brush 的 areas 与光标激活态，而本仓图表重渲染频繁
（主题/数据/resize）；自有状态 + DOM 浮层可在重渲染后按数据坐标重定位，且 large 模式
与多 lane 行为完全确定。交互契约（拖拽框选、高亮、右键菜单）不变。

- 直方图（value-range 模式）：拖拽只取 X 分量，浮层占满 grid 全高；松手后
  `convertFromPixel({xAxisIndex:0}, px)` 得值域，再按 D6 做兜底柱无界判定。
- 散点（rect 模式）：逐 lane 取 `grid.coordinateSystem.getRect()` 与拖拽矩形求交，
  交集为空跳过该 lane；交矩形角点 `convertFromPixel` 得 X 轴下标区间与 Y 值区间，
  过滤该 lane 点集（x=轴下标、y=绘制值含 jitter/锚定，D5 WYSIWYG）取 `realSerial`，
  跨 lane 合并去重。点集由 SerialChart 在 buildOption 里同步写出的 `displayLanes`
  提供（只在 mouseup 时读，不 watch，避免渲染循环）。
- **large 模式（≥5000 点）天然兼容**：命中判定是我们自己的点集过滤，不依赖
  ECharts 的 brushSelected/dataIndex。
- 拖拽起点可在容器内任意位置（含标题留白），选区矩形与各 grid 矩形求交后再换算——
  这样锚定在轴顶/底边缘的超界点也能被框住；与所有 grid 都不相交则不产生选区。
  位移 <3px 视为点击，不产生选区。
- 右键：容器 DOM `contextmenu`（有选区才 preventDefault）+ 自绘浮层；选区为空不弹。
  图组件 emit `create-subset(selection)`，SingleParamTab 转给 useSubsetPanels（约 6 行，
  578+6 < 600 行约束内）。
- 新建面板后父图选区保留（可继续调整再建）；「清除选择」清状态 + 移除浮层。
  图实例重建（渲染器切换/容器 v-if）时选区清空；重渲染/resize 后浮层按数据坐标重定位。

### 5.4 请求复用

useSubsetPanels 复用 useHistogram 的请求构造（同一 API 函数加可选 selection 形参），
过滤参数读 useSingleTabStore；serials 形态的 serial_col 取散点图响应的生效列
（`serialDistData.serial_col`，含手动覆盖后的值），不由面板区猜。

## 6. 错误与边界

- 空选区右键：不弹菜单。
- 子集为空（400 empty_selection）：面板内错误条「选区内无有效数据」，可关闭。
- 请求失败：面板内 ErrorBanner + 重试（重试原选区）。
- 切文件/切参数：面板清空（R5：前端 watch 清 + 后端 stale param 守卫双层）。
  换账号：由 auth 复位路径显式清空（仿 `resetChartDockMemoryState`，不赌 fileId 一定变）。
- 选区含被当前行级筛选（Bin1）排除的 serial：静默按实际匹配颗数展示，n 以响应为准。
- brush 浮层色、菜单、面板标题/统计卡：dark/light 双主题（项目硬约束）。
- 3D/QQ/箱线/多文件 tab/晶圆图：本期不参与框选。

## 7. 测试分层（docs/reference/testing-gates.md）

- **T1** `test/backend/test_analysis_histogram_selection.py`：守卫全组合（4.3 表逐行）、
  两种选区过滤正确性（颗数/bin 范围）、CPK=原规格限+子集 mean/std（含子集全在限外）、
  空子集 400、单参数限制、字符串/数值序列列、serial_col 覆盖与非法列、
  fast path 忽略 selection、Bin1 上下文叠加。
- **T2** `frontend/test/unit/chartBrushSelection.spec.ts`：coordRange→选区 payload 纯函数
  （值域、category 下标映射、jitter/锚定命中、多 lane 合并去重、空 areas）；
  useSubsetPanels 增删清纯逻辑。
- **T3** `frontend/e2e/analysis/subset-drilldown.spec.ts`：只留接线证明——
  ① hist 框选→右键→面板出现（n、CPK 非空）；② serial 框选→同上；
  ③ 切参数后面板清空。组合全在 T1，不在浏览器逐组点。
  面板带 `data-subset-panel` / `data-subset-n` 契约属性；双主题各验一次菜单可见性。
- 门禁：批内 `npm run test:e2e:affected`（analysis 档）；收口 `e2e_pool.mjs --slots=4`
  + 后端全量；提交前 `npx vitest run` + `npm run lint:e2e` + `npm run build`。

## 8. 不做的事（YAGNI）

- 子集面板持久化 / 拖进主拼格 / 跨参数切换 / 子集散点图。
- 预设区域菜单项（「USL 右侧」等）——框选已覆盖，需要时后加。
- 选区导出 serial 列表 / 子集导出文件。
- 多文件 tab、晶圆图、相关性页的框选。

## 修订（2026-11-12）

用户需求日期 **2026-11-12**：四点跟进改动经用户批准，反转原文四处决策。
实施计划 `docs/superpowers/plans/2026-11-12-subset-followup.md`（SDD 六任务，
提交 5902485 T1 / 3956bf7 T2 / 6b7577a T3 / c148315 T4 / 4c2ee07 T5 / Task 6 收口，
清单见 `docs/tasks/todo.md` 对应条目）。**原文正文保留不改**（历史规格），
本节逐条记录反转与修复；引用原文时以「原 §x」标注。

### 反转 1：切参数清空 → 面板跟随 + serials 固化（原 §1 生命周期表、§3.4、§5.1 useSubsetPanels 行、§6）

- 原口径：切文件/切参数清空全部面板。
- 新口径：**切文件仍清空**（R5 不变）；**切参数不清空**——首次加载成功时后端随
  histogram 响应回传 `selection_serials` / `selection_serial_col`（T1），前端
  `fixateSelection` 把 `value_range` 选区固化成 `serials`；切参数时 serials 面板
  对新参数重查（`load` 带 epoch 代际守卫，过期响应/过期拒绝一律丢弃，loading 由
  最新一次 load 接管）；后端没回 serials 的 value_range 面板冻结在原参数原结果。
- 这是 R5「上下文切换清持久态」的**显式例外**（用户批准）；换账号仍由
  `resetSubsetPanels()` 显式清空，不赌 fileId 一定变。
- 判据反转：原 §7 T3③「切参数后面板清空」→「切参数面板跟随 + serials 固化重查」
  （e2e 钉请求体 `"kind":"serials"` + `"serials":[4,5,6]` + 标题跟随新参数）。

### 反转 2：选区保留 → 创建即消费（原 §5.3 末条「新建面板后父图选区保留」）

- 原口径：新建面板后父图选区保留（可继续调整再建）。
- 新口径：点「新建子集直方图」**即消费选区**——`createAndClose` 清浮层 + 关菜单，
  选区只展示一次；serial 散点改为 mouseup 立即消费（见反转 3）。
  可继续框选再建（每次拖拽产生新选区），但旧选区不残留。

### 反转 3：serial 建面板 → 跨参数芯片高亮（原 §1 表、§3.1–3.2、§7 T3②）

- 原口径：serial 散点框选 → 右键「新建子集直方图」面板。
- 新口径：serial 框选 **mouseup 立即高亮**命中芯片，不建面板——叠加「高亮芯片」
  系列 + 底层 site 系列降透明（≤0.25）；高亮是会话单例（`useSerialHighlight`），
  **切测试项按 serial 对新参数重画**（跨参数保持，同反转 1 的 R5 显式例外）；
  右键菜单只留「清除高亮」（无「新建子集直方图」）；登出/换账号
  `resetSerialHighlight()`。命中语义仍按 D5 WYSIWYG（收集 `realSerial`）。
- 判据反转：原 §7 T3②「serial 框选→建面板」→「serial 框选→芯片高亮 + 跨参数保持」
  （e2e 钉叠加系列点集恰为 {4,5,6}、底层降透明、切 VCC 后标题与点集双钉）。

### 反转 4：子图无缩放 → inside dataZoom（原 §5.2 D5 括注「直方图无 dataZoom」、§5.1 HistogramChart 行）

- 原口径：直方图无 dataZoom，子图复用 HistogramChart 亦无缩放。
- 新口径：HistogramChart 新增 `enableDataZoom` prop（**默认关**）；子集面板开
  inside dataZoom（滚轮缩放 + 拖拽平移），**主直方图保持无缩放**；子图不传
  `enable-selection` ⇒ brush 不绑 mousedown，与 inside dataZoom 无左键冲突。
  serial 图框选开启态 `moveOnMouseMove=false`（拖拽让位框选），滚轮缩放不受影响
  （Task 3 的 preventDefault 只拦 compat mousedown，不拦 wheel）。
- e2e 钉：子图滚轮后窗口 start>0 且 end<100（收窄，区分缩放与平移）、拖拽后 start
  继续增大；主图交互前后 dataZoom 缺席（null）。

### 光标 bug 修复（Task 3，随反转 2 落地）

- 现象：框选拖拽后浏览器留下插入光标/文本选区。
- 根因：折叠 caret 被浏览器塞进焦点可编辑节点（el-select 隐藏 input），放置先于
  事件派发，拖拽移动期间反复重放；zrender 6 的 `e.event` 是 pointerdown，直接
  取消它会抑制框选依赖的 compat mouseup（菜单永不出现）且拦不住 caret。
- 修法：**按下/移动/抬起三清** `window.getSelection().removeAllRanges()` +
  **compat mousedown capture 阶段 preventDefault** + 容器 `user-select:none`。
- 承重断言：e2e 拖拽后断言 `selection.toString()===''` **且 `rangeCount===0`**——
  toString 在 headless 恒真（zrender SVG 自带 user-select:none），rangeCount 才抓
  得到折叠 caret（RED rc=1 → GREEN rc=0 实测）。

### 不变项

**D1**（子集分箱强制 DR）、**D2**（不做 IQR 再剔除）、**D4**（面板不进 ChartDock）、
**D5**（散点 WYSIWYG 命中）、**D6**（兜底柱无界语义）全部不变；后端守卫表（原 §4.3）
不变，`selection_serials` 回传为增量字段；CPK 仍锚定原参数规格限（RDL）。