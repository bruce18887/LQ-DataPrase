# Lessons Learned

## SFTP — 每次请求重建连接导致点击卡顿

- **Bug**: `SftpViewSet._get_connection` 每个请求都新建 `paramiko.Transport` 完成完整 SSH 握手（多个网络往返 ~300–500ms），用完即 `close()`。凭据虽缓存，但**连接本身没复用**，每次点击进目录都重付握手延迟（与带宽无关）。
- **Fix**: 新增 `apps/sftp/pool.py` 进程内连接池，按 `user_id` 复用。复用前校验 `transport.is_active()` + 空闲 TTL（默认 300s），死/旧则用缓存凭据重建；操作失败调 `pool.invalidate` 丢弃坏连接；`disconnect` 调 `pool.close`。
- **Rule**: 部署用 gunicorn **sync** worker（`--workers N` 无 `-k`），单 worker 串行处理请求 → 连接池**无需加锁**。若改用 gthread/gevent worker，paramiko 非线程安全，必须补 per-user 锁（已在 pool.py docstring 注明）。
- **Rule**: SSE 流式下载（`download_dir`）的 generator 正常结束**不关连接**（留池复用），仅在 `GeneratorExit`/异常时 `invalidate`（流式中途连接状态不可靠）。
- **Rule**: 改连接获取签名后，注意清理 views.py 里不再使用的 import（如 `get_session` 移到 pool 后）。

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

## quest.txt 四问题（图表空白 / 批次消失 / 当前文件下拉 / SFTP卡顿）2026-06-08

- **图表「Can't get DOM width or height」根因 = 直接 `echarts.init` 而非 `initEchartsWhenReady`**：仪表盘单文件分析 5 组件直接 `echarts.init(el)` 一次性初始化；数据到达后 `nextTick` 时容器高度（`flex:1`/`calc(100%-42px)`）未确定 → clientHeight=0 → 报警+空白，布局撑开后不重绘。修复迁移到既有 `utils/echarts-init.ts initEchartsWhenReady`（ResizeObserver+rAF 轮询）。**Rule**: 项目已有零尺寸保护工具时新图表组件**禁止**裸调 `echarts.init`——grep `echarts.init` 找漏网。`AggregatedBinChart.vue` 是标准参照（buildOption + handle）。
- **「SFTP 下载新批次后旧批次消失」是前端分页表现 bug，非数据丢失**：后端 `_register_file` 只新增、`list_batches` distinct 返回全部、磁盘各批独立目录——数据完好。但 `FileListTab/FileManager` 的 `batchGroups` 从**分页 20 条** `/files/?ordering=-created_at` 第 1 页分组，新文件占满首页就把旧批次挤出。**Rule**: 「列表项消失」先分清「数据没了」还是「分页/过滤没取到」——查后端 DB 实证（shell distinct）再动手。修复用磁盘走查的 `/batch-dirs/` 作分组源并扩展其返回每批 `files[]`，与分页解耦。
- **e2e 中 `v-show` 多 tab 同时存在 DOM → 选择器命中隐藏副本**：DataManagement 的 view/export 用 `v-show`，两个 `.banner-file-select` 同时在 DOM，`.first()` 命中 `display:none` 的那个 → toBeVisible 永远 hidden。**Rule**: `v-show` 切 tab 时定位必须加 `.content-section:visible` 限定当前可见 section。
- **EP 2.14 el-select 断言**：真 `<input>` 未聚焦时 hidden，可见性判断用 `.el-select__wrapper`；占位符与选中值**都**渲染在 `.el-select__placeholder`（选中后复用为值展示），`.el-select__selected-item` 同时匹配 input-wrapper + placeholder（strict 违例）。**Rule**: 可见性用 `.el-select__wrapper`，选中值用 `.el-select__placeholder` 文本。
- **`vue-tsc --noEmit` vs `-b` 严格度不同**：`--noEmit`（单 tsconfig）过，但 `-b`（build mode）暴露更多既有错误（TS6133 未读变量、EChartsOption 字面量类型不兼容）。本仓库 `-b` 全量 build 本就有一堆前序未提交报错。**Rule**: 改动验证用 `--noEmit` 看自己范围；判断「是否我引入的回归」grep 自己改的文件名，别被既有 build 噪音误导，可疑时 `git stash` 对照。

## 联想输入 — el-autocomplete vs el-select + filterable 2026-06-10

