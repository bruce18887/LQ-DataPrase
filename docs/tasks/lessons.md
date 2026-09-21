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

## 2026-09-19 加载项「UI 一直还原不了」的根因不在 UI 代码：Excel 装的是四轮前的旧 xll

- **现象**：用户连续反馈「Exp 里没有控件」「没弹出任何东西」「还原不了原来的 UI」。据此换过四轮方案
  （v0.2.0 任务窗格 → v0.2.1 无模式浮动窗口 → v0.2.2 可见性兜底 → v0.3.0 表上 Form Control），
  四轮全部提交在**零实机验证**下（本机 COM 启动曾被权限拦截）。
- **根因（硬证据）**：`HKCU\Software\Microsoft\Office\16.0\Excel\Options\OPEN` 指向
  `%APPDATA%\Microsoft\AddIns\DataPrase\DataPrase-AddIn64.xll`，该文件 mtime **09-15 23:26**、
  md5 `7880dbf9…`；而 `dist\` 与 `bin\Release\` 的 v0.3.0 产物 md5 `17e2e043…`（09-19 22:25）。
  **两者不是同一个二进制**：`package.cmd` 只刷新 `dist/`，`install.ps1` 9/15 之后从未再跑，
  所以 Excel 一直在加载 v0.1.5。用户报的「弹出旧的模态选测试项框」正是 v0.1.5 的
  `ItemPickerDialog` 行为（该文件在 v0.2.1 已删）——**症状与最新源码无关**。
- **规则**：**报「改了没效果」，先证「跑的是不是新代码」**，再看代码。三条廉价判据：
  ①比对**装载路径**上的二进制与构建产物的 md5/mtime（不是源码目录的产物，是宿主实际读的那份）；
  ②读宿主的注册加载项键（Excel = `Options\OPEN*`）确认实际加载的是哪个文件；
  ③让产物自带**可查询的版本出口**（本例 `=DpPing()` → `DataPrase 0.1.5` 一锤定音）。
- **版本号别只改一处**：`AddIn.cs` 的 `AddInVersion.Value` 是手写常量，而
  `Properties/AssemblyInfo.cs` 的 `AssemblyVersion` 一直停在 `0.1.0.0`，xll 文件名也不带版本
  → 光看文件属性/文件名无法区分四轮，只有 `=DpPing()` 认得出来。**分发物必须能从运行时读出版本**。
- **顺带纠正一处过度断言**：`Exp-template.xlsm` 实测含 30 个 `xl/activeX/` 部件（15 控件 .xml+.bin）
  +2 vml +1 ctrlProps，而 `Exp-template.xlsb` **一个都没有**（20 部件）；原始宿主
  `LiqunData_V0.066.xlsb` 却有 34 个 activeX 部件 → 「.xlsb 存不进 ActiveX」不成立，
  丢部件的是这一次格式转换。核对部件清单时**注意大小写**：对 `x.lower()` 的集合搜 `'activeX'`
  恒为 0，会把自己骗成「模板本来就没控件」。

## 2026-09-19 隐藏 COM 实例不处理 Options\OPEN——验证通路必须显式 RegisterXLL

- **实测**：`New-Object -ComObject Excel.Application` + `Visible=$false` 起实例后，
  `Workbooks` 集合为**空**、`=DpPing()` 返回 `#NAME?`（值 -2146826259）、`Run('DpExpRefresh')`
  报「无法运行宏」——**注册表 OPEN 槽里的 xll 在自动化实例里根本没装载**。
  照这个现象判「加载项坏了」会判错：用户交互式 Excel 里是正常的。
- **规则**：无头自检脚本一律显式 `excel.RegisterXLL(绝对路径)` 再断言；启动路径的正确性用
  「读注册表 OPEN 值 + 比对目标文件 md5」另证，别指望自动化实例替你复现启动加载。
- **由此首次验证通过的未知点**：`[ExcelCommand]` 注册的宏名**能被 Excel 按裸名解析**
  （RegisterXLL 后 `Run('DpExpRefresh')` 无错，v0.1.5 同一调用必报「宏不可用」）——
  即 lessons:69 记的「Form Control `OnAction` 能否解析 XLL 命令名，本方案最大未知」在
  **名称解析这一层已通**（`OnAction` 与 `Application.Run` 走同一套宏名查找）。
  仍**未**验证：真实点击控件时 Excel 是否回调该命令、控件外观/位置是否符合原面板。
- 脚本：`DataPrase-ExcelAddin/build/verify-installed.ps1`（打印 OPEN 槽 / 启动时 Workbooks /
  DpPing 版本 / `Run('DpExpRefresh')` / `AddFormControl` 建-读-删往返）。

## 2026-09-19 设置项接线（批 2/3）四条可复用约束

- **ag-grid IRM 的块大小是「两端共用一个数」**：前端 `getRows` 用 `floor(startRow / 块大小)` 反推页码，
  而 `startRow` 由 grid 自己的 `cacheBlockSize` 决定。只把设置值喂给请求、没让 grid 采纳
  → 第二次请求会算回 `page=1`，表现为「滚到底又从头开始、行重复」。所以改块大小后必须
  `purgeInfiniteCache()`，且**断言要验第二次请求的 `page=2`**，只断言第一次请求带新值不算过。
- **同一个数值区间的三份字面量必然漂移**：设置页控件 `:min/:max`、序列化器校验、读取侧钳位
  三处各写一份，改一处忘两处是常态。做法：常量放读取侧（`EXPORT_DPI_MIN/MAX` 落 Django-free 的
  `charts.py`）、序列化器引用自己的一对、再用一条**源码扫描**用例断言三者相等
  （读 `ChartSettingsForm.vue` 抠 `:min/:max`）。先例：`test_export_stats_consistency.py` 的源码扫描。
- **`apps/export/charts.py` 被 ProcessPoolExecutor 子进程 import**（`chart_workers.py:3-8` 明文禁止
  在其中加 Django import）。所以「读用户设置」必须放独立模块（本次 `apps/export/user_prefs.py`），
  读库 + 钳位在那儿做完，穿进 worker 的只能是**已钳位的纯标量**（放进 task dict）。
- **接线项的默认值要三方对齐后再定**：`chart_dpi` 曾有模型 150 / 前端 150 / 代码常量 100 三个值，
  其中 100 带着「PNG 体积降 2/3」的实测理由。接线时默认一律取**代码里被实测过的那个**，
  并同步改模型默认 + migration + 前端 defaults；否则「设置生效了」的第一秒就把用户体积翻倍。

（同日另一条见上方「chart_renderer 接线」条目：写用户级设置的 e2e 必须先确认 8000 属主读哪份
system_config，以及「判别式用例要一条该红一条该绿」。）

## 2026-09-19 chart_renderer 接线：写用户级设置的 e2e 复用了真实数据目录的后端

- **险情（比"测试红"更严重）**：8000 上原有两个手起 `manage.py runserver`，不带 `LQDP_SYSTEM_CONFIG_FILE`
  → 读仓库根 `system_config.json` → `data_dir = C:\Users\Administrator\LQ-DataPrase`（**真实数据目录**）。
  `playwright.config.ts` 本地 `reuseExistingServer: !CI` 为真，会静默复用它。新用例要
  `PUT /auth/settings/ {chart_renderer: 'canvas'}`，这条写请求就会**落进用户真实账号的设置**，
  而用例 `finally` 把值固定恢复成 `'svg'` —— 若用户原本存的是 `canvas`，会被用例收尾静默改掉。
- **规则**：凡 e2e 用例会 **PUT/POST 用户级持久化设置**（`/auth/settings/`、系统路径等）的，
  跑之前必须先确认 8000 的属主读哪份 config：`Get-NetTCPConnection -LocalPort 8000` 取 PID →
  `Get-CimInstance Win32_Process` 看 CommandLine，再比对仓库根 `system_config.json` 与
  `%TEMP%\lqdp-e2e-system-config.json` 的 `data_dir` 是否同一份。不是同一份就**别复用**，
  让 Playwright 自起带钉死配置的服务；动别人的 PID 前先问用户。
- **推论**：用例的 `finally` 恢复逻辑只能恢复**它自己假设的初值**，不是"用户原值"。要写用户级设置，
  正确做法是先 GET 存原值、`finally` 写回原值（现有 `export-timeout.spec.ts` 的 `restoreTimeout`
  同样有硬编码 600 这个隐患，只是该项默认恰好等于 600 才没暴露）。
- **顺带（R2② 我又犯了一次）**：断言渲染器时假设 zrender 画笔根带 `data-zr-dom-id`，未经 trace 确认 →
  首跑两条全红，其中"默认 svg"这条本应恒过，它的红才暴露选择器错。ECharts 6 下判渲染器的正确口径
  与 `e2e/helpers/charts.ts` 一致：**echarts.init 宿主容器内**有 `<canvas>` 即 canvas、有 `<svg>` 即 svg
  （宿主 div 自身无子节点，Element Plus 图标不会落进来），不要依赖 zrender 内部属性名。
  判别式测试要设计成「一条该红、一条该绿」，两条同红 = 大概率是测试自己的问题。

## 2026-09-15 把 0 基 dump 当 1 基读，凭空造出两个假 bug

