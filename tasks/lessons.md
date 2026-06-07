# Lessons Learned

## 后端重构 — views.py 按职责拆分

- **问题**: analysis/views.py 1383 行，gage/views.py 638 行，buyoff/views.py 482 行，export/views.py 525 行。一个文件混了请求解析、业务逻辑、Excel 布局三种职责。
- **方案**: 薄 View（请求解析+响应组装）+ Service（纯业务逻辑）+ Layout Builder（Excel/PPTX 构建）。平均 views.py 从 757→288 行（-62%）。
- **模式参考**: `apps/accounts/views.py`（178 行，clean DRF）+ `apps/datafiles/services.py`（服务层模式）+ `apps/export/excelize_helpers.py`（共享样式）。已有良好模式先例。
- **Rule**: views.py 超过 300 行时，应检查是否混入了非 HTTP 层的业务逻辑或格式化代码，按"View → Service → Builder"三层分离。
- **Rule**: 导出类功能使用 excelize 库（Go 绑定），不要回退到 openpyxl。
- **Rule**: 提取函数时要验证 return dict key 完全匹配，特别是 stat key 这种长列表。

## Excel 导出 — DataFrame 索引与 enumerate 不匹配

- **Bug**: `to_excel` 中 `detect_fail_data()` 返回原始 DataFrame 索引（如 `{5, 12, 30}`），但写入 Excel 的循环用 `enumerate` 生成 `0,1,2,...` 连续索引。经过 site/passfail 过滤后，DataFrame 索引不连续，导致 `r_idx in fail_set` 永远为 False，所有标红失效。
- **Fix**: 在 `detect_fail_data()` 前调用 `export_df.reset_index(drop=True)` 保证索引连续。
- **Rule**: 任何时候对 DataFrame 做行过滤（site、passfail），之后需要重置索引才能用 `enumerate` 访问。

## Excel 导出 — 空字符串过滤器清空数据（"只有列名没有数据"）

- **Bug**: 前端 `DataBrowser.vue` 的 `passfail`/`siteFilter` 默认值是空字符串 `''`（未选择），但后端 `to_excel` 的判断是 `if site_filter != '全部':`。`'' != '全部'` 为 True，于是按 `site == ''` 过滤 → 没有任何行匹配 → `export_df` 变 0 行 → 导出只有表头、无数据。`export_to_xlsx_optimized` 本身完全正常。
- **复现/验证**: `test/test_excel_highlight_export.py` 直接调用导出函数读回 xlsx 校验行数；复刻 view 过滤逻辑证明 `site_filter=''` → 0 行，`'全部'` → 2301 行。
- **Fix**: 守卫真值——`if site_filter and site_filter != '全部':`、`if passfail and passfail != '全部':`，并把 passfail 的 `else` 改成显式 `elif passfail == 'Pass':`，避免空串落入 Pass 分支。
- **Rule**: 后端 `request.data.get(k, default)` 的 default 只在键缺失时生效；前端若显式发送空串，default 不会触发。哨兵值判断必须先做真值守卫（`if v and v != SENTINEL`），不能假设"非哨兵=有效过滤"。
- **Rule**: 导出/过滤类 bug 必须读回产物（openpyxl 读 xlsx）断言真实行数，不能只看函数返回非空 bytes。

## UPH 端点 — 前端已建、后端缺失（404）

- **Bug**: `GET/POST /api/v1/analysis/uph/` 返回 404。前端 `UphCard.vue` + `analysisApi.getUph` 已存在并约定了响应结构，但 `AnalysisViewSet` 没有 `uph` action，`statistics.py` 也没有 `compute_uph`。旧项目无此功能（全新特性）。
- **Fix**: 在 `statistics.py` 实现 `compute_uph`（并行站点吞吐模型：`UPH = 3600 × site_count / avg_test_time_sec`），在 `AnalysisViewSet` 加 `uph` action。
- **关键数据细节**: 各格式测试时间列名不同——CTA8290D=`Test_Time`(秒)、ETS88=`Test Time`(ms)、STS8200=`T_TIME`(ms)。必须按 `metadata['units']` 判断 `ms`→÷1000 归一到秒。ETS88 的 Site 列混入日期字符串，需 `pd.to_numeric(...).dropna()` 过滤。
- **Rule**: 前端有 API 调用 + 类型接口但后端 404 时，先确认是"缺端点"还是"缺整个功能"。缺功能要按前端 interface 字段反推后端响应结构，逐字段实现。
- **Rule**: 涉及多格式的统计计算，必须用真实文件逐格式验证数值合理性（FT ~1600/ETS ~728/CP ~25673 UPH），并跑一次 `APIRequestFactory + force_authenticate` 的全链路 200 校验，不能只验证 URL 能 resolve。

## Buyoff — 角色分配未传到后端

- **Bug**: 前端有 FT/QA1/QA2 角色选择 UI，但 `generateForm` 只发了 `file_ids` 数组。后端按数组顺序分配角色，若用户跳过一个角色（如只选 QA1、QA2），角色映射错乱。
- **Fix**: 前端发送 `role_map` 字典（`{"FT": 123, "QA1": 456}`），后端优先使用。
- **Rule**: 前后端接口要传递完整语义，不能依赖隐式顺序。

