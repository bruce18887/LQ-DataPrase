# 批4 刀一/刀二 设计：e2e 拆文件与用户名路径防御（2026-11-15）

上游：`docs/superpowers/specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md` §10（批4 条目清单）
与 §6.2 决策 D。本稿只覆盖**本轮要做的两刀**，刀三～刀五与四条待拍板项在 §5 挂账，不在本稿展开。

## 0. 切法（2026-11-15 用户拍板）

批4 按模块族切五刀，本轮做前两刀，**各一条过程分支、各自 FF**，理由沿用批3a/批3b 那条：
两处独立、不共用文件，合成一份计划只会让门禁档位互相污染。

| 刀 | 内容 | 本轮 |
|---|---|---|
| 刀一 | 拆 `e2e/data/duplicate-keep.spec.ts` + 共享助手抽取（§10 的硬前置） | ✅ 分支 `feature/batch4a-e2e-dup-split` |
| 刀二 | FIX-2 `..` 用户名上传逃逸（双层防御），探针先行 | ✅ 分支 `feature/batch4b-username-guard`（刀一 FF 后再切） |
| 刀三 | FIX-1 刷新不吞勾选 + FIX-4 sibling loader 随激活刷新 | ❌ 依赖刀一 的落点 |
| 刀四 | 决策 D（用户管理左槽搜索/角色筛选）+ `SettingsPage.vue:313` 死规则 + 两项可推翻 + 1280 面板 | ❌ 含待拍板项 |
| 刀五 | 未封顶下拉两处 + `useSelectFilter` 抽取 + 批1 遗留 flake | ❌ |

FIX-3（两处原型键查表）按 §10 是机会主义，谁碰那两个文件顺手换，不单列。

## 1. 立据（全部 2026-11-15 现量，base = `b797d1f`）

| # | 事实 | 证据 |
|---|---|---|
| E1 | `frontend/e2e/data/repair-center.spec.ts` = **591/600** 行 | `wc -l`；闸在 `scripts/line-limit.mjs:18`（`LINE_LIMIT=600`），`*.ts` 在计数口径内（`:26`），`.vue`/`.py`/`.ts` 整文件计数 |
| E2 | 拆文件后**必然**产生 `apiGet` 的第三份副本，而仓里已写明第三份就该进 helper | `frontend/e2e/data/disk-usage-chip.spec.ts:32-36` 注释原话「这是本仓**第二**份同名副本，够不上抽 helper；出现第三份时就把它搬进 `e2e/helpers/`，别再往 spec 里复制」 |
| E3 | 四个待共享助手现在全是 spec 局部函数，`frontend/e2e/helpers/` 里一个都没有 | `repair-center.spec.ts:29 shellDjango`、`:38 apiGet`、`:48 apiPost`、`:171 openRepairCenter` |
| E4 | 池档 slot 内**串行**：`--workers=1`，spec 文件由 `playwright --list` 枚举（新文件自动进池，无需登记） | `scripts/e2e_pool.mjs:215`、`:158-161` |
| E5 | serial 档**并行**：`fullyParallel: true` + `workers: min(6, cpus/2)` ⇒ 拆出的两个文件会同时打同一后端 | `frontend/playwright.config.ts:63`、`:69` |
| E6 | SQLite 侧已有并发写承接：每个新连接 `journal_mode=WAL` + `busy_timeout=30000` | `apps/common/db_pragmas.py:14-20`（`apps/common/db_pragmas.py:10-11` 同时说明测试运行器用 `:memory:`，不支持 WAL） |
| E7 | 改 `frontend/e2e/helpers/**` 判**全量 e2e**；改 `frontend/e2e/data/**` 判 `data` 模块档 | `scripts/affected-rules.mjs:114`（`['frontend/e2e/helpers/', [GLOBAL]]`）、`:119`（`['frontend/e2e/', null] // 其余按目录名即模块`） |
| E8 | 改 `apps/accounts/**` 与 `apps/common/**` 判**全量**；只有 `apps/datafiles/**` 是 `data` 档 | `scripts/affected-rules.mjs:92`、`:95`、`:96` |
| E9 | `_user_upload_dir` 生产侧 **24 处调用点、8 个模块**（batch_views 4、file_views 4、sftp/views 6、sftp_job 2、consolidate_uploads 3、_helpers 内部 3、browse_views 1、seed_test_data 1） | `grep -rn "_user_upload_dir("` |
| E10 | `apps/datafiles/tests.py` 现 **1959 行 = 豁免冻结值**，多一行即报红 | `wc -l` 与 `scripts/line-limit.mjs:36-37`（`frozenLines=1959`，`kind:'grew'` 语义见 `frontend/test/unit/lineLimit.spec.ts:73-78`） |
| E11 | `is_safe_username` 现在住在 `apps/datafiles/`，引用面只有 1 个消费者 | `apps/datafiles/storage_usage.py:48/:51/:75`、`apps/datafiles/views/usage_views.py:11/:30`；`test/` 下 0 处直接引用 |
| E12 | 四条建号通路**不经过** `UserCreateSerializer` | `apps/accounts/admin.py:12-13`（`User` 注册了 `UserAdmin`）、`apps/accounts/management/commands/seed_users.py:33-42`（`get_or_create`）、`standalone.py:114`（首启 `create_superuser`）、`manage.py createsuperuser`（走 `apps/accounts/models.py:23-28` 的 manager 覆写） |
| E13 | 未捕获的非-`APIException` 异常一律冒成 **JSON 500** | `apps/common/exceptions.py:156-167` |
| E14 | `APIException` 子类经既有处理器可拿到**稳定机器码**，无需新机制 | `apps/common/exceptions.py:36-44`（`_KNOWN_EXCEPTIONS` 就是为此存在的映射表）、`:154`（先走 DRF 默认处理器再归一化信封） |
| E15 | 探针（`tasks/probe_b4_dotdot_users.py`，只读、不写库、不发 HTTP、不建目录）本机实测 | 用户总数 3 / 不安全用户名 **0** / 带点号的正常用户名 0 / `data` 下不安全目录名 `[]` / 归一化逃逸目标 `C:\Users\Administrator\LQ-DataPrase\media\single` 不存在 ⇒ **本机无存量，不需要数据迁移** |
| E16 | E15 是**本机事实** | 探针跑的是 `config.settings.development` + `C:\Users\Administrator\LQ-DataPrase\media`。服务器（`bpsemi-CD`，见 `docs/tasks/todo.md` 升级条目）与打包装机是**另外两套库**，要引用 E15 前须在目标机重跑同一条命令 |