- **现象**：route-B 会话用 pyxlsb 导出的 `tasks/_exp_dump.txt` 作为依据，判定 VBA 写 Exp 分布表
  有「列号整体 +1 偏移（All Site 计数写进了 E=Site1 列）」与「`B3:B27` 是运算符列却被当乘数」
  两个硬伤，并据此拍板了「修正布局（C=Range / D=All Site / E–L=Site1–8）」。
- **根因**：该 dump 的**行、列都是 0 基**编号（它的 "A2" 实际是 Excel 的 B3、"C1" 是 D2）。
  当 1 基读，整张表就被平移一列，于是「模板本来就该在 D/E 的写入」看起来像偏了一格。
- **事实**：用 openpyxl 读 `Exp-template.xlsm` 的**真实单元格与公式**逐格核对，VBA 的写入位置与
  模板**完全一致**——`D2='Range'` / `E2='All Site'` / `F2:M2='Site1/N'…`；`D3='=$D$36+B3*$F$36'`
  （模板自己就用 B3 当乘数）；`D36/E36`=Low/High Limit；`C53:C56`=Range/Mean/STD/CPK；`G36`=Unit。
  差一点把**正确**的生产代码改成错的。
- **规则**：拿到 dump / 探针输出，先确认**坐标系**（0 基还是 1 基、列号还是列名、是否跳过表头），
  再用**权威原件**交叉验证（能读原始文件就别只信中间产物），之后才动生产代码。凭单一中间产物
  下的「口径修正」结论，须标注为**待原件验证**。

## 2026-09-19 加载项给表上加「能响应的控件」：Form Control + [ExcelCommand]（不是 ActiveX）

- **结论**：加载项要在工作表上放能响应的控件，走 **Form Control**（`Shapes.AddFormControl`）+ 把控件
  `OnAction` 指向 **Excel-DNA `[ExcelCommand]`** 宏（已确认该特性存在，docs 记作「for macro commands」）。
  宏里用 `Shape.ControlFormat.Value` 读状态、`Application.Caller` 认是哪个控件。**不需要任何工作簿 VBA**，
  且 Form Control 能存进 `.xlsx`。
- **对比真 ActiveX**：ActiveX 的点击事件过程必须活在工作簿**自己的 VBA 工程**里（原工具靠宏格式 `.xlsb`
  承载 `ComboBox1_Change` / `OptionButtonN_Click` / `CheckBoxN_Click`；拆 `vbaProject.bin` 得到）。加载项
  没有工作簿 VBA，要对 ActiveX 挂事件得引 MSForms 互操作（`tlbimp` FM20.DLL）做 COM 事件汇。→ 只有「外观
  必须与 ActiveX 完全一致」时才值得走 ActiveX。
- **API 坑**：①`Shapes.AddFormControl(Type, Left, Top, Width, Height)` 的坐标是 **int**（传 double 编译不过）；
  ②下拉取值靠 `ControlFormat.ListFillRange` 指向一段单元格（本实现写到 AZ 列），`ControlFormat.Value` 是
  **1 基**索引；③复选/单选的 `Value` 为 1(选中) / -1(未选)；④表上**单选按钮的分组不可靠**（按相邻/插入顺序），
  **互斥必须在处理程序里自行保证**；⑤`ExcelCommandAttribute` 无属性，命令名 = **方法名**。
- **未验证点**（本机无法实机跑 Excel）：`OnAction` 能否解析 XLL 注册的命令名——是本方案最大未知，标注待验。

## 2026-09-16 表内 ActiveX 控件无法移植到 XLL；兜底要判「事实」而非「异常」

- **原工具的「UI」是 16 个 ActiveX(MSForms) 控件**：拆开 `Exp-template.xlsm` 才确认——
  `xl/activeX/activeX1..15.bin` + `xl/drawings/vmlDrawing1.vml` 给出控件名
  （`ComboBox1` / `OptionButton1..5` / `CheckBox1..9` / 按钮），事件代码在 `xl/vbaProject.bin`。
- **⚠️ 修正（2026-09-19，联网核实）**：先前断言「XLL 结构上无法驱动表内 ActiveX」是**过度断言**。
  公开先例证明 .NET 侧能对**已存在**的表内 ActiveX 控件挂事件：
  `var cb = (MSForms.CommandButton)sheet.OLEObjects(name).Object; cb.Click += handler;`
  （SO 24003113 / Excel-DNA issue #303 / 项目 DBAddin / MSDN「run C# code behind a button on a
  worksheet without VBA」）。**能挂事件**；真正的难点是 ①从加载项**新建** ActiveX 控件、
  ②本项目注入的 `.xlsb` **已丢 activeX 部件**。
- 规则：**断言「某平台结构上做不到」前先联网核实**（Office COM/OLE 这类历史久、先例多的领域尤其），
  别把「我一时没做到 / 想复杂了」当成「结构上不可能」；措辞不确定时用「本轮未走通」而非「不可能」。
- **换容器格式会静默丢部件**：`Exp-template.xlsb` 里**根本没有 `xl/activeX/`**——把 .xlsm 转成
  .xlsb 时这些部件被丢了，所以注入出的 Exp 表**天生没有控件**。用户报「Exp 里没有控件」
  的根因在此，不是代码没写。规则：**.xlsm↔.xlsb 转换后要逐项核对原始部件清单**。
- **兜底要判「事实」而不是「异常」**：无模式 `Form.Show()` 后**检查 `_form.Visible` 是否为真**，
  为假才退到模态路径。这直接补上本日上一条「异常式兜底对静默失败无效」的漏洞——
  静默失败不抛异常，但「窗口到底有没有出来」是**可读的事实**。
- **UI 尽量留在 Excel 主线程**：WinForms 窗口跑主线程 → 「应用」回调直接调 COM 合法，
  **无需跨线程编组**（`ExcelAsyncUtil.QueueAsMacro`）；只有把窗口放独立线程才需要它。

## 2026-09-16 Excel-DNA 任务窗格「静默失败」——异常式兜底因此失效

- **现象**：`CustomTaskPaneFactory.CreateCustomTaskPane(ctrl, title)` **编译通过**（API 用法正确），
  运行也**不抛异常**，但面板**就是不显示**。于是「创建失败就退回模态对话框」的 catch 兜底
  **永远不会触发**，用户看到的是「什么都没发生，也没弹窗」。
- **教训**：**只靠异常判断成败的兜底，遇到「不抛异常但也没生效」的 API 就是无效的。**
  这类静默失败的 API，要么能验证生效（本机无法启动 Excel 时做不到），
  要么就别拿它当主路径——换成**已被证实本环境可用**的手段（此处 WinForms 窗口：
  配置对话框能正常弹出，即证明该加载项的 WinForms 渲染链路是通的）。
- **顺带**：`CustomTaskPane` 用反射枚举返回空成员，但 `CreateCustomTaskPane`/`DockPosition`/
  `Width`/`Visible` 全都能编译通过——**编译验证比反射可信**；反射拿不到成员，不代表类型不可用。
- 决策口径同 2026-09-15 那条：**无复现手段 + 主路径静默失败 → 立刻换确定能成的实现**，
  不要让用户在「没反应」和「没反应」之间来回试。
- **⚠️ 根因（2026-09-19 联网核实）**：`CreateCustomTaskPane` 在**控件未 COM 可见**时会失败——
  .NET Framework 需 `[ComVisible(true)]`（类接口自动生成），.NET 6+ 还需**显式默认接口**
  （公开 `interface` + `[ComDefaultInterface]` + `[Guid]`），否则报裸 `E_FAIL`（0x80004005）/
  「Unable to create specified ActiveX control」（Excel-DNA issue #558、docs issue #17、
  SO 55738903 已采纳答案）。本项目 `ExpPaneControl` 是 `internal` 且无 `[ComVisible(true)]`
  → 正命中该失败画像。规则：**任务窗格控件必须 `public` + `[ComVisible(true)]`（.NET Core 另加默认接口）**。

## 2026-09-15 两个输入报同一错 = 换方向；无复现手段时别把不确定性连推给用户

- **现象**：Excel-DNA 加载项里 `range.AutoFilter()`（无参）报「类 Range 的 _AutoFilter 方法无效」。
  换成两种完全不同的区块（数据区上一行 / 列名行）——**报同一个错**。
- **判读**：两个不同输入得到同一错误，说明**与输入无关**，是**调用方式本身**不被接受。
  这一步本该更早做：第一次换区块仍同错时，就该停止换输入、转向查调用形式。
- **根因推断**：`Range.AutoFilter` 在 Excel 类型库里**同时是属性**（返回 `AutoFilter` 对象）
  **和方法**（5 个可选参数）。PIA/嵌入互操作（`ExcelDna.Interop` 强制 `EmbedInteropTypes`）下
  这个同名冲突容易绑到错的 DISPID，Excel 便回「方法无效」；VBA 的 `Selection.AutoFilter` 走
  IDispatch 按名解析，所以同一句在 VBA 里正常。**结论：Office 里「属性/方法同名」的成员
  （`AutoFilter`、`Range.Hidden` 等）在 .NET 侧要按显式 DISPID 或晚期绑定处理，别指望
  `obj.Method()` 天然解析对。**
