# 实施计划：圈选子图四点跟进改动（2026-11-12）

Spec: `docs/superpowers/specs/2026-11-11-chart-region-subset-design.md`。
本计划经用户批准（2026-11-12「开工把，子代理驱动」），**反转原 spec 的四处决策**
（切参数清空面板 / 建面板后选区保留 / serial 圈选建子集面板 / 子图无缩放），
spec 修订文本由 Task 6 写回。原 spec 的 D1/D2/D4/D5/D6 决策不变。

用户原始需求（四点）：
1. 子图面板跟着测试项切换持续存在；值域选区只展示一次（子图出来即消失）；关闭子图清除选区。
2. 圈选后图表最下方中间偶现输入光标（bug，修掉）。
3. serial 分布圈选不再建子图，改为按 serial 高亮芯片；切测试项仍能看到这些芯片的位置。
4. 直方子图要有和其它图表一样的拖拽/缩放。

关键设计决策（已与用户对齐）：
- 值域选区跨参数跟随走**后端固化 serial**：histogram 端点在 value_range 选区生效时
  回传 `selection_serials` + `selection_serial_col`；前端首次加载成功后把选区固化成
  serials，此后切参数用 serials 重查。无序列列的文件两字段缺席 → 面板冻结在原参数（优雅降级）。
- serial 高亮是会话级单例 store，切参数不清、切文件/换账号清；右键菜单只留「清除高亮」。
- 高亮用**叠加系列**（选中点原坐标重画 + 底层系列降透明度），兼容 large 模式（≥5000 点
  逐点 itemStyle 被忽略）与按 Site 拆分多 lane。

## Global Constraints

以下约束绑定每个任务（审查时逐字对照）：

1. 测试分层以 `docs/reference/testing-gates.md` 为唯一事实来源：T1 后端契约全组合
   （`test/backend/`，SimpleTestCase）；T2 vitest 纯函数（`frontend/test/unit/`，node 环境）；
   T3 Playwright 只留接线证明（`frontend/e2e/`）。T1/T3 判据冲突 → T1 全组合、T3 一条接线。
2. 每批 commit 前跑 `cd frontend && npm run test:e2e:affected`；commit 前还要
   `npx vitest run` + `npm run lint:e2e` + `npm run build`（都在 frontend/ 下）。
   收口（Task 6）：仓库根 `node scripts/e2e_pool.mjs --slots=4` + 后端全套
   `python manage.py test test.backend apps.<枚举 apps/ 下每个目录>`（**绝不写 `apps.*`**）。
3. 判绿/红取日志末尾 `RESULT:` 行（后端取 `OK`/`FAILED` 行），不取 `$?`；
   `NO AFFECTED TESTS` 不等于绿灯。
4. 600 行限制：被跟踪 .py/.ts/.vue 整文件 ≤600 行（SFC 整体计）。
   `SingleParamTab.vue` 现 584 行，本计划只允许它净减或持平，不许增长。
5. 双主题：一切前端视觉改动 light/night 都必须可读；颜色走 CSS 变量/主题 token
   （如 `var(--brand)`），night 下不得纯黑文字。
6. R5 上下文切换复位：切文件/换账号必须清面板与高亮；**切测试项（参数）是本计划
   的显式例外**——面板跟随重查、高亮保持。
7. R3/R4 守卫纪律：非法形态在解析层 400；数值入口 `pd.to_numeric(errors='coerce')`，
   NaN/inf 不参与计算。
8. D1/D2/D5/D6 不变：子集强制 DR 分箱、CPK 锚定原规格限、不做 IQR 再过滤；
   WYSIWYG 命中取绘制坐标；框选触达兜底柱 → 该侧无界（null）。
9. e2e 是 ESM：禁用 `__dirname`；上传型用例 afterAll 删夹具（`deleteFilesByNameQuiet`）；
   共享夹具的 describe 必须 serial 模式。
10. 提交纪律：逐文件 `git add`（禁 `git add -A`）；提交信息从 diff 现读；**不 push**；
    不跑 build.bat；禁裸 stash。工作目录 = 当前检出 master（台账有裁定）。