## Sigma Limit — 缺少旧版配色

- **Bug**: 新端点只输出纯文本数据，缺少旧版的蓝色背景（原 Limit）、红色/黄色（Sigma 对比）配色。
- **Fix**: 补上条件填充逻辑。
- **Rule**: 移植功能时要同步视觉细节，不能只移植数据逻辑。

## E2E / Playwright 测试框架

- **L1 选择器作用域冲突**: `getByRole('link', { name })` 会同时命中侧边栏菜单与 Topbar 面包屑（strict-mode 报错）。规则：侧边栏断言一律限定 `page.locator('aside.sidebar')`，已封装 `sidebarLink()`。
- **L2 storageState 只恢复 token、不恢复身份**: `App.vue` 仅 `<router-view>`，启动不调 `/auth/profile/`，`user` 仅 `login()` 时写内存。注入 token 能过路由守卫但 `isAdmin=false`、Topbar 用户名空。规则：角色相关用例清空 storageState 后用 `loginAs()` 实时登录，同会话内不刷新。
- **L3 全局 401 拦截器吞登录错误**: `api/index.ts` 对任意 401 都 `window.location.href='/login'`，错误密码登录会整页跳转，`LoginPage` 内联 `error-msg` 来不及渲染。规则：错误密码用例断言“停留 /login + token 为空”。
- **L4 后端依赖缺失阻断 webServer**: `apps/export/export_ppt.py` 顶层 `import matplotlib`，缺失则 Django 无法启动。规则：跑 E2E 前确保 `.venv` 装好 `requirements/base.txt`。
- **L5 登录按钮文案含空格**: `LoginPage.vue` 渲染「登 录」。用 `button.neon-button` 比文本匹配更稳。

## 性能审计 — Django 后端优化模式

- **缓存已在位**: `apps/datafiles/services.py` 已有 `@lru_cache(maxsize=64)` 的 `get_cached_parsed_file`，所有 views 已使用。审计时需先检查缓存是否存在，不必假设缺失。
- **DataBrowserView 分页优化**: 之前模式是 `df.to_dict(orient='records')` 转全部行 → Python 过滤 → 切片。优化为：pandas 级别过滤 → `df.iloc[start:end]` 切片 → 仅对分页行 `to_dict()`。大文件从 O(N) 降为 O(page_size)。
- **DataBrowserView bug**: `parser.get_bin_column_name()` 引用了未定义的 `parser`。修复：在方法内 `parser = get_parser(datafile.format_type)` 显式实例化。
- **废弃代码模式**: 同名的 `@action` 方法在 ViewSet 中，后面的定义会覆盖前面的。Python 类方法覆盖规则导致 ~400 行死代码。grep `"^def " | sort | uniq -d` 快速定位。
- **clean_data NaN 处理**: 递归遍历响应树把所有 NaN 替换为 0.0 会掩盖数据问题。改为 `return None`（JSON null），让前端感知缺失值。但更优方案是在 pandas 源头做 `.replace({np.nan: None})`。
- **Rule**: DRF `request.data` vs `request.query_params` — `request.data` 只在 POST/PUT/PATCH body 中有值。端点为 GET 时所有参数必须用 `request.query_params.get()` 或 `.getlist()`（Django QueryDict 支持重复 key 传列表）。

## SFTP 会话缓存 — 共享 Redis + 加密（2026-06-07）