- **决策教训**：本机无法启动 Excel（权限拦截）时，**不要连续多轮把不确定性推给用户去试**。
  先问「这个功能是否必需」：本例是纯化妆性步骤，且 VBA 原逻辑本身不成立（拿插入的第 7 个
  **空行**当筛选头），最终**直接删除 + 说明替代操作（Ctrl+Shift+L）**，比继续盲猜更负责。
  规则：**无复现手段 + 非必需功能 → 砍掉并说明，而不是让用户当我的调试器。**

## 2026-09-15 Windows 脚本的行尾与编码（.cmd 必须 CRLF，.ps1 中文必须带 BOM）

- **`.cmd` / `.bat` 必须是 CRLF 行尾**：LF-only 的批处理会被 cmd.exe 拆错——实测报
  `'uild.exe`)' 不是内部或外部命令` 这类把一行劈成几段的错，看着像路径问题实为行尾问题。
  工具链写文件默认 LF，**生成 .cmd 后要转 CRLF**（`-replace "\`n","\`r\`n"` 再写回）。
- **PowerShell 5.1 按 ANSI(GBK) 读 `.ps1`，不是 UTF-8**：脚本里的中文会把引号读坏，
  报「表达式或语句中包含意外的标记」等语法错。规则：`.ps1` 存 **UTF-8 带 BOM**；
  或干脆脚本内只用 ASCII。
- **`.cmd` 里别写非 ASCII**：cmd.exe 走控制台代码页（本机 GBK），UTF-8 的中文文件名/内容
  会变成乱码（首版 `package.cmd` 生成的 `安装说明.txt` 落盘成了 `瀹夎璇存槑.txt`）。
  规则：批处理内一律 ASCII；要中文就交给 `.ps1`（带 BOM）输出。
- 通用做法：**先做编码/行尾检查再交付脚本**——`ParseFile` 做 .ps1 语法自检、
  对 .cmd 实际跑一次，别等用户双击才发现。

## 2026-09-14 VBA → Excel-DNA 加载项迁移新增教训

- **VBA 的 `=` / `<>` 字符串比较会给较短串补尾空格，C# `==` 不会**：VBA 里
  `"Report Generated By" = "Report Generated By        "`（常量带尾空格）为 True，
  移植时直接 `==` 会让机台识别全挂（ETS88 首格判定）。规则：源自 VBA 的字符串判等
  统一走「两侧 `TrimEnd(' ')` + Ordinal 比较」（本项目 `VbaString.EqualsPadded`），
  别逐处手写；带尾空格的 VBA 常量存成去空规范值。
- **VBA `IsEmpty(Range)` 靠默认属性求值才等价于「空单元格」**：`IsEmpty(Cells(i,1))`
  传的是 Range 对象（`IsEmpty` 对对象本应恒 False），实际靠 VB 默认成员求值成 `.Value`。
  移植时须显式区分「空白 null」与「空串 ""」——VBA 里 `Empty = ""` 为 True，但
  `IsEmpty("")` 为 False，这个差异决定「连续空行」终止判定是否触发。
- **VBA 的 `Double = Empty` 等价于 `= 0`**：`NoLimit = (Lolimit = Empty And Hilimit = Empty)`
  里 Lolimit/Hilimit 是 Double → 实际语义是「双限值都为 0 即无限制」（限值格为空格时
  VBA 不赋值、保持默认 0，同落此支）。移植「比较 Empty」的表达式要还原成与 0 比较，
  别当成 null 判断或「顺手修正」。
- **Excel-DNA 打包只纳入「被真正引用」的托管依赖**：AddIn 未使用 Core 类型时编译器
  不生成程序集引用 → packed `.xll` 内不含 `DataPrase.Core.dll`。判据：packed xll 体积
  增量 ≈ 主 dll 的 LZMA 压缩体积（仅 ~3.4KB）即证依赖没进包；单文件分发须等代码
  真引用后再复核（删掉旁置 dll 仍能加载才算数）。

## 2026-09-12 序列分布重叠优化新增教训

- **ECharts markLine 的 z 不继承宿主 series**：MarkerView.updateZ 走 retrieveZInfo(
  markerModel)，取 MarkLineModel 自身 z（默认 5）——宿主 series 抬 z 后参考线反被
  数据带压住（序列分布 site z=2..N+1 时 N≥4 即触发）。规则：markLine 需独立显式
  抬 z（写进 markLine 配置内），且上限要高于 site/Fail 层动态 z（本项目取
  max(20, N+4)）。
- **EP slider 键盘驱动 e2e 必须 focus `.el-slider__button-wrapper`**：tabindex=0 与
  onKeydown 挂在外层 wrapper（button.vue），内层 `.el-slider__button` 是不可聚焦的
  视觉 div——对内层 focus 后方向键静默无效（断言停在旧值）。

## 2026-09-09 分析页 dock 整体高度进布局记忆新增教训

- **e2e 记忆类用例必须先开开关，否则整条持久化链路静默不跑**：seed_users 把 e2e
  账号 `analysis_chart_memory` 强制 False（防并行污染）→ saveChartState 早退（无 PUT）、
  persist 不写 localStorage、wireMemory 走复位分支清本机键；UI 一切正常、只表现为
  「刷新丢」，曾先误判为并行竞态。规则：记忆类 e2e 开头
  `PUT /auth/settings/ {analysis_chart_memory:true, analysis_chart_state:{}}` 清场+开启、
  finally 复原 False（chart-memory.spec 模式）；断言服务端写入用本上下文
  `page.on('request')` 捕 PUT 载荷，勿读共享服务端态（并行同账号必竞态）。
- **刷新恢复断言要断掉 settings GET 防并行覆盖**：`page.route` abort GET → 记忆开关落
  null 态 → 不套服务端布局，恢复只走本机 localStorage 链路；此时勾选不恢复需手动勾
  （enterAll 会翻掉已恢复勾选的同款坑）。
- **组件局部 ref 是「记忆漏项」的温床**：dock 底部横条高度原是 ChartDock.vue 局部
  `bodyH` ref，布局记忆只存 rows/rowPcts/colPcts → 刷新必丢。新增视图态要么明确
  「不持久化」（如最大化，注释写明），要么进 dock 单例同链路持久化，不留第三种。

## 2026-09-09 SFTP 互斥/取消 + 文件相关性六项改进新增教训

- **EP 2.14 filterable select + automatic-dropdown 会把焦点困在 wrapper，打字全丢**：
  mousedown 时 filter input 仍 display:none，浏览器默认焦点落到 tabindex=-1 的
  `el-select__wrapper`；`useFocusController.afterFocus` 在 wrapper 获焦时即开菜单
  （automatic-dropdown 语义）→ input 显形；随后的 click 里 EP 本应把焦点挪进 input
  的 `handleClick` 被 `isFocusable(event.target)` 守卫 early-return → 焦点停在
  wrapper，之后键入全部丢失（**真实用户同样中招**，不只是 e2e；旧「首击只聚焦不
  展开、二击才开」怪象是同一机制的另一面）。规则：**automatic-dropdown 必须配
  「打开即显式聚焦 filter input」**（visible-change(true) → nextTick focus，见
  SerialSelector.vue）；e2e 要断言「打开后打字能过滤」（footer 文案切换），只断言
  菜单可见钉不住。ExportParamSelector / TestColumnSelector 的同类首击怪象同根因，
  待后续批次套用同一修法。
- **本地秒传的传输链路用 `page.route` 延迟钉出确定性断言窗口**：route 处理器里
  `setTimeout` 3s 再 `continue()`，请求被拦在浏览器、进度卡/互斥禁用已即时渲染 →
  从容断言互斥与取消；abort 后 `route.continue()` 会 reject，**必须
  `.catch(() => {})`**；断言完 `unroute` 恢复真实链路再验证状态未被取消破坏。
- **excelize `auto_filter` 写绝对引用**：写 `'A2:I3'` 读回是 `$A$2:$I$3`——测试断言
  先 `replace('$','')` 再比对，别照搬 openpyxl 的行为预期。

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

## 2026-09-13 序列分布 Fail/超界 强调层回退（产品反馈）

- **并集语义的强调层名会被用户误读**：「Fail/超界」层入层条件是「die fail（值可能完全
  正常、跨测试项 fail）」∪「值超显示范围」，但用户把带内红点全部读成「超界」并质疑
  数据（「值在范围内为什么也是越界」）。教训：强调层入层条件是并集时，层名/图例必须
  让主语义（本例为 Fail die）自明，或拆成两层分别表达；渲染正确≠可读正确。回退后
  fail/超界点随 Site 系列着色，其余可读性改动（自适应点径/透明度、最密垫底 z 序、
  拆分小多图、slider）保留；回退钉见 serial-overlap.spec.ts「自动档」用例。

## 2026-09-13 后端死代码清除（Plan A P0）：删代码的五条取证规则

- **重复检测器的输出不能直接决定「删哪一侧」**：token/行级重复扫描把
  `gage_legacy_builder.py`（唯一 live 的 Gage 导出实现）报成「10+ 处陈旧的重复块」，
  还给出超过文件长度的行号，按其结论删除会直接搞坏导出。规则：先用调用链取证
  （`views.py` 入口 → re-export 层 → builder，加测试直接 import 哪个），再决定删谁；
  两个互为镜像命名的文件（`gage_legacy_builder` vs `gage_summary_builder`）必须逐个
  确认死活方向，动手前把「哪个是 live」这句话复述一遍。检测器只能提出候选，不能下判决。