11. API 契约：`selection_serials` / `selection_serial_col` 只在 value_range 选区生效
    且解析出序列列时出现在 histogram 响应顶层；serials kind、无选区、无序列列 → 两字段缺席。
12. 前端直连 `api.post` 返回完整 AxiosResponse，须自取 `resp.data`（解包只在 useAsyncData）。

## Task 1: 后端 value_range 选区固化 serials（T1 契约）

**目标**：histogram 端点在 value_range 选区过滤成功后，把命中行的序列号随响应回传，
供前端把选区固化成 serials 跨参数重查。契约见 Global Constraints #11。

**文件**：
- `apps/analysis/services/data_services/subset_selection.py`（96 行，加纯函数）
- `apps/analysis/views/analysis_views.py`（histogram action，约 199–239 行）
- `test/backend/test_histogram_selection.py`（既有 T1 文件，追加用例）

**改动**：
1. `subset_selection.py` 新增纯函数 `resolve_selection_serials(df)`：
   - `serial_col = get_serial_column(df)`（已从 `apps.analysis.services.statistics` 导入）；
     为 None → 返回 None。
   - 取 `df[serial_col]` 的值列表：numpy 标量转 Python 原生（int/float），字符串保持 str；
     丢弃 NaN/None（`pd.isna`）；保持行序。
   - 列表为空 → 返回 None；否则返回 `(serials_list, serial_col)`。
2. `analysis_views.py` histogram action：在 `filter_df_by_selection` 成功之后
   （约 205–209 行块内），当 `selection['kind'] == 'value_range'` 时调
   `resolve_selection_serials(df)`（df 已是过滤后的子集）。响应 payload（约 233 行
   `clean_data({...})`）在解析成功时追加两个顶层字段：
   `selection_serials`（列表）与 `selection_serial_col`（列名字符串）。
   解析为 None 或 kind 非 value_range → 两字段都不出现（旧响应逐字不变）。
   注意 `clean_data` 会清洗 NaN，但列表里已在纯函数丢弃 NaN，不依赖它。

**测试（TDD，先 RED 后 GREEN）**：
- `test_histogram_selection.py` 追加：
  - 新类 `ResolveSelectionSerialsTests(SimpleTestCase)`（纯函数全组合）：
    数值序列列 → `(list, 'Serial_No')`；字符串序列列 → str 列表；
    无序列列（只有 P1 列的 df）→ None；含 NaN 序列行 → 丢弃；空 df → None。
  - `HistogramViewSelectionTests` 追加（`_frame()` 已含 `Serial_No=[1..6]`，直接用）：
    - value_range `{'lo': 9.0, 'hi': None}` → 200，`r.data['selection_serials'] == [4, 5, 6]`，
      `r.data['selection_serial_col'] == 'Serial_No'`。
    - serials kind（如 `{'kind':'serials','serials':[1,2]}`）→ 200，两字段 `not in r.data`。
    - 无选区 → 200，两字段缺席（旧口径）。
    - 无序列列的 df（`self._post(..., df=pd.DataFrame({'P1':[1.0,10.0]}))`，metadata 用 `_md()`）
      + value_range → 200，两字段缺席，results 正常。
- RED：实现前跑 `python manage.py test test.backend.test_histogram_selection`，
  新用例失败（ImportError/字段缺席）即为预期红。GREEN：实现后同命令全绿。

**门禁**：focused 后端测试全绿后，`cd frontend && npm run test:e2e:affected`
（后端改动由 affected 判档），再 `npx vitest run` + `npm run lint:e2e` + `npm run build`。
取 `RESULT:` 行判绿。逐文件 add，提交信息从 diff 现读。

## Task 2: 子集面板跟随测试项切换（前端生命周期）

**目标**：面板不再随切参数清空；首次加载成功后把 value_range 选区固化成 serials
（消费 Task 1 的响应字段），切参数时用 serials 对新参数重查。无 serials 的面板冻结。

