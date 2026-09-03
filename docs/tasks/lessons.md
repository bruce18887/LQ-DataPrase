# Lessons Learned

> 维护约定：跨日期高频重复的教训已沉淀到文首「通用规则 R1–R8」，日期条目只保留独有内容；
> 新教训按「现象 → 根因 → 修复/规则」压到最短追加到对应日期段；能归入 R 系列的**不重复写**。
> （2026-08-30 合并 副本 tasks/lessons.md 全部历史并浓缩去重；原始文件见 lessons.bak-2026-08-30.md。）

## 通用规则 R1–R8

- **R1 完成即提交，磁盘才是事实**：功能验证通过即 `git commit`（或 `git diff > tasks/xxx.patch` 留底）——曾发生改动未提交被 `git checkout .` 一次清空、整日重放。任何「声称完成」用 `git log`/`git diff` 验证磁盘状态，勿依赖会话记录；4+ 步重构结束前 `git status` + `git diff --stat` + 针对改动点跑回归。多代理/多会话并发写共享 docs（todo/lessons 已入 git 版本库）时，先读现状再改、保留他人条目、条目标题带「日期+主题」锚定便于找回；若不慎覆盖/清空，恢复路径：`git log -- docs/tasks/lessons.md` 找到覆盖前提交，用 `git checkout <commit> -- docs/tasks/lessons.md`（或 `git show <commit>:docs/tasks/lessons.md > lessons.md`）取回上一版本。
- **R2 e2e 断言规范**：① 断言端到端可观察状态（DOM/文本），勿在中间步骤拦截网络；`waitForResponse` 必须在触发请求**之前**用 `Promise.all([waitForResponse, action])` 注册。② 选择器先经 trace 确认真实存在的 class；`v-show`/多 tab 常驻 DOM → 必须加 `:visible` 或 `.first()` 限定；组件根定位 class 用 fallthrough 加在根元素。③ 全量失败先对 baseline 跑一遍定位「存量失败」，再单文件隔离复跑（含 retries）区分 flake 与回归；跨套件共享 DB 状态要自建/自清（`000_E2E_` 命名前缀 + finally 清理），防残留行污染 files[0]。④ **由页面加载自身**触发的请求（reload / 深链恢复自动选文件发请求）不能靠「goto 之后 waitForResponse」等稳定：goto 解析→注册之间有几百 ms 窗口，响应先到就永远等不到（实测注册 +541ms / 响应 +543ms，2ms 余量；后端加缓存/变快后从偶绿转必红）。改等 UI 状态（目标可见 + `.el-loading-mask` toHaveCount 0）；同理「不应发请求」的计数器 `page.on('request')` 必须装在 `goto` **之前**，并用 baseline 差值扣掉前置阶段已发出的请求，否则漏计造成假通过。⑤ `locator.boundingBox()` 对空 locator **不是**返回 null，而是等满 actionTimeout 后抛错——`?? fallback` 救不了，必须先 `.count()` 判存在（canvas 渲染器下无 `svg` 时典型）。
- **R3 前后端契约与守卫**：① 相似端点守卫必须对齐（如 histogram/qqplot/boxplot 的 `param not in df.columns`），grep 对比即可发现——一个 400 守卫、一个 500 就是状态码雪崩温床。② 「前端已过滤 → 后端不用管」是错误假设：任何接 Series/参数的业务函数都要容错（bool/str/object/category、空串、null），视图层过滤规则可能漂移、直连 API 可绕过。③ 哨兵/默认值判断先做真值守卫（`if v and v != '全部'`）；`request.data.get(k, default)` 的 default 只在键**缺失**时生效；GET 端点参数一律 `request.query_params`。④ 前端已有 API/类型但后端 404 → 先分清「缺端点」还是「缺功能」，按前端 interface 字段反推后端结构逐字段实现。⑤ 接口传完整语义（如 `role_map` dict），不能依赖隐式数组顺序。
- **R4 数值与序列化容错**：① pandas 数值入口统一 `pd.to_numeric(data, errors='coerce').astype(float)`——bool 必须显式 astype（to_numeric 不改 bool dtype），str 由 coerce 转 NaN；过滤用 `np.isfinite()` 向量化，不要 `apply(lambda x: abs(x) < inf)`（str 上崩、慢 10x）。改完以诊断脚本复跑归零（如 `bp_issues=0`）为硬标准，别只看"我写的小测试过了"。② 后端 NaN → JSON null：前端所有可能为 null 的数字渲染前 `Number.isFinite()` 护，TS interface 写 `number | null`。③ 写新 stats service 前先扫 `df.dtypes.value_counts()` 找 bool/object 漏网；回归测试必须覆盖「脆弱数据」路径（全同值列、NaN、离散列）。
- **R5 持久化状态与上下文切换**：持久化到 Pinia/localStorage 的「用户上次选择」（selectedParam/selectedFileId/tab），在文件/项目/数据上下文切换时必须在**父组件入口**显式重置（`state=''`/`store.x=''` 清空后再异步加载）——子组件只清本地值会被 v-model 双绑推回旧值。跨上下文状态泄漏要**双层防御**：前端清状态 + 后端 validation（光一层不够：多 tab/深链接/旧版缓存可绕过前端；只有后端则用户 400 时已困惑）。
- **R6 测试基础设施**：① DRF 视图测试必须 `force_authenticate(request, user=...)`（Permission 检查 `request._auth`，`request.user = SimpleNamespace` 无效），`is_authenticated=True` 必设。② mock ORM 对象给视图用时字段列全（id/filename/format_type 最低配），勿只放当前用例需要的。③ monkey-patch 必须 patch **实际消费模块**的绑定（`from .x import f` 创建独立绑定，patch 包名不生效）+ `addCleanup` 还原。④ 管理类 ViewSet 测试覆盖 4 形态：PUT 单字段 / PATCH 单字段 / PUT 全字段 / PUT 不存在 id。
- **R7 主题与图表**：① 任何前端改动维护 dark+light 双主题：组件只认 CSS token（scoped 内 `var(--xxx)`），禁止页面级全局 night 覆盖（曾 47 条非 scoped 覆盖是主题不一致根因）；选择器统一 `:root[data-theme="night"]`；element-plus 主题 css 的 night/light 块必须对称（否则 light 显示出厂 #409eff 而非品牌色）。② ECharts 不认 CSS 变量：setOption 颜色取 `useChartTheme()` 的 JS 语义色；DOM（模板 style/进度条）里才用 `var(--token)`。③ 新图表组件禁止裸调 `echarts.init`，必须走 `initEchartsWhenReady`（零尺寸保护，容器高度未定会报 "Can't get DOM width or height"+空白）；共享 chart composable 必须支持容器被 v-if 销毁后重建（复用前校验 `getDom() === 当前 ref && isConnected`，不符 dispose 重建）。
- **R8 构建验证与回归判定**：① 根目录 `npx vue-tsc --noEmit` 在 solution-style tsconfig 下是「空检查」（仅 references，直接退出不查文件）——门禁必须 `npm run build`（vue-tsc -b + vite build）；`] as any[]` 括号配对陷阱类型错误 vue-tsc -b 报 TS1005/TS1128，目录级 --noEmit 却静默放过。② 判断「是否我引入的回归」：grep 自己改的文件名，勿被既有 build 噪音误导，可疑时 `git stash` 对照。③ Windows 编辑文件偶发 `ReplaceFileW EIO(1175)`：等 2–8s 重试，勿原地反复重试、勿用 shell 重写中文文件（编码规则不变）。

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