## 2. 刀一 · 拆 `duplicate-keep.spec.ts`

### 2.1 目标与非目标

目标只有一个：**把 591/600 还回余量，且不削弱任何一条既有判据**（§10 原话「别为凑行数砍判据」）。
拆完之后重复项这一族还要往里加 §5.4 续删、UX-1 锁定态、FIX-1 对照用例三批东西。

非目标，明确不做：
- **不改取数通路**。`frontend/e2e/helpers/cleanup.ts:34-47` 已经用 `page.request` + storageState 自动带 token，
  那是更干净的写法；但在一次拆分里同时改「谁调用」和「怎么调用」，红点就无法归因。通路统一另开工单。
- **不动其余 fetch 变体**。`view-data.spec.ts:22/:170/:184`、`settings/*.spec.ts`、`sftp/reconnect.spec.ts`、
  `batch/batch-phase.spec.ts:69`、`renderer-memory.spec.ts:90` 等各有形状差异（返回裁剪过的对象、走 `page.request`、
  带 PUT 断言），本刀一律不碰。E2 那条规则管的是**同形副本**。

### 2.2 归属切分

| 去处 | 内容 | 现在的行号 |
|---|---|---|
| 进 `helpers/apiClient.ts` | `apiGet`、`apiPost` | `:38`、`:48` |
| 进 `helpers/djangoShell.ts` | `shellDjango` | `:29` |
| 进 `helpers/repairCenterFlow.ts` | `openRepairCenter`（两半共用，留在任一 spec 里就是复制） | `:171` |
| 搬进新 spec | `DUP_PREFIX`、`DUP_CONTENT`、`dupDirs`、`seedDuplicatePair`、`dupEndState`、`dupRemainingBatches`、`cleanupDup` + 5 条重复项用例 + `:302-365` 那段分层说明 docblock | `:63-150`、`:302-576` |
| 两边各留一行（**不抽**） | `ADMIN_BATCH_DIR = path.join(DATA_DIR,'media','data',ACCOUNTS.admin.username,'batch')` | `:21` |

`ADMIN_BATCH_DIR` 刻意不抽：它是对既有 fixture 常量的一次拼装，不是行为复制；为它单开一个导出
就是拿 E2 那条「三条相似行好过过早抽象」反着做。
`PYTHON`/`PROJECT_ROOT` 随 `shellDjango` 进 `djangoShell.ts`，`apiClient.ts` 不需要它们。

### 2.3 helper 契约

