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
// 直方图框选：值域（不需要序列列）
{ "kind": "value_range", "lo": 1.23, "hi": 1.45 }
// 散点框选：serial 集合；serial_col 可选，缺省自动检测
{ "kind": "serials", "serials": [1, 2, 3], "serial_col": "Serial_No" }
```

### 4.2 过滤位置

视图 `AnalysisViewSet.histogram`（apps/analysis/views/analysis_views.py）：
在现有过滤链（`filter_bin1_rows` / `filter_test_items`）**之后**、per-param 循环
**之前**对 df 做行级过滤，然后照常走 `compute_histogram_stats`：

- `value_range`：`pd.to_numeric(df[param], errors='coerce')` 后 `.between(lo, hi)`
  过滤行（R4：coerce + 向量化，不用 apply）。
- `serials`：序列列解析复用 `get_serial_column(df)`（serial_distribution 同款）；
  请求带 `serial_col` 时校验该列存在于 df，否则 400。匹配双方做类型容错
  （数值列 coerce 后 isin；字符串列直接 isin）；未匹配的 serial 静默忽略，
  实际颗数以响应 n 为准。

### 4.3 守卫表（全部 400，结构化 error code）

| 情形 | code |
|---|---|
| kind 不在白名单 / selection 非 dict | `invalid_selection` |
| value_range 的 lo/hi 非有限数或 lo > hi | `invalid_selection` |
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

## 5. 前端设计

### 5.1 新文件（600 行约束驱动）

SingleParamTab.vue 已 578 行（上限 600），新逻辑全部进新文件，
SingleParamTab 只加约 3 行（挂 `<SubsetPanelArea/>` + 两图各一个 `enable-selection` prop）。

| 新文件（frontend/src/pages/analysis/ 下） | 职责 |
|---|---|
| `composables/useChartBrushSelect.ts` | 两图共用：brush option 注入、brushEnd 取 coordRange、选区状态、右键菜单开关与位置。直方图 lineX / 散点 rect |
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

### 5.3 brush 技术要点

- 直方图：brush lineX、xAxisIndex 0、brushMode single、隐藏 brush toolbox，
  挂载后 `dispatchAction(takeGlobalCursor)` 常驻激活；brushEnd 的
  `areas[0].coordRange` 即值域 [lo, hi]（value 轴直接是数据坐标）。
- 散点：brush rect；split-by-site 多 lane 时 xAxisIndex/yAxisIndex 配 'all'，
  逐 lane 取 coordRange 过滤各自点集后合并去重。x 是 category 轴，
  coordRange 给的是轴下标——点集 value[0] 本来就是下标（serialIndex 映射），直接可比。
- **large 模式（≥5000 点）不依赖 `brushSelected` 的 dataIndex**：自己用 coordRange
  过滤点集取 realSerial，大数据量下稳定。
- 右键：容器 DOM `contextmenu`（preventDefault）+ 自绘浮层，不依赖 ECharts 命中；
  选区为空不弹。菜单动作直接调 useSubsetPanels 单例，不经 SingleParamTab 中转。
- 新建面板后父图选区保留（可继续调整再建）；「清除选择」= `dispatchAction({type:'brush', areas:[]})`。

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