## 2026-08-29 UI token 迁移（四批）新增教训

- **PowerShell `-File` 传数组参数会被外层 shell 吞**：`powershell -File x.ps1 -Paths @('a','b')` 经 cmd/Node 转手后数组丢失，脚本只收到首元素（表现为「只改了一个文件」）。修：改用 `powershell -Command "& '.\x.ps1' -Paths 'a','b' -Tag '1'"`，-Command 的字符串在子进程内按 PS 语法解析。识别信号：批量脚本报告修改数远小于预期。
- **CSS 自定义属性值保留换行空白**：`--font-sans` 多行书写时 `getComputedStyle().getPropertyValue` 返回含换行/缩进的声明值，e2e 字面断言（fonts.spec）必挂。修：token 文件里字体栈单行书写；凡被 JS 字面读取的自定义属性都不要折行。
- **e2e DB 种子重复行污染前缀匹配型断言**：legend-color 的 evaluate 按 `filename.startsWith('BPD60320_FT.')` 取 lot，种子被灌过两套同名行（08-25/08-27）→ 后端 4 个 lot vs UI 选 2 个文件，「柱系列数应等于文件数」4≠2 时挂时绿（取决于并行时序）。修：清理旧套重复行（seed_test_data --refresh 按文件名增量，不会重灌）；写前缀匹配型断言前先查 DB 有无同名重复行（R2 家族）。
- **批量正则删 CSS 夜块的四种副作用**（批 A 清理 `.theme-*` 覆盖时）：① 选择器列表尾逗号被留成悬空选择器（`SEL,` 后直接 `}`/`</style>`）；② 匹配从 HTML 注释内部的 `:root.theme-night` 文字开始→截断未闭合注释；③ 删 `.theme-*` 行时把选择器行的 `{` 一并带走；④ 补括号过度产生 `, {`。规则：批量 CSS 块删除后必跑括号平衡+悬空逗号体检脚本（见 tasks/_css_check.py 模式）+ build，勿只看 diff。
- **EP 主题 css 新增双主题通用规则与旧 night !important 块的博弈**：文件尾纯选择器规则（`.el-dialog{...}`）优先级低于 `:root[data-theme="night"] .el-dialog{...!important}`——只加通用段不改 night 块，night 下新规格全部不生效（双主题割裂）。修：通用段与旧 night !important 块**同步改为同 token 值**（如 --card-glass/--grad-brand）；night 块保留 !important 只作兼容兑底。
- **存量失败判定实例：electron.spec 的 `/login` 用例**：P1 项目带 admin storageState，已登录访问 `/login` 被路由守卫重定向到仪表板（DOM 快照可见已登录页面）→ `.login-container` 永不出现，与代码改动无关（同文件 `/#/login` 用例通过）。判据：error-context 的 DOM 快照 + 项目配置交叉验证，勿盲目修代码。
- **存量失败判定实例 ×2（组件改造收尾全量回归）**：① boxplot-bool-params / file-switch-param-reset 四例：spec 在 page.evaluate 里裸 `fetch('/api/v1/files/?search=…')` 不带 Authorization 头（JWT 在 localStorage、只有 axios 拦截器会加）→ 后端 401 → file_id 解析失败；WebServer 日志看 401 即定位。② large-data-qqplot 断言 `content-encoding === 'gzip'`：GZipMiddleware 已于 2026-08-11 移除（settings 注释明记勿全局恢复），断言陈旧。另：roadmap.spec 页面在旧提交 9b4418d 已删（/roadmap → 404）；判存量先看 git log -S 与后端日志，勿先怀疑本轮改动。
- **全量 e2e 中 vite dev server 中途崩溃**：并行负载下 webServer 死掉后大量用例报 `ERR_CONNECTION_REFUSED`（跨套件成片），全量汇总数字不可信——按 R2 分组隔离复跑（每轮新 webServer，workers≤2）再定论；纯 UI 套件（theme/data/sftp/exports）隔离后全绿即为环境性。