- 三个新文件都用 `.ts`，与 `helpers/` 现有约定一致，且落在 `lint:e2e` 的覆盖面内
  （`frontend/tsconfig.e2e.json:22` `include: ["e2e/**/*.ts", ...]`，`:15-16` 开着 `noUnusedLocals`/`noUnusedParameters`
  ⇒ 拆完留下的死 import、失去调用者的助手会被 `npm run lint:e2e` 当场抓出，这条判据本刀**免费**拿到）。
- 函数体**逐字搬**（含注释里那些"为什么这么写"的部分：`apiGet` 返回 `{status, body}` 而非 throw、
  `shellDjango` 内层只用单引号外层双引号是为兼容 cmd、`cleanupDup` 先删 DB 行再删盘目录是返工轮 4② 的正解）。
  只有 `import` 行与 `Page` 类型标注随搬动调整。
- `djangoShell.ts` 与 `e2e/global-setup.ts:15-35` 的 `runDjango` **不合并**：后者跑的是子命令
  （`migrate`/`seed_users`）并显式注入 `LQDP_SYSTEM_CONFIG_FILE`、失败必须抛；前者跑 `shell -c` 且由调用方
  决定是否吞错（`repair-center.spec.ts:162-168` 就是刻意吞）。语义不同，合并会改掉 `globalSetup` 的失败策略。
- 新 spec 自带 `{ tag: ['@p2', '@data'] }`：`playwright.config.ts:124` 的 Edge 项目用
  `grepInvert: /@p[012]/` 排除带优先级的用例，标签丢了就会在两个项目里各跑一遍（同文件 `:114-115` 注释记过这笔账）。
- `describe.serial` 的语义只约束**文件内**次序。留下的 4 条继续 serial，`:578` 那句
  「serial 保证前 3 个用例已执行且 afterEach 已清理」仍然成立（它依赖的 3 条就是同文件的前 3 条，没被拆走）。

### 2.4 并发差异（本刀唯一真正的新风险）

拆成两个文件后，serial 档（E5：`workers ≤ 6`、`fullyParallel`）会让 `repair-center` 与 `duplicate-keep`
**同时**打同一个后端，其中包含 `manage.py shell` 的写事务。逐条判过：

1. **重复组计数不会被污染**：只有 `duplicate-keep.spec.ts` 播种重复组，且文件内 serial ⇒
   `toContainText('2 个')`、「按选择删除 3 个」这类全局计数判据不会互相插队。
   `:319-321` 写明的隐含前提（「本 slot 的种子数据贡献 0 个重复组」）在拆分后依旧只依赖种子，不依赖兄弟文件。
2. **SQLite 写写争用有承接**：E6 的 `busy_timeout=30000` 把「撞锁即失败」换成「等锁」，
   而 serial 档**本来**就有 6 个 worker 通过 HTTP 并发写同一个库（今天如此），
   新增的只是「另一个进程也来写」。
3. **收口档没有这个问题**：E4 的 slot 内 `--workers=1` 是串行的。
4. **既有先例**：`repair-center.spec.ts:247-248` 已经为跨 worker 干扰改过一次判据形状
   （`delete_orphaned_db` 全量语义 ⇒ 改成轮询 API 终态，不看卡片）。本刀不重犯这个错，也**不**新增依赖卡片全局计数。

判定：接受这个差异，不做额外串行化。若 serial 档实测出 `database is locked` 或重复组计数漂移的红，
就回到这一节，把两个文件用 Playwright 的 project 依赖或 `--grepInvert` 排到互斥批次，**不许**改成削判据。

### 2.5 判据与门禁

- 本刀**不新增产品判据**：9 条用例（4 留 + 5 搬）逐条同名同断言，承重不变。等价性由两件事证明：
  ① 拆前后各取一次**用例标题全集**再比集合相等 —— 拆前 `npx playwright test e2e/data/repair-center.spec.ts --list`
  一份，拆后对 `repair-center.spec.ts` 与 `duplicate-keep.spec.ts` 各取一份求并集，两个集合必须相等
  （机械闸，不靠眼看；标题漂了就说明有用例在搬动中丢了或被改写过）；② 拆后跑 E7 判出的档。
- E7：动 `frontend/e2e/helpers/` ⇒ **全量 e2e**。所以刀一 的收口验证是
  `node scripts/e2e_pool.mjs --slots=4` + `npm run lint:e2e` + `npx vitest run`（行数闸在内）+ 后端全套。
- 行数：拆后两文件的实际行数**现量再写台账**，不引用本稿的估算。

## 3. 刀二 · FIX-2 `..` 用户名上传逃逸（双层）

### 3.1 缺陷与真实边界

