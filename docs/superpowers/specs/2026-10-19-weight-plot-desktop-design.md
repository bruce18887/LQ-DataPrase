# 权重画图（桌面应用版）设计

- 日期：2026-10-19
- 状态：待评审 v1（四个架构岔口已由用户点定，见 §2）
- 源需求稿：`docs/superpowers/specs/2026-10-19-weight-plot-design.md`（**Excel 加载项版**，本稿不覆盖它）
- 目标工程：LQ-DataPrase（Django + Vue3/Electron）
- 输入样例：`本机一份私有权重 CSV（路径与文件名都不写入本文档）`（**禁止入库**，理由见 §8）

## 1. 背景与结论性判断

源稿写的是另一个工程：其第 6 行自标「关联工程」为本机另一份 Excel 加载项工程（Excel-DNA，net462），落点是 Ribbon、
`[ExcelCommand]` OnAction、ChartObject、Form Control 复选框。实测该工程 `grep -ril weight --include=*.cs`
**零命中** —— 源稿是一张纸，从未实现。

本稿把源稿当**需求来源**，功能落进 LQ-DataPrase 桌面应用。可继承的是宿主无关的口径（§3、§2 表格里的一半行），
必须重写的是 Excel 宿主专属的部分（源稿 §4.2 几何、§6 控件、§8 验证通路整节作废）。

## 2. 已确认的四个岔口（用户点定）

| # | 决定 | 理由/后果 |
|---|---|---|
| 1 | 数据来源：**只本地选文件** | 不做 SFTP 取文件、不复用数据管理的已上传文件 |
| 2 | Excel 导出：**数值表 + 原生 Excel 图** | `openpyxl==3.1.5` 已在 `requirements/base.txt:48`，实测 `.venv` 可导入 `openpyxl.chart.ScatterChart/LineChart`，无需加依赖 |
| 3 | 入口形状：**侧栏独立项 + 路由 `/weight`** | 独立 path 才不会因 `Sidebar.vue:118-120` 的 `startsWith` 让「SFTP 浏览器」同时高亮 |
| 4 | 解析层：**后端单解析器**（方案 A） | 页面与 xlsx 共用同一个解析器；后端不采信前端算出的数值（lessons R3②）；判据落 T1 |

## 2.1 本稿自定的口径（用户未逐条点定，评审时请优先看这张表）

用户明示的只有 §2 那四条。下面 8 条是本稿替他定的或有意偏离源稿的，每条都可单独推翻：

| # | 口径 | 出处 | 类型 |
|---|---|---|---|
| 1 | 组间基色用现行 8 色板按 `组序 % 8` 循环，**不新建 14 色板**；要新建必须先过 `tasks/cvd_verify.mjs` 的成环 ΔE≥15 | §6.1/§6.4 | 与源稿 §5.3 冲突，有实测依据 |
| 2 | 组内 4 条用**线型**区分而非同色系明暗变体 | §6.2 | 有意收窄，需可见提示 |
| 3 | 均值线改**深灰 1.5pt 细虚线、无圆点**（粗实线会把贴得很近的 4 条原始线整条盖住） | §6.3 | 2026-10-20 用户实测 |
| 4 | 均值一次算完、按钮只切显示（源稿：点按钮才算） | §5.2 | 有意偏离，用户不可见 |
| 5 | 入站三边界：2 MB / 2000 条 / 单条 1024 | §3.4 | 源稿没有，本稿新增 |
| 6 | 状态只住 Pinia，刷新即丢、不落 localStorage；不落库 ⇒ 无导出历史 | §11 | 依用户第 3 条推得 |
| 7 | 权限：所有已登录用户，不新增 `FEATURE_PERMISSIONS` key | §12 | 本稿自定 |
| 8 | 导出**每个测试项一张图**、图例只列本组 4/5 条（14 组一张图时 y 轴会被大值组压扁）；跨组颜色对照仍靠表内系列名着色 | §7.3 | 2026-10-20 用户实测改版 |

## 3. 输入契约与解析（继承源稿 §3）

### 3.1 解析规则

- 识别 `double 名称[声明长度] = {数值列表};`，允许换行与空白；
- **空白必须含 TAB**：真实样例是 `double<TAB>名称[16]= {…};`，且条目之间夹空行；
- **必须同时接受 CRLF 与 LF**（样例是 CRLF，Linux CI 检出可能是 LF）；
- 忽略其他行与空行；数值按等价格于 `InvariantCulture` 的方式解析，支持小数与科学计数法；
- 名称原样保留，区分大小写。

### 3.2 命名与分组（继承源稿）

- 某名称只出现 1 次：保持原名；出现 N 次：全部加序号 `名称_1 .. 名称_N`；均值行 `名称_Avg`；
- 组序 = 测试项在文件中**首次出现的顺序**；组内按出现顺序排；
- 逐点均值：同名声明在同一 code 上求算术平均；长度不齐时，每个 code 只对该位置有值的成员求平均，无值留空；
  均值序列长度 = 组内最大声明长度。

### 3.3 校验与错误

沿用 `apps/common/errors.py:14` 的 `error_response(code, detail=None, status=400, **extra)`，HTTP 一律 400。

