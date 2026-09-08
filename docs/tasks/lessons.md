# Lessons Learned

> 维护约定：跨日期高频重复的教训已沉淀到文首「通用规则 R1–R8」，日期条目只保留独有内容；
> 新教训按「现象 → 根因 → 修复/规则」压到最短追加到对应日期段；能归入 R 系列的**不重复写**。
> （2026-08-30 合并 副本 tasks/lessons.md 全部历史并浓缩去重；原始文件见 lessons.bak-2026-08-30.md。）
> 2026-09-08 拆出：≤2026-07-02 的 21 段已**原样**归档至 `lessons-archive.md`（回查 grep 该文件）；此后日期条目超过约 1 个月且已被 R 系列吸收的，定期移入归档。

## 通用规则 R1–R8

- **R1 完成即提交，磁盘才是事实**：功能验证通过即 `git commit`（或 `git diff > tasks/xxx.patch` 留底）——曾发生改动未提交被 `git checkout .` 一次清空、整日重放。任何「声称完成」用 `git log`/`git diff` 验证磁盘状态，勿依赖会话记录；4+ 步重构结束前 `git status` + `git diff --stat` + 针对改动点跑回归。多代理/多会话并发写共享 docs（todo/lessons 已入 git 版本库）时，先读现状再改、保留他人条目、条目标题带「日期+主题」锚定便于找回；若不慎覆盖/清空，恢复路径：`git log -- docs/tasks/lessons.md` 找到覆盖前提交，用 `git checkout <commit> -- docs/tasks/lessons.md`（或 `git show <commit>:docs/tasks/lessons.md > lessons.md`）取回上一版本。
- **R2 e2e 断言规范**：① 断言端到端可观察状态（DOM/文本），勿在中间步骤拦截网络；`waitForResponse` 必须在触发请求**之前**用 `Promise.all([waitForResponse, action])` 注册。② 选择器先经 trace 确认真实存在的 class；`v-show`/多 tab 常驻 DOM → 必须加 `:visible` 或 `.first()` 限定；组件根定位 class 用 fallthrough 加在根元素。③ 全量失败先对 baseline 跑一遍定位「存量失败」，再单文件隔离复跑（含 retries）区分 flake 与回归；跨套件共享 DB 状态要自建/自清（`000_E2E_` 命名前缀 + finally 清理），防残留行污染 files[0]。④ **由页面加载自身**触发的请求（reload / 深链恢复自动选文件发请求）不能靠「goto 之后 waitForResponse」等稳定：goto 解析→注册之间有几百 ms 窗口，响应先到就永远等不到（实测注册 +541ms / 响应 +543ms，2ms 余量；后端加缓存/变快后从偶绿转必红）。改等 UI 状态（目标可见 + `.el-loading-mask` toHaveCount 0）；同理「不应发请求」的计数器 `page.on('request')` 必须装在 `goto` **之前**，并用 baseline 差值扣掉前置阶段已发出的请求，否则漏计造成假通过。⑤ `locator.boundingBox()` 对空 locator **不是**返回 null，而是等满 actionTimeout 后抛错——`?? fallback` 救不了，必须先 `.count()` 判存在（canvas 渲染器下无 `svg` 时典型）。
- **R3 前后端契约与守卫**：① 相似端点守卫必须对齐（如 histogram/qqplot/boxplot 的 `param not in df.columns`），grep 对比即可发现——一个 400 守卫、一个 500 就是状态码雪崩温床。② 「前端已过滤 → 后端不用管」是错误假设：任何接 Series/参数的业务函数都要容错（bool/str/object/category、空串、null），视图层过滤规则可能漂移、直连 API 可绕过。③ 哨兵/默认值判断先做真值守卫（`if v and v != '全部'`）；`request.data.get(k, default)` 的 default 只在键**缺失**时生效；GET 端点参数一律 `request.query_params`。④ 前端已有 API/类型但后端 404 → 先分清「缺端点」还是「缺功能」，按前端 interface 字段反推后端结构逐字段实现。⑤ 接口传完整语义（如 `role_map` dict），不能依赖隐式数组顺序。
- **R4 数值与序列化容错**：① pandas 数值入口统一 `pd.to_numeric(data, errors='coerce').astype(float)`——bool 必须显式 astype（to_numeric 不改 bool dtype），str 由 coerce 转 NaN；过滤用 `np.isfinite()` 向量化，不要 `apply(lambda x: abs(x) < inf)`（str 上崩、慢 10x）。改完以诊断脚本复跑归零（如 `bp_issues=0`）为硬标准，别只看"我写的小测试过了"。② 后端 NaN → JSON null：前端所有可能为 null 的数字渲染前 `Number.isFinite()` 护，TS interface 写 `number | null`。③ 写新 stats service 前先扫 `df.dtypes.value_counts()` 找 bool/object 漏网；回归测试必须覆盖「脆弱数据」路径（全同值列、NaN、离散列）。
- **R5 持久化状态与上下文切换**：持久化到 Pinia/localStorage 的「用户上次选择」（selectedParam/selectedFileId/tab），在文件/项目/数据上下文切换时必须在**父组件入口**显式重置（`state=''`/`store.x=''` 清空后再异步加载）——子组件只清本地值会被 v-model 双绑推回旧值。跨上下文状态泄漏要**双层防御**：前端清状态 + 后端 validation（光一层不够：多 tab/深链接/旧版缓存可绕过前端；只有后端则用户 400 时已困惑）。
- **R6 测试基础设施**：① DRF 视图测试必须 `force_authenticate(request, user=...)`（Permission 检查 `request._auth`，`request.user = SimpleNamespace` 无效），`is_authenticated=True` 必设。② mock ORM 对象给视图用时字段列全（id/filename/format_type 最低配），勿只放当前用例需要的。③ monkey-patch 必须 patch **实际消费模块**的绑定（`from .x import f` 创建独立绑定，patch 包名不生效）+ `addCleanup` 还原。④ 管理类 ViewSet 测试覆盖 4 形态：PUT 单字段 / PATCH 单字段 / PUT 全字段 / PUT 不存在 id。
- **R7 主题与图表**：① 任何前端改动维护 dark+light 双主题：组件只认 CSS token（scoped 内 `var(--xxx)`），禁止页面级全局 night 覆盖（曾 47 条非 scoped 覆盖是主题不一致根因）；选择器统一 `:root[data-theme="night"]`；element-plus 主题 css 的 night/light 块必须对称（否则 light 显示出厂 #409eff 而非品牌色）。② ECharts 不认 CSS 变量：setOption 颜色取 `useChartTheme()` 的 JS 语义色；DOM（模板 style/进度条）里才用 `var(--token)`。③ 新图表组件禁止裸调 `echarts.init`，必须走 `initEchartsWhenReady`（零尺寸保护，容器高度未定会报 "Can't get DOM width or height"+空白）；共享 chart composable 必须支持容器被 v-if 销毁后重建（复用前校验 `getDom() === 当前 ref && isConnected`，不符 dispose 重建）。
- **R8 构建验证与回归判定**：① 根目录 `npx vue-tsc --noEmit` 在 solution-style tsconfig 下是「空检查」（仅 references，直接退出不查文件）——门禁必须 `npm run build`（vue-tsc -b + vite build）；`] as any[]` 括号配对陷阱类型错误 vue-tsc -b 报 TS1005/TS1128，目录级 --noEmit 却静默放过。② 判断「是否我引入的回归」：grep 自己改的文件名，勿被既有 build 噪音误导，可疑时 `git stash` 对照。③ Windows 编辑文件偶发 `ReplaceFileW EIO(1175)`：等 2–8s 重试，勿原地反复重试、勿用 shell 重写中文文件（编码规则不变）。