- **需求**: 所有输入框都要有联想/下拉选择功能（类似 Streamlit）。
- **尝试 1 — el-autocomplete**: 提供输入联想但**丢失了下拉选择**功能。用户反馈"不能进行下拉 select 了"。
- **正确方案 — el-select + filterable**: Element Plus 的 `el-select` 设置 `filterable` 属性后，同时支持输入过滤和下拉选择。配合 `filter-method` 自定义过滤（前缀优先）和自定义 option 模板（高亮匹配），完美满足需求。
- **标签输入联想**: 原生 `<input>` + 自定义下拉建议列表（`.tag-suggestions`）。调用已有的 `listTags(prefix)` API，debounce 200ms。键盘导航（↑↓/Enter/Escape）。选择后自动提交标签。
- **Rule**: 需求是"输入+下拉选择"时，优先用 `el-select + filterable`，不要用 `el-autocomplete`（后者只提供联想，不提供 select 体验）。纯标签输入场景可以用原生 input + 自定义下拉（更轻量）。
- **Rule**: 标签联想的下拉建议要用 `@mousedown.prevent` 而非 `@click`，否则 blur 事件先触发导致输入框关闭，建议项点击无效。

## QQ 图 null r_squared 引发 Vue 异步渲染 (debug-qqplot-sw-bin-bug)

- **Bug**: 「QQPlotStatsTable.vue:32」直接对 `props.result.r_squared.toFixed(4)`。后端传过来的 JSON 中 `r_squared` 为 `null`，调用 `null.toFixed()` 抛 `TypeError: Cannot read properties of null (reading "toFixed")`。与此同时的还有 Vue 渲染错误信号 ` Cannot read properties of null (reading "emitsOptions")`，该错误是同一个 实例 在多个代理事件同步入队后渲染中的二次代理雪崩产生的广义 patch failure，原始代理事件是 `toFixed(null)`。

- **根因**：`SW_Bin` 是 soft-bin 分类列，在 `gage_m_S4.csv` 中所有 100 行的值都是 `1.0`（软分类 `pass=1`）。后端 `compute_qqplot` 调 `scipy.stats.probplot(clean, dist="norm")` 时因 y 全同值计算的相关系数 r 为 NaN，DRF 序列化后 JSON 中变成 `null`。

- **Rule 1 — JSON 序列化 NaN = null**：后端计算走 scipy / numpy / pandas 产生 NaN 时 DRF 默认序列化为 JSON `null`。前端取到任何可能为 null 的数字字段时，`.toFixed()` / `.toLocaleString()` 都应先 `Number.isFinite()` 护。

  ```typescript
  const r2 = result.r_squared
  const text = typeof r2 === 'number' && Number.isFinite(r2) ? r2.toFixed(4) : 'N/A'
  ```

- **Rule 2 — TypeScript interface 要先容错**：定义 props 类型时 不要写 `interface { r_squared: number }`。数据字段在后端会变 null，代码约束会隐藏问题。应写 `number | null`，渲染时叠加 `typeof === "number" && Number.isFinite(x)` 两重检查。

- **Rule 3 — "emitsOptions null" 是二次代理例现"**：上报代理事件只是 patch 阶段的多组件代理问题雪崩的错误信号之一。需拼 pageerror 输出里面错误位置远越 "emitsOptions" 本上的代理事件。不要被错误位置误导为"是另一个独立 bug"。

- **Rule 4 — 回归测试要覆盖“脆弱”数据路径**：`gage-qqbox-repro.spec.ts` 之前只选 5 个“好”参数（如 `PWM_Hz_IQ_VIN_12V`），未覆盖 `SW_Bin` 这类常量列。回归测试套件需要包含至少一个“全同值 / NaN / 离散”用例，如 `sw-bin-qqplot-repro.spec.ts`。

- **Rule 5 — 加 instrumentation 注意 import 顺序**：`__dbgState = computed(() => props.xxx)` 引用了 `props.xxx`，但 `<script setup>` 里 `defineProps` 还未执行。要在 `defineProps` 之后再定义引用 props 的 computed / watch。

## pd.to_numeric(bool) 不转 dtype + abs('str') 崩 — compute_boxplot_stats 容错（2026-06-13）

- **Bug**: `apps/analysis/services/statistics/computations.py:compute_boxplot_stats` 接到 `Dut_Pass`（bool Series）或 `Site #`（str Series）就崩。两条崩路径：
  1. **bool**：`pd.to_numeric(s, errors='coerce')` 对 bool Series **不**改 dtype（实测仍是 `bool`），`clean_data.quantile(0.25)` 返 `np.bool_`，`q3 - q1` 时 numpy 抛 `TypeError: numpy boolean subtract, the - operator, is not supported, use the bitwise_xor, the ^ operator, or the logical_xor function instead`。
  2. **str**：`clean_data.apply(lambda x: abs(x) < float('inf'))` 在 string 上抛 `TypeError: bad operand type for abs(): 'str'`。