- **删模块要 grep 非 `.py` 的构建配置；悬空 hiddenimport 会静默自洽**：
  `lq_dataprase.spec` 的 `hiddenimports` 仍列着已删的 `apps.gage.services`。PyInstaller 对
  缺失 hidden import 只写一行日志就 `continue`，而 `git rm` 残留的空目录（只剩
  `__pycache__`）让这个名字以 **namespace package** 身份被 `find_spec` 命中，连那行日志都不
  打——构建期运行期都不报错，产物里却根本没有这个包。规则：删模块后
  `grep -rn "<module>" --include="*.spec" --include="*.json" --include="*.yml" ...`，
  并 `rm -rf` 掉只剩 `__pycache__` 的空目录（`find <dir> -type f` 先确认）。
- **`manage.py test 2>&1 | tail -N` 读不到汇总行**：stdout 被 pipe 时是块缓冲，
  `Seed users completed.` 这类 stdout 在进程退出才 flush，排到 stderr 的 `Ran/OK` **之后**，
  `tail` 恰好把汇总挤出窗口 → 看起来像"没跑完"，实际 exit=0 全绿。规则：读用例数一律
  `> tasks/x.log 2>&1` 再 `grep -aE "^(Ran |OK|FAILED|ERROR)"`。
- **纯删除批次要用「精确用例数」当门禁，不能只看 OK**：`test_export_histogram_grid.py:26`
  是模块级 import，删掉生产 shim 后只要这行漏改，整个文件不收集，钉着**新**几何的
  `GridMatchesScreenTests` 一起静默消失，而全量只少几个用例、照样 `OK`。规则：删除前先
  记真值基线（本次 919），每批断言确切差值（A3 应正好 −2 → 917），差值不符即停。
  历史「888/899」这类记忆数字不可信，基线必须现测。
- **把已删函数的算式复制进测试文件只是「历史事实存档」，不是防护网**：为了留住
  「旧网格会把 8 个点全丢掉」这一前置事实，测试里留了 `_legacy_bins_geometry`。用例拿它
  与它自己比对，生产侧再怎么回归它都不会变红——docstring 若写"防止用例空转"就是过度
  声明，会误导后人以为这里有保护。规则：这类 helper 要明写「存档、非守卫」，并把真正的
  守卫指回钉生产路径的用例；同时承接被删测试独有的断言事实（本次补了 `bins[-1]=32.5`），
  别只换个名字继续跑。

## 2026-09-13 分析页图表工具栏齿轮化 + 序列轴自适应新增教训

- **用「注释行」当锚点做文本替换会连体删掉紧随的函数声明**：把
  `// 注释 + function xAxisDef(i, showLabel) {` 整段当 old_string，new_string 却只写了
  注释与新增块 → 函数体悬空、`let grids` 等声明被挪到使用点之后，`vue-tsc -b` 连环报
  「Cannot find name」。规则：替换函数头时 old_string 只含注释行、函数声明原样保留在
  new_string 里；同一文件的多处结构性编辑之间插一次 build，别等一批改完。
- **单向绑定（`:model-value` + 事件）的 slider，e2e 里连按方向键会假行为**：值要经
  `emit → 父 ref → computed → 回流 prop`，中间隔一次 Vue 重渲染；高负载（6 worker）下
  `for` 循环连按 3 次快于回流，EP 内部值每次被旧 prop 拽回，最终只 +1（实测期望 6 得 4），
  且**隔离跑绿、并发全量必红**——最容易被误判成回归。规则：键盘驱动这类 slider 一律
  **逐按逐轮询**（press → `expect.poll(值)`），不要一次连按再断言终值。
- **「超视野参考线贴边钳制」分支的 e2e 不能赌种子数据的巧合**：种子文件的规格限未必
  远离数据带 → `test.skip(!out)` 恒命中 = 该分支零覆盖。规则：用 `page.route` 改写响应里
  的规格限到数据范围之外稳定走目标分支；断言写成「钳后值 === 轴边界 + 标签带 ↑/↓」，
  注入值本身无需回传即可自证。
- **收紧图表轴范围前先写出「不破坏 anchor 语义」的不变量并落进注释**：后端按
  `spec±10%` 给点打 anchor（超界点在前端贴边绘制），前端把范围收到数据带时必须证明
  「新范围 ⊇ 全部 anchor==0 值」且「⊂ 后端范围」——后端 anchor==0 的定义恰好保证后者。
  否则后人把 marks（规格限/σ）并入范围，就会把锚点画进图里、或裁掉正常点。
- **给超界点预留的头部可能反噬**：初版在数据范围外再加 15% 头部避免贴边锚点与数据带
  重叠，实测对「数据本就贴近规格限」的参数把范围撑得比改动前更宽（负优化）。规则：
  自适应轴只取 anchor==0 值 ± 固定 padding；padding 已足以分离贴边锚点，勿叠加预留。

## 2026-09-13 分析页工具栏冻结 + 统计条压缩新增教训

- **`position: sticky` 的参照是「padding 盒顶边」而非 border 盒**：给 `.content-area`（padding
  24px）里滚动的顶栏写断言，`toolbar.y − container.getBoundingClientRect().top` 恒等于
  padding-top（实测 24px，看着像「没生效」）。规则：sticky 断言基准用
  `容器 rect.top + getComputedStyle(el).paddingTop`，别直接比容器顶。
- **sticky 失效的头号原因是祖先 `overflow` 而非 z-index**：EP 的 `.el-tabs__content` 默认
  `overflow:hidden`，会把 sticky 的滚动祖先换成它自己（自身不滚动）→ 相对页面滚动永久失效。
  规则：加 sticky 前先过一遍祖先链，把中间层的 `overflow:hidden` 放开（本项目：
  `AnalysisPage` 的 `:deep(.el-tabs__content){overflow:visible}`）。
- **「固定高度单行条」必须 `flex-wrap:nowrap + overflow-x:auto`**：`flex-wrap:wrap` 在窄容器
  下折行会让高度翻倍（实测 26px→49px），压缩高度的目标落空。规则：要求固定高度的横向统计条
  一律 nowrap + 横向滚动，别拿 wrap 当兜底。
- **他人进程不要硬杀；被权限拦住就绕**：e2e 跑不动先分清占用者是「另一会话在跑的服务」还是
  「本仓测试残留」。前者绝不能杀（打断他人工作），后者也应先确认。被工具权限拒绝时，用**临时
  配置绕开**（前端换端口起 preview + 后端就绪探测换端点复用既有进程）完成任务，别把杀进程当解法。

## 2026-09-14 分析页左栏宽度下限 + 表格瘦身新增教训

- **「百分比列宽 + 内容决定宽度的表格」在缩放/窄视口下必然裁列**：左栏是 `el-col :span="6"`
  （=25%），而栏内表格的数字列宽由内容决定（10px 等宽数字、6~12 字符的限值）。1920 视口
  125% 页面缩放下左栏只剩 307px，表格内在宽 404px → `Gap`/`Unit`、`>Max` 列在视口里根本
  看不到（只有表格内部横向滚动条）。规则：承载「内容定宽表格」的栅格列必须给 `min-width`
  下限，数值 = 最宽表的内在宽 + 卡片内边距，且必须**实测**、不要估算。
- **内在宽的测法：先把容器压窄再读 `scrollWidth`**。容器刚好放得下时 EP 会把列拉伸填满，
  量到的列宽 = 容器宽、不是内在宽（我第一次就量出「范围对比 355、Site统计 355」两个假数）。
  规则：`覆盖 min-width 到 100px → 读 .el-scrollbar__wrap 的 scrollWidth`，才是真实下界。
- **省宽度的高性价比顺序：先看「每行同值」的列能否提到表头，再动内边距，最后才动字号**。
  单位列（后端每个参数只有一个 `unit`，各行同值）提到卡头省 49px；单元格 padding 6→4px
  再省 20px；两者合计让内在宽从 404 降到 ~275，字号一点没动。
- **`el-col` 的 `flex: 0 0 X%` 不可收缩：给兄弟列加 `min-width` 会静默撑破整行**。左栏
  min-width 385 后，25%+75% 之和（385+921=1306）> 行宽 1228，而 `.content-area` 是
  `overflow-x:hidden` → 多出来的图表右缘被直接裁掉，截图上看不出异常。规则：把右列改成
  `flex: 1 1 0; min-width: 0`（吃剩余空间），并断言「左 + 右 = 行宽」。
- **e2e 断言口径「可滚动到达」≠「可见」**：旧用例把「表格内部能横向滚到最后一列」
  （`scrollbar-always-on`）当通过条件，恰好与用户诉求（不滚动就同屏看全）相反 → 回归长期
  漏检。规则：布局类回归断言「零溢出 + 目标元素完整落在容器内」，并用**列清单精确相等**
  钉死列结构，别只断言最后一列「可达」。
- **`zoom` 缩放下的尺寸测量陷阱**：`documentElement.style.zoom = 1.25` 时
  `getBoundingClientRect()` 返回**缩放后**的值，`clientWidth/offsetWidth` 返回**未缩放的
  布局值**；混用会得到「左 385 + 右 921 = 1306 > 行 1228」这种自相矛盾的读数。规则：
  一次比较里只用同一套 API 量同类尺寸。