## 2026-09-08 e2e 体系修复（21 确定性失败 + 提速基建）新增教训

- **`browser.newContext()` 会继承项目的 `use.storageState`**：afterAll 清理里裸
  `newContext()` 拿到的是**已登录** context（storageState 从 playwright projects 配置
  继承），并非干净上下文；旧 token 30 分钟有效期内清理链路「时好时坏」被误判为 flake。
  需要未登录态必须显式 `newContext({ storageState: { cookies: [], origins: [] } })`。
  另：`.main-layout` 是 App.vue 全路由根节点（登录页也有），`gotoApp('/login')` 恒
  「过」但语义错误，不能用它证明「当前在登录页」。
- **EP multiple el-select 的 popper 残留不是 flake 而是确定性坑**：Escape 依赖焦点
  仍在 select 上，焦点被抢后按键落空 → popper 残留，`dp-file-option__meta` 子树拦截
  后续对筛选区控件的点击（2026-09-07/08 两次被归「flake」的本体）。multiple 模式
  勾选后 popper 本就不自动关。修法见 helpers/params.ts `closeFilePopper`（Escape →
  仍未 hidden → 点 tab 标题 → toBeHidden 兜底断言），四个 tab 作用域共用。
- **ECharts 实例属性定位器必须匹配容器本体**：实例属性挂在 `echarts.init` 传入的
  容器元素**本体**上；ref 即容器的组件（如 `.scatter-chart-inner`）要写
  `.scatter-chart-inner[_echarts_instance_]`，后代形式 `div[...]` 恒为空 → 定位器
  永假红（legend-color 相关性散点用例跨天失败的本体）。
- **R2④ 再现两例（注册时机必须紧贴触发动作）**：① exports spec 的 histogram 响应
  注册写在文件选择 click 之后，响应先到则白等满 15s（有 .catch 兜底成纯浪费）；
  ② file-switch spec 的 boxplot 注册晚于选参、中间还垫了 500ms，响应先到等满 20s
  直接假红。规则不变：waitForResponse 与触发动作相邻且在前，中间不许再插任何 await。
- **vite preview 不继承 `server.proxy`**：webServer 换 `vite build + preview` 后
  /api 代理静默失效（页面能开、接口全 404），必须在 vite.config.ts 显式配
  `preview.proxy`（内容同 server.proxy）。改 webServer 形态时先想这条。
- **EP el-select 对已选中值再点一次不触发 change、不发请求**：条件等待
  （waitLoadingGone 等「自动选参链完成」）把时序钉死后，原本靠竞态通过（自动选参
  未完成 → 点击 = 真切换）的用例会**确定性**失败——实测 file-switch-param-reset：
  QQ/Box 开启时文件切换已自动为 params[0] 发过 qqplot/boxplot，再
  `selectParam(params[0])` 是同值点击，两个 20s waitForResponse 全超时（安静环境
  2/2 必挂）。规则：用例要「驱动切换」必须选**不同于当前选中**的值（params[1]）；
  写「选 X → 断言请求」前先想清楚 X 是否已被产品自动选过。
- **webServer 换 build+preview 后，e2e 跑的是生产 bundle——dev-only 机制探针必挂**
  （一换全暴露，3 例同根因）：① `__vueParentComponent` 是 Vue **仅 dev** 挂在 DOM
  上的属性，生产构建恒 undefined → view-data 经它读 grid api 的断言拿到 null；
  且产品无列菜单 UI（defaultColDef 未启用 filter → ag-grid 不渲染表头菜单按钮），
  重显路径改走「系统设置（权威事实源）更新 + 完整重导航」（view 页不把文件选择写
  进 URL，裸 reload 丢文件选择得空网格）。② CSS 压缩器（lightningcss）
  把源码 `'Segoe UI'` 规范化为 `"Segoe UI"` → fonts token 用例按原文比较 dev 绿 /
  preview 必挂，比较前两侧剥引号。③ 生产包导航快且密 → auth401 落地 /login 后
  其余在途 401 再触发 window.location 重定向，evaluate 撞上导航抛 context
  destroyed → try/catch + expect.poll 重试。规则：动 webServer 形态后，全量跑一遍
  找「依赖 dev 行为（未压缩 CSS / dev 时序 / dev 全局变量）」的用例。

## 2026-09-07 图表记忆「刷新即默认」三根因修复新增教训

- **Vue 子组件 prop 更新滞后于 promise 微任务回调**：父组件 setup 里 `promise.then` 先改
  ref（勾选恢复），子组件（v-if 后挂载）同 promise 的回调后执行——但子组件读到的
  `props.activeKeys` 仍是旧值：prop 要等父组件重渲染才流入，微任务跑在渲染刷新之前。
  微任务回调里对「依赖 prop 的派生数据」做结构性操作（reconcile/裁剪）前必须
  `nextTick`，否则按旧 active 集合操作（实测：apply 裁掉 serial 行、占比被
  normalizeSizes 重置回默认 58/42，覆盖服务端 32/68）。e2e 用 `page.route` 给
  settings GET 延迟 1.5s 把「dock 先挂载、记忆后到」钉成确定性时序再断言。
- **XHR/axios 在 pagehide/unload 期间会被浏览器取消**：防抖 + pagehide 冲刷的持久化
  方案必须用 `fetch(…, { keepalive: true })`（≤64KB），否则快速 F5 静默丢掉最后一次
  改动；而「服务端是事实源、加载时覆盖本机」的架构会把这次丢失放大成
  「刷新即回默认」（服务端旧态每次都覆盖本机新布局）。