**分工是既有的硬规矩**（该文件 docstring 明写「文案的单一来源仍在前端 `ERROR_CODE_MAP`；后端不要在这里再造
一份中文表 —— 两份必漂，见 lessons 2026-09-19」）：后端只给**稳定机器码 + 结构化 detail**，
中文句子落在 `frontend/src/utils/error.ts:15` 的 `ERROR_CODE_MAP`。

**为什么"顺手写一句英文 detail"也算违规**（Task 3 评审实测）：`error.ts:60-64` 的 `pickMessage` 优先级是
`message` → `detail` → 查表，而 `errors.py` 会把非空字符串 `detail` 同时复制成 `message` ⇒ 只要 detail 是非空
字符串，它就**赢过** `ERROR_CODE_MAP` 的中文，中文界面会直接显示 `text is required`。
所以守卫类（缺参数/类型不对）错误一律 `detail=None`、只在 `extra` 里给 `field=`，
让人话只从 `ERROR_CODE_MAP` 出；curl 侧仍能从 `code` 与 `field` 读到机器可读信息。

| code | 触发 | detail / extra 字段 |
|---|---|---|
| `no_declaration` | 文件中没有任何合法声明 | `detail` 为 None，文案纯靠 `ERROR_CODE_MAP` |
| `weight_length_mismatch` | 声明长度与实际数值个数不一致 | `line`（行号）、`name`、`declared`、`actual` |
| `weight_bad_number` | 某个数值无法解析 | `line`、`token`（原始串） |
| `weight_too_large` | 越过 §3.4 任一边界 | `limit`、`actual`、`which`（`text`/`declarations`/`length`） |

新增码必须同时进 `ERROR_CODE_MAP`，否则前端只显示裸机器码（`error.ts:63` 的回落分支）。

### 3.4 入站边界（源稿没有，本稿新增）

解析结果会直接决定 X 轴宽度与系列数，所以边界必须在后端把住，不能依赖前端：

| 边界 | 值 | 超限 |
|---|---|---|
| `text` 字符数 | ≤ 2 000 000 | `weight_too_large` |
| 声明条数 | ≤ 2000 | `weight_too_large` |
| 单条声明长度 | ≤ 1024 | `weight_too_large` |

## 4. 架构与数据流

```
选文件 → File.text() → POST /api/v1/weight/parse/  {filename, text}
                      → 200 {groups[], code_max, series_count, group_count}
                      → 前端建 ECharts option 画图（开关/均值都在前端内存里切）
导出   → POST /api/v1/weight/export/ {filename, text, visible_group_indexes[], show_mean, palette[]}
                      → 200 FileResponse(io.BytesIO) → 前端 blob 下载
```

**零落库的字面成立**：两端点都不建 model、不写 `MEDIA_ROOT`、不用 multipart、不碰 migration。

**但"零写库"这话别说满**（Task 5 评审实测）：文件名走共享的 `render_export_filename`，它内部是
`UserSetting.objects.get_or_create(user=…)`（`apps/common/export_naming.py:97`）—— 对一个从未存过设置的账号，
它会 **INSERT 一行 UserSetting**。那是本仓所有导出通路共有的既有行为，写的是**账号设置**、不是权重数据：
权重本身仍然无任何记录，用户的第 3 条要求照样成立。但任何人后续要写"零 SQL / 零写入"的断言，
必须以"除这一行设置外"为前提，否则那条断言是假的。

两条已被实测否证的路，别再试：

- 复用现有上传：全后端**只有一个** multipart 视图 [apps/datafiles/views/file_views.py:535](../../../apps/datafiles/views/file_views.py)，
  它会落盘并建 `DataFile`/`ParseHistory` 且跑格式嗅探（这格式必挂）⇒ 违反「不落库」。
- 走作业化：[apps/jobs/views.py:122-124](../../../apps/jobs/views.py) 的 `_submit_export` 上来就
  `get_object_or_404(DataFile, …)`，无库记录即 404 ⇒ 导出只能是**同步** `FileResponse`。

同步 + 零持久化的现成先例：[apps/batch_report/views.py:85](../../../apps/batch_report/views.py)
`FileResponse(io.BytesIO(...), as_attachment=True, filename=...)`。

必须用 `FileResponse` 而非手写头，理由已有注释：WSGI 响应头只认 latin-1，中文文件名手写
`Content-Disposition` 会 `UnicodeEncodeError`（见 [apps/export/views.py:183-185](../../../apps/export/views.py)）。

## 5. 前端页面与交互

### 5.1 入口

- 路由 `/weight`，`meta: { title: '权重画图', icon: <新增图标>, desc: '权重 CSV 逐点曲线与均值' }`，
  图标加进 [frontend/src/router/index.ts:2-4](../../../frontend/src/router/index.ts) 的 import；
- 菜单项插在 [frontend/src/components/layout/Sidebar.vue:100 与 102 之间](../../../frontend/src/components/layout/Sidebar.vue)，
  **不得带 `groupStart`**，否则「SFTP 浏览器」下面会多一道分隔线；图标同步加进该文件 73-82 行的 import；
- 不照「SFTP 搜索」那条 `meta.parent` 写法（它压根不在侧栏）。

### 5.2 布局与图表口径（2026-10-19 初版；版式部分已被 §5.3 取代）