`apps/datafiles/views/_helpers.py:172-185` 把 `str(user.username)` 直接拼进
`MEDIA_ROOT/data/<username>/<file_type>` 并就地 `makedirs`；Django 默认 `UnicodeUsernameValidator`
实测接受 `..` ⇒ 拼出 `MEDIA_ROOT/data/../single`，归一化即 `MEDIA_ROOT/single`，上传路径逃逸用户目录。
同文件 `:173-180` 的 docstring 此刻是**假话**（原话写「Django 的校验器保证用户名对文件系统安全，
所以不做额外清洗」）。

E12 是要害：只按 §10 原案改 `UserCreateSerializer` 封不住 —— Django admin 后台、`seed_users`、
首启 bootstrap、`createsuperuser` 四条通路都不经过它。

### 3.2 两层形状

**第一层（根因，挡住新账号）** `apps/accounts/serializers.py` 的 `UserCreateSerializer` 加
`validate_username`，判据复用 `is_safe_username`；不合格 → DRF `ValidationError` →
400 + `username` 字段错（信封走 E14 的既有归一化）。
**不挡四条旁路的 serializer 层是故意的**：admin 表单/命令通路属于「运维自己造账号」，
第二层负责兜住它们，不去给 `BaseUserAdmin` 加定制、也不改 seed 命令。

**第二层（防御，让旁路失败得响亮而不是静默逃逸）** `_user_upload_dir` 在 `makedirs` 之前过
`is_safe_username`，不合格 → 抛新的领域异常。为什么不能直接 `raise ValueError`：E13 说得很清楚，
那会变成 500 + 前端一条「服务器内部错误」toast，而账号名不能当目录名**不是服务器坏了**。

领域异常与机器码：
- `apps/common/exceptions.py` 加 `UnsafeUsernameError(APIException)`（`status_code=400`、
  `default_code='unsafe_username'`），并在同文件 `_KNOWN_EXCEPTIONS:36-44` 注册
  `(UnsafeUsernameError, 'unsafe_username', '账号名无法用作数据目录名')` —— 用的就是那个映射表存在的目的，
  不新造机制。异常类放这个文件而不是 `apps/common/errors.py`：后者 docstring `:9` 明写
  「本模块只负责视图主动 return 的错误」，异常属于前者管。
- 24 处调用点（E9）**一处都不加 try**：靠处理器统一出信封。这是选它而不选逐处 `error_response` 的全部理由。

判据的唯一来源要搬位置：`is_safe_username` 现在住在 `apps/datafiles/`（E11），让
`apps/accounts/serializers.py` 去 import 它 = 让 accounts 的**产品主路径**依赖 datafiles
（今天只有 `apps/accounts/management/commands/seed_test_data.py:16` 这条开发工具链这么干）。
所以抽到 `apps/common/usernames.py`（`UNSAFE_USERNAMES` + `is_safe_username`），
改 2 处既有 import（`storage_usage.py`、`usage_views.py:11`），不留 re-export shim。

状态码取 400 而非 403：本仓的 403 是角色门禁（`permissions.py` 的 `FeaturePermission` →
`forbidden`），而这里跟权限无关，是这个账号自己无法寻址自己的数据目录。

### 3.3 各通路的失败形态（拆给验收看）

| 通路 | 改后行为 |
|---|---|
| HTTP：upload / batch-dirs 列·导入·删除 / 子批删除 / combine / uncombine / consistency-check / SFTP 各端点 | 400 `{code:'unsafe_username', message:'账号名无法用作数据目录名', detail:…}` |
| `apps/sftp/views.py:336-343`、`:376-379`、`:527-532` 这类 `except Exception` 包裹 | 领域异常被吞成既有 `sftp_download_failed` 信封 —— **仍然失败关闭**，只是机器码不如直连路径精确。收窄 `except` 不在本刀做（§4） |
| 后台作业 `apps/jobs/sftp_job.py:97`/`:159` | 异常冒进 job 的失败通路，作业记失败而非静默写到 `MEDIA_ROOT` |
| 命令 `seed_test_data.py:132`、`consolidate_uploads.py:78-83` | 非 HTTP 通路不经处理器 ⇒ 命令崩、非零退出、消息可读 |

### 3.4 存量：本机为零，别把它当全线结论

E15 的五个数 ⇒ 本机不需要数据迁移，也意味着第二层在**本机**不会打断任何现有账号。
但 E16 划了界：服务器与打包装机是另外两套库。运维口径写清楚：
这条改动把「`..` 账号静默写到 `MEDIA_ROOT`」换成「明确 400 + `unsafe_username`」——
在存在这种账号的装机上，那个账号的上传会**开始报错**，这是有意的 fail-closed，
不是新缺陷；处置办法是改名（`UserSerializer:26-32` 的 `username` 可写，仅管理员可达）
或停用。要改装机前先在那台机器上重跑 `tasks/probe_b4_dotdot_users.py`。