- **「挂载即 reconcile 并持久化」在可恢复视图态下是自毁写**：勾选未就绪时 active
  暂为 ['hist']，reconcile+persist 把已存多图布局裁剪降级——本机+服务端两层同毁，
  且此后每次刷新都复现（毒状态自我维持，实测 dev 库被降级成 [['hist']] 无 toggles）。
  规则：挂载首拍只对齐渲染**不落盘**（`reconcile(active, { persist: false })`），
  落盘交给「数据 settle 后的权威对齐」；网络失败（memoryEnabled=null）分支同样
  不落盘挂载裁剪结果，保住「一次网络抖动不清本机」的设计承诺。
- **布局本身是勾选的事实记录**：服务端 state 只剩 layout 没有 toggles 时（上报丢失
  的产物），由 layout keys 反推 toggles 自愈——否则勾选缺省 false 与已存布局矛盾，
  矛盾会被 reconcile「修复」成降级。

## 2026-09-06 dock 图表布局缩放二次修复新增教训

- **CSS Grid 轨道裸 `1fr` 压不小**：`1fr` = `minmax(auto, 1fr)`，auto 最小尺寸 = 内容尺寸，
  轨道会被内容（含 ECharts 容器 wrapper 的历史高度）撑住 → 拖分隔条面板变小、画布不动被
  裁掉。直方图幸存只因外层滚动容器（overflow 非 visible）的 auto-min 归零，属巧合非机制。
  规则：**想让格子严格等于可用空间，列/行一律写 `minmax(0, 1fr)`**，不依赖每个子组件自己
  `overflow: hidden` 自保。
- **ResizeObserver 只护 onMounted 时已存在的容器**：QQ/箱线先渲染占位符、数据到达后 `v-if`
  才翻转出真容器——onMounted 时 chartRef 为空，observer 跳过且永不补挂；v-if 重建的新 DOM
  同理让旧 observer 盯死节点。修法（useChart）：`setupResizeObserver()` 先 disconnect 再判断
  （早退守卫前不移除旧 observer 会永久残留）+ `watch(chartRef)` 在容器出现/替换时补挂 observer
  并 ensureInit。R7③ 的「v-if 重建校验 getDom 身份」管实例复用，本条管 observer 挂载时机，
  两者缺一图表都不会跟随缩放。
- **e2e 断言画布尺寸的两个参照陷阱**：① `inst.getWidth()/getHeight()` 是 ECharts 内部缓存，
  实测出现过 inst 报旧值而真实 svg 已贴合 → 量宿主容器内 svg/canvas 的 getBoundingClientRect；
  ② 参照不能用 `.chart-b`/面板体——序列图宿主因 col-selector/OutlierHintBar 等固定高度兄弟
  legitimately 小于面板体，全等断言必假红（第一版 e2e 因此 2 例挂）。正确口径：
  **画布 rect == 宿主容器自身 client 尺寸**（±4px），仍能抓住「画布大于容器=被裁」的 bug 形态。
  另：循环断言多面板缩放时基线必须**逐 key 采集**，复用单 key（如 hist）基线会让其它面板
  「撑高 > hist 原高」恒假红。

## 2026-09-06 dock 底部空白二次修复（行占比归一）新增教训

- **删行只删长度不重分配，残留占比和 ≠100 → 末行下方永久空白**：`moveTo` 删空源行时把该行
  占比从 `rowPcts` 里 filter 掉，`normalizeSizes` 只校验**长度**一致就不动 → 和从 100 掉到
  100−删去项，`rowHeightCss` 按原占比渲染，dock body 底部留出 (100−sum)% 空白（底部横条
  「贴不到图表」的真正根因；今天上午修的画布 minmax/observer 是它的伴随症状）。
  规则：**占比数组的一切增删后必须归一到 sum=100**（按比例补齐保留用户比例，勿无脑重置均分）。
- **合成 PointerEvent 排查 DOM 事件链：先量 `elementFromPoint` 再怀疑处理器**：浏览器工具
  注入的 pointer 事件能正常触发 pointerdown/move（ghost 跟手、drop-left 指示出现），但
  `dropTarget` 恒 null——根因是 drop 点滚出了视口，`document.elementFromPoint` 对视口外坐标
  返回 null。拖拽类断言/脚本先 `scrollIntoView` 保证源与目标都可见。不可靠环境下直接上
  Playwright 真实鼠标（trusted events），同一条用例兼做回归钉。

## 2026-09-06 最大化卡死修复（视图态自愈）新增教训

- **组件级「临时视图态」必须对驱动它的数据集变化自愈，否则组合操作把用户卡死**：
  dock 最大化 `maxKey` 只在 toggleMax 里写，勾选集变化（activeKeys watch→reconcile）不感知
  → 最大化期间勾选其它图永远不显示（勾选框看似生效实则无反应）、关掉的图重新勾上会突然
  独占全屏——用户本能自救（点勾选框）全部无效，只能刷新。规则：**视图态在其输入集合的
  watcher 里一并清理**（本例：activeKeys watch 里 `maxKey.value = null`），且 UI 上要给
  且图标字形要语义自明（还原 ⤡ 与最大化 ⤢ 成对镜像；⤓ 与下载箭头近形，曾被用户误读为导出）。
- **复现「A 之后 B 失效」类 bug 先单独验证 A 的正向路径**：程序化点 ⤓ 能正常还原 →
  说明按钮没坏，问题在状态机与其它输入的组合——直接把怀疑序列（最大化→取消/重勾→观察
  面板列表）在浏览器里重放，一次定位；比逐行读代码猜测快得多。

## 2026-09-06 图表账号记忆（子代理驱动开发）新增教训

- **按账号存 UI 状态 + 共享测试账号 = e2e 并行污染源**：多 worker 共用 admin 时，
  A 用例存下的布局/勾选会改写 B 用例的起点，且互为 flake（单跑全绿、并跑必炸）。
  三件套对策缺一不可：seed 强制关闭记忆（存量账号归零）/ 功能用例用低权专属账号
  storageState（user）/ finally API 清场（PUT memory:false + state:{}，前置清场防
  上轮残留同理）。用例间确实要独占同一账号状态时 `describe.configure({ mode: 'serial' })`。
- **模块级会话缓存的三个必须**：①SPA 换账号（router.push 登出、页面不刷新）必须
  reset 缓存，且钩子要接进 auth store 的 login/clearSession（reset*Cache 先例），
  否则 B 账号读到 A 的布局；②「拉取失败」绝不能和「用户主动关」合并成同一个态
  （失败置 enabled=false 会把一次网络抖动放大成"清掉本机数据"，要单列 fetchFailed）；
  ③「保存为开」必须显式把会话内开关拨回 true——只 PUT 成功不改内存态的话，
  UI 显示开、实际防抖写仍被旧值阻断（Task6R 实测踩中）。