> **2026-10-20 用户看过实机后要求「连版式一起重排」**：下表的「左图右表」几何与顶部条不再采用，
> 现行版式见 §5.3。本节其余工程口径（`useChart`、`el-table`、按 `visible` 渲染图列表、
> 每图自带组内图例、均值默认打开）继续有效。

| 区块 | 内容 |
|---|---|
| 顶部条 | 选文件按钮 + 当前文件名 + 「均值」按钮 + 「导出 Excel」按钮 + 解析错误条 |
| 左 | ECharts 图列表：**每个可见测试项一张**（纵向滚动，标题=测试项名，各自 x/y 轴） |
| 右上 | 组复选框 chip 组（每项一个，一次开关该组整张图） |
| 右下 | 数值表：原序号 / 系列名 / code 0..code_max |

- 文件选择用浏览器 `File` + `.text()`，**不用** Electron `openFileDialog`：它只回路径字符串，
  服务器部署形态下后端读不到那个路径。Electron 那三个 dialog IPC（`electron/ipc-handlers.ts:60-90`）
  目前只有 `SystemPathsSettings.vue` 用过 `openDirectoryDialog`，本功能不动它。
- 图表初始化必须走 `useChart`（[frontend/src/composables/useChart.ts:28](../../../frontend/src/composables/useChart.ts)）
  → `initEchartsWhenReady`（[frontend/src/utils/echarts-init.ts:76](../../../frontend/src/utils/echarts-init.ts)），
  禁止裸调 `echarts.init`（lessons R7③）。
- 表格用 `el-table` + 横向滚动，不引 ag-grid chunk。
- 开关与均值的实现：页面按 `visible` **渲染图列表**，每张图只构建本组 series（`buildOption(group, …)`）。
  不用 ECharts 原生 legend 做跨组开关 —— 原生 legend 是逐系列的，做不到「14 项按测试项开关」；
  分组后每图自带的 legend 只列本组 4/5 条，用作组内线型对照（与导出侧同口径）。
  **2026-10-22 起这行 legend 由页面级总开关控制显隐**（§5.4），`showMean` 与 `visible` 的语义不变。
  `buildOption` 必须住纯模块以便 T2 覆盖（§9）。
- **2026-10-20 改版原因（用户实测反馈）**：14 组共用一张图时，WT0004 那种数万量级的值把 y 轴
  压到只剩顶部一根尖峰，其余组全成底部平线，图不可读。⇒ 每个测试项独立成图、独立缩放。
- **2026-10-20 样式定稿（用户截图）**：4 条原始线 = 细线 + 小圆点（圆点填线色）；均值线 =
  深灰 1.5pt 细虚线 + 每个点的数值标签（不画圆点，避免盖住原始点）；**均值默认打开**（选文件后
  `showMean=true`，表格初始 70 行）。页面标签重叠时隐藏重叠标签（`labelLayout.hideOverlap`）；
  Excel 导出侧仍全量写。
- 源稿 §3.4「点按钮时才计算均值」**有意改为**：一次算完、按钮只切显示。数据量 56×64，
  源稿那条是为 Excel 写单元格省的，这里成本不存在，用户可见行为完全一致。

### 5.3 2026-10-20 版式重设计（已实施）

> ⚠ 本节里「数值明细 = 右侧 `el-drawer`」「切页关闭抽屉」「操作条含数值明细按钮」三条已被
> §5.4（2026-10-22）取代，其余（卡头承载测试项名、画廊列宽、精度口径）仍是现行口径。

用户批复「连版式一起重排」，并追加「小数点位数限制到 5 位」；评审板见
`docs/plans/weight-redesign-preview.html`（gitignore，本机原型）与 `tasks/weight-redesign-shots/`。
现行结构：

| 区块 | 内容与几何 |
|---|---|
| 工作区卡 | 文件身份（图标 + 文件名 +「已载入」+ 项/系列/Code 规模 + 隐私提示）与操作（重新选择 / 显示均值 switch / 数值明细 + 行数 / 导出 Excel）同一张卡；下方是「测试项」chip 云 + 全选/清空 + 线型说明 |
| 图表画廊 | `repeat(auto-fill, minmax(460px, 1fr))`；1280 画布下每卡 609×336（图表区 300）；卡头承载测试项名、系列数、Code 数，ECharts 内标题 `show:false` |
| 图表口径 | 4 条原始线 + 均值细虚线不变；图例只显示组内 `1 / 2 / 3 / 4 / 均值`（组名已在卡头，长名不再分页）；画布内不画轴名（609px 卡宽下会被卡头/右缘裁切）；grid 右留 34 给最右点标签 |
| 数值明细 | 右侧 `el-drawer` 780px、全高；原序号/系列名前两列 `fixed="left"`；组底色交替只染系列名单格（与 xlsx 同口径）；均值行加粗、品牌色左标线 +「均值」徽标；表格始终显示全部测试项，组开关不影响行 |
| 空态 | 独立卡片：真实格式样例 + 主按钮 + 规模限制；未载入文件时不渲染工作区卡/画廊 |
| 交互 | 均值是 `role="switch"`、文案固定「显示均值」；解析失败仍保留现图并显示顶部错误条；切页（keep-alive）时关闭抽屉 |