**文件**：
- `frontend/src/pages/analysis/composables/selectionGeometry.ts`（加纯函数）
- `frontend/src/pages/analysis/composables/useSubsetPanels.ts`（94 行，生命周期改造）
- `frontend/test/unit/selectionGeometry.spec.ts`（追加 T2）
- `frontend/e2e/analysis/subset-drilldown.spec.ts`（反转切参数用例）

**改动**：
1. `selectionGeometry.ts` 新增纯函数
   `fixateSelection(sel: ChartSelection, respData: any): ChartSelection`：
   仅当 `sel.kind === 'value_range'` 且 `respData?.selection_serials` 是非空数组时返回
   `{ kind: 'serials', serials: respData.selection_serials, serial_col: respData.selection_serial_col }`；
   其余情况原样返回 sel。
2. `useSubsetPanels.ts`：
   - `SubsetPanel` 接口加内部字段 `epoch: number`（createPanel 初始 0）。
   - `load(panel)`：开头 `const myEpoch = ++panel.epoch`；await 之后应用结果前
     `if (panel.epoch !== myEpoch) return`（过期响应丢弃，loading 由更新的 load 接管，
     finally 里同样只在 epoch 匹配时置 loading=false）。
   - 成功拿到 result 后：`panel.selection = fixateSelection(panel.selection, resp.data)`。
   - watch 拆分（仍在既有 detached `effectScope(true)` 内）：
     - `watch(() => store.fileId, clearAll)`（切文件清空，R5 保留）；
     - `watch(() => store.selectedParam, (p) => { if (!p) return; for (const panel of panels.value) {
       if (panel.selection.kind !== 'serials') continue; panel.param = p; void load(panel) } })`。
     - value_range 面板（后端没回 serials）跳过 → 冻结在原参数原结果。
   - 更新文件头注释：切参数不再清空（本计划显式例外），固化与冻结语义写清。
   - 标题无需改：`subsetPanelTitle` 对 serials 选区已输出「N 颗序列」。
3. e2e 反转：把 `切参数 → 子集面板清空` 用例改为 `切参数 → 面板跟随（serials 固化）`：
   直方图右缘框选建面板（n=3）后，`selectParam(page, 'VCC')`，
   `waitForResponse` 钉住重查请求体含 `"kind":"serials"`、`"serials":[4,5,6]`、`"params":["VCC"]`；
   断言面板仍 1 个、`data-subset-n="3"`、标题含 `VCC 子集` 与 `3 颗序列`。
   （夹具 KELVIN_VIN [1,1.5,0.5,10,11,12] 右缘框选命中 serial {4,5,6}；VCC 同 3 颗 die。）

**测试（TDD）**：
- T2 `selectionGeometry.spec.ts` 追加 fixateSelection 全组合：
  value_range + 有 serials（含/不含 serial_col）→ serials 选区；
  value_range + 字段缺席/空数组 → 原样；serials kind → 原样。
  RED：函数不存在时跑 `npx vitest run test/unit/selectionGeometry.spec.ts` 失败；GREEN 后全绿。
- T3 即上面反转的 e2e 用例（接线证明）。

**门禁**：`cd frontend && npm run test:e2e:affected`（analysis 档）+
`npx vitest run` + `npm run lint:e2e` + `npm run build`。取 `RESULT:` 行。

## Task 3: 选区一次性消费 + 光标 bug 修复

**目标**：直方图「新建子集直方图」点下去后选区浮层立即消失（只展示一次）；
圈选拖拽不再触发浏览器原生文本选择/插入光标。

**文件**：
- `frontend/src/pages/analysis/composables/useChartBrushSelect.ts`（253 行）
- `frontend/src/pages/analysis/components/HistogramChart.vue`（scoped 样式）
- `frontend/src/pages/analysis/components/SerialChart.vue`（scoped 样式）
- `frontend/e2e/analysis/subset-drilldown.spec.ts`（追加断言）