- **e2e 断言布局恢复要先清本机层**：双层存储（localStorage+账号）下不清本机键，
  刷新恢复断言区分不了来源（本机层也能恢复出同样布局），钉不住「换设备恢复」承诺
  ——主流程用例 reload 前先清布局键，恢复只能来自账号层。
- **user 账号无种子文件**：seed_test_data 只种 admin 且 DataFile 按 owner 隔离
  ——低权账号的分析页用例需自上传自清理，别假设 admin 的文件对 user 可见。

## 2026-09-05 分析页 tab 独立文件选择新增教训

- **多个 teleport 下拉面板共存时，全局 `:visible` 选项查询必错**：给 4 个 tab 各放一个
  `el-select` 后，它们的面板都被 teleport 到 `body`，**不随隐藏 pane 的 `display:none`
  一起消失**。用 `.el-select-dropdown__item:visible` 全局取选项会命中隐藏 pane 那一份，而它的
  reference 尺寸为零 → popper 逐帧重定位 → Playwright 永判“element is not stable”（实测卡满
  15s actionTimeout），而且 `.first()` 会点到**另一个 tab** 的文件上（表现为“选 A 实际选了 B”，
  断言拿到相同 file_id）。规则：任何可重复出现的 select 必须带**实例级 popper-class**
  （本轮：`dp-file-picker-<scope>` / `dp-outlier-popper-<scope>` / `dp-iqr-popper-<scope>`），
  测试选项一律从 `.dp-xxx-<scope>:visible .el-select-dropdown__item` 取；同一理由，
  `data-filter` 类契约属性也需限定在 `.el-tab-pane:visible` 内（访问过两个 tab 后同名属性有多份）。
- **不要把 `loading` 透传给 `el-select`**：EP 会往后缀插槽放 `is-loading` 无限旋转图标，
  reference 子树逐帧变化 → popper 逐帧重定位 → 下拉永不安定；加载状态要用**常驻固定尺寸
  槽位**里的指示器（槽位不预留时，它的挂载/移除会改变 flex 行宽，同样让 select 宽度变化）。
- **手工起 dev 服务会污染 e2e 数据环境**（本仓第二次踩）：不带 `LQDP_SYSTEM_CONFIG_FILE`
  跑 `manage.py runserver` → 按项目根 `system_config.json` 的 `data_dir` 连到**用户目录库**；
  而 `playwright.config.ts` 是 `reuseExistingServer: !CI`，会**静默复用**这个旧进程 → e2e 列表
  里的 file_id 存于用户目录库、磁盘文件在项目根 media → 38 条 `file_not_found_or_parse_failed`。
  一开始被当成代码回归。规则：跑 e2e 前除了查端口占用，还要确认占用者的**命令行与数据目录**；
  判定“是不是我引入的回归”时，先看失败是不是后端 4xx（数据层）而不是断言不匹配（UI 层）。
- **同一端点被多个 tab 各自发时，请求计数类断言要取对时机**：`/analysis/histogram/` 快路径
  现在每个 tab 各发一份，测试里“取最后一个请求的 file_id”必须在**切 tab 之前**取值，否则
  会拿到新 tab 那一次（本轮新增用例自己踩到，断言假失败）。
- **切文件后 UI 仍显示上一个文件的数据，读值类断言必须等新文件的计算请求**：
  切换窗口内图表/范围表/参数列表还是旧文件的（遮罩不在，`waitLoadingGone` 拦不住），
  实测读到过 DB 残留文件恒定列的 1/1 范围 → `span=0` → 两个「不同」限值算出同值 →
  `expect(x).not.toBe(x)` 假红。这竞态一直存在，但基线时推荐文件恰好是列表首项
  （选已选中项不触发切换）所以从不暴露；DB 残留改变 `files[0]` 后才现形 ——
  **看似新失败先查 files[0] 是不是变成了残留文件**。修法：读值前用
  `selectAnalysisFile` / `pickTabFileAndWaitCompute`（helpers/params.ts）等新文件
   自己的计算请求；严谨场景先等初始加载完再切。

## 2026-09-05 分析页 31 项 bug 修复（四批）新增教训

- **改 popper-class 名 = 同改 spec 内联定位器**：ParamSelector 作用域化
  （`param-select-dropdown` → `dp-param-popper-single/multi`）时，
  helpers/params.ts 的 selectParam/listParams 一并迁了，但 multi-file.spec.ts
  的**内联** `selectLimitsParam` 还引用旧类 → 4 个用例 15s 超时。e2e/README 的
  契约章节也一并改。规则：全局 class 改名后 grep 全仓（src + e2e + docs），
  存量 spec 的内联定位器不走 helper，最容易漏。
- **response 的 `postData()` 在 `request()` 上**：Playwright 的
  `waitForResponse` 谓词里是 `r.request().postData()`，写成 `r.postData()` 是
  TypeError 立挂。已有存量写法（如 multi-file.spec.ts:65）可抄。
- **后台跑 e2e 丢输出**：长命令套 `run_in_background` 时日志文件常为空（退出码
  1 也无堆栈）。30s+ 的命令直接前台跑（timeout 拉满），或改管道只留关键行；
  `findstr` 过滤失败时输出（exit code 1）也一起吞。本轮全量后端（888 项 ~243s）
  前台直跑一次看清。
- **astype(int) 对非整数序列号截断成功**：`pd.Series([2.5]).astype(int)` 不抛异常
  （截成 2），sv 的键仍是 2.5 → 点静默丢失。修法：转前 `(as_int == s).all()` 校验
  整数性，失败走原值集合路径（serial_distribution.py 注释已记）。
- **空操作兜底最难被发现**：histogram 的 `bin_min, bin_max = stats['rdl'][0], stats['rdl'][1]`
  看似兜底，实际赋值来源与 resolve 值**同一对**（单边 None 时仍是 None）。
  修这类代码时先问「兜底的输入与输出是不是同一个值」。
- **防御写在错误的层会失效**：uph 服务层有 `try/except` 降级告警，但视图层先裸
  `float()` —— 异常在容错之前就抛。改守卫先看调用链上哪一层先碰到脏数据。

## 2026-09-03 全量评审修复（四批）新增教训

- **测试风格必须匹配唯一 runner，否则静默零覆盖**：`test/backend/test_outliers.py` 是裸 `class TestX` +
  `import pytest` + 12 处 `pytest.approx`，而项目唯一 runner 是 `manage.py test`（unittest）且 pytest 不在
  requirements、未装进 `.venv` → 整个模块 `ModuleNotFoundError`，20 个用例一个没跑，只记 1 个 error。
  **只删 `import pytest` 更危险**：裸 class 不被 unittest 收集，会从「1 个 error」变成「零错误、零覆盖」。
  验收标准不是「命令没报错」，而是 `Ran N tests` 的 N 真的包含新增用例 + grep `_FailedTest`
  （`unittest.loader._FailedTest` 就是整模块 import 失败的特征信号）。