## 2026-08-29 e2e 端口被残留 runserver 进程树劫持（同一会话复现两次）

- **现象**：batch-phase e2e 报 `/api/v1/batch-dirs/import/` 404，但该端点在当前代码明确存在（直连探测命中路由返回 401）。
- **根因**：8000 端口被**非 Playwright 起的**残留 `manage.py runserver` 占着，`reuseExistingServer: !CI` 静默复用它（R3「复用旧代码进程 → e2e 结果无效」家族）；且 runserver 是 autoreload 父监视 + 子服务结构——只杀占端口的子进程，父进程立刻 respawn，端口「释放」后马上被占回。
- **修复/规则**：杀 runserver 必须**杀整棵进程树**——用 Win32_Process 沿 ParentProcessId 向上走到最顶层 runserver 祖先，整链一起杀，杀后验证无 `CommandLine like '%runserver%'` 的 python 残留再跑 e2e。识别信号：e2e 报「已知存在端点 404」→ 先查端口占用进程，勿先怀疑代码。PS 5.1 探测非 2xx 用 try/catch 读 `$_.Exception.Response`（无 `-SkipHttpErrorCheck`）。

## 2026-08-30 SFTP 目录下载进度卡 1%：SSE 事件粒度与字节基准

- **批量/目录下载进度不能按「整文件完成」发事件**：旧 `download_dir` 用阻塞式 `sftp.get()`，事件只在每个文件下完后发一次——大文件期间进度停在 0%/1%（观感卡死）。修法（与单文件 SSE 同构）：抽 `iter_remote_chunks`（256KB 分块，单文件/目录共用）+ 按「实际累计字节/远端总字节」发进度（0.1s 节流）+ **每文件至少一次补偿事件**（小文件 <0.1s 读完时补发最终值，保证文件计数与百分比前进）。
- **重构后 deadline 检查必须「先查再读」**：循环内先 `time.time() > deadline` 再 `next()`；若先读后查，最后一次 read 完成时（耗时 > 剩余时间）直接超时，**吞掉该文件的 progress 事件**（「至少一个 progress 事件」是既有契约，见 2026-08-28）。
- **`mock.patch.object(类, 方法)` 的 MagicMock 不做描述符绑定**：替换类方法后 `self.method(a,b,c)` **不会自动传 self**（patch 的是 MagicMock 实例而非函数）——side_effect 按实参个数写（5 参写 6 参必 500）。
- **生成器「已完成文件」与「半截文件」状态必须分离**：文件完整写入关闭后立即清 `current_partial` 引用，否则补偿事件 yield 点的 GeneratorExit 会把**已完成文件**当半截删掉（DB 行还在、磁盘文件没了）。
- **时间戳后缀要覆盖所有断言点**：单文件重名落盘 `big_<ts>.csv`，`icontains('big.csv')` 匹配不到 → 搜索词卸到无后缀前缀（`search=big`）+ 返回文件名 `^big` 过滤；排查此类失败先确认「UI 已导入提示是否出现」，区分「下载没成功」与「断言错了」。
- **serial 文件内前一用例失败 → 后续用例 did not run**：排障先看 error-context 定位真实失败点，再考虑串行跳过。
- 改动后尽快 commit/备份、双代理并发写共享 docs 的教训 → 见 R1。

## 2026-08-28 两仪表板重建设计→实施（P0–P4）：主题 token 化 / 五层 IA / 验证链

- vue-tsc 空检查、`] as any[]` 括号陷阱 → 见 R8。
- **e2e DB 残留会污染 files[0]**：其他套件遗留 `status='error'` 的 sample.csv 按 `-created_at` 排最前 → 仪表板自动选到坏文件、summary 返回 error、UPH 400 刷屏、dashboard 全部用例失败。修：DELETE 残留行或用例层面「选第一个 ready 文件」；项目根 db.sqlite3 是 e2e 库，可安全清理。（跨套件污染见 R2。）
- **/batch 路由已重定向到 /dashboard**（BatchReport 页下线）——batch.spec.ts 的批次报表断言属陈旧失败；admin.spec「已禁用」断言与实现脱节（UserManagement.vue 显示原始 is_active 值，从未渲染中文「已禁用」），是**基线既有失败**。全量回归前先跑 baseline 定位存量失败（见 R2）。
- 全量 parallel flake 模式（6 workers × SQLite）：个别套件全量失败、隔离复跑全绿——按 R2 判定；Windows ReplaceFileW EIO(1175) 见 R8。
- 主题治理：页面级全局 night 覆盖是根因 → 组件只认 token（scoped `var(--xxx)`）→ 删除全局块；图表色板统一 `useChartTheme()` semantic（pass/fail/warn/limit/sigma/kde/cpk/failBar）；双主题选择器统一 `:root[data-theme="night"]`；light 下 EP 主色是出厂 #409eff 而非品牌 #2563eb → 补对称 light 块（详见 R7）。
- **`<script setup>` 里 export interface 在本项目 Vue 3.5 是允许的**，不必为此改写。
- el-tabs 隐藏 pane 也在 DOM：两个 tab 的 `.context-bar` 同时存在 → 用 `.context-bar:visible` 或 `.first()`；el-drawer 关闭按钮是 `.el-drawer__close-btn`（无文字），断言关闭别按 hasText('关闭')。