**页面显示精度**：新增 `PAGE_MAX_DECIMALS = 5`。图上均值标签与明细表最多 5 位小数
（图上标签去尾零，表格按源小数位与 5 取小，并把 `-0.00000` 归一为 `0.00000`）。
**§7.4 的 xlsx 导出也同步为 5 位均值小数**（`parser.MEAN_DECIMALS = 5`，用户 2026-10-20 追加要求）；
原始值仍按各自原文小数位写 number_format。

实测（原型 1280 画布，真实夹具 14 组 / 56 系列 / Code 0–63）：工作区卡短名 173.5px、长名压力 239.5px；
图表卡 609×336；明细 70 行、抽屉 780px。真实应用 1440 视口的内容区更窄，卡片按
`minmax(460px, 1fr)` 自动收缩；双主题与长名压力截图在 `tasks/weight-redesign-shots/`。
T2 计 25 例（`weightChartOption.spec.ts`，含 5 位精度与短图例）；T3 用例同步覆盖抽屉打开/关闭、
均值 switch、全选/清空，并保留「隐藏组不删表行」的对照。

### 5.4 2026-10-22 图例总开关 + 数值明细改页签（已实施）

用户两条点定：① 图例要一个**页面级总开关**，一键把 14 张图底部那行 `1 / 2 / 3 / 4 / 均值` 整行关掉；
② 数值明细**不要抽屉**，改成第二个页签。澄清后的口径：总开关关的是**图例本身**（曲线照画），
不是「按图例项全局关系列」；工作区卡（文件身份 + 测试项 chip + 开关 + 导出）**常驻在页签之上**，
只有下方视图区分「图表 / 数值明细」两页。

| 项 | 现行口径 |
|---|---|
| 图例开关 | `stores/weight.ts` 的 `showLegend`，默认 `true`，换文件与 `reset()` 复位，仍不落 localStorage（§11 不变）；卡片上是第二个 `role="switch"`「显示图例」，与「显示均值」共用 `.ws-switch` 样式 |
| 语义边界 | 只翻 `legend.show`，**series 一条不少**（T2 钉：关图例后仍是 4 成员 + 1 均值）；`grid.bottom` 随图例 `40 ↔ 16`，隐藏时把那 24px 还给绘图区 —— 不省高就等于白关 |
| 关掉后失去什么 | 点图例单独藏某条线的能力、组内线型的静态对照。后者由「组内曲线」那排的线型说明承载（`WeightFilterChips.vue`，原名 `WeightGroupChips.vue`，见 §5.5），完整系列名仍在 tooltip 与明细表 |
| 导出 | **不受影响**：xlsx 的 Excel 图例照旧在右侧。导出请求契约仍是 `visible_group_indexes` / `show_mean` / `palette` / `mean_color`，本轮没扩字段 |
| 页签 | `el-tabs` 只做导航（两个空 `el-tab-pane`），内容由页面按 `view` 自己渲染 —— 沿用 `BinSiteCrossTable.vue` 的既有写法。画廊 `v-show`（14 个 ECharts 实例不销毁，切回只 resize）、明细 `v-if`（进入才构建 70 行 × 66 列） |
| 明细视图 | `WeightSeriesDrawer.vue` → `WeightTableView.vue`：`el-drawer` / teleport / 关闭按钮与页面的 `onDeactivated` 一并删除；表格高度不再依赖抽屉，改 `el-table :max-height="560"`（仓内表格一律 max-height，不靠父级给高） |
| 契约变化 | 行数徽标从「数值明细」按钮搬到页签标签（`数值明细 70`）；`weight-open-table` / `weight-drawer` / `weight-close-table` 退役，新增 `weight-legend-switch`、`weight-table-view` 与图表卡上的 `data-legend="on\|off"` |

实测（一次性版式探针 + 截图，`tasks/weight-tab-shots/`，夹具 14 组 / 56 系列 / Code 0–63）：
1280 视口下工作区卡 992×204、页签条 39px、图表卡 489×336、明细表 992×562（表体 533）；
1440 下卡 1152×172（chip 收成单行）、明细表 1152×562。操作条（重新选择 + 两个 switch + 导出）
1280 下 389×32 **仍是单行**，两档文档横向溢出均为 0。明细表宽度从抽屉的 780px 变成整幅 992/1152px。
T2 增至 27 例（图例两分支 + `grid.bottom` 与缺省值）；T3 改为点页签进出明细，并断 14 张图的
`data-legend` 一起翻（只翻一张说明 prop 没发到面板）。

### 5.5 2026-10-22 组内曲线逐槽开关（已实施）

§5.4 的总开关只管「图例那行画不画」；本轮补另一半 —— **每个图例项各一个开关**。用户点定两条：
开关粒度 = **按图例项 1/2/3/4**（不是每张子图各一个图例开关）；**导出不跟**（xlsx 仍画全部曲线）。

控件放在筛选区第二行「组内曲线」，chip 上直接画本槽用的线型（实线 / 虚线 / 点线 / 点划线），
不再只写数字。chip 个数 = `slotCount(doc)` = 各组成员数的最大值（解析器不封顶，同名出现 6 次就有第 6 槽），
所以不是写死的四颗。`均值` 不在这排里 —— 它已有「显示均值」，一个状态两个控件迟早漂。

三条语义裁定（各有 T2 断言，都是会写错的地方）：