### 3.5 注释订正（两处，漏一处就是留假话）

1. `apps/datafiles/views/_helpers.py:173-180`：删掉「Django 校验器保证安全 ⇒ 不再清洗」那句，
   改成点名 `is_safe_username` + 为什么抛 `UnsafeUsernameError` 而不是 ValueError（E13）。
2. `apps/datafiles/storage_usage.py:72-73`：「已知同形状的老入口 `_helpers.py:172` 没挡这一条」
   在第二层落地后失效，要改成「老入口已挡，两侧共用同一判据」。

### 3.6 判据

T1（全部后端，不开浏览器）：
- `apps/accounts/tests.py`（现 498 行，余量 102）：① `POST /auth/users/ {"username": ".."}` → 400
  且 `username` 字段带错；② 带点号的正常账号 `a.b` → 仍 201、响应里 `username == 'a.b'`（E15 说本机没有这种账号，
  所以这条必须**造**出来，它证明的是白名单早退而不是「凡点号都拒」）；③ `.` 与空串同样 400。
- `test/backend/test_batch_dir_traversal.py`（现 176 行，与 `_safe_batch_dir` 的
  `test_rejects_parent_and_self_segments:41`、`test_import_rejects_dotdot:106` 同族，是这条防御的天然落点）：
  ④ `_user_upload_dir(不安全账号)` 抛 `UnsafeUsernameError` 且**不创建任何目录**（断完 `isdir` 为假）；
  ⑤ 经 API 打一次上传 → 400 + `code == 'unsafe_username'`（钉住 E14 的映射真的生效，
  而不是只证明了异常会抛）。
- **不许往 `apps/datafiles/tests.py` 加**：E10，它冻在 1959 行，多一行即红。
- 反向保护：既有的 `upload`/`batch-dirs` 全套用例必须照样绿（正常用户名不受影响）。

### 3.7 门禁

E8 ⇒ 碰 `apps/accounts/` 与 `apps/common/` 都是 `[GLOBAL]`：刀二**升全量档**，
`node scripts/e2e_pool.mjs --slots=4` + 后端全套 + `npx vitest run` + `npm run lint:e2e`，
不是「纯后端小改只跑 test:backend」。两刀各自一轮全量档的墙钟要提前认下来。

## 4. 明确不做

- sftp 那三处 `except Exception` 的收窄（会改变既有失败信封，属独立小批）。
- `User.username` 字段级 `validators` + `AlterField` 迁移（覆盖不到 `objects.create`/`get_or_create`，
  收益不抵一次迁移）。
- 存量账号改名/停用的自动工具（E15 本机零存量）。
- 前端 `ERROR_CODE_MAP` 新增 `unsafe_username` 键：处理器已把中文句子放进 `message`，
  再加一份就是 `apps/common/errors.py:24-25` 警告过的「两份必漂」。
- 把 e2e 取数通路统一成 `page.request`；抽 `useSelectFilter`；其余 fetch 变体收编。

## 5. 挂账（本稿不做，各有归属）

刀三 FIX-1 + FIX-4（§10 要求两者判据**分两条用例**，否则刷新时机与勾选保留会在同一条断言里互相掩盖）；
刀四 决策 D + `SettingsPage.vue:313` + 1280 日期面板覆盖右槽「查询」（待产品/UX 拍板修法形状）+
两项可推翻（`Stamp → Medal`、审计页 28px 收成 12px，各一行级、各补一轮聚焦测试）；
刀五 未封顶下拉两处（`CorrelationToolsTab.vue:36/:41`、`FileSelect.vue:2/:29`）+ 批1 遗留三项；
UX-1（§10.1，做之前先确认用户真要不要显式「锁定本组」）；FIX-3 机会主义两处。
另有 `C:\lqdp-e2e` 约 7.7 GB 测试盘残留是否清理（`docs/tasks/todo.md` 批2 遗留最后一条，等用户说）。

## 6. 分支与并入手续

两刀各一条过程分支，均从当时的 master 切出。FF 一律走 `git branch -f master <sha>`
（纯快进，零工作树变动，沿用 `docs/tasks/todo.md:184` 那条共享工作树先例），**不 push**
（`origin` 是公开仓库，master 现已 ahead 179）。
跑池之前先 `netstat` 确认 slot 基址端口没被别的会话占着（本仓第八类 e2e 红因就是他会话活池占端口）。
