# Lessons Archive（lessons.md 旧区归档）

> 本文件由 `docs/tasks/lessons.md` 于 2026-09-08 拆出，收录 ≤2026-07-02 的 21 个日期段，**内容原样未改**；
> 回查方式：按日期标题或关键词 grep 本文件。新教训仍追加 lessons.md，不写这里。

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