- **触发面**：histogram 视图用 `dtype in ('int64', 'float64')` 严格过滤（`Dut_Pass` / `Site #` 都不在下拉里），**UI 上用户选不到**。但 boxplot 视图的 `_sanitize_numeric_params` 用 `is_numeric_dtype`，bool 返回 True → 直连 API 调 `/statistics/boxplot/?params=Dut_Pass` 就崩。
- **复现验证**（`tasks/check_sampledata_null_r2.py`）：
  - **98 个 bp_issues**（72× boolean / 26× string）跨所有 11 个 sample data 文件
  - ETS88 文件 `BPD93204_FT1_ETS163550_12252024.csv` 不命中（它没有 `Dut_Pass` bool 列）；gage_m_S4 / R2601070008 / DA35_BPC50338 / Buyoff 三件套全中
- **Fix（最小改动 scope）**：[computations.py:199-209](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/apps/analysis/services/statistics/computations.py#L199-L209) 在入口处：
  ```python
  coerced = pd.to_numeric(data, errors='coerce').astype(float)  # 强制 float，bool->0.0/1.0
  clean_data = coerced.dropna()
  clean_data = clean_data[np.isfinite(clean_data)]              # 向量化替代 abs(x) < inf
  ```
  - `.astype(float)` 是关键——`pd.to_numeric` 单独不够，bool Series 不会被它改 dtype
  - `np.isfinite(clean_data)` 同时挡 inf 和 nan，且在 str 上不会崩（coerce 阶段已经转 NaN）
- **回归测试**：
  - **Django 单元** [apps/analysis/tests.py:BoxPlotStatsDtypeToleranceTests](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/apps/analysis/tests.py#L200-L268) — 5 用例：boolean / string / pure-string / 纯 bool 常量 / 正常数值；不依赖 DB
  - **e2e** [frontend/e2e/analysis/boxplot-bool-params.spec.ts](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend/e2e/analysis/boxplot-bool-params.spec.ts) — 直连 `GET /api/v1/statistics/boxplot/?params=Dut_Pass` 断言 200 + overall.count=100 + min=0/max=1；`params=Site #` 断言 400 no_valid_params（不是 500）
  - **回归扫描**：`tasks/check_sampledata_null_r2.py` 复跑后 `bp_issues = 0` ✓
- **Rule 1**：任何 pandas 数值计算前做 `pd.to_numeric(...).astype(float)` 而不是只 `pd.to_numeric(...).errors='coerce'`，**bool 必须显式 astype(float)**，否则 dtype 保留崩后续。
- **Rule 2**：过滤 inf / nan 用 `np.isfinite(clean_data)` 向量化，**不要**写 `clean_data.apply(lambda x: abs(x) < float('inf'))`——abs 在 string 上崩，apply 也比向量化慢 10x+。
- **Rule 3**："前端过滤了某个 dtype → 后端不用管"是错误假设。**任何接 Series 的 service 函数都要容错所有 dtype**（bool / str / object / category），因为：1) 视图层过滤规则可能漂移；2) 直连 API / 脚本 / 后续 caller 可能绕过；3) validation 脚本必然直接调 service。
- **Rule 4**：写新 stats service 之前**先扫一遍 sample data 里所有 dtype 分布**——`df.dtypes.value_counts()` 一行就能看到有没有 bool / object 漏网，比靠经验猜全面。
- **Rule 5**：复跑诊断脚本确认 `bp_issues` 归零是验证修复的硬标准。光看"我自己写的小测试过了"不够——可能只是测试用例没覆盖到。

## Pinia store 持久化导致 stale selectedParam 跨文件泄漏（2026-06-13）

- **Bug**: 用户在 `gage_m_S4.csv`（file_id=14518）选了 `R_Kelvin_AGND` 作为单参数分析的目标测试项；切到 `BPD93204_FT1_ETS163550_12252024.csv`（file_id=14514，ETS88 格式，无此列）后，三个分析 API 同时报错：
  - `POST /api/v1/analysis/qqplot/` 400
  - `GET  /api/v1/statistics/boxplot/?params=R_Kelvin_AGND&group_by=site` 400
  - `POST /api/v1/analysis/histogram/` **500**（KeyError）
- **根因（前端 + 后端共谋）**：
  1. `analysisStore.selectedParam` 在 Pinia 里被持久化（用户上次选的 param 跨页面刷新仍存）。`AnalysisPage.onFileChange` 只重新加载 `params` 列表，**没有重置** `selectedParam` / 持久化值。
  2. `SingleParamTab.vue` 的 `watch(() => props.fileId)` 也只清空 `localSelectedParam`，但在父组件传 `selected-param` 之前已经先于 prop update 触发 → 竞态下仍可能带旧值发请求。
  3. 后端 `histogram` 视图循环里 `df[param]` 不在白名单就 500；`qqplot` / `boxplot` 视图有 `param not in df.columns` 守卫返回 400。结果是同一根因出三种 status code——诊断时极易把 400 误判为「qqplot 自己有 bug」而漏掉真正的 stale param 主线。