- **`manage.py test --parallel N` 在本项目会掩盖真实失败**：报 `TypeError: cannot pickle 'traceback' object`
  并直接崩，看不到是哪个用例挂。全量回归一律串行跑（857 项 ~250s，可接受）。
- **改根因函数前先用真实数据确认占位符语义，别信注释**：`apps/common/constants.py:3` 的注释写着
  「'min'/'max' 类关键字按数据边界解析，不在此列」，而下一行的 `NON_NUMERIC_KEYWORDS` **实际包含**
  'min'/'max'/'lower limit'/'upper limit'。实测真实 `gage_m_S1.csv` 有 13 个系统列（Serial_No/Dut_Pass/
  SW_Bin/QR_Code/Start_T/Test_Time…）的限值字段就是字面 `'Min'`/`'Max'` —— 在该格式里这是「无规格限」
  的占位，不是「用数据极值」。旧 `parse_limit_string` 把它们解析成数据 min/max 当 LSL/USL，
  数学上必然 Cpk ≤ 0.5（μ∈[min,max] 且 range≈6.9σ）→ 13 个系统列全部判 D 级红。
  规则：注释与代码冲突时以**代码 + 真实数据**为准；限值/哨兵语义要用真实样本文件验，不要靠推断。
- **改根因函数要一次性 grep 全部消费方，含「隐藏的内部调用」**：把 `parse_limit_string` 改成可返回 None 时，
  差点漏掉 `compute_range_statistics` 内部的 `safe_gap(rdl_min, rdl_max)` —— `safe_gap(None, None)` 直接
  `TypeError`，会让所有经它的导出端点 500。规则：改返回类型前先 grep 该返回值的**算术/round/比较**消费点，
  而不只是 grep 函数名。
- **现有测试可能钉住的就是 bug 本身**：本轮两个失败用例都是这种。① `dashboard/tests.py::test_overview_row_schema`
  断言 `assertIsInstance(row['cpk'], float)`，而那 13 个 `'Min'/'Max'` 占位列因此**必须**有 float cpk；
  ② `export/tests.py::test_batch_charts_site_stats_string_failcount` 的 metadata 写成 `{'limits': {...}}`，
  而实现读的是 `mins`/`maxs` → rdl 退化成幻影 `(0.0,0.0)` → 「所有值 > 0」全判 fail → 红底断言碰巧通过。
  规则：改动后测试变红，先判断它钉的是**契约**还是**缺陷**（看它的 fixture 是否真的走了它声称的路径），
  再决定改代码还是改测试；改测试必须在注释里写清旧断言依赖的是哪个 bug，并补一条「防止 None 分支
  永不执行导致测试退化」的正向断言（如 `assertIn('Serial_No', placeholder_rows)`）。
- **子代理的实测结论也要复核，本轮 6 处被推翻或修正**：① str 列 `abs()` 抛的是**可捕获的**
  `TypeError: bad operand type for abs(): 'str'`，不是声称的 `ArrowNotImplementedError`（严重度下调）；
  ② buyoff 文本 bin 的真实症状是**静默丢行返回 200**（4 行只剩 1 行），比声称的 400 更危险；
  ③ `charts.py` 的 x 轴**没有**错开 0.5·gap —— `low-2*gap` 恰好是第一个 bin 的**中心**，
  原结论是拿「中心」比「边界」得出的，属误判；④ `download_file_stream` 本来就有半截清理；
  ⑤ bool 列在旧 export 白名单下本来就被排除（真缺陷是 int32/float32 漏列 + pandas 3.0 下 `==object`
  对 str 列恒 False）；⑥ 反向风险：换成 `is_numeric_dtype` 后 bool **会被纳入**，必须显式 `and not is_bool_dtype`。
  规则：转述子代理结论前，对「要写进代码注释」和「要当修复依据」的那几条亲自跑一次最小复现；
  已写进注释的错误说法要一并更正，否则错误会被下一个人当事实引用。
- **收窄序列化器字段前先查它被谁复用**：堵 `PUT /auth/profile/` 自助提权时，不能直接把
  `UserSerializer.role` 设 `read_only` —— `UserManagementViewSet.get_serializer_class()` 复用它，
  那样管理员也改不了角色（且会撞既有 `test_put_with_full_body_still_works`）。正解是新增窄口径的
  `UserProfileSerializer`，并配一条**防过度修复**的用例（管理员仍能改角色/停用）。
- **锁权限类改动先查有没有人拿它当健康检查**：`playwright.config.ts:124` 用 `/api/schema/` 做后端
  webServer 就绪探测，直接给 Swagger 加 `SERVE_PERMISSIONS` 会让整套 e2e 起不来。改用
  `API_DOCS_ENABLED` 开关（development=True / standalone=False）既关掉出货版的匿名暴露，又不动 e2e 基建。
- **settings mixin 的 import 期守卫会限制「把默认值改安全」**：`config/settings/base.py` 被
  development/standalone 以 `import *` 复用，而它的 SECRET_KEY 守卫在 import 期执行 —— 把 `DEBUG` 默认
  改 False 会让 `from ...base import *` 在 development.py 来得及设 `DEBUG=True` 之前就抛
  `ImproperlyConfigured`，打断所有没设 SECRET_KEY 的 `manage.py` 调用。规则：改「安全默认值」前先看该模块
  是不是被 import 的 mixin、有没有模块级 raise；不能改就把理由写进代码注释，别留下一个看起来像疏忽的默认值。
- **桌面应用的网络暴露面要按「打包后怎么加载」判断**：生产 Electron 是 `win.loadFile()`（`file://`，
  Origin 为 `null`）访问 `http://localhost:<port>`，所以**每个生产请求都是跨源**，`CORS_ALLOW_ALL_ORIGINS`
  不能一刀切关（会直接打断打包版）；而 dev 态 vite 是 proxy `/api`，本来就不需要 CORS。可先做的收敛是
  绑 127.0.0.1 + bootstrap 硬互锁（非回环绑定 + 默认口令 → 拒绝启动）；彻底解法是让 Django 同源提供 SPA。