- **改动前先跑基线，别把既有失败算成回归**：`git stash push -- <本次改的文件>` + 重建
  + 同一条用例复跑。实测 legend-color 的「相关性散点」与 dock-resize 的「最大化可复原」
  在**改前代码上同样失败**（前者是本机环境的固定失败，后者是既有 flaky）——不做基线就会
  把这两条误判成新回归，白排查一轮。
- **Playwright `storageState` 是 per-origin 的**：临时把前端换到别的端口跑 e2e，token 仍指
  向原端口的 localStorage → 全部用例被路由守卫踢回 `/login`（现象是「`.main-layout` 找不到」，
  很容易误读成应用没起来）。规则：换 origin 必须让 setup 项目在新 origin 重新登录；并且
  `storageState` 只能挂在业务项目上——挂到顶层 `use` 会让 setup 自己带着旧 token 打开
  `/login`，登录表单永远不出现。
- **依赖数据的断言要写成「有条件覆盖 + 注解」(cut) 后缀只在参数真有异常值时才出现
  （`useFiltered = hasOutliers && 模式≠off`），而哪些参数有异常值取决于数据。规则：在抽样
  参数里扫第一个符合条件的，扫不到不失败（不变量与后缀无关），用
  `test.info().annotations` 如实记录是否覆盖到最宽场景。
- **导出色最忌「白字 + 淡彩底」**：`FFFFFF` 压 `F5B7B1`/`D5F5E3` 这类高明度淡彩，对比度只有
  1.5~2:1，肉眼看就是「字糊在底色里」——用户报的「对比度不清晰」多半是这一条，而不是配色不够。
  规则：判定语义优先用**深色字体色**（`#1E7A34`/`#8A5A00`/`#B3261E`，压白底均 ≥5:1），
  确需底色时用极淡底 + 同色系深字，永远不要白字压淡底。
- **判定「底色 vs 字体色」不是非此即彼，先分清诉求**：本项最初报的是「对比度不清晰」，
  根因是**白字压淡彩底**（`FFFFFF` 压 `F5B7B1`，约 1.8:1），不是"有底色"本身；
  我先据此改成"只用字体色"，用户看后又要回底色（宽表扫读快）。**规则：先修对比度
  （深色字配浅底 / 白字配深底，都过 4.5:1），再谈要不要底色；把两件事混成一件会来回改。**
  底色方案要配条件格式，字体色方案静态即可（见下条）。
- **大色块是「不正式」的主因**：分区/分组竖带用四条高饱和色（`3498DB`/`27AE60`/`E67E22`/`8E44AD`）
  会把工程表变成看板。规则：结构分层只用中性灰（`FAFAFA`/`F7F8F9`/`F2F2F2`），主色只留给
  标题/表头带一处；分区靠**文字标签**区分，不靠色相。
- **写样式断言前先量一下 excelize 的返回形状**：`f.get_style(sid).font.color` 是 6 位十六进制
  **字符串**（`'B3261E'`），而 `.fill.color` 是**列表**（无填充时为 `[]`）。凭直觉写成同一种形状，
  测试会静默拿到空值或 `['B3261E']` 而误判。规则：新增样式断言前先用一个最小脚本打印
  `repr(...)` 确认形状。
- **改配色前先查「谁在断言颜色字面量」**：`test/backend/test_buyoff_layout.py` 直接断言
  `'D5F5E3'`/`'FCF3CF'`/`'F5B7B1'`，改色必红。规则：改配色前全局搜颜色字面量与
  `fill|font.color|fgColor`，把「断言颜色」的用例改成断言**语义**（哪种判定），别只改字面量——
  否则下次换色又红一遍。
- **条件格式只能比数值，单元格存文本会静默永不命中**：Result 的百分比原本存的是
  `"6.000000%"` 字符串，CF 规则挂上去不会报错、也永远不触发。改法是**存小数 + 百分比数字格式**
  （`0.06` + `0.000000%`）。便宜的验证点：excelize 的 `get_cell_value` 返回**格式化后**的值，
  所以改完显示仍是 `'6.000000%'`，既有的字符串断言一字不用动。
- **excelize 的 `criteria='between'` 是坏的**：它写出 `operator="between"` 却不写那两个边界
  `<formula>`，规则实际无效（`greater than` / `less than` 都正常）。规则：区间判定用
  「严格比较 + 按优先级排列 + `stop_if_true`」逐条短路表达，别用 between；边界要跟 Python
  口径对齐时用严格不等（`>fail` 红 / `>warn` 黄），别用 `>=`。
- **CF 的底色读回来在 `bgColor`，不是 `fgColor`**：excelize 写的是
  `<patternFill patternType="solid"><bgColor .../></patternFill>`，只看 `fill.fgColor`
  会得到 `00000000` 并误判成"CF 不生效"。另外 **excelize 没有 CF 读取接口**（只有 set/unset），
  断言必须落盘后用 openpyxl 读 `ws.conditional_formatting._cf_rules`。
- **断言 CF 要"模拟求值"而不是"断言规则存在"**：只查规则条数挡不住口径写错（阈值 0.05 写成
  0.5 照样通过）。做法：按 `priority` 排序，对给定数值逐条套 `operator` + `formula[0]`，
  返回第一条命中的 `dxf` 底色 —— 这样 5%/10% 分档、边界属于哪一档都被真正钉住。
- **`f.save_as()` 与 `save_excelize()` 的取舍**：后者会 `f.close()`，调用后就再也读不了单元格，
  在"一个用例里既读值又读 CF"时会把后续断言全部弄坏。规则：需要同一句柄多次读取时用
  `save_as` 落到临时文件后自行读走字节，别用 `save_excelize`。
- **写 `''` 不是「空格」，是文本单元格 —— 会让数值型条件格式把整列空白格都标中**：
  Gage Summary 的「R&R% 列空白格也被标红」这个 bug 根因不在条件格式，而在数据：
  代码把含大量 `''` 的 `row_data` 逐格写入，excelize 落成 `t="s"`（共享字符串）。
  Excel 比较时**文本恒大于任何数值**，于是 `>= 30%` 对空白格成立。规则：写单元格时
  统一拦掉 `None`/`''`（留真空格），收口在一处；排查"条件格式乱标"先看被标格的
  原始 XML 有没有 `t="s"`，别一头扎进规则里。切分现象：openpyxl 读回 `None` 是真空格、
  读回 `''` 是空串 —— 用这个断言最省事。
- **excelize 没有 auto-fit，自己算列宽有两个必踩的坑**：①**横向合并区**（跨列标题）
  的锚点值会被 `get_cols` 记在最左列，不跳过就会把首列撑成整行宽；②**表头区之外的行**
  不该参与，否则一句 `"Failed Items (R&R% >= 30%): 3"` 会把 File Name 列撑到 32.5。
  另：`get_cols` 返回的是**格式化后**的显示值，正合适；东亚宽字符要按 2 计。
- **断言 excelize 写的列宽别走 openpyxl**：excelize 会把等宽的相邻列合并成一个
  `<col min=1 max=3 width=11.5>`，openpyxl 的 `column_dimensions[letter]` 会读回
  与 XML 不符的值（同一区间内的列报出不同宽度）。直接解 sheet xml 的 `<cols>` 最准。
- **配色断言值得写成"守门测试"**：上一轮加的 WCAG 对比度断言，这轮改 warn 底色时
  当场拦下 `#7D6608` 压 `#FFE0B2` 只有 4.38:1。规则：配色表里每对"底色+字色"都写成
  断言，改色时由测试告诉你哪里掉下 4.5:1，比肉眼靠谱。

### 2026-09-17 派生值改 Excel 公式（excelize）

- **`set_cell_formula` 把字符串原样写进 `<f>`，禁止带前导 `=`**：传 `"=A1+A2"` 会落成
  `<f>=A1+A2</f>`（非法 OOXML，Excel 打开可能提示修复）；正确写法是 `"A1+A2"`。识别特征：
  openpyxl 读该格 `.value` 会得到 `==A1+A2`（前导 `=` 是 openpyxl 自己加的，多一个 `=` 就说明
  文件里写坏了一个）。规则：统一走一个收口函数去掉前导 `=`。
- **公式格不落缓存值，`get_cell_value` 读回空串**：excelize 写公式只写 `<f>`，不写 `<v>`。
  两个后果：①导出时必须 `set_calc_props(CalcPropsOptions(full_calc_on_load=True))`
  （写进 workbook.xml 的 `calcPr`），否则用户在 Excel 重算前看到的是一片空白；②测试取公式
  的算值只能用 `calc_cell_value`，它返回**格式化后的显示值**（百分比格是 `'15.492%'`，
  不是 `0.154919`）。`excelize.open_reader(bytes)` 可从落盘字节重开一个能求值的句柄。
- **excelize 内置计算器对 `常数*SQRT(除法)` 解析不了**：实测
  `ROUND(6*SQRT(SUMSQ(x)/n),4)` 算成 `0`，而 `ROUND(SQRT(SUMSQ(x)/n)*6,4)` 正确。
  这是**计算器实现的 bug，不是 Excel 的问题**（Excel 两种写法都对）。规则：写公式时让
  「常数乘在 SQRT 之后」；更重要的教训是 —— 公式一旦依赖测试环境的计算器求值，
  就得接受它是个**受限的第三方实现**，踩到就先绕开写法，别怀疑自己的公式。