1. **线型按原槽位固定**：隐藏槽 0 后 `_2/_3/_4` 仍是虚线/点线/点划，不顶位换成实线。
   实现上先带原始 `within` 下标再过滤；T2 那条断言就是挡「改用过滤后的下标」。
2. **x 轴上界按全组算**：`groupCodeMax` 不看槽位可见性 ⇒ 隐藏最长那条时轴不收缩，
   14 张图在勾选过程中保持可横向对齐。
3. **明细表与 xlsx 都不跟**：与既有「勾选只影响画廊」同口径。⇒ 导出与页面**有意分歧**，
   必须可见提示：chip 行尾常驻「这里只关图表，明细表与导出的 xlsx 仍含全部曲线」，
   用户指南 §3 那句「导出的是当前所见」也改成明确区分「测试项跟、组内曲线不跟」。

边界口径一并定死：`visibleSlots` **缺省 = 全显**（旧调用方零改动），传 `[]` = 全关（只剩轴，不报错、不设保护）；
两种写法在 T2 各钉一条，防实现里 `slots?.includes(i)` 与 `!slots || includes(i)` 混用。

契约变化：`WeightGroupChips.vue` → `WeightFilterChips.vue`（现在渲染两行筛选）；chip 类名分
`.weight-chip--group` / `.weight-chip--slot`（裸 `.weight-chip` 会同时命中两排，T3 的计数断言必须带修饰类）；
图表卡新增 **`data-series="画出/总数"`**（如 `3/4`），卡头系列数同口径。
store 加 `visibleSlots`（`setDoc` 按 `slotCount` 全开、`reset` 归零，仍不落 localStorage）。

## 6. 配色（本稿唯一一处与源稿的实质冲突，附实测依据）

源稿 §5.3 要「14 个基色 + 组内 4 个明暗/色相变体」。仓里有既有的**已实测结论**：
[frontend/src/utils/echarts-theme.ts:124-136](../../../frontend/src/utils/echarts-theme.ts) 注明现行 8 色板
「CVD 复验未通过，按指南 §6.2 维持现状」，被点名的失败样本正是同色系明暗变体
（night 浅蓝/粉红 deutan ΔE=13.6）。复验工具在 `tasks/cvd_verify.mjs`，其判据是
**protan 与 deutan 两种模拟下，相邻色（含首尾成环）ΔE ≥ 15**，rgba 先按 night 底 `#1a1a2e` 预合成。

定的方案：

1. **色板真源保持在前端** `echarts-theme.ts` 的 `seriesColors`（已按主题分两份、已 CVD 定性）。
   后端**不存色板**：组色 = `seriesColors[组序 % 8]`，导出时前端把页面实际用到的那 8 个 hex 随请求带上。
   理由：色板若在 Python 再存一份就是两处真源，必然漂移。
2. **组内 4 条改用线型区分**（实线 / 虚线 / 点线 / 点划线），同组同基色。这是对源稿「同名不同颜色」的
   **有意收窄**，按 lessons「语义放宽要有可见提示」的口径：页面上「组内以线型区分」要写成可见说明，
   `docs/user-guide` 同步加一条，且文案指的路必须真实存在。
3. **均值线**：深灰 **1.5pt 细虚线、无圆点**。源稿要「深灰粗虚线」；早期本稿改粗实线是因为组内
   四条用掉虚线类线型，但 2026-10-20 用户实测粗实线会把贴得很近的原始线整条盖住 ⇒ 改为细虚线，
   靠颜色/宽度与彩色原始线区分（图例里也能看出来）。
4. 若将来仍要 14 个独立基色：先往 `tasks/cvd_verify.mjs` 加一组 14 色候选跑一次，
   两种模拟的成环相邻 ΔE 全部 ≥ 15 才允许用；验不过就停在上面第 1、2 条，不许「注明口径」了事。

双主题：本功能所有 DOM 颜色只取 CSS token，ECharts 侧颜色取 JS 语义色（lessons R7①②）。

## 7. Excel 导出

### 7.1 工作表与文件名

- `总览`：序号 / 测试项（蓝色内部超链接）/ 系列数 / 数据点数 / 最长 Code / 最小权重 / 最大权重；
  只列可见测试项；
- 每个可见测试项一张 sheet：sheet 名 = 测试项名（非法字符 `[]:*?/\'` → `_`、31 字符上限、
  大小写不敏感重名加 `_2`；`总览` 与 Excel 保留名 `History` 不分配给测试项）；
- 每次导出都是新文件，同名工作表问题不存在；
- 下载文件名走单一来源 [apps/common/export_naming.py:89](../../../apps/common/export_naming.py)
  的 `render_export_filename(user, export_type, extension, context)`，`export_type='weight_plot'`；
- 字体沿用 [apps/export/fonts.py:10](../../../apps/export/fonts.py) 的 `EXCEL_FONT_FAMILY`。

### 7.2 几何（2026-10-20 终版）

| 区域 | 内容 |
|---|---|
| 总览 | 第 1 行表头（深蓝底白字），第 2 行起每个可见项一行；测试项列超链接到分项 sheet |
| 分项 sheet | 图锚 `A1`，16 × 11cm；`A23`「← 返回总览」；表头第 24 行（A=原序号、B=系列名、C..=code 0..本组最长）；数据第 25 行起 |
| 单图 | 标题=测试项名；图例在底部；x 只到本组最长 - 1，y auto |
| 着色 | 系列名颜色 = 组色；奇数组极浅底；均值行灰色加粗 |