- **`<str:>` URL 转换器只挡 `/`，挡不住 `..`**：`batch-dirs/<str:dir_name>/` 配 `shutil.rmtree` 时，
  `dir_name='..'`（或 e2e/攻击里用 `%2e%2e`，Django 在路由前就已解码）能过 `isdir` 校验并把
  **整个用户上传根**（batch/ + single/）删掉，且 `ignore_errors=True` 静默。而从**请求体**取名的端点
  （`BatchDirImportView` 的 `dir_name`）连 `/` 都不受限制，`../../<他人>` 可跨用户 os.walk 并注册其文件。
  规则：任何「用户提供的名字 → 拼路径 → rmtree/os.walk/open」都必须过统一守卫（非法字符黑名单 +
  拒 `.`/`..` + `realpath` + `commonpath` 归属校验 + 拒绝解析结果等于 base 本身）；仓库里已有
  `_safe_extract_zip` 的 Zip-Slip 范式可直接沿用，别在各端点各写一套。

## 2026-09-02 批次 3：store 快照、测试大文件拆分

- **`ref(store.x)` 快照 = 单向同步且不报错**：子组件把 store 值拷进本地 ref 再
  `watch(本地 → store)`，只有本地→store 一个方向；store 变了组件毫无察觉。反向补 watch
  漏一个字段，该字段就永久停在挂载时快照——界面显示新值、请求带旧值，全程无报错。
  实测：页头改「敏感度 (IQR 倍数)」后单参数直方图仍发 `iqr_multiplier:1.5`
  （e2e RED 报 `Expected: 3 / Received: 1.5`）。**通则（R5 补充）：配置类 store 值一律
  `storeToRefs`，不写快照、不写回写 watch**——逐字段补 watch 本身就是踩坑面。
- **同名端点多个调用方，e2e 断言必须按请求体挑选对象**：分析页 `/analysis/histogram/`
  有两个调用方（页头拉参数列表不带 `params`；单参数图带 `params:[选中参数]`）。页头那个
  直读 store 本来就正确，所以「任一 histogram 请求含 iqr_multiplier:3」今天就已成立 = 假绿。
  谓词要精确到 `params.length===1 && params[0]===选中参数`。
- **大测试文件按主题拆分，先量跨类 fixture 依赖再分组**：`tests.py` 2468 行里的类互相借
  道具（`StaleParamAcrossFileSwitchTests._patched_view` 被 4 个类调、
  `ChartConfigFilterTests.METADATA/_frame` 被 2 个借，还有 `class 子(父)` 继承），
  只按相邻行分组会 NameError。跨模块 import 提供者即可，**不会被重复收集**（实测：拆分前后
  唯一用例 ID 集合 151==151、`Found 151 test(s)` 未涨）。验收口径就用这条：用例 ID 逐条
  diff 为空 + 总数不变，比"跑起来没报错"强。
- **产品决策变更后要顺着断言反查旧用例**：`large-data-qqplot.spec.ts` 断言
  `content-encoding==='gzip'`，而 GZipMiddleware 早在 `45f741e` 就被移除（实测压缩 68MB
  JSON 耗 3.6s > localhost 传输 0.2s，`config/settings/base.py` 有注释）——该断言自那次
  提交起必失败（移除发生在 `45f741e`，2026-08-12，距 HEAD 已 39 个 commit）。定位法：
  `git log -S "<被删的东西>" -- <配置文件>`
  与 `git log -- <spec>` 比对时间线。修法是改成当前契约（不压缩 + 响应体字节数上限，
  性能护栏由降采样承担），**不是删断言**。
- **列表行断言不要锚 `first()`**：`file-select` 的 `meta.first()` + 五段正则 = 假设
  「本库恰好排第一的行五个字段都全」。`FileSelect.metaText` 对空字段 `filter(Boolean)`，
  本地库残留的 2 行 88B 测试上传（`program_name=''`）只渲染 4 段 → 必失败，而产品行为
  是对的。通则（R2 补充）：数据相关断言一律先过滤/锚定到具名种子文件，再取该行。
- **分析页 e2e 与 Django 测试套件不可并跑**：两者共用 `media/` + `db.sqlite3`，后端套件
  会覆盖 e2e 依赖的种子文件——并跑那轮 5 例里 3 例假失败（文件行读成「1 行 · 213 B」），
  串行复跑即绿。跑验证前先确认后台没有其它测试进程。
- **全局夜模式的 `td.el-table__cell { background-color: X !important }` 会抹掉一切
  行级语义着色**：`styles/element-plus-theme.css` 里这条 !important 让失败行/当前范围行
  /告警行在夜模式下集体看不见（组件侧无论 scoped :deep 写得多准都被盖掉）。正确做法是
  只设 `--el-table-tr-bg-color`——EP 自带 `.el-table tr{background-color:var(--el-table-tr-bg-color)}`
  会用它，td 保持透明，组件的半透明 tint 自然叠在 tr 底色上。**通则（R7 补充）：
  主题覆盖层不要对"组件自己负责着色"的元素加 !important，优先改变量。**
  定位手段（比猜特指度可靠）：遍历 `document.styleSheets`，用 `el.matches(每个逗号分段选择器)`
  列出所有命中该元素且声明了 background-color 的规则，再看 `getPropertyPriority('background-color')`。
- **`color-mix()` 的计算值 Chrome 序列化成 `color(srgb r g b / a)`**，不是 `rgba(...)`：
  只匹配 `rgba(`/`#hex` 的颜色探针会把 alpha 读成 0，直接误判「color-mix 没生效/底色全透明」。
  e2e 里做颜色断言统一走 `e2e/helpers/colors.ts`（已同时支持 rgba/color()/hex，
  并把祖先 alpha 自下而上合成再算对比度）。

## 2026-08-30 SFTP 目录下载进度卡 1%：SSE 事件粒度与字节基准

- **批量/目录下载进度不能按「整文件完成」发事件**：旧 `download_dir` 用阻塞式 `sftp.get()`，事件只在每个文件下完后发一次——大文件期间进度停在 0%/1%（观感卡死）。修法（与单文件 SSE 同构）：抽 `iter_remote_chunks`（256KB 分块，单文件/目录共用）+ 按「实际累计字节/远端总字节」发进度（0.1s 节流）+ **每文件至少一次补偿事件**（小文件 <0.1s 读完时补发最终值，保证文件计数与百分比前进）。
- **重构后 deadline 检查必须「先查再读」**：循环内先 `time.time() > deadline` 再 `next()`；若先读后查，最后一次 read 完成时（耗时 > 剩余时间）直接超时，**吞掉该文件的 progress 事件**（「至少一个 progress 事件」是既有契约，见 2026-08-28）。
- **`mock.patch.object(类, 方法)` 的 MagicMock 不做描述符绑定**：替换类方法后 `self.method(a,b,c)` **不会自动传 self**（patch 的是 MagicMock 实例而非函数）——side_effect 按实参个数写（5 参写 6 参必 500）。
- **生成器「已完成文件」与「半截文件」状态必须分离**：文件完整写入关闭后立即清 `current_partial` 引用，否则补偿事件 yield 点的 GeneratorExit 会把**已完成文件**当半截删掉（DB 行还在、磁盘文件没了）。
- **时间戳后缀要覆盖所有断言点**：单文件重名落盘 `big_<ts>.csv`，`icontains('big.csv')` 匹配不到 → 搜索词卸到无后缀前缀（`search=big`）+ 返回文件名 `^big` 过滤；排查此类失败先确认「UI 已导入提示是否出现」，区分「下载没成功」与「断言错了」。
- **serial 文件内前一用例失败 → 后续用例 did not run**：排障先看 error-context 定位真实失败点，再考虑串行跳过。
- 改动后尽快 commit/备份、双代理并发写共享 docs 的教训 → 见 R1。