- **同表引用优先于跨表引用**：Gage 的 V/W/X/Y 本可引用各文件工作表，但那是跨表（要处理
  sheet 名引号/转义）且踩上 100 行上限。改为引用 **Summary 表内**逐文件的 H/I 与 E/F，
  公式更短、无转义、可独立验证 —— 选派生数据的引用来源时，先挑同一张表里已经有的。
- **公式化的边界要有"静态兜底"**：只有操作数可判定时才落公式，`N/A`（限值缺失/公差为 0）
  仍写静态文本、不落公式。这样既避免 `#VALUE!`，又保住了 N/A 的灰色语义，也让
  「不可判定」在测试里仍可被 openpyxl 直接读到。
- **别用带点号的函数名（`STDEV.P`/`STDEV.S`/…），也别用 `IFERROR` 兜底掩盖错误**：
  用户实机打开时 Gage 的 Reproducibility 整列变 0 ——根因是公式用了 `STDEV.P`（Excel 2010
  才加的点号函数名，部分查看器认不出会报错），而外面套的 `IFERROR(...,0)` 把错误**静默吞成 0**，
  既没报错也没显示异常，极难定位。改法：用老函数名 `STDEVP`（Excel 97 起就有），
  并把单文件边界写成显式的 `IF(COUNT(range)<2, 0, …)` 而不是 `IFERROR` —— 万一将来还有不兼容，
  会显示 `#NAME?`/`#DIV/0!` 而不是又一个静默的 0。**诊断线索**：若整列某个统计量恒为 0、
  而相邻列正常，先怀疑该列独有的函数名/写法，再看有没有 `IFERROR` 吞了错误；
  另外"单元格里显示公式原文"通常是**在编辑态**，不代表存的是文本。


## 2026-09-19 加载项 Exp 面板「少控件 + 图全 0」= 一个非法控件值；Form Control 的取值口径别照抄 ActiveX

- **现象**：Exp 表上只出现 3 个控件（下拉 + 2 个单选），分布图全 0.00% 没有柱子。
- **根因**：`ExpControls.SetValue` 给未选中的单选/复选框写 `Value = -1`（ActiveX/MSForms 的
  `vbUnchecked` 约定）。**Form Control 不认 -1**，实测必抛「不能设置类 OptionButton 的 Value 属性」。
  而 `Build()` 的循环是「先 Add 再 SetValue」，所以抛错时该控件已经建出来了——
  于是现场恰好留下 3 个形状（下拉 + Limit0 + Limit1），看着像「建到一半」，其实是**第二个单选抛的**。
- **合法取值（隐藏实例逐个试出来的）**：初始值 **-4146**；`1`=选中、`0`=未选中（读回 -4146）；
  复选框还接受 `2`（混合），**单选按钮不接受 2**；`-1` 与 `-4105` 一律抛。
  → 规则：**跨控件家族搬「约定」前先在本机实测取值域**，ActiveX 与 Form Control 的
  `Value` 语义不通用（`lessons:66` 那条「1/-1」就是照抄来的，已纠正）。
- **连坐**：两个调用点都是 `Build()` 的下一行才 `WriteExpDistribution`（`ProcessRunner.cs`、`Actions.cs`），
  Build 抛错 → 分布公式没写 → Exp 停在模板的 `[1]Data!` 外部引用 → **图全 0**。
  一个 bug 同时造出「少控件」和「没柱子」两个看似无关的现象。
  → 规则：**可选的化妆性步骤不能挡在必需的数据步骤前面**；顺序改成先写公式再建面板。
- **`ProcessRunner.Append()` 把异常降级成一行警告**，用户几乎看不见 → 破坏性流程里的可选步骤
  失败要显眼，否则现场只剩「结果不对」而没有任何线索。

## 2026-09-19 控件位置：别按「行号 × 行高」算，Exp 行高实测 10.2pt 不是 15pt

- `ExpControls.Add` 用 `Top = (row - 1) * 15` 假设每行 15pt；Exp 表实际 **10.2pt/行**
  → 整面板下漂 1.47 倍（本意 37 行落在 53 行），这就是用户说的「错位」。
- 修法：**按单元格锚定**——`Cells[row, col].Resize[h, w]` 的 `Top/Left/Width/Height` 直接取。
  原模板的控件本来就是单元格锚定（`Exp-template.xlsm` 的 `xl/drawings/vmlDrawing1.vml`
  里 `<x:Anchor>` 8 元组，0 基行列）：ComboBox H35 跨 5 列 2 行、OptionButton B36-B40、
  CheckBox B43-B51、按钮 N35 跨 3 列 2 行。**还原 UI 要先量原件，别自己编行号。**
- `AddFormControl` 只吃 **int** 坐标，10.2pt 行高必然带小数：`(int)` 强转是向下截断，
  逐行累积仍显错位 → 用 `Math.Round`；自检的落点判定也要留 **1.5pt 容差**，
  否则会把取整误差误判成 bug（真 bug 偏 18 行，量级差两个数量级）。
- `TextFrame2.TextRange.Text` 对 Form Control **必抛**（「在此对象上找不到属性 Text」），
  只有旧式 `TextFrame.Characters().Text` 可用；`ControlFormat.Link` 在 PowerShell 晚期绑定下
  报「找不到成员」（与 `AutoFilter`/`Hidden` 同族陷阱），别用晚期绑定判存在性。
- 表上**裸放的单选按钮 Excel 自己就互斥**（实测：两个都设 1，前一个自动回 -4146），
  `lessons:67` 说「互斥必须在处理程序里自行保证」不成立——除非放进 GroupBox 才需要分组。

## 2026-09-19 无头自检两条硬坑：MessageBox 会挂死自动化、`$x = Function` 会吞掉标签

- **`MessageBox.Show` 在 COM 自动化实例里会永久阻塞**：给 `DpExpRefresh` 加「说清原因」的提示后，
  `Run('DpExpRefresh')` 直接把自检脚本挂死（Excel 进程留着标题为「LQ-DataPrase - 分布表控件」的
  隐形模态框）。→ 产品侧：任何由宏/命令触发的提示都要先判 `Application.Interactive`；
  脚本侧：`New-Object -ComObject Excel.Application` 之后**显式设 `$excel.Interactive = $false`**
  （COM 起来的实例默认仍报 Interactive=true，这点反直觉）。
- **PowerShell 里 `$v = Step "label" { ... }` 会把标签行和值一起捕获**，日志里看不到标签、
  断言还拿到脏字符串。要单独打印的分支就别走这个包装函数。
- 自检函数（`DpSelfCheck` / `DpSelfCheckFlow`，`IsHidden=true`）跑的是**生产代码路径**：
  前者在临时簿上重建面板并回报「16/16 建出、落点行、OnAction 是否挂上」，
  后者打开真实 datalog 跑 `ProcessRunner.Run` 再回报「panel/allSiteSum/e3 是否已指向本地 Data!/B43 标题」。
  实测：`controls=16/16 landed=16/16 onaction=16/16`、`tester=CTA8290D items=328 allSiteSum=352`
  （与该用户截图里 Exp 的 Test Number 352 对得上）、换测试项后 B43 由 `R_Kelvin_VIN` → `R_Kelvin_VDRV`。
- **`imageMso` 会静默不渲染，且离线判不出来**：`ToolsOptions` 与 `OptionsDialog` 在本机
  Office 16.0.19127 上都取不到图（按钮只剩文字），而 `FileOpen`/`FilterAutoFilter`/`ChartInsert`/`Help`
  正常。试过把候选 id 拿去 grep Office 二进制做离线判定——**作废**：`FilterAutoFilter` 明明能渲染，
  在 `Office16` 下 396 个 dll/exe 里却搜不到明文，说明名字表不是明文资源。
  → 结论：**imageMso 只能实机肉眼看**；要确定性就别依赖它，用 `getImage` 回调自绘位图。
- **`getImage` 自绘图标可用**：`public object GetSettingsImage(IRibbonControl)` 里用 GDI+ 画
  32×32 透明底 + `Segoe UI Symbol` 的 `⚙`，经 `AxHost.GetIPictureDispFromPicture` 转成
  `IPictureDisp` 返回（派生一个 `AxHost` 子类暴露该受保护静态方法，`base("00000000-...-000000000046")`）。
  实测 ribbon 上正常出图。两个坑：① 返回类型写 `object`，别引 `stdole`；
  ② `Image` 在 `System.Drawing` 与 `ExcelDna.Integration` 里**同名**，必须全限定，否则 CS0104；
  ③ 回调里任何异常都要吞掉返回 null，否则整条 ribbon 可能加载失败。
  字符用 `"\u2699"` 转义写，别在源码里放非 ASCII 图标字符（Ribbon.cs 无 BOM，靠 Roslyn 猜编码）。

## 2026-09-20 设置接线轮的 e2e 三条静默陷阱（现象都不是「断言写错」那么简单）