- **修复（双层防御）**：
  1. **前端主修** — `AnalysisPage.onFileChange` 开头先 `params.value=[] / selectedParam.value='' / analysisStore.selectedParam=''`，再异步加载新文件参数（用第一个自动选中）。
  2. **前端兜底** — `SingleParamTab` 增 `watch(() => props.fileId, () => { localSelectedParam.value = ''; if (showQQPlot.value) loadQQPlot() })`，防止父组件传参竞态。
  3. **后端兜底** — `histogram` / `boxplot` / `qqplot` 视图在循环前 `valid_params = [p for p in params if p in df.columns]`；空集返回 400 `{error: 'no_valid_params', detail, requested, missing}` 而不是 500。
- **关键陷阱 1（watch + v-model:selectedParam 双绑）**：`SingleParamTab` 用 `defineProps(['selectedParam'])` + `defineEmits(['update:selectedParam'])` 透传父组件 v-model。子组件 `watch(props.fileId)` 清的是自己 `localSelectedParam`，但**父组件绑的 `selectedParam` ref 仍带旧值**——必须从源头（`AnalysisPage`）清，否则 `v-model` 双向同步又把 stale 值推回来。
- **关键陷阱 2（DRF test 客户端未 force_authenticate → 401）**：用 `APIRequestFactory` + 简单 `request.user = SimpleNamespace(...)` 调 view，DRF 的 `IsAuthenticated` 仍会拦截（permission 类检查的是 `request._auth` 而不是 `request.user`），视图永远 401。**必须** `from rest_framework.test import force_authenticate; force_authenticate(request, user=SimpleNamespace(pk=1, is_authenticated=True, is_active=True, is_anonymous=False, is_staff=False, is_superuser=False))`。`is_authenticated` 必须为 True 才能绕过。
- **关键陷阱 3（mock DataFile 缺字段）**：测试 view 时 `datafile = types.SimpleNamespace(id=1, filename='x')` 是常见模式，但 `AnalysisViewSet.histogram` 里读 `datafile.format_type` 直接 AttributeError。**Rule**: mock datafile 时把 model 必读字段全列出来（`id, filename, format_type`），不要只放当前用例需要的。
- **回归测试**（`apps/analysis/tests.py:StaleParamAcrossFileSwitchTests` 4 用例）：
  - `test_histogram_view_returns_400_for_unknown_param` — 全 bogus param → 400 + `error: no_valid_params` + `missing: [__bogus__]` + `requested: [__bogus__]`
  - `test_histogram_view_drops_partial_unknown_params` — 混合 param → 200，bogus 被丢、real 进 results（防「over-eager 守卫误伤合法 param」）
  - `test_qqplot_view_returns_param_not_found_for_unknown_param` — POST qqplot bogus → 400 `param_not_found`
  - `test_boxplot_view_returns_400_for_unknown_param` — GET boxplot bogus → 400 `no_valid_params` + `missing: [__bogus__]`
- **e2e 测试**（`frontend/e2e/analysis/file-switch-param-reset.spec.ts`）：gage → ETS88 切文件，断言新文件首参 ≠ 旧文件首参 + 无 4xx/5xx 命中分析 API。
- **Rule 1**：任何持久化到 Pinia / localStorage / Vuex 的"用户上次选择"（selectedFileId / selectedParam / selectedTab），**在文件/数据上下文切换时必须显式重置**。父组件 `onFileChange` / `onProjectChange` 入口处先 `state.value='' / store.value='' / analysisStore.x=''` 三件套清空，再异步加载新上下文。
- **Rule 2**：跨多个相似端点（histogram / qqplot / boxplot）的"按 param 取列"操作，**守卫必须对齐**——一个有 `param in df.columns` 检查、另一个没有，就是状态码雪崩的根因。Code review 时 grep `if .* not in df.columns` 对比各 view 即可秒发现。
- **Rule 3**：DRF view 单测想绕过 auth，**必须** `force_authenticate`（`rest_framework.test`），不能 `request.user = SimpleNamespace(...)`——后者只设了 user 属性，没改 `request._auth` / `request.successful_authenticator`，`IsAuthenticated` 仍拒。
- **Rule 4**：mock DataFile / ORM 对象给视图用时，**第一步**先 grep view 里所有 `datafile.xxx` 引用，把必需字段列全（id / filename / format_type 是最低配），否则测试会因「业务逻辑改了但 mock 没改」间歇性挂。
- **Rule 5**：「跨上下文状态泄漏」类 bug 必须**双层防御**——前端清状态 + 后端 validation。光前端清不够（用户多 tab / 深链接 / 旧版缓存都可能绕过）；光后端 validation 不够（用户看到 400 时已经疑惑「我刚才明明选对了」）。两层都在，重建到中间状态的路径都能被截。