## 2026-07-02 视图测试中 monkey-patch 必须 patch 实际消费模块

- `apps/analysis/views/__init__.py` re-export `_load_df_from_request`，但 `analysis_views.py`/`statistics_views.py` 内部 `from ._helpers import ...` 各自绑定 → 只 patch 包名不生效，视图仍查 DataFile，`SimpleTestCase` 抛 `DatabaseOperationForbidden`。
- 修：分别 patch 两个消费模块内的名字，`self.addCleanup(restore)` 还原。规则见 R6。

## 2026-07-02 后端异常值检测必须考虑 RDL 规格限

- `detect_outliers_iqr` 纯 IQR 会把 RDL（规格限）范围内的合法数据标为异常。修：加 `spec_limits: tuple = None` 可选参数（默认 None 向后兼容），边界扩到 `min(lower_bound, spec_lower)` / `max(upper_bound, spec_upper)`；**5 个调用点全更新**（histogram / serial_distribution / correlation / computations-QQ graph 等），grep 找调用点。
- Rule: 统计方法检测的「异常」在业务上下文（规格限）中可能是合法数据；改核心函数必须更新所有调用点。

## 2026-07-01 RDL 模式下异常值裁剪应以 Limit 线为硬边界（前端）

- `HistogramChart.vue` RDL 模式用 IQR 边界裁剪，把原始 LSL/USL 线内部的 bin 隐藏。修：`rangeType === 'RDL'` 时 clipMin/clipMax 扩展到 `lower_limit/upper_limit`，Limit 线内 bin 始终保留；其他 rangeType 保持纯 IQR。
- Rule: 裁剪/异常值可视化必须结合当前 `rangeType` 的语义，不能一刀切同一套边界；e2e 断言依赖控件状态（如 RDL 模式）时，显式把被测对象设到目标状态，勿依赖 store 默认值。

## 2026-06-30 E2E 选择器必须与实际 DOM class 一致

- `SingleParamTab.vue` 根元素实际 class 是 `analysis-tab-layout`，测试凭组件名臆测 `.single-param-tab` 导致元素找不到。修：组件根显式加 `class="single-param-tab"`（Vue fallthrough 自动合并到根 div）。
- Rule: 写选择器前先用 trace 确认目标 class 真实存在于 DOM；多个测试文件共享的根选择器常量必须真实存在；定位 class 加在组件根（见 R2）。

## 2026-06-13 pd.to_numeric(bool) 不转 dtype + abs('str') 崩（compute_boxplot_stats 容错）

- bool 列：`pd.to_numeric(errors='coerce')` **不改 dtype** → quantile 返 `np.bool_` → `q3 - q1` 抛 "boolean subtract not supported"；str 列：`apply(lambda x: abs(x) < inf)` 直接崩 "bad operand type for abs(): 'str'"。
- 触发面：boxplot 视图 `_sanitize_numeric_params` 用 `is_numeric_dtype`（bool 返回 True）→ 直连 API `?params=Dut_Pass` 即崩（histogram 有 dtype 严格过滤所以 UI 选不到——但不构成「不用管」的理由，见 R3）。扫描工具显示 98 个 bp_issues（72 boolean / 26 string）跨 11 个 sample 文件。
- 修：入口 `pd.to_numeric(data, errors='coerce').astype(float)` + `dropna()` + `np.isfinite()` 向量化（规则见 R4）。

## 2026-06-13 Pinia store 持久化导致 stale selectedParam 跨文件泄漏

- 用户旧文件选的 param 持久化；切文件后三个分析端点同根因报 400/400/500（histogram 无守卫 500、qqplot/boxplot 400）——**同根因三种状态码**，诊断时勿把 400 误判为「qqplot 自己的 bug」而漏掉 stale param 主线。
- 修（双层防御，见 R5）：① `AnalysisPage.onFileChange` 入口先 `params=[] / selectedParam='' / store.selectedParam=''` 再异步加载（用第一个自动选中）；② `SingleParamTab` 加 watch(fileId) 清 local（防父组件传参竞态）；③ 后端循环前 `valid_params = [p for p in params if p in df.columns]`，空集返 400 `{error:'no_valid_params', detail, requested, missing}` 而非 500。
- 陷阱：子组件 watch 只清 `localSelectedParam` 不够——父组件 v-model 绑的 ref 仍带旧值，必须从源头清；mock DataFile 缺 `format_type` 字段 → 测试 AttributeError（见 R6）。

## 2026-06-10 联想输入：el-select + filterable 而非 el-autocomplete

- 需求是「输入+下拉选择」：`el-select` 加 `filterable` 同时支持过滤与下拉（配 `filter-method` 前缀优先 + option 模板高亮）；`el-autocomplete` 只有联想、丢失下拉选择，用户反馈「不能下拉 select 了」。
- 标签联想：原生 `<input>` + 自定义建议列表（调 listTags(prefix)，debounce 200ms，↑↓/Enter/Escape 键盘导航）；建议项用 **`@mousedown.prevent` 而非 `@click`**（否则 blur 先触发导致输入框关闭、点击无效）。

## 2026-06-08 quest.txt 四问题