### 7.3 图

- `ScatterChart(scatterStyle='lineMarker')`；4 条原始线：细线 1.25pt + 圆点（size 4），
  线型按组内序（实/虚/点/点划）、组基色；
- 均值线（`show_mean`）：深灰 1.5pt 细虚线、**无圆点** + **每点数值标签**（5 位小数、顶部）；
- 图内只含本组系列；x 轴 `0..本组最长系列长度-1`（组内独立缩放），y 轴 auto；
- **X 轴在底部、Y 轴在左侧、刻度标签可见**：openpyxl 默认把两条 `valAx` 都写成 `axPos="l"`，
  两轴叠在左侧会把刻度/标题挤没；这里显式 `X=bottom / Y=left`、`crosses=min`（X 轴落在 y 最小值处，
  不穿过 y=0 的数据中间）、`tickLblPos=nextTo`、`delete=False`；
- 每条系列的 y 取该行同长度区域，**短数组只取自身长度，不用空单元格补齐**（继承源稿 §5.1）；
- 图例在底部，只列本组 4/5 条；跨组颜色对照由总览/分项表的系列名着色承载（§7.2）。

### 7.4 数值精度

- 原始值：按该声明原文里的最大小数位 `d` 写 number_format（`d=0` → `0`，否则 `0.` + `0`×`d`），
  落实源稿「数值保留原始精度」且不假造位数；
- 均值：固定 5 位小数（2026-10-20 用户点定，页面与导出一致）。**这是本稿自定的显示口径**，不援引
  `apps/export/formatting.py` 的 `format_percent_value`（那是百分比→字符串，语义不同；它的
  `PERCENT_DECIMALS = 6` 只是数值上曾与均值同位，现已不一致）。
  显示口径不影响数值：单元格里存的仍是全精度 float，不做四舍五入截断。

## 8. 安全与夹具（公开仓库的硬约束）

样例 CSV 含内部测试项名（形如 `<工位前缀>_OCP_130A_Trim_TrimWeight` 的产品/工位代号；**本稿故意不抄原串**，
因为 `docs/superpowers/` 是入库跟踪的，抄进来就是把刚虚拟化掉的东西再发布一遍），而本仓库**是公开的**。
`docs/reference/testing-gates.md` §6 记着 2026-10-16 的真实事故：真实 gage CSV 进历史后被一条无关 push
带上公开仓库，前向修复挡不住按 SHA 取 blob。

因此：

- **禁止**把那份私有样例 CSV 原样放进仓库、`Data/`、`test/fixtures/` 或任何 e2e 目录；
- 新建派生夹具 `test/fixtures/weight/trim_weight_ci.csv`：测试项名**按位次**换 `WT0001..WT0014`，
  **原样保留**全部数值、行数、数组长度分布、TAB 分隔、空行位置。
  2026-10-19 对真实样例的实测形状（写进夹具断言，别再猜）：56 条声明、14 个名称、每个名称恰好出现 4 次、
  数组长度集合 = {4,8,16,32,64}、CRLF 112 行、TAB 56 个、**声明长度与实际个数不符的情形 = 0 条**、
  **全部数值都是 5 位小数（小数位分布只有 [5]）**。
  后两条直接决定测试怎么写：长度不符与非法数值这类错误只能用**合成文本**测（夹具里根本没有这种素材）；
  「按原始小数位写 number_format」用夹具断**不承重**（实现写死 5 位也照样绿），必须用混合精度的合成 doc。
- 派生脚本 `scripts/make_weight_ci_fixture.py` 里**禁止出现真实标识符字面量**（源稿同族事故：把「禁止残留串」
  和真实→假名映射写进入库文件，等于把刚虚拟化掉的东西再发布一遍）；映射只按需导出到不入库的目录；
- 夹具必须进 `.gitattributes`：`test/fixtures/weight/*.csv -text`（TAB 是承重项；本机 `core.autocrlf=true`）。
  验收判据用 `git status --porcelain --untracked-files=all` 的条数恰好等于放开的文件数。
- 肉眼验证用本机那份私有样例，产物不落仓库（路径不进任何入库文件）。

## 9. 测试分层与门禁

按 [docs/reference/testing-gates.md](../../../docs/reference/testing-gates.md) §2 选层：

- **T1 后端** `test/backend/test_weight_parser.py`：真实样例规模（56 条 / 14 组 / 最大 64）、组序=首次出现、
  `_1.._N`、单次出现不加序号、逐点均值、长度不齐只对有值者平均、四类报错各带行号、杂行忽略、TAB 与 CRLF 路径。
  全组合进这里，3.6 例/秒。
- **T1 后端** `test/backend/test_weight_api.py`：parse 响应字段与计数；export 用 `openpyxl.load_workbook`
  读回，断 `总览` + 每个可见测试项一张 sheet、总览超链接、分项数据与图、均值线按 `show_mean` 出现、
  number_format、sheet 名清洗/去重；三个入站边界各拒一种。
- **T2 前端** `frontend/test/unit/weightChartOption.spec.ts`：`buildOption(group, …)` 纯函数
  （`environment: node`、零 DOM）—— 只含传入组的系列、X 轴 `0..本组最长-1`、圆点标记、
  均值线带数值标签、图例打开、组色与线型分配。