- **e2e「滚不到目标列」的红：真凶是循环形状，不是选错元素**（ag-grid 35.3 实测）。
  `.ag-header-viewport` / `.ag-center-cols-viewport` / `.ag-body-horizontal-scroll-viewport`
  三者横向滚动量**双向同步**，写哪个都动 —— 我前两版分别断言「只有滚动条代理是权威」
  「赋 scrollLeft 会被同帧写回」，都是自己圆现象，手工探针一跑全部推翻。两个真坑：
  ① 可滚上限是 `scrollWidth - clientWidth`（实测 35674 = 36400 - 726），而
  `while (el.scrollLeft < el.scrollWidth)` 永真 → 目标列没渲染出来就是**死循环**，
  症状是整条用例 60s 超时、零断言消息（`view-data.spec.ts` 在 HEAD 上就这么红的）；
  ② `.ag-root` 刚出现时列宽还没测出来（实测那一刻 `scrollWidth === clientWidth === 926`、
  表头 0 格，约 265ms 后才 36400 / 6）→ 那之前既滚不动也探不到。规则：渐进滚动一律
  **按 x 有界推进 + 每次滚完再探测 + 先等有界等到可滚宽度**（见 `scrollGridUntil`）。
  纵向另说：给 `.ag-center-cols-viewport` 赋 `scrollTop` 不触发 IRM 续块（实测等不到
  `page=2`），驱动 `.ag-body-vertical-scroll-viewport` 就好（机制未查证，按可用做法写）。
- **定位器类失败先量再改**：这类问题一次浏览器内 `evaluate` 探针（量 `clientWidth` /
  `scrollWidth` / 写后可读回值 / 目标元素出现位置）只要 3 分钟，而我先连改两版、跑两轮 e2e
  各 20+ 分钟才逼出真相。**能在页面里一次测出来的东西，不要靠猜 + 跑套件去验**（R2②
  「选择器先经 trace 确认真实存在」的加强版：存在且可写 ≠ 语义是你以为的那个）。
- **折叠式汇总面板让「文案不在 DOM」看起来像功能没生效**：`AlertBanner.vue` 默认 `open=false`，
  多条告警合成一行「N 项告警」，逐条 `message` 要点了 `.banner-head` 才渲染。断言链必须是
  「`[data-testid="alert-banner"]` 可见 → 点头部展开 → 再断文案」，直接 `getByText(明细文案)`
  会误判成「后端警报没生成」。
- **设置类用例的三个数据前提都不能假设**：① 「仪表板默认打开最新 ready 文件」会被同套件里
  别的用例中途上传的文件顶掉（实测被残留的 `a.csv` 夺走 → 总览一行 CPK 都没有，
  helper 抛「没有带 CPK 数值的行」）→ 必须经 `.dash-file-select` **显式选种子文件**，
  且**每次 `page.reload()` 后重选**（`DashboardPage.reconcileSelection` 在挂载时把选中重置回
  `files[0]`，选中态不落盘）；② 别把「默认阈值下这一行是 A 级」写成前置断言——哪行 CPK 多少
  取决于数据，只断言充分关系（三级阈值全抬到该 CPK 之上 → 必判 D）；③ PUT 用户级设置后
  `finally` 写回**原值**而不是硬编码默认，admin storageState 是全套件共享账号。

## 2026-09-20 字体接线轮：探针宿主与「单一来源」的四条

- **e2e 探针的宿主兜底会让断言静默空过**：`document.querySelector(host) || documentElement`
  在宿主不存在时落到 html/body，读到的是**继承值**，「字体栈应含 Microsoft YaHei」照样绿。
  实测 `/data` 上 `.ag-grid-wrapper` 一直在（el-tab-pane 保持挂载），但未选文件时 AG Grid
  **整个不渲染**，声明在 `:deep(.ag-custom-theme.ag-theme-quartz)` 上的 `--ag-*` 一个都没读到；
  只有字号断言报出 `16px`（= body 的 `--text-base`）才把真相暴露出来。
  规则：断言作用域内 CSS 变量必须打在**真实渲染的元素**上（`.ag-cell`），探针宿主缺失要 fail
  而不是兜底；写这类用例先确认目标组件在该路由下是否真的挂载。
- **判断「有没有测试」要把 `test/` 和 `frontend/e2e/` 一起扫**：我只 grep 了 `test/` 就断言
  「项目里没有任何字体测试」，实际 `frontend/e2e/global/fonts.spec.ts` 早就在钉 `--font-sans`
  与 `--el-font-family`，方案里写成「新建」差点重复造一套。规则：覆盖判断先两处都查，已有
  spec 一律扩写。
- **注释里的「必须与 X 同步」要先实测两边是否真一致**：`theme/typography.ts` 自称与
  design-tokens 同步，实际 `fontSize` 整套 rem（12/14/16/18/20/24/30/36）与 `--p-fs-*`
  （11/12/12.5/14/16/18/22/26/36）互相矛盾，且除 `fontFamily` 外零消费方。规则：拿它当事实
  之前先量一次，量完发现是死导出就直接删，别留着继续骗人。
- **跨模块统一常量要扫源码，不能只顺着工厂函数**：改前的字族旁路比审计列出的更多——
  `export_batch_charts_xlsx.py:59` 自带第 3 份 rcParams 列表，`excel_builders.py` 在建表函数里
  就地 `new_style(family=...)` 绕过 helpers，样式对象回读只覆盖得到「走工厂的那部分」。
  规则：这类「单一来源」整改自带一个源码级 grep 用例把旁路变成红的（见
  `test/backend/test_export_fonts.py::NoBypassSourceTests`），别靠 review 的眼力。

## 2026-09-20 字号归档（第二步）：自建差量基线的四条

- **会改像素的批量替换，先证明基线可复现再动手**：本轮建的是「计算值快照」而非像素截图
  （Electron 跨机器截图必飘）。开改之前同一份源码跑两遍快照，实测 482 元素路径 **DIFF=0**
  才敢下 codemod。反过来说：没有这一步，「0 回归」这个结论本身就没有意义。
- **差量工具自己也要被证伪**：before 自比 0 回归只能证明「不误报」，证不了「会报错」。
  补 5 个合成反例（改在档值 / 凭空多出档位 / 折叠目标缺失 / 大字被误改 / 正确归档）跑一遍，
  才确认脚本真有判别力。规则：新写的守门/比对脚本，除了正例必须配反例。
- **折叠是「多对一」，差量不能按序号配对**：9px 和 10px 都归 micro(11px)，于是
  `removed=[9,10,15]` vs `added=[11,14]` 数量不等 —— 第一版按 index zip 判，直接报两条
  假回归。改成按集合判（每个消失的尺寸，其归档目标必须存在于 after）。
- **快照采集器的两个静默坑**：① `about:blank` 上读 `localStorage` 抛 SecurityError，
  切主题前必须先 `goto` 到同源文档；② 同一个 cssPath 本来就有多种字号（如 `.ag-cell`），
  把它拼成单值字符串会让 key 随元素数无限增长且读不出差异 —— 存**尺寸→次数**的集合。

## 2026-09-20 「管理员能禁用自己」的死锁：判断一个操作可不可逆，要把恢复路径全查一遍

- **现象**：用户管理页允许管理员禁用/删除自己，且没有任何自助恢复入口。用户问
  「如何处理」——答案是**只能直连数据库**。
- **根因（四条恢复路径全堵）**：①登录端点在 `authenticate()` **之前**就拦停用账号
  （`views.py:90-95` → 403 `account_disabled`）；②SimpleJWT 每请求校验 `is_active`
  （`CHECK_USER_IS_ACTIVE` 默认 True 且本仓未覆盖）→ 现有 token 当场失效被踢出；
  ③Django admin 登录同样要求 `is_active`；④`seed_users` 只修 `role`/`is_superuser`，
  **从不碰 `is_active`**（`seed_users.py:51-61`）。四路皆断。
- **规则**：判定某操作「用户事后能自己救回来吗」时，要沿**所有**恢复路径走一遍
  （应用登录端点 / token 校验中间件 / admin 后台 / seed 或修复命令），别只看这个端点
  自身能不能撤销。「能改回去」常常是假象——改回去的入口本身被同一个开关挡住了。
- **代理守卫挂 `perform_update`/`perform_destroy`，不要挂 `update()`/`destroy()`**：
  `serializer.validated_data` 已完成类型强制（`is_active` 是真布尔、且部分更新时只含
  请求体出现的键），用原始 `request.data` 得自己处理 `'false'` 这类字符串；
  `perform_destroy` 是 `destroy()` 的标准扩展点，天然覆盖删除。
- **「最后 N 个」类规则要先算清它在什么情况下才可能触发**：本仓的「必须保留至少一个
  启用的管理员」实际只拦「唯一管理员把**自己**降级」。推理：请求者必然已是启用的
  管理员（SimpleJWT 挡住停用者），目标非自己时请求者本人就在 `exclude(pk=target)`
  里 → 规则不可能成立。写这类守卫前先做这一步，否则容易写出永不触发的死代码，
  或反过来过度设限。**同时必须配「原路径仍然放行」的用例**（本次：有第二管理员时
  自降角色 / 停用另一个管理员 / 删他人三条），否则守卫收紧到什么程度无人把关。