- **图表空白根因 = 裸调 `echarts.init` 而非 `initEchartsWhenReady`**：数据到达后 nextTick 时容器高度未定（clientHeight=0）→ "Can't get DOM width or height" + 空白，布局撑开后不重绘。修：迁移到既有 `utils/echarts-init.ts`（ResizeObserver+rAF 轮询）。项目已有零尺寸保护工具时**禁止**裸调 `echarts.init`，grep 找漏网（见 R7）。
- **「SFTP 下载新批次后旧批次消失」是前端分页表现 bug，非数据丢失**：batchGroups 从分页 20 条分组，新文件占满首页就把旧批次挤出。修：用 `/batch-dirs/` 作分组源（并扩展返回每批 files[]），与分页解耦。Rule: 「列表项消失」先分清「数据没了」还是「分页/过滤没取到」——查后端 DB 实证再动手。
- v-show 多 tab 同 DOM → `.content-section:visible` 限定（见 R2）；EP 2.14 el-select 可见性判 `.el-select__wrapper`、占位/选中值都渲染在 `.el-select__placeholder`（`.el-select__selected-item` 会同时命中 input-wrapper+placeholder，strict 违例）。
- `vue-tsc --noEmit` vs `-b` 严格度不同（见 R8）。

## 2026-06-07 JWT 自动续签：401 拦截器 + 共享 refresh 队列

- 背景：历史拦截器对任意 401 都 `removeItem + location.href='/login'`；access 30min 过期、refresh 7 天有效但前端从未调过 `/auth/refresh/` → 用户「18:52 还在用、18:53 直接 401 被踢」。后端已配 `ROTATE_REFRESH_TOKENS=True`+`BLACKLIST_AFTER_ROTATION=True`。
- 修：拦截器 401 → 共享 in-flight `refreshPromise`（模块级，finally 清空）→ 成功重写 Authorization 重试原请求；refresh 自身 401 短路 forceLogout。
- **7 个关键陷阱**：① `token_blacklist` 必须加进 INSTALLED_APPS 并 migrate——否则 `refresh.blacklist()` AttributeError 被 `try/except: pass` 静默吞掉，**刷新成功但老 refresh 永不吊销**（诊断：`showmigrations token_blacklist`；验证：同一 refresh 连续刷两次，第二次必须 401）。② refresh 请求不能走共享 api 实例（又被同一拦截器捕获）→ 裸 `axios.post(baseURL + '/auth/refresh/')`。③ 循环 import 下顶层 `api.defaults.baseURL` 是 undefined → 用 `getBaseURL()` 函数调用时再读。④ 并发 401（仪表板首屏 5+ 请求）必须 await 同一个 refreshPromise——ROTATE 下每次刷新旧 refresh 失效，并发各自刷新会把 token 链断成多段。⑤ refresh 自身 401 不许再触发刷新（`url.includes('/auth/')` 直接 forceLogout）。⑥ `_retry` 标志挂 axios config；重试走完整请求管线，headers 必须重写 `Authorization: 'Bearer <new>'`。⑦ forceLogout 不能走 `store.logout()`（它发的 logout 请求又过拦截器）→ 直接 removeItem×2 + location.href；已在 /login 时跳过（别覆盖用户已填表单）。
- e2e 设计（等不了 30min）：后端单元测 7 用例（双 token 返回/旋转/黑名单/garbage 401/空 body 400/不要求 auth）+ 浏览器内调 `/auth/refresh/` + 手动 `setItem('access_token','invalid.token.value')` 模拟「access 失效但 refresh 有效」，断言没跳 /login 且 access_token 已被替换。

## 2026-06-07 登录错误码设计：`{code, detail, ...}` 统一信封

- 原 LoginView 失败只回一种 detail，且 **`is_active=False` 根本没被检查**（`authenticate()` 不查 is_active，被禁用用户只要密码对就能登录——后端 bug）。
- 5 码：400 `missing_credentials` / 401 `user_not_found` / 401 `invalid_credentials(remaining_attempts)` / 403 `account_disabled` / 423 `account_locked(retry_after_minutes, locked_until)`。
- 设计要点：**DISABLED 优先于 LOCKED**（可操作性排序——能立刻找管理员修的优先提示，不能让人干等 15 分钟）；内网 ATE 工具**不隐藏「用户名不存在」**（UX > 字典攻击防护，攻击者本就在内网）；新增 is_active 校验是后端 bug 修复。
- 前端 `parseLoginError` 分 4 层：`ECONNABORTED` 超时 / `!response` 网络断开 / `>=500` 5xx / `response.data.code` 业务 / 兜底 unknown；CSS 按**类目**上色（网络·琥珀 / 账号·深红 / 5xx·暗橙），不按 HTTP status。
- Rule: 错误响应必须结构化 `{code,...}`（前端 i18n/监控靠 code）；`serializer.is_valid()` 默认只返布尔，要自定义 400 code 需自己判 `validated_data`（或 `raise_exception=True`，见 R3）。

## 2026-06-07 DRF ModelViewSet.update() 硬编码 partial=False

- 前端「只带一个字段的 PUT」（`{is_active:false}`）→ 400。根因：`UpdateModelMixin.update()` 内部硬编码 `partial=False`（`viewsets.ModelViewSet.update()` 没传 partial；在 `get_serializer()` 里 `setdefault('partial',True)` **无效**，被 mixin 覆写）。
- 修：覆写 `update()` 中 `kwargs['partial'] = True` 再 `super().update(...)`。
- 陷阱：partial=True **不跳过** UniqueValidator/RegexValidator/`validate_<field>()`（字段级校验与 partial 无关）；PATCH 路由默认 partial；强制 partial 不影响「PUT 全字段」（验证器接受全字段+忽略多余）；前端错误展示要能透出 `{field: [msgs]}`（formatError 参考 UserManagement.vue:188-208）。
- Rule: 管理类 ViewSet + 前端单字段 PUT/PATCH → 强制 partial=True；`serializer.save(owner=...)` 的 `create(self, validated_data, **kwargs)` 必须 **`**kwargs` 透传**（与 partial 机制独立，两套都别漏）；测试覆盖 4 形态（见 R6）。