- **问题**: `connect` 用 Django 默认 LocMemCache（per-process）存 SFTP 凭据 1 小时 — 多 gunicorn worker 间不共享，且密码是明文。换成共享 Redis 仍会落明文。
- **方案**: 新建 [apps/sftp/cache.py](file:///c:/Users/Administrator/Desktop/DataPrase/DataPhrase_Django/apps/sftp/cache.py) 封装 `redis.Redis.from_url` + Fernet 加密。Key 命名空间 `sftp:conn:<user_id>`，TTL 通过 `settings.SFTP_SESSION_TTL`（默认 3600）。URL 解析顺序：`SFTP_SESSION_REDIS_URL` → `REDIS_URL` → `CELERY_BROKER_URL`，避免硬编码。connect 成功后即使写缓存失败也不影响连接（只 warn）。解密失败时自动 drop 旧值，避免老 key 卡死后续请求。
- **Rule**: 任何「多 worker 共享 + 含敏感信息」的缓存，必须 ① 走共享 Redis（不能 LocMem）② 落盘前用 Fernet 加密 ③ 解密失败要主动清旧 key（不要让 stale token 反复抛异常）。
- **Rule**: cache 写入失败不应阻断主流程 — 主业务成功只是「记住连接」失败时，应 warn + 继续返回 connected，让用户至少这次能用。

## 生产 SECRET_KEY / SFTP_CONFIG_KEY 环境变量（2026-06-07）

- **问题**: `SECRET_KEY` 与 `SFTP_CONFIG_KEY` 都是 `django-insecure-` 默认值，写死在 `config/settings/base.py` 提交到仓库。生产部署若忘记设环境变量就直接用默认密钥——任何人都能伪造 session。
- **方案**: base.py 从 env 读 `SECRET_KEY` / `DJANGO_DEBUG` / `DJANGO_ALLOWED_HOSTS` / `SFTP_CONFIG_KEY` / `SFTP_SESSION_TTL` / `SFTP_SESSION_REDIS_URL` / `REDIS_URL`，默认值保留以不破坏开发。`if not DEBUG and (SECRET_KEY == _DEFAULT or 'django-insecure' in SECRET_KEY)` 抛 `ImproperlyConfigured` 启动失败。`SFTP_CONFIG_KEY` 未设时用 `warnings.warn`（不 hard-fail，因为 PBKDF2 派生自 SECRET_KEY 在功能上等价）。`.env.example` 增加生成指令注释，`docker-compose.yml` 暴露 `${VAR:-default}` 形式。
- **Rule**: 任何「默认是 django-insecure」的 SECRET_KEY，必须在 production guard 中显式拦截：检查 `== _DEFAULT` 同时 `in 'django-insecure'`，两者都要（防 `SECRET_KEY=django-insecure-...override` 这类字符串绕过）。
- **Rule**: production 缺「强烈推荐但非必须」的安全项时用 `warnings.warn` 而非 `raise` —— 强制中断会让人把它注释掉，warning 至少在 CI 日志里可见。

## extract_product_code 改用 CSV 测试程序名（2026-06-07）

- **问题**: 原 `B[A-Z]{1,2}\d+` 正则对 `BPD60320_FT.csv` 准，但遇到 `DA35_BPC50338_...`、`BN281R3CYCAA_...` 这类数据文件名（产品码被前缀或后缀污染）会误判或截断。
- **方案**: 新增 `extract_product_code(filename, program_name='')` —— 若 `program_name` 以 `.pts`/`.pgs`/`.pds` 结尾（不区分大小写），用 `os.path.splitext(basename)[0]` 作为产品码；否则回退到原文件名正则。CTA8290D/CTA8280F/ETS88/STS8200 四个 parser 的 metadata 都已经把测试程序名（TestFile / TestFileName / Data Sheet File / Program:）填到 `program_name` 字段，调用方 `_register_file` 改成 `extract_product_code(filename, program_name)` 即可。
- **Rule**: 解析器/分类器优先用 CSV 头里结构化字段（test program 名），再用文件名启发式。同一产品跨多次跑、跨测试机型的程序名是稳定的，而数据文件名会带站点/批次元数据噪音。
- **Rule**: 新增 `program_name` 参数时，**migration 里的历史调用**也兼容（`extract_product_code(df.filename)` 单参形式仍工作）。Migration 导入的函数签名要保证向后兼容，否则历史 migration 在新代码上会爆。

## extract_product_code 优先级反转 + 全 token 捕获（2026-06-07）

- **问题**: 上一版直接返回 program name basename（如 `BPC50338XBAC_EN`），把测试阶段 / 硬件后缀当成产品码的一部分；同样 `JAVBN281R3CYCAAV1.6` 整段也被当 product code。产品码被污染导致同产品多文件聚不到同一 `product_code` 桶。
- **方案**:
  1. 正则 `r'^(B[A-Z]{1,2}\d+)'` → `r'^(B[A-Z]{1,2}\d+[A-Z0-9]*)'`，整段 B 前缀 token 全部捕获：`BN281R3CYCAA` 拿全、`BPC50338` 不变。
  2. 优先级反转：**数据文件名优先**（B 前缀 regex 在文件名 token 上已经足够稳），**CSV 测试程序名兜底**（仅当数据文件名无 B 前缀 token）。两个 source 都走同一个 `_match_product_code()`，行为一致。
  3. `BPC50338_FT_SAB_BPC50338XBAC_EN.pts` 走 program name 兜底时也按 `_` 切分后取首个 `B<letters><digits><alnum>` token，输出 `BPC50338`。
- **Rule**: 解析器拿"产品码"这种**高维分类键**时，**绝不能直接返回某个原始字段 basename**。即使 source 看起来稳定（test program 名），也要再过一道相同的提取规则，剥掉后缀。Canonical id 必须是"最少字符、最大识别度"的 token。
- **Rule**: 改产品码提取逻辑后**必须跑 `python manage.py backfill_product_code`** 刷历史 DataFile 行（已写 `apps/datafiles/management/commands/backfill_product_code.py`，含 `--dry-run`）。否则旧文件继续带错 product_code，新文件才正确。
- **Rule**: 写"两阶段提取"（primary source + fallback）时，**两阶段走同一个匹配函数**。不要让 fallback 用更宽松的规则（"看到 basename 就当产品码"），否则一开 fallback 就回到老 bug。

## 用户目录 id→username 重构 — 「声称完成但未落盘」（2026-06-07）

- **问题**: 2026-06-06 会话记录"已完成：不同用户的数据管理路径用 name（如 admin/user）"，但 2026-06-07 用户回访发现 `media/data/1/single/*.csv` 仍按 `user_id=1` 落盘。**git log 验证：`git log --all -- apps/datafiles/views.py` 期间没有相关 commit，磁盘代码仍是 `def _user_upload_dir(user_id, file_type='single')`。** 进一步查：4 个 sftp/views.py 调用 + 4 个 datafiles/views.py 调用（`FileUploadView` / `BatchDirListView` / `BatchDirImportView` / `BatchDirDeleteView` / SFTP `download` / `download_dir` / `download_batch` / `download_and_parse` / `download_and_parse_batch`）全部传 `request.user.id`。
- **磁盘状态分裂**: `media/data/1/single/`（7 文件）= 老 ID 路径，`media/data/admin/batch/BE01-2604230009/...`（4 文件）= 已迁到 username 路径 —— 说明 SFTP 路径曾在某次实验中被改对、但 datafiles 主路径漏改。混用 state 是回归信号。
- **Fix**:
  1. `apps/datafiles/views.py` 把 `_user_upload_dir(user_id)` 改成 `_user_upload_dir(user, file_type)`，用 `str(user.username)`；9 处 caller 同步从 `request.user.id` 改成 `request.user`。
  2. `apps/datafiles/management/commands/migrate_user_paths.py`（新增）—— `--dry-run` 走 `scandir(media/data)` 找数字目录，按 `DataFile` 记录反查 `id→username`；username 目录已存在时按文件粒度合并（`shutil.move` 单文件，冲突同名保留源），不存在则直接 `os.rename`。DB 端用正则 `[/\\]data[/\\]\d+[/\\](?:single|batch)[/\\]` 筛出旧路径，逐行 `re.sub` 改写并 `update(file_path=...)`。
  3. `apps/datafiles/tests.py` 新增 `UserUploadDirTests`（6 用例）：锁住 username 路径、拒绝 None user、Unicode 用户名、不同 user 不串目录。
- **Rule**: 「声称完成」必须用 `git diff` 或 `git log` 验证磁盘状态，而不是依赖 session 记录或项目 memory。Memory 是描述性元数据，磁盘才是事实。**任何 4+ 步的重构，结束前必须 `git status` + `git diff --stat` + 跑至少一个针对改动点的回归测试。**
- **Rule**: 跨多个 view 的 helper 改名（参数从 int 改成 User 对象），所有 caller 必须 `grep` 一遍，不能靠目视。本仓 `Grep -n "_user_upload_dir\("` 在改完前/后各跑一次，确认 0 旧调用、0 旧参数。
- **Rule**: 数据迁移（文件 + DB 行）的命令必须支持 `--dry-run`，并提供「文件级合并」分支 —— 当目标目录已存在部分内容时，整目录 rename 会撞名。`_merge_tree(src, dst)` 按 `os.walk` 单文件移动 + 同名跳过，比 `shutil.copytree` 更安全（不会因为 target 是源目录的子目录而爆）。

## Vue 子组件直接修改 props 对象 — el-table 不重渲染（2026-06-07）

- **问题**: SingleFileTable 内部 `row.tags = data.tags` 直接修改 props 内部对象的属性，**Vue 不会追踪** props 内部对象属性的赋值，父组件 `files` ref 不会触发响应式更新，el-table 看到的 `data` 数组引用没变，**新 tag 不出现在 DOM**。Page snapshot 显示 tag 列还是"添加"按钮，toHaveCount(1) 失败。
- **根因**: `props.files` 是父组件 computed 派生的普通对象数组。Vue 3 的 ref 追踪的是 .value 数组的**引用替换**，不是数组元素的对象属性修改。`{ ...f, tags: updated.tags }` + `files.value = next` 才会触发响应式。
- **Fix**（在 `FileManager.onSingleTagsUpdated`）：子组件 emit('tags-updated', row) 之后，父组件必须**用 map 替换数组元素**：
  ```typescript
  const next = files.value.map((f) => (f.id === updated.id ? { ...f, tags: [...updated.tags] } : f))
  files.value = next
  ```
  子组件仍保留 `row.tags = data.tags` 以同步本地引用，但**真正的 UI 重渲染靠父组件的赋值**。
- **Rule**: 任何"子组件修改 row 后要立刻在表格里看到"的需求，必须走 `emit` + 父组件 `files.value = next` 模式。不要在子组件里直接 `row.x = y` 然后期望父组件自动追踪。
- **Rule**: 排查 el-table / el-form 不更新问题时，先看父组件 reactive state 引用是否真的被替换（`console.log(files.value === oldFiles.value)`），而不是看子组件的本地变量。

## JWT 自动续签 — 401 拦截器 + refresh 队列模式（2026-06-07）

- **问题**: 历史 `api/index.ts` 拦截器对 401 只做 `localStorage.removeItem` + `window.location.href='/login'`，但 `access_token` 30 分钟过期、`refresh_token` 7 天有效，期间任一 API 401 都被踢回登录页（用户看到的「18:52:35 还在用、18:53:36 直接 401」就是这模式）。后端 `SIMPLE_JWT` 已配 `ROTATE_REFRESH_TOKENS=True` + `BLACKLIST_AFTER_ROTATION=True`，`refresh_token` 也已存 localStorage 但**前端从未调用过 `/auth/refresh/`**。
- **关键陷阱 1（2026-06-07）**：`BLACKLIST_AFTER_ROTATION=True` 必须把 `'rest_framework_simplejwt.token_blacklist'` 加进 `INSTALLED_APPS`，否则 simplejwt 的 `TokenRefreshSerializer` 里 `refresh.blacklist()` 调用会触发 `AttributeError` 并被 `try/except: pass` 静默吞掉。**结果：刷新成功，但老 refresh 永远不被吊销**，攻击者拿到任一历史 refresh 都能续签。
  - 诊断信号：`./manage.py showmigrations token_blacklist` → "No installed app with label 'token_blacklist'"。
  - 验证：连续两次用同一个 refresh 调用 `/auth/refresh/`，第二次必须返回 401。
- **关键陷阱 2**：`auth.ts` 不能走共享的 `api` 实例调 `/auth/refresh/`。如果 refresh 请求本身被共享实例的 401 拦截器捕获且当前没有有效 refresh token，会直接 logout（无限循环直到 401 风暴结束）。解法：单独 `axios.post(baseURL + '/auth/refresh/')` 走原始 axios。
- **关键陷阱 3（循环 import）**：`auth.ts` 顶层 `const baseURL = api.defaults.baseURL` 在循环 import 下会读到 `undefined`（`api/index.ts` 还没执行到 `axios.create`），导致 refresh 请求打到相对 URL 解析到当前页面。解法：用 `getBaseURL()` 函数在调用时再读 `api.defaults.baseURL`。
- **关键陷阱 4（并发 401 风暴）**：仪表板首屏会并发发 5+ 个请求，每个都 401 → 都触发 `refreshAccessToken`。**`ROTATE_REFRESH_TOKENS=True` 每次刷新都让老 refresh 失效**，3 个并发 refresh 会让 token 链断成 3 段：第 1 个 refresh 用 refresh_token_0 拿到 refresh_token_1，第 2 个 refresh 用 refresh_token_0（已被黑名单）→ 401，第 3 个用 refresh_token_0 → 401。
  - 解法：模块级 `let refreshPromise: Promise<string | null> | null = null`，所有并发的 401 **await 同一个 refresh promise**。Promise 在 finally 块里清空。
- **关键陷阱 5（refresh 自身的 401 不能触发新一轮 refresh）**：拦截器看到原始请求 `url.includes('/auth/')` 时直接 `forceLogout()`。否则 refresh 失败 → 拦截器再用刚失败的 refresh 调一次 refresh → 死循环。
- **关键陷阱 6（`_retry` 标志位必须挂在 axios config 上）**：retry 完一次后必须打 `originalRequest._retry = true`，否则无限重试。axios 重试时 `api(originalRequest)` 走完整请求管线，**headers 必须重新写**：`originalRequest.headers = { ...headers, Authorization: 'Bearer <new>' }`。
- **关键陷阱 7（forceLogout 不能再走 store.logout()）**：store 的 `logout()` 会发 `authApi.logout(refresh)`，那个请求本身又会过 401 拦截器。**直接在拦截器里 `removeItem × 2 + window.location.href = '/login'`**。已经处于 `/login` 路径时跳过 redirect，避免覆盖用户已经填写的表单。
- **e2e 设计**：测试 refresh 不能等 30 min。模式：① 单元测后端接口（`tests.py` 7 用例：login 返回双 token、refresh 旋转、refresh 黑名单、garbage token 401、空 body 400、不要求 auth）；② 浏览器内调 `/auth/refresh/` 验证旋转 + 黑名单；③ 模拟「access_token 失效但 refresh_token 有效」：手动 `setItem('access_token', 'invalid.token.value')` → 触发受保护接口 → 断言没跳 /login 且 localStorage 里的 access_token 已被替换。
- **Rule**: 任何用 simplejwt 的项目，启用了 `ROTATE_REFRESH_TOKENS` 或 `BLACKLIST_AFTER_ROTATION` **必须**把 `rest_framework_simplejwt.token_blacklist` 加进 `INSTALLED_APPS` 并跑 `migrate`，否则 blackList 静默失效。
- **Rule**: 401 拦截器中，refresh 请求**自身**（`url.includes('/auth/refresh')` 或 `url.includes('/auth/login')`）必须 short-circuit 走 logout，不允许触发新一轮 refresh。
- **Rule**: 并发 401 必须共享同一个 in-flight refresh promise，否则 `ROTATE_REFRESH_TOKENS=True` 下 refresh token 链会断。
- **Rule**: 拦截器中的循环 import 必须用「函数懒读」化解（`getBaseURL()` 而非常量），否则 `api.defaults.baseURL` 在模块顶层求值时是 undefined。

## 登录错误码设计 — `{code, detail, ...}` 统一信封（2026-06-07）

- **问题（2026-06-07）**：原 `LoginView` 失败只回 `{'detail': 'Invalid username or password.'}` 一种消息，401/400/423 都一个样；用户看不到「用户名不存在」「密码错 N 次后会被锁」「账号被禁用」这些该知道的信息。`is_active=False` 字段**根本没被检查**（后端 bug，被禁用的用户只要知道密码就能登录）。
- **修复结构**：所有失败响应统一为 `{code, detail, ...extra}`：
  - `code` 是稳定字符串，前端 `switch`；`detail` 是用户可读中文（可被前端覆盖以支持 i18n）
  - `extra` 携带结构化字段：剩余尝试次数 / 解锁时间 / 缺哪些字段
- **5 个错误码**：
  | HTTP | code | 场景 | extra |
  |------|------|------|-------|
  | 400 | `missing_credentials` | 缺 username / password | `missing_fields: string[]` |
  | 401 | `user_not_found` | 用户名不存在 | — |
  | 401 | `invalid_credentials` | 密码错 | `remaining_attempts: number` |
  | 403 | `account_disabled` | `is_active=False` | — |
  | 423 | `account_locked` | 5 次错密码 / 或 `lockout_until` 未过期 | `retry_after_minutes`, `locked_until` (ISO 8601) |
- **关键设计 1（DISABLED 优先于 LOCKED）**：账号同时被禁 + 锁定时，告诉用户「被禁用」而不是「15 分钟后再试」。前者立刻可解（联系管理员），后者只能干等——避免无效等待。
- **关键设计 2（不再隐藏「用户名不存在」）**：教科书安全建议是统一返回「用户名或密码错误」防字典攻击。**内网 ATE 数据分析工具不适用此原则**——用户体验 > 字典攻击防护（攻击者本来就在公司内网，可以 `ls /home`）。`invalid_credentials` 仍带 `remaining_attempts` 给倒数。
- **关键设计 3（新增 `is_active` 校验）**：这是**后端 bug 修复**——历史代码 `User.objects.get(username=username)` 之后直接调 `authenticate()`，没碰 `is_active`。`is_active=False` 的用户只要密码对就能拿到 token。**这种 bug 在生产里能存在多久完全靠运气**（没人禁用账号就发现不了）。
- **关键设计 4（parseLoginError 区分错误来源）**：前端 `parseLoginError` 不是只看 `response.data.code`，还要看 `axiosError.code`：
  - `code === 'ECONNABORTED'` → timeout（30s axios 超时）
  - `!response`（无 response 对象）→ 网络断开（连不到后端）
  - `response.status >= 500` → 后端 5xx（结构化错误可能缺失）
  - `response.data.code` → 业务错误
  - 兜底 → `unknown`
- **关键设计 5（CSS 上色按错误类目，不按 HTTP status）**：网络/超时用**琥珀色**（"服务器侧问题"），账号被禁用用**深红色**（"你的账号出问题了"），5xx 用**暗橙**（"灰色地带，不是你的错"）。视觉区分比纯文字更能传达严重程度。
- **Rule**: 后端 API 错误响应**必须**返回结构化 `{code, ...}`，禁止只回 `{detail: 'free-form text'}`。前端 i18n、A/B 测试、监控告警都靠 `code` 字段
- **Rule**: DRF `LoginView` 这种有多种失败模式的视图，**必须**显式检查 `user.is_active`——`authenticate()` 不替你做这个检查。被禁用的用户能登录是 1 行代码的差距
- **Rule**: 「DISABLED vs LOCKED」之类的多状态检查，按**可操作性**排序：能立刻找管理员修的优先告诉用户，能等自动恢复的次之
- **Rule**: 前端 axios 错误处理**必须**区分 4 个层级：业务错误（`response.data.code`）/ 5xx / 网络断开（`!response`）/ 超时（`code === 'ECONNABORTED'`）。混为一谈会让用户看到"登录失败请检查用户名密码"当后端宕机时
- **Rule**: 写新的 DRF 视图前先看 `serializers.is_valid()` 返回什么——它**默认只返回布尔值**，需要 `raise_exception=True` 才会抛 ValidationError。如果想在 400 时返回自定义 `code`，得自己用 `serializer.validated_data` 判 missing 字段，不能 raise


## el-table inline input 立即 blur 误清空编辑状态（2026-06-07）

- **问题**: el-table 单元格内用 `<input v-if="editingId === row.id">` 实现就地编辑。点"添加"按钮后 input 出现，但 **el-table 内部布局 reflow（input 出现撑高行高）** 会触发 `blur` 事件。`@blur="commitNewTag(row)"` 同步执行，**newTagValue 还是空字符串**（fill 还没发生），`commitNewTag` 进入 `if (!t) { editingId.value = null; newTagValue.value = ''; return }` —— editingId 被清空、input 消失，后续 `tagInput.fill(...)` 找不到元素。
- **诊断证据**: `console.log` 显示 `commitNewTag called {tag: '', editingId: null}`，但应该 `editingId: row.id`。
- **Fix**（在 `SingleFileTable`）：把 `@blur="commitNewTag(row)"` 拆成 `@blur="scheduleBlurCommit(row)"`，延迟 150ms 后**先检查 editingId 是否仍匹配**：
  ```typescript
  function scheduleBlurCommit(row: DataFile) {
    if (blurTimer) clearTimeout(blurTimer)
    blurTimer = setTimeout(() => {
      if (editingId.value !== row.id) return  // keyup.enter 已先 commit
      const t = newTagValue.value.trim()
      if (t) commitNewTag(row)
      else { editingId.value = null; newTagValue.value = '' }
    }, 150)
  }
  ```
  这样：按 Enter 立刻 commit（editingId → null），setTimeout 触发的 blur 看到 editingId 变化 → 直接 return。点别处 → 100ms 内没新 commit → setTimeout 触发的 blur 走正常清空路径。
- **Rule**: 任何"立即出现的 input / popover / dropdown"，**@blur 触发时间不可预测**（element-plus 内部 reflow、autofocus 失败、表格行高度变化等都可能），必须延迟 + 检查 ownership 状态再决定要不要 commit，不能直接同步调用。
- **Rule**: 排查"input 出现后立即消失"问题时，先看 console.log 函数第一行的 editingId 值 —— 如果是 null，说明 blur commit 在 fill 之前就跑了。

## Playwright waitForResponse 异步注册竞态（2026-06-07）

- **问题**: `await page.waitForResponse((r) => /set_tags/.test(r.url()))` 在 `tagInput.fill(tagName)` **之后**注册。在某些 timing 下，fill 触发的 input 事件 → keyup.enter 已经把 setTags 请求发出 → waitForResponse 注册时请求已在飞行中，listener 永远等不到匹配的 response → 10s 后 TimeoutError。
- **诊断证据**: console 显示 `setTags response {tags: [...]}` 说明请求**确实成功**返回了，但 `setTagsResp = page.waitForResponse(...)` 这次没匹配到（因为它注册得太晚）。
- **Fix**: e2e 断言不要单独等网络层。**改用 DOM 断言**（`toHaveCount(1)` 等 el-tag 出现），让 setTags 200 + 父组件 onSingleTagsUpdated + el-table 重渲染**隐式串成一条线**：
  ```typescript
  await tagInput.fill(tagName)
  await tagInput.press('Enter')
  await expect(firstRow.locator('.el-tag').filter({ hasText: tagName })).toHaveCount(1, { timeout: 15_000 })
  ```
- **Rule**: e2e 断言要测**端到端可观察状态**（DOM 元素、文本），不要在中间步骤拦截网络请求做诊断。`waitForResponse` 仅在"必须验证某个特定请求被发出"时使用，并且**必须**在触发请求的操作**之前**注册（用 `Promise.all([waitForResponse, action])`）。

- **el-table type="expand" 必须配 row-key（2026-06-07）**：当 `<el-table>` 里有 `<el-table-column type="expand">` 时，Element Plus **强制**要求 `<el-table>` 上有 `row-key` prop，否则在 mount/setup 阶段抛 `Error: [ElTable] prop row-key is required`（wrapped 在 unhandled watcher callback 后面，看不到根因）。`row-key` 用于跟踪每行的展开/选中状态。没有它，无论 `expand-row-keys` 配没配都会崩。**Rule**: 给 el-table 加 expand 列时，**第一步**就同步加 `:row-key="(row) => row.id"`，别等跑起来才补。`SingleFileTable.vue` 之前有 row-key 所以没踩，但 `FileListTab.vue` 之前没加、补 expand 列时漏了。

## DRF ModelViewSet.update() 硬编码 partial=False（2026-06-07）

- **问题**: 用户管理页面 `PUT /api/v1/auth/users/2/ {is_active: false}` 返回 400。前端发的是「只带一个字段的 PUT」（常见模式：整体替换语义 + 实际只改一个字段）。后端 `UserSerializer` 严格校验 `username`/`email`/`display_name`/`role` 必填 → 400。
- **根因**: `rest_framework.mixins.UpdateModelMixin.update()` 内部硬编码 `partial=False`：
  ```python
  # rest_framework/mixins.py:151-156
  def update(self, request, *args, **kwargs):
      partial = kwargs.pop('partial', False)   # ← 这里是 pop，但调用时传的硬编码 False
      instance = self.get_object()
      serializer = self.get_serializer(instance, data=request.data, partial=partial)
      ```
  **注意**：看似 `partial` 是从 `kwargs` 弹出的（意味着可以从 `update` 调用方传 partial=True），但 DRF 的 `ModelViewSet.update()` 模板是
  ```python
  # rest_framework/viewsets.py:120
  def update(self, request, *args, **kwargs):
      return super().update(request, *args, **kwargs)   # ← 没传 partial
  ```
  → `kwargs.pop('partial', False)` 拿到 False → `partial=False`。**仅在 `get_serializer()` 里 `kwargs.setdefault('partial', True)` 不生效**——`UpdateModelMixin.update()` 自己调的 `self.get_serializer(..., partial=partial)` 已经把 partial 写死了
- **修复（2 种）**：
  1. **覆写 `update()`**（推荐，最直观）：
     ```python
     def update(self, request, *args, **kwargs):
         kwargs['partial'] = True
         return super().update(request, *args, **kwargs)
     ```
  2. **让 `get_serializer()` 看 `self.action`**：
     ```python
     def get_serializer(self, *args, **kwargs):
         if self.action in ('update', 'partial_update'):
             kwargs.setdefault('partial', True)
         return super().get_serializer(*args, **kwargs)
     ```
     —— 但这仍然不解决 mixin 覆写的问题，需要在 `update` 也强制 partial。
- **关键陷阱 1（partial=True 不跳 validator）**：`partial=True` **不**等于"跳过所有校验"。`UniqueValidator` / `RegexValidator` / 自定义 `validate_<field>()` 仍然跑——因为它们是 field-level validation，不依赖 partial 标志。`test_put_username_must_remain_unique` 验证了这一点（PATCH username=已存在 → 400，不是 200）。`partial` 只控制「必填字段缺失时不报 required」
- **关键陷阱 2（PATCH 路由已默认 partial）**：DRF 的 `UpdateModelMixin` 的 `partial_update()` 默认就是 `partial=True`，对应路由 `PATCH /<id>/`。前端写 PUT 也很常见（HTTP RFC 9110 §9.3.4 允许 PUT 做部分替换）。后端要兼容两种调用方——直接强制 PUT 也走 partial
- **关键陷阱 3（PUT 完整 body 仍要工作）**：强制 `partial=True` 不会让「PUT 带全部 8 字段」失败——验证器会对「提供全字段」和「提供部分字段」都接受（多出的字段被忽略）。`test_put_with_full_body_still_works` 验证了这一点
- **关键陷阱 4（前端错误显示要能渲染后端 detail）**：后端 400 会带 `{"username": ["This field may not be blank."]}` 这种结构化信息，**前端 catch 必须能透出**：
  ```typescript
  function formatError(err: unknown, fallback: string): string {
    const data = (err as any).response?.data
    if (data) {
      if (typeof data.detail === 'string') return data.detail
      for (const [field, msgs] of Object.entries(data)) {
        if (Array.isArray(msgs) && msgs.length) return `${field}: ${msgs[0]}`
      }
    }
    return (err as any).message || fallback
  }
  ```
  否则用户只能看到通用「操作失败」，完全不知道为什么。`UserManagement.vue:188-208` 是参考实现，5 处 catch 都接入
- **Rule**: 任何「管理类 ViewSet + 前端只改一个字段的 PUT/PATCH」场景，后端**必须**在 `update()` 强制 `kwargs['partial'] = True`，否则必踩这个坑。`get_serializer()` 里加 `partial=True` **无效**——被 mixin 覆写
- **Rule**: 当 `serializer.save(owner=...)` 在 ViewSet 里传额外 kwargs 时，序列化器 `create(self, validated_data, **kwargs)` 必须 `**kwargs` 透传。这与上一个坑是「DRF serializer 接受 kwargs 的两种边界」：save() 走 `**kwargs`，update()/partial_update() 走 `partial` 标志。**两套机制互相独立**，得分别处理
- **Rule**: 给后端写 ViewSet 测试时，**必须**覆盖 4 种调用形态：① PUT 单字段（`partial=True` 路径）② PATCH 单字段（DRF 默认）③ PUT 全字段（确保没破坏完整替换）④ PUT 到不存在 id（404）。任意一种漏测，前端改动就可能悄悄回归

## useChart v-if 容器重建后旧 ECharts 实例失效 → 图表空白（2026-06-07）

- **现象**: gage_m_S4.csv → 数据分析 → 开「显示QQ图」→ 切换测试项，**QQ 图区域空白**（首次正常，之后变空白）。控制台偶发 `qqplot 400` / `histogram 500`。
- **诊断走过的弯路**: 一开始只盯后端 status code（确实查到 histogram 缺 param 守卫会 500），但**用 APIClient 逐 param 测全 200**，无法复现。真正主因要用 Playwright 在真实浏览器里复现 + **看渲染**（截图发现 200 但 QQ 容器空白），不能只看网络层。
- **主因（前端 `composables/useChart.ts`）**: `ensureInit()` 只要 `chartInstance.value` 存在就 `return true`。但 `QQPlotChart.vue` 的图表 `<div ref="chartRef">` 用 `v-else` 条件渲染——`loadQQPlot` 开头把 `qqResult=null` 销毁了该 div，数据回来后 Vue **重建一个新 div**。`chartInstance` 仍绑在**已脱离 DOM 的旧节点**上，`setOption` 渲染到 detached node → 新 div 永远空白。histogram 不复现是因为 `histResult` 从不被置 null，容器不销毁。
- **Fix**: `ensureInit()` 在复用前校验 `chartInstance.getDom() === chartRef.value && isConnected`；不符则 `handle.dispose()` 并在当前（live）容器重建。对容器不切换的图表是 no-op。
- **次因（后端 `analysis/views.py histogram`）**: 切文件瞬间子组件 watcher 用上一文件 stale param 发请求。`qqplot` 有 `if param not in df.columns -> 400` 守卫；`histogram` 没有 → `df[param]` KeyError → 500。Fix：循环内 `if param not in df.columns: continue`。
- **回归测试**: e2e 断言「每次切 param 后 QQ 容器 SVG 仍有非零尺寸」——**已验证**：还原 useChart 前 e2e 必 fail，修复后 pass（这是「证明测试能抓到 bug」的关键步骤）。后端 3 个 APITestCase 锁 histogram 未知 param 返回 200。
- **Rule**: 共享图表 composable（useChart）**必须**支持「容器被 v-if 销毁后重建」——缓存实例前校验 `getDom()` 仍是当前 live 的 ref 元素，否则 dispose 重建。任何「图表组件用 v-if/v-else 切换容器 + 数据中途置 null」的组合都会触发此 bug。
- **Rule**: 排查「请求 200 但图表空白」类问题，**先在真实浏览器复现并截图看渲染**，而不是只在后端 APIClient 里循环测 status code——纯前端渲染/生命周期 bug 在后端测不出来。
- **Rule**: 两个相似端点（histogram / qqplot）做同一件事（按 param 取列），守卫必须**对齐**——一个有 `param not in df.columns` 守卫、另一个没有，就是 500 的温床。新增/复制端点时 grep 同类守卫。