**改动**：
1. **先复现**（TDD RED）：在 e2e 里对直方图拖拽后断言
   `await page.evaluate(() => window.getSelection()?.toString() ?? '') === ''`。
   默认渲染器若是 canvas 复现不出，用 SVG 渲染器复现（设置里可切换，或 addInitScript
   写渲染器设置键——先读 `frontend/src/utils/echarts-theme.ts` 的 getChartRenderer 确认键名）。
   报告里记录哪种渲染器复现、光标落在哪个 DOM 节点。
2. `useChartBrushSelect.ts` `onZrMouseDown`（110 行）：通过 button/enabled 守卫后
   加 `ev.preventDefault()`——阻断原生文本选择与插入光标；zrender 内部 handler 不受影响。
3. `useChartBrushSelect.ts` `createAndClose`（239 行）：emit onCreate 之后调
   `clearSelection()`（选区在创建时刻被消费；clearSelection 已含关菜单）。
   rect 模式本任务不动（Task 4 改）。
4. `HistogramChart.vue` `.chart-container` 与 `SerialChart.vue` `.serial-canvas`
   的 scoped 样式加 `user-select: none;`（双保险，覆盖拖拽越出画布选到周边文本）。
5. e2e 追加断言（GREEN 判据）：
   - 直方图拖拽后（右键前）`window.getSelection()?.toString()` 为空；
   - 点「新建子集直方图」后 `.chart-brush-overlay` 计数为 0。

**门禁**：`cd frontend && npm run test:e2e:affected` + `npx vitest run` +
`npm run lint:e2e` + `npm run build`。取 `RESULT:` 行。

## Task 4: serial 圈选改跨参数芯片高亮

**目标**：serial 分布框选不再建子集面板，改为立即高亮命中芯片（按 serial）；
切测试项高亮保持（在新参数的图上重画同一批芯片）；右键菜单只留「清除高亮」；
切文件/换账号清高亮。

**文件**：
- 新 `frontend/src/pages/analysis/composables/serialHighlight.ts`（纯匹配函数）
- 新 `frontend/src/pages/analysis/composables/useSerialHighlight.ts`（会话单例 store）
- 新 `frontend/test/unit/serialHighlight.spec.ts`（T2）
- `frontend/src/pages/analysis/composables/useChartBrushSelect.ts`（加 immediate/canMenu）
- `frontend/src/pages/analysis/components/SerialChart.vue`（高亮渲染 + 接线）
- `frontend/src/pages/analysis/components/ChartContextMenu.vue`（mode prop）
- `frontend/src/pages/analysis/components/SingleParamTab.vue`（584 行，只减不增）
- `frontend/src/stores/auth.ts`（复位接线，27 行旁）
- `frontend/e2e/analysis/subset-drilldown.spec.ts`（重写 serial 用例）

**改动**：
1. `serialHighlight.ts` 纯函数
   `pickHighlightPoints<T extends { realSerial: number | string }>(laneGroups: T[][], serials: (number | string)[]): T[][]`：
   Set 成员判定，**严格类型**（数值 4 不匹配字符串 '4'，与后端 isin 口径一致）；
   保持 lane 结构与点对象原样（tooltip 需要 value/realY/realSerial/isFail/anchor 全字段）。
2. `useSerialHighlight.ts`：模块单例（仿 useSubsetPanels 的 detached effectScope 模式）：
   `serials: ref<(number|string)[]>`、`serialCol: ref<string|undefined>`、
   `set(sel)`（只收 kind==='serials'）、`clear()`；
   `watch(() => store.fileId, clear)`（store = useSingleTabStore）；
   导出 `resetSerialHighlight()`。**切参数不清**。
3. `auth.ts`：在 `resetSubsetPanels()`（27 行）旁加 `resetSerialHighlight()`。
4. `useChartBrushSelect.ts` opts 加两个可选项：
   - `immediate?: boolean`：rect 模式 mouseup 算出 selection 后立即
     `opts.onCreate(selection.value)` 然后 `clearSelection()`（浮层只闪一次，高亮接管）；
     value-range 模式忽略此项。
   - `canMenu?: () => boolean`：`onContextMenu` 的开门条件改为
     `opts.enabled() && (selection.value || opts.canMenu?.())`（无选区但有高亮也能右键）。