- **e2e flake 归因：基线要 stash 后跑，且要跑够轮次**（R2③ 的加强版）。本次
  `admin.spec` 的 `@p2 禁用 / 启用用户` 在 workers=6 下**每轮 flake 一次**、重试即过；
  只跑一轮根本区分不了「我引入的」与「既有」。做法：`git stash push -- <我的生产改动>`
  再跑 3 轮 → **3/3 复现同一条**才敢判定无关。另一个坑：**基线跑本身可能被
  webServer 崩溃污染**——那次 4 failed / 2 passed 的根因是
  `page.goto: net::ERR_CONNECTION_REFUSED at localhost:3000`（vite preview 中途死掉），
  数字完全不可用。**下结论前先 `grep -c ERR_CONNECTION_REFUSED` 一次**，非零即作废重跑。
  串行 `--workers=1` 是第三重证据：同一文件 7/7 全绿说明是并发竞态而非回归。
- **并发的两个 @p2 用例共用同一 admin 账号 + 同一 DB 会互踩**（lessons 2026-09-06
  「共享测试账号 = e2e 并行污染源」同族，本次是**新实例**）：后端访问日志显示
  `DELETE /auth/users/38/ 204` 之后紧跟一条 `PUT /auth/users/38/ → 404`——
  两个页面互相操作了对方的用户 id。失败点落在用例**末的清理删除**（断言 `已删除`
  超时），不在断言链中间，容易被误读成产品 bug。**机制未完全定位，未擅自改测试**。

## 2026-09-21 HTML 报表导出：三处「看起来对但会被工具打脸」的坑

- **`locator.isVisible()` 不重试，动画/异步渲染的可见性判断必须用 `waitFor`**：批次
  下拉（Element Plus popper）展开有动画，`firstOption.isVisible()` 在动画未完成时立即
  返回 `false`（该方法是一次性快照，**不自动等待**），于是用例稳定「跳过」。
  对照：`expect(locator).toBeVisible({timeout})` 与 `locator.waitFor({state:'visible'})`
  才会重试。规则：判断「某元素是否已出现」时用 `waitFor`；`isVisible()` 只用于「现在就
  在不在」的无等待场景。诊断线索：skip 前的 `[diag]` 日志已证明选项数量（104）非零，
  坑在**可见**而非**存在**。
- **源码扫描守门会被你自己的注释触发**：`test_export_fonts` 用正则
  `rcParams\[\s*['"]font\.sans-serif['"]\]` 扫 `apps/export/**/*.py`。新模块的 docstring
  里写了「不在本模块内自设 `rcParams['font.sans-serif']`」——**那句说明本身就是命中**，
  测试直接红。规则：在受源码正则守门的模块里，连「解释为什么不要写 X」的注释都要规避 X
  的字面量（改写成自然语言，如「sans-serif 候选列表」）。
- **`vue-tsc --noEmit` 不是本仓的构建校验入口，`vue-tsc -b` 才是**：新增 composable 后
  用 `npx vue-tsc --noEmit` 报「无输出=通过」，但 e2e 的 webServer 跑 `npm run build`
  （= `vue-tsc -b && vite build`）时立刻报 `TS2307 Cannot find module`（导入路径多一级）。
  两者 project references 行为不同。规则：本地校验前端类型请跑 `npm run build` 或
  `npx vue-tsc -b`，别信 `--noEmit` 的沉默。

## 2026-09-21 SFTP 搜索子系统：移植、依赖漂移与「测不出来的那一类」

- **参考工具里能跑 ≠ 能移植**：`DataPrase-SFTP Searcher/config/sftp_connection.py:18` 用的是
  `AutoAddPolicy()`，照搬进本项目会**直接破**主机密钥 TOFU 契约（
  `test/backend/test_sftp_host_keys.py::test_mismatch_refuses_and_credentials_are_not_sent`
  钉着「密钥不匹配即拒绝、凭据不发往可疑主机」）。**怎么办**：移植前先查「这段代码依赖的性质
  在本项目有没有反向钉桩」，再用真数据/真服务冒烟一次，并核对**当前依赖版本**的 API 签名。
  （同一族的「转述前先自己复现一次」见 2026-09-08 段。）
- **依赖版本升级会让「看着还在」的保护静默失效**：venv 里 paramiko 5.0.0 的 `SFTPClient`
  **没有** `realpath`（只有 `normalize`），而 `search/walker.py::_resolve_dir` 早期只按
  `realpath` 取解析结果 → 每个目录都静默退回 normpath，软链接环保护名存实亡；单元测试全绿
  （`FakeSftp` 两个名字都有），**只有真 paramiko 服务器跑起来才现形**。同族漂移：
  `Transport.__init__` 在 5.0 已无 `default_timeout`，读超时只能用现成的
  `downloads.channel_timeout`（设 channel 的 socket 超时）。**怎么办**：降级路径必须走异常，
  不许静默 fallback；并给降级补一条 `assertNoLogs` 用例（见
  `test_sftp_search_integration.py::test_dir_resolution_never_degrades_silently_on_real_client`）。
- **多线程共用一条 paramiko SFTP channel 的表现是永久卡死，不是返回错值**：并行 IO 打在同一
  个 client 上会把协议流错位，`as_completed` 永不返回；而 `spec.timeout` 只覆盖扫描循环
  （runner 的判点在两批目录之间），**救不到列目录阶段**。**怎么办**：并行 IO 的测试要有看门狗
  （本子系统 `HARD_CAP_SEC = 60`），把「挂死整轮 test run」换成一次有界、可复现的 FAIL。
- **DRF 内容协商会吃掉 SSE 的 `Accept` 头**：客户端发 `Accept: text/event-stream` 时，视图若
  只有 JSONRenderer 在谈，会在**进 action 之前**被判 **406**（连「400 + 一句原因」都到不了用户
  手里）。Django test client 默认不发这个头、浏览器 fetch 默认 `*/*`、curl 默认 `*/*` →
  单测与手工 curl **全都测不到**。**怎么办**：流式端点至少做一次真 socket 的 HTTP 全链路验证；
  修法是把 `text/event-stream` 声明成可协商类型（`search_views.SSERenderer`，真流走
  `StreamingHttpResponse` 不经渲染器），并留一条 `HTTP_ACCEPT='text/event-stream'` 的回归用例
  （`apps/sftp/tests_search.py`），同一头下的校验失败仍须是 400 + JSON 体。
- **两档实现自动降级时，语义不等价的能力必须整体禁掉其中一档**：服务端 grep 档与客户端档在
  模糊（grep 无子序列原语）、非 ASCII（grep 只按 UTF-8 字节 → 本域 GBK 文件**静默漏**）、
  跨语言整词（`LC_ALL=C grep -w` 与 `re` 的 `\b` 对 CJK 判定相反）、递归深度（GNU grep **没有**
  `--max-depth`）上都不等价。做法：这类查询在 `search/engine.select_engine` 整体排除 grep 档，
  并给一条写明**后果**的用户可见 `notice`。理由：**「同一查询的结果取决于服务器恰好有什么」
  是比缺功能更糟的性质**。
- **`LC_ALL=C grep` 的 `--include`/`--exclude` 按 argv 顺序求值、最后命中者决定去留**
  （实测 GNU grep 3.0），**不是**「exclude 恒压 include」。若某实现要求 exclude 优先而 grep
  给不到，唯一同时满足两种语义的排法是**把全部 `--include` 排在 `--exclude` 之前**
  （`search/shell_grep.py` 就是这么排的；排反的后果实测：16 个文件全回来，参照档只该有 6 个）。
  另：`--exclude='.*'` 不管目录，目录要另给 `--exclude-dir`。**怎么办**：别凭记忆写 shell 工具的
  语义，跑一次真二进制取证，并把结论同时钉进注释与平价测试
  （`test/backend/test_sftp_search_parity.py`）。
- **一个永远不可能变红的测试不是测试**：给 `apps/sftp/pool.py` 补 per-user RLock 时，原计划的
  并发用例用微秒级 mock 握手，GIL 不在临界区内切换 → **不加锁也全绿**，计划预测的红压根不出现。
  加 `BUILD_DELAY = 0.05`（`test/backend/test_sftp_pool_lock.py`）让线程真重叠之后用例才有效。
  **怎么办**：写完并发测试先故意把被测保护撤掉，确认它会红，再恢复保护。
- **桌面版后端的并发模型要与代码自述的前提对账**：`pool.py` 曾自述「gunicorn sync worker 下
  同用户不会并发」故不加锁，但 `standalone.py:224` 实跑的是 `runserver --noreload`，而
  **Django 6.0 的 `--nothreading` 是 `action="store_false"`，默认 threaded** → 前提早已失效。
  **怎么办**：读到「本实现无锁/无校验，因为 X」这类注释，去核实 X 在**当前部署形态**下还成立
  不成立——运行时假设和代码一样会腐烂。
- **把一条测试划进「人工验证」之前，先问它防的是不是竞态/时序**：`workers=1` 与 `workers=4`
  结果必须逐字一致这条，一度被降级成 curl 人工清单，而它是全计划里唯一能抓出并行协议错乱的
  保护；收进自动化后第一次跑就抓到上面那条 realpath 静默失效。**这类缺陷只在自动化里反复跑
  才现形**，人工清单跑过一次就再也不跑。