## 2026-08-30 指南 §11 页面篇落地（单文件 + 批次两批）

- **列表接口不带 metadata，详情接口补字段**：总览条「测试开始」需 `metadata.start_time`，但
  `DataFileListSerializer` 不含 metadata（列表 payload 含 mins/maxs 大数组不能扩）→ 页面级
  `loadFileMeta()` 走既有 `/files/:id/` 详情取 start_time（后端零改动、不新增接口，符合 spec「不新增后端接口」）。
- **临时截图用例必须带 @pN 标签或接受只跑 Edge**：P0/P1/P2 项目 `grep: /@pN/`，无标签用例只在
  Edge 项目执行；且 `globalSetup` 每轮重置 DB，历史批次不保留 → 批次截图用例需自造批次目录
  （`media/data/admin/batch/000_E2E_SHOT_<ts>/` + `/batch-dirs/import/` 注册 + 结束 DELETE + rmSync）。
- **label 内含子元素时 `getByText(x, { exact: true })` 失败**：总览条 UPH 标签内嵌公式 ? 悬停 span，
  元素全文是「UPH?」→ exact 'UPH' 匹配不到；含嵌套子节点的标签断言改用正则或容器级 testid。
- **组合多文件全量轮的成片失败先隔离复跑判定**（R2 复用）：dashboard+batch+theme 组合轮
  night-visibility 4 失败 + 用例数异常，workers=1 隔离复跑 6/6 全绿 → dev server 并行劣化 flake，非代码回归。
- **ECharts 渲染器默认 SVG，`var(--token)` 可直用**：项目默认 svg 渲染器，itemStyle/label 里
  `var(--success)` 等语义色可正常解析（既有组件已验证）；切 canvas 渲染器为已知存量约束，新图同样沿用。

## 2026-08-30 仪表板用户反馈修正轮

- **ECharts 笛卡尔热力图必须配 visualMap**：否则 `setOption` 直接抛
  “Heatmap must use with visualMap”，整系列不渲染——页面只剩坐标轴 splitArea，
  极易误判成「配色/标签 bug」。自定义逐格着色方案：`visualMap: { show:false, dimension, inRange }`
  承担着色（插值只认具体色值，var()/color-mix 不参与），label 用具体色值。
  诊断捷径：node SSR（`echarts.init(null,null,{renderer:'svg',ssr:true})` + `renderToSVGString()`）
  秒级复现 setOption 异常与标签输出，比开浏览器快。
- **SFC scoped 样式打不到 plain script 子组件的 h() 节点**：`<script lang="ts">` 里
  defineComponent + h() 组装的组件是独立组件，其内部节点不带父 SFC 的 scope 属性 →
  样式全失效（表象：布局「挤作一团」而非报错）。修：`.root :deep(.x)` 统一穿透；
  teleported 内容（ElTooltip content）scoped/:deep 都够不到，用内联 style。
- **Canvas SDK `canvasImage` 双重约束**：① 只收字符串字面量/无插值模板字面量（常量拼接编译期报错）；
  ② 本地图片必须相对 canvas 文件路径（绝对路径仅本地 canvas 临时可用）——跨目录截图复制进
  canvases 目录后 `./x.png` 引用。
- **百分比显示统一 3 位小数上限**（用户定稿）：formatPercent 自适应上限 6→3，极小非零值
  “<0.001” 防假零；裸值渲染点（`{c}%` 标签、YieldBadge 数字、后端 6 位 percentage）必须过格式化。

## 2026-08-30 反馈轮 2：图表 resize 与 e2e 后端环境

- **图表 resize 必须容器级 ResizeObserver**：window resize 覆盖不到「容器 display:none→可见」——
  隐藏 Tab 期间缩放会把 `chart.resize()` 锁到 0 尺寸，切回空白/挤压。修：`observeContainerResize`
  （echarts-init.ts，RO + rAF 合帧）；v-if 条件容器按元素身份挂载（重建后重挂）；
  数据后到场景在 render 内补挂。e2e 复现法：隐藏 Tab 时 `setViewportSize` 两连变再切回，
  断言 svg 宽 ≥ 0.8×容器宽。
- **e2e 勿手动起后端**：后台终端的 `$env:` 赋值不可靠（后端回退项目根 system_config.json 的
  home data_dir → `/batch-dirs/import/` 404「目录不存在」）；用 Playwright webServer（config
  显式传 LQDP_SYSTEM_CONFIG_FILE）最稳。数据环境污染根因见 2026-09-05 段；残留 runserver
  进程树杀法（`taskkill /PID x /F /T`）见 2026-08-29 段。
- **el-table 宽屏撑满**：全固定 width 列在超宽屏右侧留白；文本/时间列用 min-width 让余量弹性分配，
  树形表避免单一 min-width 列（phase）独吞余量。

## 2026-08-30 反馈轮 3：图表「经常消失」根因补漏

- **initEchartsWhenReady 超时不能断 ResizeObserver**：原实现 5s 超时连 RO 一起 disconnect——
  容器 5s 内没尺寸（隐藏 Tab/折叠卡）则 init 永久放弃，之后容器可见也没人重试→图表永久空白。
  修：超时只停 rAF/轮询，RO 保留到 handle.dispose()，容器后拿尺寸时 onReady 自愈 init。
- **v-if 图表容器重建必须 dispose 旧实例**：`v-if="data.length"` 空态↔数据切换重建 div 后，
  旧实例渲染进 detached 节点→新容器空白（表象：卡头 pills 有数、图区空）；修法（复用前校验
  容器身份，不符 dispose 重建）见 R7③；通则：任何 v-if/v-for 包裹的图表容器都要在 render
  路径做元素身份守卫。

## 2026-08-29 UI token 迁移（四批）新增教训