- **T3 浏览器** `frontend/e2e/weight/weight-plot.spec.ts` **只一条接线证明**：注入夹具 → 渲染出 14 张图 →
  关一组图少一张且表行不变 → 均值默认打开（70 行）→ 隐藏/显示均值 → 导出触发下载且文件名可读回。
  不在浏览器里逐组合点按钮。
  用例必须打优先级标签（`test.describe('…', { tag: ['@p1'] }, …)`，写法见 `global.spec.ts:16`）；
  定向单跑该文件时**必须带 `--project=P1`**：项目是按标签收例的（`frontend/playwright.config.ts:124,129-146`
  里 Edge 用 `grepInvert: /@p[012]/`、P0/P1/P2 各用 `grep: /@pN/`），不带项目就会落进 Edge 的
  `grepInvert` 被静默跳过 —— 那正是仓里「SFTP 用例不带 `--project=P1` 出假绿」的同一条机制，与新目录无关，
  `testDir: './e2e'` 会自动收到 `e2e/weight/`，不需要改任何 glob。
- 冒烟：`frontend/e2e/fixtures/test-data.ts:112-118` 的 `ROUTES` 加一项（`menu: '权重画图'`），
  `e2e/global/global.spec.ts` 的菜单顺序断言只检前 4 项（14-31 行），新项追加在 SFTP 之后不会破它，
  但**必须**同时有侧栏项，否则 `pages.spec.ts` 的 sidebarLink 断言会红。
- 双主题：`frontend/e2e/theme/night-visibility.spec.ts` 增补该页可见性一条。

**门禁成本（记账，不可省）**：本功能必改 `frontend/src/router/`、`config/`、新增 `apps/weight/`，
三者都落在 testing-gates §3 的全局清单/未知路径上 ⇒ 每批快门禁直接升级成全量池（实测 6–8min），
收口还要 `node scripts/e2e_pool.mjs --slots=4` + 后端全套。

## 10. 涉及文件

### 新增（后端）

- `apps/weight/__init__.py`、`apps/weight/apps.py`（AppConfig，无 models、无 migrations）
- `apps/weight/parser.py`（§3 全部规则，纯函数、零 Django 依赖）
- `apps/weight/views.py`、`apps/weight/urls.py`（两个端点，`IsAuthenticated`）
- `apps/weight/xlsx.py`（§7，openpyxl Workbook）
- `test/backend/test_weight_parser.py`、`test/backend/test_weight_api.py`
- `test/fixtures/weight/trim_weight_ci.csv`、`scripts/make_weight_ci_fixture.py`

### 新增（前端）

- `frontend/src/pages/weight/WeightPlotPage.vue`
- `frontend/src/pages/weight/components/WeightChartPanel.vue`、`WeightFilterChips.vue`（原名 `WeightGroupChips.vue`，§5.5）、`WeightSeriesTable.vue`
- `frontend/src/pages/weight/components/WeightWorkspaceCard.vue`、`WeightTableView.vue`（原 `WeightSeriesDrawer.vue`，§5.4）、`WeightEmptyState.vue`、`WeightActionButton.vue`（2026-10-20 版式重设计）
- `frontend/src/pages/weight/weightChartOption.ts`（纯模块，T2 目标）
- `frontend/src/pages/weight/composables/useWeightPlot.ts`
- `frontend/src/api/weight.ts`
- `frontend/src/stores/weight.ts`（Pinia，会话驻留）
- `frontend/e2e/weight/weight-plot.spec.ts`

### 修改

- `frontend/src/router/index.ts`、`frontend/src/components/layout/Sidebar.vue`
- `config/settings/base.py`（INSTALLED_APPS，56-66 行那一组之后）、`config/urls.py`（`api/v1/` 挂载）
- `requirements` 无新增（openpyxl 已在）
- `frontend/e2e/fixtures/test-data.ts`、`frontend/e2e/theme/night-visibility.spec.ts`
- `.gitattributes`（`test/fixtures/weight/*.csv -text`）
- `apps/common/export_naming.py`：`EXPORT_TEMPLATE_DEFAULTS`（19-29 行）与 `EXPORT_TEMPLATE_VARIABLES`
  （32-42 行）各加 `weight_plot` 一条。该文件 97 行是 `EXPORT_TEMPLATE_DEFAULTS.get(export_type, 'export')`
  ⇒ **不加就静默退化成 `export.xlsx`**，测试要钉住这一点。
- `frontend/src/constants/export-templates.ts`：该文件 docstring 明写与后端两张表「一一对应，
  修改任何一侧必须同步另一侧」，加 `EXPORT_TEMPLATE_META.weight_plot`；
  同时扩 `frontend/src/types` 里的 `ExportTypeKey` 联合类型 —— `EXPORT_TEMPLATE_META` 的类型是
  `Record<ExportTypeKey, ExportTemplateMeta>`，只改后端不改联合类型 ⇒ `npm run build` 直接红。
- `frontend/src/utils/error.ts` 的 `ERROR_CODE_MAP`（15 行起）：§3.3 四个新码的中文文案。
  漏了不会报错，只会把裸机器码显示给用户（`error.ts:63` 的 `?? d.code` 回落）。