## 2026-06-07 useChart v-if 容器重建后旧 ECharts 实例失效 → 图表空白

- QQPlotChart 的 `<div ref>` 用 v-else 条件渲染：`loadQQPlot` 先把 qqResult=null 销毁 div，数据回来 Vue **重建新 div**；`chartInstance` 仍绑在已脱离 DOM 的旧节点 → setOption 渲到 detached node，新 div 永远空白（histogram 不复现因其容器从不被置 null）。诊断弯路：先盯后端状态码，但 APIClient 逐 param 全 200——**必须真实浏览器复现+截图看渲染**。
- 修：`ensureInit()` 复用前校验 `chartInstance.getDom() === chartRef.value && isConnected`，不符则 dispose 并在当前容器重建（容器不切换时 no-op）。
- 次因（后端）：`histogram` 视图循环 `df[param]` 无守卫 → KeyError 500（qqplot 有守卫）→ 修 `if param not in df.columns: continue`（守卫对齐见 R3）。

## 2026-06-07 Vue 子组件直接修改 props 对象 — el-table 不重渲染

- `row.tags = data.tags` 直接改 props 内部对象属性：Vue 3 的 ref 追踪的是 `.value` 数组的**引用替换**，不是数组元素对象属性修改 → 父组件 files 数组引用没变 → 新 tag 不出现在 DOM。
- 修：子组件 emit('tags-updated', row)，父组件 `files.value = files.value.map(f => f.id === updated.id ? {...f, tags:[...updated.tags]} : f)` 整体替换；子组件保留本地赋值以同步引用，但**真正重渲染靠父组件赋值**。
- Rule: 「子组件改 row 后要立刻在表格里看到」必须 emit + 父组件整体替换引用；排查先 `console.log(files.value === oldFiles.value)` 看父组件引用是否真被替换。

## 2026-06-07 el-table inline input 立即 blur 误清空编辑状态

- 点「添加」后 `<input v-if>` 出现 → el-table 内部布局 reflow 触发 `blur`，同步 commit 时 `newTagValue` 还是空串 → `editingId` 被清空、input 消失，后续 `fill()` 找不到元素（console 显示 `commitNewTag {tag:'', editingId:null}`）。
- 修：blur 延迟 150ms，先校验 `editingId.value === row.id`（Enter 已先 commit 则直接 return），再决定 commit 或清空。
- Rule: 任何「立即出现的 input/popover」的 @blur 触发时间不可预测（reflow/autofocus 失败/行高变化都可能），必须延迟 + 检查 ownership 再 commit；排查先看 blur 函数第一行 editingId 是否为 null。

## 2026-06-07 Playwright waitForResponse 异步注册竞态

- `fill(tagName)` **之后**才 `waitForResponse(/set_tags/)`：某些 timing 下 fill→keyup.enter 已把请求发出，listener 注册太晚永远等不到 → 10s TimeoutError（console 证明请求确实成功返回）。
- 修：e2e 不单独等网络层，改 DOM 断言（`el-tag` toHaveCount）；确需 waitForResponse 时用 `Promise.all([waitForResponse, action])` 先注册（见 R2）。

## 2026-06-07 el-table type="expand" 必须配 row-key

- 存在 `type="expand"` 列时 el-table **强制要求** `row-key` prop，否则 mount/setup 抛 `[ElTable] prop row-key is required`（被 wrapped 在 unhandled watcher 回调后，看不到根因）；`expand-row-keys` 配了也救不了。
- Rule: 加 expand 列**第一步**就同步加 `:row-key="(row) => row.id"`。

## 2026-06-07 用户目录 id→username 重构：「声称完成但未落盘」+ 迁移安全

- 前一会话记录「已完成」；`git log --all -- apps/datafiles/views.py` 无相关 commit、磁盘代码仍是 `_user_upload_dir(user_id)`（4 个 sftp 调用 + 5 个 datafiles 调用全传 `request.user.id`）；且出现 `media/data/1/single/`（老）与 `media/data/admin/batch/`（新）并存——**目录状态分裂是回归信号**。
- 修：`_user_upload_dir(user, file_type)` 用 `str(user.username)`，9 处 caller 全改；新增 `migrate_user_paths` 命令（`--dry-run` + 文件级合并 `_merge_tree` move 同名跳过 + DB 正则改写 `[/\\]data[/\\]\d+[/\\](?:single|batch)[/\\]`）。
- Rule: 「声称完成」必须 git 验证磁盘（见 R1）；helper 改名后 `Grep -n "_user_upload_dir("` 改前/改后各跑一次确认 0 旧调用；数据迁移命令必须 `--dry-run` + **文件级合并**分支（整目录 rename 在目标已存在部分内容时撞名）。

## 2026-06-07 extract_product_code：CSV 程序名兜底 + 全 token 捕获

- 演进（两轮迭代最终形态）：文件名正则 `^B[A-Z]{1,2}\d+` 对 `DA35_BPC50338_...`/`BN281R3CYCAA_...` 误判或截断 → 改用 CSV 测试程序名（.pts/.pgs/.pds 的 basename）→ 但直接返回 basename 又测试阶段/硬件后缀当产品码（`BPC50338XBAC_EN`、`JAVBN281R3CYCAAV1.6` 污染）→ **最终**：数据文件名优先（正则 `^(B[A-Z]{1,2}\d+[A-Z0-9]*)` 整段 B 前缀 token 全捕获），CSV 程序名兜底，**两个 source 走同一个 `_match_product_code()`**（兜底也按 `_` 切分取首个 B token）。
- Rule: 高维分类键（product_code）绝不能直接返回原始字段 basename——canonical id 必须「最少字符、最大识别度」；两阶段提取时 fallback 不能用更宽松规则（一开 fallback 就回老 bug）；改后必须跑 `backfill_product_code`（`--dry-run`）刷历史行；migration 中历史调用签名必须向后兼容（`extract_product_code(df.filename)` 单参形式仍工作）。