- **PowerShell `-File` 传数组参数会被外层 shell 吞**：`powershell -File x.ps1 -Paths @('a','b')` 经 cmd/Node 转手后数组丢失，脚本只收到首元素（表现为「只改了一个文件」）。修：改用 `powershell -Command "& '.\x.ps1' -Paths 'a','b' -Tag '1'"`，-Command 的字符串在子进程内按 PS 语法解析。识别信号：批量脚本报告修改数远小于预期。
- **CSS 自定义属性值保留换行空白**：`--font-sans` 多行书写时 `getComputedStyle().getPropertyValue` 返回含换行/缩进的声明值，e2e 字面断言（fonts.spec）必挂。修：token 文件里字体栈单行书写；凡被 JS 字面读取的自定义属性都不要折行。
- **e2e DB 种子重复行污染前缀匹配型断言**：legend-color 的 evaluate 按 `filename.startsWith('BPD60320_FT.')` 取 lot，种子被灌过两套同名行（08-25/08-27）→ 后端 4 个 lot vs UI 选 2 个文件，「柱系列数应等于文件数」4≠2 时挂时绿（取决于并行时序）。修：清理旧套重复行（seed_test_data --refresh 按文件名增量，不会重灌）；写前缀匹配型断言前先查 DB 有无同名重复行（R2 家族）。
- **批量正则删 CSS 夜块的四种副作用**（批 A 清理 `.theme-*` 覆盖时）：① 选择器列表尾逗号被留成悬空选择器（`SEL,` 后直接 `}`/`</style>`）；② 匹配从 HTML 注释内部的 `:root.theme-night` 文字开始→截断未闭合注释；③ 删 `.theme-*` 行时把选择器行的 `{` 一并带走；④ 补括号过度产生 `, {`。规则：批量 CSS 块删除后必跑括号平衡+悬空逗号体检脚本（见 tasks/_css_check.py 模式）+ build，勿只看 diff。
- **EP 主题 css 只加通用段不生效**：文件尾纯选择器规则优先级低于 `:root[data-theme="night"] …!important`，night 下新规格全部不生效——通用段须与旧 night !important 块**同步改为同 token 值**（如 --card-glass/--grad-brand），night 块保留 !important 只作兼容兜底（对称性要求详见 R7①）。
- **存量失败判定实例：electron.spec 的 `/login` 用例**：P1 项目带 admin storageState，已登录访问 `/login` 被路由守卫重定向到仪表板（DOM 快照可见已登录页面）→ `.login-container` 永不出现，与代码改动无关（同文件 `/#/login` 用例通过）。判据：error-context 的 DOM 快照 + 项目配置交叉验证，勿盲目修代码。
- **存量失败判定实例 ×2（组件改造收尾全量回归）**：① boxplot-bool-params / file-switch-param-reset 四例：spec 在 page.evaluate 里裸 `fetch('/api/v1/files/?search=…')` 不带 Authorization 头（JWT 在 localStorage、只有 axios 拦截器会加）→ 后端 401 → file_id 解析失败；WebServer 日志看 401 即定位。② large-data-qqplot 断言 `content-encoding === 'gzip'` 系陈旧失败（GZipMiddleware 已移除，完整根因/定位法/修法见 2026-09-02 段）。另：roadmap.spec 页面在旧提交 9b4418d 已删（/roadmap → 404）；判存量先看 git log -S 与后端日志，勿先怀疑本轮改动。
- **全量 e2e 中 vite dev server 中途崩溃**：并行负载下 webServer 死掉后大量用例报 `ERR_CONNECTION_REFUSED`（跨套件成片），全量汇总数字不可信——按 R2 分组隔离复跑（每轮新 webServer，workers≤2）再定论；纯 UI 套件（theme/data/sftp/exports）隔离后全绿即为环境性。

## 2026-08-29 e2e 端口被残留 runserver 进程树劫持（同一会话复现两次）

- **现象**：batch-phase e2e 报 `/api/v1/batch-dirs/import/` 404，但该端点在当前代码明确存在（直连探测命中路由返回 401）。
- **根因**：8000 端口被**非 Playwright 起的**残留 `manage.py runserver` 占着，`reuseExistingServer: !CI` 静默复用它（R3「复用旧代码进程 → e2e 结果无效」家族）；且 runserver 是 autoreload 父监视 + 子服务结构——只杀占端口的子进程，父进程立刻 respawn，端口「释放」后马上被占回。
- **修复/规则**：杀 runserver 必须**杀整棵进程树**——用 Win32_Process 沿 ParentProcessId 向上走到最顶层 runserver 祖先，整链一起杀，杀后验证无 `CommandLine like '%runserver%'` 的 python 残留再跑 e2e。识别信号：e2e 报「已知存在端点 404」→ 先查端口占用进程，勿先怀疑代码。PS 5.1 探测非 2xx 用 try/catch 读 `$_.Exception.Response`（无 `-SkipHttpErrorCheck`）。

## 2026-08-28 两仪表板重建设计→实施（P0–P4）：主题 token 化 / 五层 IA / 验证链

- vue-tsc 空检查、`] as any[]` 括号陷阱 → 见 R8。
- **e2e DB 残留会污染 files[0]**：其他套件遗留 `status='error'` 的 sample.csv 按 `-created_at` 排最前 → 仪表板自动选到坏文件、summary 返回 error、UPH 400 刷屏、dashboard 全部用例失败。修：DELETE 残留行或用例层面「选第一个 ready 文件」；项目根 db.sqlite3 是 e2e 库，可安全清理。（跨套件污染见 R2。）
- **/batch 路由已重定向到 /dashboard**（BatchReport 页下线）——batch.spec.ts 的批次报表断言属陈旧失败；admin.spec「已禁用」断言与实现脱节（UserManagement.vue 显示原始 is_active 值，从未渲染中文「已禁用」），是**基线既有失败**。全量回归前先跑 baseline 定位存量失败（见 R2）。
- 全量 parallel flake 模式（6 workers × SQLite）：个别套件全量失败、隔离复跑全绿——按 R2 判定；Windows ReplaceFileW EIO(1175) 见 R8。
- 主题治理：页面级全局 night 覆盖是根因 → 组件只认 token（scoped `var(--xxx)`）→ 删除全局块；图表色板统一 `useChartTheme()` semantic（pass/fail/warn/limit/sigma/kde/cpk/failBar）；双主题选择器统一 `:root[data-theme="night"]`；light 下 EP 主色是出厂 #409eff 而非品牌 #2563eb → 补对称 light 块（详见 R7）。
- **`<script setup>` 里 export interface 在本项目 Vue 3.5 是允许的**，不必为此改写。
- el-tabs 隐藏 pane 也在 DOM：两个 tab 的 `.context-bar` 同时存在 → 用 `.context-bar:visible` 或 `.first()`；el-drawer 关闭按钮是 `.el-drawer__close-btn`（无文字），断言关闭别按 hasText('关闭')。