- **`lq_dataprase.spec`**：该文件的 `hiddenimports` 是把每个 app **逐模块**列出来的
  （[lq_dataprase.spec:74-92](../../../lq_dataprase.spec)，注释写明「resolved at runtime via INSTALLED_APPS strings, not imports」），
  `apps.weight` 的 `__init__`/`apps`/`urls`/`views`/`parser`/`xlsx` 必须补进去，**否则打包版起来就 500**。
  这条是收口必测项：打完包跑一次 `dist` 版把两个端点各点一遍。
- `docs/user-guide`（本机 gitignore）加一页：含 §6 第 2 条「组内以线型区分」的可见说明

## 11. 状态与生命周期

- 解析结果只存 Pinia（`stores/weight.ts`），**不写 localStorage**：刷新即丢，符合「次抛」；
  切页回来还在（与「SFTP 搜索」结果跨页驻留同族，但那页用了持久层，这里刻意不跟）；
- 换文件 = 全量复位（组全开、**均值默认打开**、**图例默认打开**、图重建），对应源稿 §4.1「重新画图后状态复位」；
- 「图表 / 数值明细」当前页签是**页面局部状态**（`WeightPlotPage.vue` 的 `view`），不进 store：
  keep-alive 内切页回来仍是上次那页，但它不是数据状态，没必要进 store 增加契约面；
- 不落库 ⇒ **没有导出历史**，也不进「导出中心」那套待拍板议题；
- 解析失败：保留当前已画的图与表，只在顶部条显示错误 —— 对应源稿 §3.2「解析失败不创建/不修改任何产物」。

## 12. 权限

所有已登录用户可见：路由不加 `requiresAdmin`，端点 `IsAuthenticated`，**不**新增
`apps/accounts/permissions.py` 的 `FEATURE_PERMISSIONS` key。

## 13. 非目标

源稿 §9 全部继承：多文件叠加、单条曲线级开关、对数轴/双 Y、平滑插值、编辑数据、导出独立图片文件、
把样例内嵌进产品、与「处理并标记」/Exp 分布表联动。桌面版新增两条：

- 不与 SFTP 下载、数据管理已上传文件打通（§2 第 1 条的直接推论）；
- 不做「在 Excel 里整组开关」的宏/Form Control（openpyxl 与 excelize 都写不了，能力上限而非取舍）。

## 14. 风险与待实测（实现期第一批要清的账）

1. **openpyxl 原生图在本仓零先例**：`grep openpyxl.chart|ScatterChart|LineChart` 全仓无命中。
   具体要验三处写法 —— 关掉 marker（`marker.symbol='none'`）、数值 X 轴（不是 category 轴）、
   虚线/点划线的 `dashStyle` 取值集合。用临时簿建 → `load_workbook` 读回断言 → 再肉眼开一次 Excel。
2. **14 组循环 8 色**在全开时的组间区分度不足：靠 chip 文本 + 整组开关收敛。若肉眼判定不够，
   只走 §6 第 4 条的验算路径，不许现场拍脑袋加色。
3. **首绘与重建耗时**要量一次真实数（56 系列 / 3584 点）。源稿风险 1 在浏览器里不成立，
   但仍要有实测值，别把「我觉得快」写进结论。
4. **布局像素实测**：1280 / 1440 两档量图区可用高宽与 chip 组是否折行，量完再锁几何
   （本仓有「先量差值再拍」的前例，未量不许改布局参数）。
5. **打包形态**：`lq_dataprase.spec` 的 hiddenimports 漏项只有打包版才暴露（§10 修改项最后一条）。

## 15. 验收判据

全绿才算完成，逐条可执行：

- `python manage.py test test.backend.test_weight_parser test.backend.test_weight_api` 通过，
  且报错类用例各自断到行号；
- `cd frontend && npx vitest run` 通过，`weightChartOption.spec.ts` 断的是每组图的系列集合、
  独立 x 上限、圆点与均值标签、5 位小数与短图例、图例总开关的两分支（`legend.show` 与
  `grid.bottom` 40/16）、逐槽开关的三条裁定（线型不顶位 / x 上界不收缩 / 缺省全显与 `[]` 全关分开钉），
  而非「渲染没报错」（§5.4、§5.5）；
- `npm run build`（含 `vue-tsc -b`）+ `npm run lint:e2e` 通过；
- `frontend/e2e/weight/weight-plot.spec.ts`（@p1）通过：14 张图、整组开关不删表行、
  均值 switch 70↔56、图例总开关 14 张齐翻、逐槽开关 14 张卡 `data-series` 齐翻且明细仍 70 行、
  明细页签进出、全选/清空、导出下载、坏文件保留现图；字体与夜间主题回归同批绿；
- `node scripts/e2e_pool.mjs --slots=4` 全量池绿，且跑完端口释放、无孤儿 `runserver`；
- `node tasks/cvd_verify.mjs` 对最终选定的组间基色方案跑过（或明确停在 §6 第 1、2 条不引入新色板）；
- `git log --diff-filter=A --name-only origin/master..HEAD | grep -E '^Data/|Trim_Weight'` **为空**；
- 打包版起一次，两个端点各调一次，导出文件能在真实 Excel 打开：总览表有 14 个测试项超链接，
  每个分项 sheet 的图含本组 4 条原始线 + 均值标签，数据表逐点对得上。