5. `SerialChart.vue`：
   - 删掉 `defineEmits<{ 'create-subset': ... }>()`；brush `onCreate` 改为
     `(sel) => { if (sel.kind === 'serials') highlight.set(sel) }`；opts 加 `immediate: true`、
     `canMenu: () => highlight.serials.value.length > 0`。
   - buildOption：高亮激活（`props.enableSelection && highlight.serials.value.length > 0`）时：
     - 底层 site 系列 `itemStyle.opacity` 降为 `Math.min(props.opacity, 0.25)`；
     - 用 `pickHighlightPoints(laneGroups, highlight.serials.value)` 取各 lane 命中点
       （laneGroups 是 152 行的绘制点全字段数组，**不是** displayLanes），
       每 lane 追加叠加系列：`name: '高亮芯片'`、type scatter、
       `symbolSize: props.symbolSize + 2`、`itemStyle: { color: 品牌色, opacity: 1 }`、
       `z: markZ + 1`、split 时绑各自 xAxisIndex/yAxisIndex、isLarge 时 `large: true`。
       品牌色取 `getComputedStyle(document.documentElement).getPropertyValue('--brand').trim()`，
       读不到回退 `'#409eff'`（双主题自动跟随）。
     - 图例不含「高亮芯片」（legendData 在 push 叠加系列之前计算，或显式过滤）。
     - 叠加系列 tooltip 沿用现有 formatter（点对象带 realSerial/realY/isFail/anchor）。
   - useChart 的 deps 数组加 `() => highlight.serials.value`（set/clear 触发重渲染）。
   - **删除** 353–354 行 `watch(() => props.data?.param, () => brush.clearSelection())`：
     选区已在 mouseup 消费，高亮必须跨参数保持。
   - ChartContextMenu 传 `mode="highlight"`、`@clear="highlight.clear()"`。
   - 高亮渲染以 `props.enableSelection` 为闸：其它页面（多文件 tab 等）的 SerialChart
     不显示单参数 tab 的高亮（避免跨文件串扰）。
6. `ChartContextMenu.vue`：加 prop `mode?: 'subset' | 'highlight'`（默认 'subset'）。
   highlight 模式只渲染一个按钮 `data-menu-clear-highlight`「清除高亮」emit('clear')；
   subset 模式两个按钮逐字不变。样式沿用（已走主题 token）。
7. `SingleParamTab.vue` 113 行：`enable-selection @create-subset="subsetPanels.create"`
   → `enable-selection`（SerialChart 不再 emit；hist 的 89 行不动）。行数只减不增。
8. e2e 重写 `散点矩形框选 → 右键新建子集面板（serials，n=3）` 为
   `散点框选 → 芯片高亮（不建面板，跨参数保持）`：
   - 拖拽 serial 右上矩形（沿用现有分数坐标）→ mouseup 后**无** `[data-subset-panel]`、
     无 `.chart-brush-overlay`；
   - `__echartsInstance__.getOption().series` 里 `name==='高亮芯片'` 的系列 data.length===3，
     底层 site 系列 itemStyle.opacity ≤ 0.25；
   - `selectParam(page, 'VCC')` 后高亮系列仍 3 点（同一批 die）；
   - 右键 → 菜单可见、`[data-menu-create-subset]` 计数 0、`[data-menu-clear-highlight]` 可见；
     点击 → 高亮系列消失（或 data.length 0）、底层 opacity 恢复 > 0.25。
   - 夜间用例追加：night 下高亮菜单文字非纯黑（沿用现有 night 判据）。

**测试（TDD）**：
- T2 `serialHighlight.spec.ts`：逐 lane 精确匹配；数值/字符串严格不互配；
  空 serials → 各 lane 空；serials 重复 → 点只出现一次；未命中 serial → 空。
  RED：模块不存在时 vitest 失败；GREEN 全绿。