## 2026-06-07 SFTP 会话缓存：共享 Redis + Fernet 加密

- `connect` 用 Django LocMemCache（per-process）存凭据 1h，多 gunicorn worker 不共享且密码明文 → 新 `apps/sftp/cache.py`：`redis.Redis.from_url` + Fernet；key 命名空间 `sftp:conn:<user_id>`；URL 解析顺序 `SFTP_SESSION_REDIS_URL → REDIS_URL → CELERY_BROKER_URL`（勿硬编码）；connect 成功即使写缓存失败也只 warn 不阻断；解密失败自动 drop 旧值（防 stale key 反复抛）。
- Rule: 任何「多 worker 共享 + 敏感信息」缓存必须 ① 共享 Redis（非 LocMem）② Fernet 加密 ③ 解密失败主动清旧 key；缓存写入失败不阻断主流程（主业务成功即可用）。

## 2026-06-07 生产 SECRET_KEY / SFTP_CONFIG_KEY 环境变量守卫

- 默认 `django-insecure-` 密钥写死提交仓库；生产忘设环境变量即用默认密钥，任何人都能伪造 session。修：base.py 从 env 读 `SECRET_KEY`/`DJANGO_DEBUG`/`DJANGO_ALLOWED_HOSTS`/`SFTP_CONFIG_KEY`/`SFTP_SESSION_TTL`/`SFTP_SESSION_REDIS_URL`/`REDIS_URL`；非 DEBUG 且 `SECRET_KEY == _DEFAULT or 'django-insecure' in SECRET_KEY` 抛 `ImproperlyConfigured` 启动失败（**双条件**，防 `django-insecure-...override` 字符串绕过）；`SFTP_CONFIG_KEY` 未设用 `warnings.warn`（PBKDF2 从 SECRET_KEY 派生，功能等价）。
- Rule: production 缺「强烈推荐但非必须」安全项用 warn 不用 raise——强制中断会让人注释掉，warn 至少在 CI 日志可见。

## 早期条目（2026-06-07 前，未标注日期）

### SFTP：每次请求重建连接导致点击卡顿

- `SftpViewSet._get_connection` 每请求新建 paramiko.Transport 完整 SSH 握手（300–500ms）用完即 close → 每次点目录都重付握手延迟。修：`apps/sftp/pool.py` 进程内连接池按 user_id 复用；复用前校验 `is_active()` + 空闲 TTL（默认 300s），死/旧则用缓存凭据重建；操作失败 `pool.invalidate` 丢弃坏连接；`disconnect` 调 `pool.close`。
- Rule: gunicorn **sync** worker（无 `-k`）单进程串行 → 池无需加锁；若改 gthread/gevent 必须补 per-user 锁（paramiko 非线程安全，pool.py docstring 已注明）；SSE generator 正常结束**不关连接**（留池复用），仅 GeneratorExit/异常时 invalidate；改连接获取签名后清理不再使用的 import。

### 后端重构：views.py 按职责拆分

- analysis 1383 / gage 638 / buyoff 482 / export 525 行，一个文件混请求解析+业务逻辑+Excel 布局。修：薄 View（请求解析+响应组装）+ Service（纯业务）+ Layout Builder（Excel/PPTX 构建），views.py 平均值 757→288 行（-62%）。
- Rule: views.py >300 行即检查是否混入非 HTTP 层业务/格式化代码，按「View → Service → Builder」三层分离；导出类功能用 excelize 库，**勿回退 openpyxl**；提取函数时验证 return dict key 完全匹配（stat key 长列表易漏）。

### Excel 导出：DataFrame 索引与 enumerate 不匹配

- `detect_fail_data()` 返回原始 DataFrame 索引（如 {5,12,30}），写入循环用 `enumerate` 生成 0,1,2…——经 site/passfail 过滤后索引不连续 → `r_idx in fail_set` 永远 False，全部标红失效。修：过滤后 `export_df.reset_index(drop=True)`。
- Rule: 对 DataFrame 做行过滤后必须重置索引才能用 enumerate 访问。

### Excel 导出：空字符串过滤器清空数据（只有列名没有数据）

- 前端 `passfail`/`siteFilter` 默认 `''`（未选择），后端 `if site_filter != '全部'` → `'' != '全部'` 为 True → 按 `site == ''` 过滤 → 0 行 → 导出只剩表头。修：`if site_filter and site_filter != '全部'`，passfail 的 else 改显式 `elif passfail == 'Pass'`（防空串落入 Pass 分支）。
- Rule: 哨兵值判断先做真值守卫（见 R3）；导出/过滤类 bug 必须读回产物（openpyxl 读 xlsx）断言真实行数，不能只看函数返回非空 bytes。

### UPH 端点：前端已建、后端缺失（404）

- `GET/POST /api/v1/analysis/uph/` 404：前端 UphCard+`analysisApi.getUph` 已存在并约定响应结构，后端无 `uph` action、无 `compute_uph`——**全新特性**（非缺端点）。修：按前端 interface 字段反推后端结构逐字段实现（`UPH = 3600 × site_count / avg_test_time_sec`）。
- 数据细节：各格式测试时间列名不同——CTA8290D=`Test_Time`(秒)、ETS88=`Test Time`(ms)、STS8200=`T_TIME`(ms)，必须按 `metadata['units']` 判断 ms→÷1000 归一；ETS88 的 Site 列混入日期字符串 → `pd.to_numeric(...).dropna()`。
- Rule: 涉及多格式的统计必须用真实文件逐格式验证数值合理性（FT ~1600 / ETS ~728 / CP ~25673 UPH）+ `APIRequestFactory + force_authenticate` 全链路 200（见 R6），不能只验证 URL 能 resolve。

### Buyoff：角色分配未传到后端

- 前端有 FT/QA1/QA2 角色 UI，但 `generateForm` 只发 `file_ids` 数组，后端按数组顺序分配角色——用户跳过某角色时映射错乱。修：前端发 `role_map` 字典（`{"FT": 123, "QA1": 456}`）后端优先使用。（见 R3。）

### Sigma Limit：缺少旧版配色

- 新端点只输出纯文本数据，缺旧版蓝色背景（Limit）+ 红色/黄色（Sigma 对比）条件填充。修：补条件填充逻辑。
- Rule: 移植功能要同步视觉细节，不能只移植数据逻辑。

### E2E / Playwright 框架经验（L1–L5）

- **L1** `getByRole('link', {name})` 同时命中侧边栏与 Topbar 面包屑（strict-mode 报错）→ 侧边栏断言限定 `page.locator('aside.sidebar')`（已封装 `sidebarLink()`）。
- **L2** storageState 只恢复 token、不恢复身份：App.vue 启动不调 `/auth/profile/`，`user` 仅 login() 时写内存 → 注入 token 过路由守卫但 `isAdmin=false`、Topbar 用户名空。规则：角色相关用例清空 storageState 后用 `loginAs()` 实时登录，同会话不刷新。
- **L3** 全局 401 拦截器吞登录错误：错误密码登录会整页跳转，LoginPage 内联 `error-msg` 来不及渲染 → 断言「停留 /login + token 为空」。
- **L4** 后端依赖缺失阻断 webServer：`apps/export/export_ppt.py` 顶层 `import matplotlib` 缺失则 Django 无法启动 → 跑 e2e 前确保 .venv 装好 requirements/base.txt。
- **L5** 登录按钮渲染「登 录」（文案含空格）→ 用 `button.neon-button` 比文本匹配稳。

### 性能审计：Django 后端优化模式

- 缓存已在位（`get_cached_parsed_file` lru_cache，所有 views 已用）——审计先确认已有模式，勿假设缺失。
- DataBrowserView 分页：优化前 `df.to_dict(orient='records')` 全行 → Python 过滤 → 切片；改为 pandas 级过滤 → `df.iloc[start:end]` 切片 → 仅分页行 to_dict()，O(N)→O(page_size)。
- `parser.get_bin_column_name()` 引用未定义 parser → 方法内显式 `parser = get_parser(datafile.format_type)`；ViewSet 中间名 `@action` 方法后者覆盖前者（~400 行死代码）→ `grep "^def " | sort | uniq -d` 快速定位；clean_data 递归把 NaN 换 0.0 会掩盖数据问题 → 源头 pandas `.replace({np.nan: None})`（JSON null 让前端感知缺失）。

### QQ 图 null r_squared 引发 Vue 渲染错误（SW_Bin 常量列）

- `SW_Bin` 全列同值（1.0）→ `scipy.stats.probplot` 相关系数 NaN → DRF 序列化 JSON 变 `null` → 前端 `null.toFixed(4)` 抛 TypeError；同时 Vue 报 `Cannot read properties of null (reading "emitsOptions")`——那是**同一实例多代理事件同步入队后二次代理雪崩**的广义 patch failure 信号，不是独立 bug。
- Rule: 数值渲染前 `Number.isFinite()` 护、interface 写 `number | null`（见 R4）；回归测试套件须含至少一个「全同值/NaN/离散」用例；instrumentation 里引用 props 的 computed/watch 必须放在 `defineProps` **之后**定义。

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
  home data_dir → `/batch-dirs/import/` 404「目录不存在」，盘上目录确实存在却对不上）；
  用 Playwright webServer（config 显式传 LQDP_SYSTEM_CONFIG_FILE）最稳。
  另：残留 runserver 进程树占 8000 会让 webServer 120s 超时——跑前查 Listen 端口 `taskkill /PID x /F /T`。
- **el-table 宽屏撑满**：全固定 width 列在超宽屏右侧留白；文本/时间列用 min-width 让余量弹性分配，
  树形表避免单一 min-width 列（phase）独吞余量。

## 2026-08-30 反馈轮 3：图表「经常消失」根因补漏

- **initEchartsWhenReady 超时不能断 ResizeObserver**：原实现 5s 超时连 RO 一起 disconnect——
  容器 5s 内没尺寸（隐藏 Tab/折叠卡）则 init 永久放弃，之后容器可见也没人重试→图表永久空白。
  修：超时只停 rAF/轮询，RO 保留到 handle.dispose()，容器后拿尺寸时 onReady 自愈 init。
- **v-if 图表容器重建必须 dispose 旧实例**：`v-if="data.length"` 空态↔数据切换会重建 div，
  旧 ECharts 实例绑定已摘除的旧 DOM，`setOption` 渲染进 detached 节点→新容器空白
  （表象：卡头 pills 有数、图区空）。修：render 内记录容器元素身份，身份变化先 dispose 再 init。
  通则：任何 v-if/v-for 包裹的图表容器都要在 render 路径做元素身份守卫。

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