- T3 即上面重写的 e2e（接线证明）。

**门禁**：`cd frontend && npm run test:e2e:affected` + `npx vitest run` +
`npm run lint:e2e` + `npm run build`。取 `RESULT:` 行。

## Task 5: 直方子图滚轮缩放 + 拖拽平移

**目标**：子集面板里的直方图有和其它图表一致的 inside dataZoom（滚轮缩放、拖拽平移）；
主直方图保持无缩放（默认关）。

**文件**：
- `frontend/src/pages/analysis/components/HistogramChart.vue`（341 行，加 prop）
- `frontend/src/pages/analysis/components/SubsetPanelArea.vue`（138 行，传 prop）
- `frontend/e2e/analysis/subset-drilldown.spec.ts`（追加用例）

**改动**：
1. `HistogramChart.vue`：props 加 `enableDataZoom?: boolean`（默认 false）；
   buildOption 返回对象加 `...(props.enableDataZoom ? { dataZoom: [{ type: 'inside', xAxisIndex: 0 }] } : {})`。
   子图 enableSelection=false → brush 不绑 mousedown，与 inside dataZoom 的拖拽平移无冲突。
2. `SubsetPanelArea.vue` 的 HistogramChart（31–40 行）加 `enable-data-zoom`。
3. e2e 追加 `子集直方图滚轮缩放 + 拖拽平移`：
   建面板后对子图画布 `mouse.wheel(0, -240)` → `getOption().dataZoom[0].start > 0`；
   再拖拽平移 → start/end 继续变化；主直方图 `getOption().dataZoom` 缺席或空。
4. e2e 追加回归 `serial 图滚轮缩放不受框选 preventDefault 影响`（Task 3 改了 mousedown）：
   serial 图（框选开启态）滚轮 → 其 dataZoom[0].start 变化。

**门禁**：`cd frontend && npm run test:e2e:affected` + `npx vitest run` +
`npm run lint:e2e` + `npm run build`。取 `RESULT:` 行。

## Task 6: 收口——e2e 补强、spec 修订、全量门禁

**目标**：四点需求全部有承重判据；原 spec 写回修订；收口全量门禁绿。

**文件**：
- `frontend/e2e/analysis/subset-drilldown.spec.ts`（查漏补缺）
- `docs/superpowers/specs/2026-11-11-chart-region-subset-design.md`（追加修订节）
- `docs/tasks/todo.md`（本任务条目进度更新）

**改动**：
1. 对照四点需求盘点 e2e 覆盖，补缺口（至少确认：面板关闭按钮 × 点击后计数 0；
   已有用例的断言都承重——精确计数/集合相等，不用 >0 之类弱判据）。
2. spec 追加「修订（2026-11-12）」节：逐条记录四处反转（切参数清空 → 面板跟随 +
   serials 固化；选区保留 → 创建即消费；serial 建面板 → 跨参数高亮；子图无缩放 →
   inside dataZoom）与光标修复，注明 D1/D2/D4/D5/D6 不变、用户需求日期 2026-11-12。
3. `docs/tasks/todo.md` 本任务条目更新为完成 + 提交清单。
4. **收口门禁**（仓库根/frontend 按命令注明位置）：
   - `cd frontend && npx vitest run && npm run lint:e2e && npm run build`
   - 仓库根 `node scripts/e2e_pool.mjs --slots=4`（判据取末尾 RESULT/verdict 行）
   - 仓库根 `python manage.py test test.backend apps.accounts apps.analysis apps.batch_report
     apps.buyoff apps.common apps.dashboard apps.datafiles apps.export apps.gage apps.jobs
     apps.sftp apps.weight`（apps/ 目录枚举，与 scripts/e2e_nightly.mjs backendLabels() 同源；
     判据取 `Ran N … OK` 行）
   - 报告里记录三条门禁的结论行原文。任何红 → 修复后重跑对应档。

**门禁**：即上面收口三件套。逐文件 add（spec/todo/e2e），提交信息从 diff 现读。