# LQ-DataPrase 架构合理性评审

> 评审日期：2026-10-15
> 评审范围：`apps/`（Django 后端）、`config/`、`frontend/src/`、`electron/`、构建打包链路、测试基础设施
> 评审方式：源码与配置实测（`wc -l` / `grep` / 逐文件阅读），结论均附 `路径:行号` 证据
> 评审基线：`.claude/CLAUDE.md` 硬性约束 + `docs/tasks/lessons.md` R1–R8 + 全栈开发工程规范

---

## 1. 总体结论

**评级：B（良好偏上）。主干健康，模块边界清楚，工程纪律罕见地成熟；缺口集中在「声明了但没落地的层」与「生产化最后一公里」。**

一句话概括：这是一个**设计意图明确、自我约束严格**的项目，问题不在于「想不到」，而在于**若干层被声明后没有接线**——Celery/Redis/PostgreSQL 三件套在代码里占着位置却零使用，全局分页与过滤配置空转，健康检查靠开发期专属端点。这类问题不致命，但会持续误导每一个新读者（包括未来的自己和代理）对「系统实际是什么」的判断。

### 评分卡

| 维度 | 评级 | 一句话判据 |
|------|------|-----------|
| 模块边界与领域划分 | **A−** | 10 个 Django app 按业务领域切分，命名自解释，无循环依赖迹象 |
| 后端分层 | **C+** | 只切到「app 级」，无 repository 层；5 个 view 模块直接 import pandas |
| 前端分层 | **A−** | api/store/composables/components 职责清晰，重复样板已被抽象掉 |
| 配置与密钥管理 | **B+** | 分环境 + 启动期 fail-fast 守卫扎实；但 PG 分支是死代码且带硬编码密码 |
| 认证与权限 | **A−** | JWT 轮换 + 黑名单 + 15 项 RBAC，默认 fail-closed |
| 错误处理一致性 | **B−** | 有全局处理器，但视图内三套错误格式并存 |
| API 契约一致性 | **B−** | 前缀统一、OpenAPI 齐备；但分页/过滤全局配置空转，无统一响应壳 |
| 异步与任务 | **D** | Celery + Redis 全量声明，`@shared_task` 数量 **0** |
| 可观测性 | **C** | 无结构化日志、无 request id、无健康检查端点 |
| 生产就绪 | **C+** | 无 graceful shutdown、无限流 |
| 桌面打包架构 | **A−** | Electron 壳 + PyInstaller 后端，进程模型与路径收敛设计良好 |
| 可复现性 | **C** | 依赖全部 `>=` 未锁定、无 CI 配置 |
| 测试体系 | **A−** | T1/T2/T3 分层 + 并行 slot 池 + 标定门禁阈值，远超同类项目 |
| 文档与规范 | **B** | lessons/todo 极详尽，但 README / CLAUDE.md 多处与代码漂移 |
| 工作区卫生 | **C+** | 工作区约 1.7GB 调试残骸，`tasks/` 483 个文件 |

### 规模基线

| 指标 | 数值 |
|------|------|
| 后端 Python（`apps/` + `config/`，排除 migrations/`__pycache__`） | 35,047 行 |
| 前端 `src/`（`.vue` + `.ts`） | 34,480 行 |
| Django app 数 | 10 |
| 后端测试函数 | ≈1,515 |
| E2E 用例 | 73 spec / ≈376 test |
| 单元测试（vitest） | 9 spec |
| 超 600 行硬约束的业务文件 | **2**（后端 1 + 前端 1） |

---

## 2. 架构实况

### 2.1 分层实况（意图 vs 实际）

项目**声明的**目标是经典三层：`Controller → Service → Repository`。**实际落地**只到两层半：

```
实际：  URL 路由  →  ViewSet（含业务逻辑 + pandas + ORM）  →  services/（纯计算，部分 app 有）
理想：  URL 路由  →  ViewSet（仅解析/校验/序列化）        →  services/（业务编排）  →  repository/（数据访问）
```

- **无 repository 层**：10 个 app 中**没有任何一个**存在 repository/dao 模块。
- **views 直写数据管道**：`analysis/views/analysis_views.py:9`、`file_correlation_views.py:11`、`statistics_views.py:3`、`views/_helpers.py:7`、`datafiles/views/browse_views.py:7` 五个视图模块直接 `import pandas as pd`；视图层共出现 10 处 `read_csv` / `read_excel` / `pd.DataFrame`。
- **视图内联业务链**：`analysis_views.py:66-233` 的 `histogram` 在一个方法里完成了参数解析、6 个图表开关、CPK 阈值读取、过滤链、失败项集合计算、低 CPK 集合缓存。这是 690 行的直接来源。
- **services 只在部分 app 存在**：`analysis`（`services/statistics/` + `services/data_services/`）、`batch_report`、`dashboard`、`datafiles` 有；`accounts`、`common`、`export`、`gage` 无。

### 2.2 「声明了但没接线」清单（本次评审最重要的发现）

| 声明物 | 声明位置 | 实际状态 | 影响 |
|--------|---------|---------|------|
| Celery | `config/celery.py`、`base.py:57` INSTALLED_APPS、`base.py:202-207` CELERY_* 设置 | **0 个 `@shared_task` / `@app.task`**；`standalone.py:138` 直接从 INSTALLED_APPS 移除 celery | 依赖链多一个 `redis`、PyInstaller 需 exclude、README 让用户装 Redis，全是空转 |
| Redis | `requirements/base.txt` `redis>=5.0`、README「Redis 7+（可选）」 | 仅作 Celery broker，无其他用途 | 同上 |
| PostgreSQL | `base.py:116-125` 为**默认** DATABASES，硬编码 `ate_password` | `development.py:29` / `standalone.py:83` / `server.py:109` / `e2e_slot.py` **全部覆盖为 SQLite** | PG 分支为死代码；`psycopg2-binary` 为无用依赖；README「生产 PostgreSQL」与事实不符 |
| 全局分页 | `base.py:163-164` `DEFAULT_PAGINATION_CLASS` + `PAGE_SIZE=20` | 仅 `datafiles/views/file_views.py:90` 自定义分页生效，其余端点无分页 | 全局配置空转，读者误以为所有列表都分页 |
| 全局过滤/排序 | `base.py:165-169` `DEFAULT_FILTER_BACKENDS` | 仅 `file_views.py:94-96` 声明了 `filterset_fields` / `search_fields` / `ordering_fields` | 同上 |
| 限流 | 异常映射表里有 `Throttled` 分支 | **无 `DEFAULT_THROTTLE_CLASSES`**，登录端点（`accounts/views.py:56` 唯一 `AllowAny`）无爆破防护 | 真实缺口 |
| 健康检查 | — | **不存在** `/health` `/ready` | Electron 探针改探 `/api/v1/`；Playwright 探 `/api/schema/`（**standalone 已关闭**，见 `config/urls.py:27`） | 打包版没有专用探活通路 |

### 2.3 进程与部署模型

```
┌─ Electron 33（main.ts）────────────────────────────────────┐
│  单实例锁 · 菜单 · 日志重定向到 userData/logs/main.log        │
│  whenReady → 读 client-config → planStartup → spawn        │
└──────────────┬────────────────────────────────────────────┘
               │ spawn(process.resourcesPath/LQ-DataPrase.exe
               │       --port 0 --host 127.0.0.1,
               │       env LQDP_BASE_DIR=userData)
               │ 端口靠解析 stdout 正则 backend.ts:298
               │ 探活 HTTP 轮询 /api/v1/ 60s  backend.ts:151-188
               ▼
┌─ Django 4.2（PyInstaller onedir）──────────────────────────┐
│  config.settings.standalone（DEBUG=False · 仅回环绑定）      │
│  DRF + SimpleJWT · 全局异常处理器 · RBAC 15 项               │
│  业务：views 直连 pandas + ORM                              │
│  进程内并发：ProcessPoolExecutor（export 图表，Windows spawn）│
│              ThreadPoolExecutor（sftp 搜索）                 │
└──────────────┬────────────────────────────────────────────┘
               ▼
        SQLite（db.sqlite3，storage v2 落在 %USERPROFILE%\LQ-DataPrase）
```

**这个模型是合理的**。Electron 壳 + PyInstaller 后端 + 本地 HTTP 是成熟范式，且项目同时保留 `config/settings/server.py` + `requirements/production.txt`（gunicorn/whitenoise），说明存在**桌面单机 + 服务器多用户双目标**——这是选择 Django 而非 FastAPI 的正当理由，Django 的重量被双目标摊薄了。

值得肯定的设计：
- **端口选择用 `--port 0` 让 OS 分配**，再解析 stdout 拿回端口——避免了硬编码端口冲突。
- **`net-probe.ts` 刻意不 import electron**，以免污染前端 tsconfig。
- **SPA 由 Django catch-all 托管**，且路径穿越防护用了 `is_relative_to` 而非 `str.startswith`（`config/urls.py` 注释明确记录了 `frontend_dist_evil` 这个前缀绕过陷阱）。
- **storage v2 迁移有事务性保障**：copy → `_verify_sqlite`（大小 + `integrity_check`）→ 改写相对路径 → 删源，配 `_startup_lock`（msvcrt/fcntl，10s）防并发。
- **`secret.key` 与 `system_config.json` 固定在锚点目录不随迁移**——理由（密钥迁移风险 > 目录整洁收益）写在 `standalone.py:49-56`。

---

## 3. 做得好的地方（有证据）

1. **配置 fail-fast 是真守卫，不是口号**
   - `base.py:33-38`：`DEBUG=False` 且 SECRET_KEY 含 `django-insecure` → `ImproperlyConfigured`，且注释解释了「为什么这个文件默认 DEBUG=True」（它是被 import 的 mixin，硬设 False 会让所有 `manage.py` 在 development 覆盖之前就炸）。
   - `server.py:78` 拒绝 `ALLOWED_HOSTS=*`；`standalone.py:104-111` 拒绝非回环绑定 + 默认密码组合。

2. **认证与权限是 fail-closed 的**
   - `base.py:160-162` `DEFAULT_PERMISSION_CLASSES = IsAuthenticated`，注释点明「23 个 DRF 视图都显式声明了权限，这条只拦未来忘记声明的视图」——防的是**将来**的漏洞。
   - `base.py:173-186`：ACCESS 30min + REFRESH 7d + `ROTATE_REFRESH_TOKENS` + `BLACKLIST_AFTER_ROTATION`，并特别把 `token_blacklist` app 写进 INSTALLED_APPS 并注释「否则 blacklist() 被静默吞掉、旧 refresh token 永久有效」。
   - `accounts/permissions.py:21` `FeaturePermission` 以 `FEATURE_PERMISSIONS` 表驱动 15 项功能 × 3 角色的 RBAC。
   - `SIMPLE_JWT` 的 `LQDP_ACCESS_TOKEN_MINUTES` 环境变量附带一段实测记录（30min 前红率 1%、30min 后 90%），这是把「测试基建的约束」写进了生产配置并解释了为何不污染默认值。

3. **前端抽象层做得干净，重复已被消灭**
   - **单一 axios 实例**：`api/index.ts:46`，所有 api 文件 `import api from './index'`，无第二处 `axios.create`。
   - **baseURL 不硬编码**：`api/index.ts:36-44` 运行时取 Electron `window.__backendUrl__`，回退 `/api/v1`，并支持 `setApiBaseURL` 热切换。
   - **401 单飞刷新**：`api/index.ts:96-226` 用 `refreshPromise` 做单飞 + `_retry` 重试管线 + `NON_RETRY_AUTH_ENDPOINTS` 防循环；`authApi.refresh` 刻意用裸 axios 绕开拦截器（`api/auth.ts:1-17`）——这是正确做法。
   - **统一错误码→文案**：`utils/error.ts:14` `ERROR_CODE_MAP` 约 30 条 + `formatError`，拦截器 `toastError` 带 2 秒去重。
   - **重复样板已被抽象**：`composables/useAsyncData.ts`（74 行）统一 loading/error/try-catch/请求序号守卫，注释明言「解决 9+ 个 analysis composable 中重复样板」；`composables/useChart.ts`（322 行）统一 9 处图表初始化，**无任何 tab 裸调 `echarts.init`**——这直接落实了 lessons R7③。
   - **分析页装配与实现分离**：`AnalysisPage.vue` 仅 113 行纯装配，4 个 tab，14 个 composable + 30 个组件（其中图表 12 个）。

4. **状态泄漏做了双层防御（落实 lessons R5）**
   - `stores/analysisTabs.ts:81/96/113/137` 用「状态袋工厂 + reset」为 4 个 tab 各建独立 store，文件切换时显式 `reset()`，注释直接引用 lessons R5。
   - 多文件选择走 URL query（`analysisTabs.ts:143-176`）而非 localStorage，避免持久化污染。

5. **桌面安全面收敛得不错**
   - `preload.ts` 仅经 contextBridge 暴露 backendUrl 读写、open/save dialog、zoom、appVersion、platform、restartApp、client-config、菜单回调——**不暴露 fs / shell**。
   - `main.ts:234-242`：`contextIsolation: true`、`nodeIntegration: false`。
   - 打包版 SECRET_KEY 从锚点 `secret.key` 读取，无则 `get_random_secret_key()` 生成落盘（`standalone.py:155-167`）。

6. **测试基建是项目最强项**
   - **分层判据明确**（T1 后端契约 / T2 前端纯函数 / T3 浏览器不可替代），且「冲突裁决」规则写死了「同一判据 T1 与 T3 都能表达时 T1 写全组合，T3 只留一条接线证明」。
   - **并行 slot 池**：`scripts/e2e_pool.mjs` 用「预铸 TEMP 模板 → 按实测时长 LPT 分区 → N 个 1 进程=1 worker=1 slot 子进程」，slot 隔离靠 `DJANGO_SETTINGS_MODULE=e2e_slot` + `LQDP_E2E_SLOT_DIR`，端口基址 21001/22001，`MAX_SLOTS=6`。
   - **门禁阈值按实测标定**（`helpers/nightly-gates.mjs`）：墙钟 12min、单价 4.5s/例、效率 0.7×N、用例 450、flake 5，且崩池轮自判 `VOID (infra)` 退出码 3——**明确区分「指标不可信」与「真退化」**。
   - **效率只在无重跑轮次判**（`hasRetries`）——考虑到「失败 attempt 吃墙钟却不进分子」，这是很细的工程判断。
   - 全量 384 例从串行 19.7min 优化到 N=4 池 6.2min（效率 0.76×N），有实测表支撑。

7. **教训库是真实的组织资产**
   - `docs/tasks/lessons.md` 1,759 行 / 181KB，R1–R8 通用规则 + 按日期条目，且规定了「能归入 R 系列的不重复写」「超过 1 个月且被 R 系列吸收的移入 archive」。
   - 条目质量高，例如 2026-09-13 那条「删代码的五条取证规则」给出了可执行判据（先用调用链取证再决定删哪侧、删模块后必须 grep `.spec`/`.json`/`.yml` 里的悬空引用、纯删除批次以**精确用例数差值**当门禁而非只看 `OK`）——这是从真实事故（重复检测器把唯一 live 的 `gage_legacy_builder.py` 报成「10+ 处陈旧重复块」，照其结论删会搞坏导出）里提炼的。

---

## 4. 问题清单

### P0 — 结构性问题，建议本周处置

**P0-1 Celery / Redis / PostgreSQL 三件套是「幽灵基础设施」**

- 证据：`grep -c "shared_task|@app.task|@celery_app.task"` 在 `apps/` + `config/` 全量为 **0**；`config/celery.py` 只有 7 行样板；`standalone.py:138` 从 INSTALLED_APPS 移除 celery；`base.py:116-125` 的 PG 配置被 4 个环境文件全部覆盖为 SQLite。
- 影响：① 依赖链与文档告诉使用者「你需要 Redis / PostgreSQL」，而实际部署一个都不用；② PyInstaller 需专门 exclude 这些包，增加打包复杂度；③ 新读者（含代理）会按「有 Celery」的心智模型理解异步设计，而真实的异步是**Web 进程内的 ProcessPoolExecutor / ThreadPoolExecutor**。
- 处置：**二选一并立即执行**。推荐**删除**（`config/celery.py`、CELERY_* 设置、`celery`/`redis`/`psycopg2-binary` 依赖、README 相应段落），把「进程内进程池」这个真实的异步策略**显式写进 `apps/CLAUDE.md`**。若确有异步化计划，则应补至少一个真实 task，否则不如没有。

**P0-2 无健康检查端点，探活通路依赖开发期专属资源**

- 证据：全仓无 `/health` / `/ready`。Electron 探 `/api/v1/`（`backend.ts:151-188`，60s 超时）；Playwright 探 `/api/schema/`（`playwright.config.ts`），而该端点由 `config/urls.py:27` 的 `API_DOCS_ENABLED` 控制，**standalone 下已关闭**。
- 影响：打包版的「后端是否就绪」判定建立在一个语义模糊的路径上（根 API 返回什么才算 ready？）；探活能力与 API 文档开关耦合，属于意外的隐藏依赖。
- 处置：加 `/health`（liveness，恒 200）与 `/ready`（readiness，检查 DB 连接 + `data_dir` 可写 + 迁移是否完成），Electron 与 Playwright 统一改探它。成本约 30 行。

**P0-3 无 graceful shutdown**

- 证据：全仓无 `signal.signal` / `SIGTERM` 处理，仅 `export/chart_workers.py:25` 有个 `atexit` 清 matplotlib 临时目录。
- 影响：SQLite + 进程内进程池 + Electron 强杀子进程的组合下，写入中途被杀存在数据库损坏与临时文件泄漏风险。对一个**每天开关多次的桌面应用**，这不是理论风险。
- 处置：`standalone.py` 注册 SIGTERM/SIGINT → 停止接受新连接 → 等待在飞请求与进程池 → 关闭 DB 连接 → 退出；Electron 侧改 `kill('SIGTERM')` + 超时才 `SIGKILL`。

**P0-4 登录端点无限流**

- 证据：`base.py` 无 `DEFAULT_THROTTLE_CLASSES`（异常映射表里却有 `Throttled` 分支，说明曾考虑过）；`accounts/views.py:56` 是唯一的 `AllowAny` 视图。
- 影响：本地回环 + CORS 全开的组合下，任何本机网页都能对登录端点做字典爆破。
- 处置：给登录加 `AnonRateThrottle`（如 5/min），必要时全局挂 `UserRateThrottle`。

**P0-5 依赖未锁定，构建不可复现**

- 证据：`requirements/base.txt` 22 条**全部 `>=`，0 个 `==`**；无 `pyproject.toml` / lockfile / `.python-version` / `.nvmrc` / `engines`；版本要求只以 README 散文形式声明（「Python 3.11+ / Node 20+」）。
- 影响：对一个 **PyInstaller 打包分发**的应用，`pandas` / `numpy` / `matplotlib` / `Pillow` 的二进制兼容窗口很窄。今天能出的包，三个月后不一定能出；用户报的 bug 可能无法在你机器上复现。这是本清单里**风险最高的一条**，因为它在顺利时完全不可见。
- 处置：引入 `pip-tools`（`requirements.in` → `requirements.txt` 锁定）或 `uv lock`；补 `pyproject.toml` + `.python-version` + `package.json` 的 `engines`。

### P1 — 一致性债，建议本月消化

**P1-1 `analysis_views.py` 690 行破硬约束**

- 证据：`apps/analysis/views/analysis_views.py` 690 行（`.claude/CLAUDE.md:62` 规定 ≤600）。文件头注释自述「为 600 行上限已拆 `file_correlation_views` mixin」，**说明作者知道这条规则并已拆过一次，但本体仍超限**。
- 处置：把 `histogram`（:66-233，170 行）的参数解析 + 过滤链下沉到 `services/data_services/histogram.py`，视图只留「解析 → 调 service → 序列化」。这一刀预计能砍掉 200+ 行。
- 同类：`datafiles/views/file_views.py`(586)、`browse_views.py`(581)、`sftp/views.py`(562)、`gage/gage_legacy_builder.py`(561)、`sftp/search/runner.py`(560)、`scanners.py`(552) 均在 550–600 区间，**处于随时越界的临界状态**，建议一并规划拆分。

**P1-2 统计端点被拆到两个 ViewSet，契约无统一来源**

- 证据：`histogram`(`analysis_views.py:66`)、`qqplot`(:621)、`wafer_map`(:235)、`multi_lot`(:279) 在 `AnalysisViewSet`；`boxplot`(`statistics_views.py:280`)、`param_trend`(:396)、`correlation_matrix`(:185) 在 `StatisticsViewSet`。
- 影响：直接命中 lessons **R3①**——「相似端点守卫必须对齐，一个 400 一个 500 就是状态码雪崩温床」。同类统计端点分居两个类，守卫对齐只能靠人工 grep，漂移是时间问题。
- 处置：按「单文件分析 / 跨文件分析」而不是「历史原因」重新切分 ViewSet，或统一并入一个 ViewSet + mixin 分文件；并把参数守卫抽成共享的校验函数。

**P1-3 统计 service 双包并行、命名割裂**

- 证据：`services/statistics/`（`computations.py` 441 行含 boxplot/qqplot、`trends.py` 218 行含 param_trend、`distributions.py`、`kde.py`、`outliers.py`、`uph.py`、`site_yield.py`、`filters.py`、`helpers.py`、`downsample.py`）与 `services/data_services/`（`histogram.py`、`correlation.py`、`cpk_table.py`、`multi_lot.py`、`wafer_map.py`、`serial_distribution.py`）职责重叠。
- 更明确的一处重复：**`services/limits.py` 与 `services/statistics/limits.py` 同时存在**。
- 处置：合并为单一 `services/statistics/` 包（或按 `single_file/` / `cross_file/` 分），删除重复的 `limits.py`，统一命名。

**P1-4 `get_bin_column_name` 6 处实现**

- 证据：`services/statistics/helpers.py:22` + 5 个 parser（`parsers/base.py:30`、`cta8280f.py:94`、`cta8290d.py:94`、`ets88.py:169`、`sts8200.py:102`）。
- 影响：Bin 列名是解析与统计的**共享契约**，6 份字面量必然漂移（与 lessons 2026-09-19 那条「同一数值区间的三份字面量必然漂移」同构）。
- 处置：parser 的 `get_bin_column_name` 改为返回 `format_type` 声明，统一由 `helpers.get_bin_column_name(format_type)` 查表；补一条源码扫描用例断言两者一致。

**P1-5 视图内错误返回三套格式并存**

- 证据：全局处理器 `apps/common/exceptions.py:113` 统一为 `{code, message, detail}`，但视图内 71 处 `except` 写法不一：
  - `analysis_views.py:69` → `Response({'error': err}, status=400)`（**与全局格式冲突**）
  - `accounts/views.py:47` → 自定义 `_error(code, detail, status_code)` 包装（近似全局格式）
  - `common/views.py:32` → `raise serializers.ValidationError(...)`（走全局处理器，正确）
- 处置：定义 `AppError` 层级（`ValidationError` / `NotFoundError` / `UpstreamError`…），视图内一律 `raise`，由全局处理器统一序列化；把 `{'error': ...}` 写法清零。这也顺带解决前端 `ERROR_CODE_MAP` 需要兜底未知形状的问题。

**P1-6 无统一响应壳，前端类型与后端契约各写一份**

- 证据：端点多数直接 `Response(dict)`，无 wrapper；`api/datafiles.ts:4-252` 手写 14 个 interface、`api/auth.ts:19-67` 手写 6 个，与 `types/index.ts` 的公共契约分散重复。
- 影响：命中反模式 #18「前后端类型重复」。字段改名时无编译期报警。
- 处置：二选一——① 引入统一响应壳 `{code, message, data}` 让前端可泛型化；② 保留裸对象，但把 `api/*.ts` 的 interface 收敛进 `types/`，并由 `drf-spectacular` 导出的 OpenAPI 生成类型（项目已配 `DEFAULT_SCHEMA_CLASS`，具备条件）。方案 ② 改动面更小，推荐。

**P1-7 N+1 查询**

- 证据：`analysis_views.py:288` `for fid in file_ids: DataFile.objects.filter(pk=fid, owner=request.user).first()`；同文件 `:328`、`:406` 循环内再次 `.filter()`；`datafiles/views/_helpers.py:282-284` 循环内 `.filter()`。
- 处置：改用 `DataFile.objects.filter(pk__in=file_ids, owner=request.user).in_bulk()` 一次取回。**顺带注意权限**：当前写法每轮都带 `owner=request.user`，改造时必须保留该过滤条件（这是防线，不是冗余）。

**P1-8 全局分页/过滤配置空转**

- 证据：`base.py:163-169` 配了 `DEFAULT_PAGINATION_CLASS` / `PAGE_SIZE` / `DEFAULT_FILTER_BACKENDS`，但仅 `file_views.py:90-96` 落地。
- 处置：要么给需要分页的列表端点补 `filterset_fields` / 分页类，要么把全局配置删掉、改为显式声明——**空转的全局配置比没有更糟**，它制造错误的系统印象。

**P1-9 无 CI**

- 证据：无 `.github/`、无任何 workflow / Jenkinsfile；1,515 个后端用例 + 376 个 e2e 全部靠本地脚本；门禁脚本（`nightly-gates.mjs`）设计精良但只在本地夜间跑。
- 影响：lessons **R1** 的核心是「完成即提交，磁盘才是事实」，而 R1 描述的事故（改动未提交被 `git checkout .` 清空）恰恰是缺 CI 环境下的典型损失。
- 处置：哪怕最小配置——push 触发 `python manage.py test` + `npm run build` + `npm run lint:e2e` + `test:unit`；e2e 全量留给夜间本地轮。

**P1-10 文档与代码漂移（4 处已确认）**

| 文档声明 | 代码事实 |
|---------|---------|
| README「asar 已禁用」 | `electron-builder.yml:90` `asar: true` |
| README「数据库：PostgreSQL（生产）」 | `standalone.py:83` / `server.py:109` 均为 SQLite |
| README「`ALLOWED_HOSTS` 默认 `*`」 | `standalone.py:73` 为 `localhost,127.0.0.1,[::1]` |
| `frontend/CLAUDE.md:7,50` 引用 `styles/variables.css` | 该文件已于 2026-08-29 删除，现为 `styles/design-tokens.css` |
| `docs/reference/version-management.md:5`「当前 0.2.0」 | `frontend/package.json` 实为 `0.7.0` |

- 影响：`frontend/CLAUDE.md` 是**代理必读**文件，其中的文件名错误会直接把改动引到不存在的路径上——这正是「教训库里记录过的坑」的同类（文档漂移比代码 bug 更难发现）。
- 处置：以代码为唯一事实来源回写这 5 处；并考虑在 CI 加一条「文档引用的路径是否存在」的检查。

### P2 — 卫生与长期项

- **P2-1 工作区约 1.7GB 残骸**：`tasks/` 483 文件 / 58M（166 log、97 截图、一次性探针 py）、`Data/` 930M、`media/` 722M、`frontend/playwright-report` 19M、`test/screenshots_night` 13M。根目录 `db.sqlite3`(3.1M) + `db.sqlite3.bak-e2e-90612`(3.4M) + `system_config.json`（内含写死的个人绝对路径 `C:\Users\Administrator\LQ-DataPrase`）。**均已 gitignore 未入库**，但影响检索速度与磁盘。另 `scripts/generate_icon.py` 与 `scripts/gen-icon.ico.js` 功能重复（旧/新），`docs/tasks/lessons.bak-2026-08-30.md` 为合并残档。
- **P2-2 前端 35 个文件超 300 行**（项目自定规范）：唯一破 600 的是 `pages/data/DataBrowserAgGrid.vue`(674)。次高 `sftp/components/SearchCriteria.vue`(582)、`analysis/components/WaferMapPanel.vue`(560)。`DataBrowserAgGrid.vue` 已拆出 `DataBrowserToolbar` / `DataQualityBar`，继续按 toolbar / 表格 / 详情三块下沉即可。
- **P2-3 `apps/common` 是杂物间**：`exceptions` / `params` / `system_config` / `backup` / `export_naming` / `file_loading` / `user_settings` / `db_pragmas` / `constants`，无 `models.py`、无领域归属。建议把 `system_config` + `backup`（存储与备份，有独立测试 `tests_system_paths.py`）独立为 `apps/storage`，其余按消费方下放。
- **P2-4 主题 token 不对称**：`styles/design-tokens.css` light 变量 30 个 vs night 57 个；`element-plus-theme.css` 有 77 处 `!important`。命中 lessons **R7①**「night/light 块必须对称，否则 light 显示出厂色而非品牌色」。建议做一轮 token 对称化盘点。
- **P2-5 token 存 localStorage**：`stores/auth.ts:15-16`、`api/index.ts:86`（读写经 `utils/safeStorage.ts` 封装防白屏）。命中反模式 #12。在 Electron + `contextIsolation` + 无远程内容的场景下风险可控（无第三方脚本注入面），但一旦将来引入富文本/外链渲染就会变成真实漏洞。建议列为「引入任何 HTML 注入面之前必须处理」的前置条件，而非立即改。
- **P2-6 CORS 全开（已知债，已有修复方案）**：`base.py:83` `CORS_ALLOW_ALL_ORIGINS = True`，注释完整解释了成因（Electron `loadFile()` 的 Origin 为 `null`，生产请求必然跨域）与正确修法（改由 Django 以 `http://` 同源托管 SPA，然后彻底关闭 CORS），并声明了残余风险（恶意网页仍可触达回环 API，只是无 token 无法认证）。**这是一处「已记录、已评估、待排期」的债**，处置前必须验证真实安装包，不宜盲改。
- **P2-7 测试文件同样受 600 行约束影响**：`apps/datafiles/tests.py` 1,965 行，`apps/analysis/tests_file_correlation.py` 560、`tests_param_guards.py` 554、`tests_chart_config.py` 520。且测试散落在两处（`apps/*/tests*.py` 42 个 + `test/backend/` 68 个）。建议测试统一到 `test/backend/` 并按被测模块拆分，同时让 `apps/*/tests.py` 只保留极薄的入口。

---

## 5. 建议路线图

| 优先级 | 动作 | 预期收益 | 风险 |
|--------|------|---------|------|
| P0 | 处置幽灵基础设施（删 Celery/Redis/PG 死分支，或补真实 task）；把「进程内进程池」写进 `apps/CLAUDE.md` | 消除最大的认知误导，依赖链瘦身，打包简化 | 低（纯删除） |
| P0 | 加 `/health` + `/ready`，Electron/Playwright 改探 | 打包版探活语义明确，解耦 API 文档开关 | 低 |
| P0 | 加 SIGTERM/SIGINT graceful shutdown | 消除 SQLite 写入中途被杀的损坏风险 | 中（需实测） |
| P0 | 登录端点限流 | 堵住本机爆破面 | 低 |
| P0 | 依赖锁定 + `pyproject.toml` + `.python-version` + `engines` | 构建可复现，这是分发型应用的底线 | 低 |
| P1 | 拆 `analysis_views.py`（histogram 下沉 service） | 回到 600 行约束内，视图层变薄 | 中（需回归 e2e analysis 36 spec） |
| P1 | 统一统计端点契约与 ViewSet 切分；合并统计 service 双包；删重复 `limits.py` | 落实 R3①，消除守卫漂移温床 | 中 |
| P1 | `get_bin_column_name` 收敛为 1 处 + 源码扫描用例 | 消除 6 份字面量漂移 | 低 |
| P1 | 统一视图错误为 `raise AppError`，清掉 `{'error': ...}` | 前后端错误契约一致 | 中（71 处 except 需逐一看） |
| P1 | 修 N+1（`in_bulk`，保留 owner 过滤） | 多文件分析响应时间下降 | 低 |
| P1 | 补最小 CI（test + build + lint:e2e + test:unit） | 落实 R1「磁盘才是事实」 | 低 |
| P1 | 回写 5 处文档漂移 | 阻止代理被错误路径误导 | 低 |
| P2 | 清理工作区残骸；拆 `apps/common`；主题 token 对称化；前端 300 行拆分 | 可维护性 | 低 |

---

## 6. 结论

**这套架构的核心判断是对的**：按领域切 app、配置分环境并 fail-fast、权限默认拒绝、前端抽象到位、测试分层且门禁有实测标定——这些都是成熟团队才会做且坚持做的选择。600 行硬约束在 35,047 + 34,480 行的规模下只有 2 处破线，本身就是强证据。

**真正需要处理的是三类问题**：

1. **幽灵层**（Celery / Redis / PostgreSQL / 全局分页过滤）：声明了但没接线。它们不产生 bug，但持续输出错误的系统心智模型——这是架构评审里最容易被低估、也最值得优先清理的一类债。
2. **后端分层停在 app 级**：没有 repository 层，views 直接握 pandas 与 ORM，业务链内联。690 行的 `analysis_views.py` 和 N+1 都是这一件事的症状，不是独立问题。
3. **生产化最后一公里**：健康检查、graceful shutdown、限流、依赖锁定。桌面分发应用对这几项的要求比 Web 服务更硬——用户机器上的崩溃你无法登上去排查。

**不需要动的**：Electron + PyInstaller 的进程模型、storage v2 的路径收敛、双 settings 目标（standalone/server）、以及整套 e2e 并行池与门禁设计。这些是项目的资产，改动它们只会引入新风险。

---

## 附录：P0 落地记录（2026-10-15 同日完成，提交 `62ac05d`）

本报告 P0 五项已全部实施。**实施期间的侦察推翻了两条原始结论**，在此更正，以免后人按旧版行事：

| 原报告结论 | 实测事实 | 处置 |
|-----------|---------|------|
| 「Celery / Redis 依赖链空转」 | **Redis 不是幽灵层** —— `apps/sftp/cache.py:15-22` 真用它做可选共享会话缓存（带 LocMemCache 回落），`REDIS_URL`/`SFTP_SESSION_REDIS_URL` 是活配置 | 只删 Celery；**保留 Redis** 并注明其唯一消费者 |
| 「登录端点无限流」 | `apps/accounts/views.py:24-25` **已有**账号级锁定（5 次失败 → `423 LOCKED` + 锁 15 分钟，含 `remaining_attempts`/`retry_after_minutes`） | 降级为「补 IP 维度」，非从零开始 |

**新增交付物**

- `apps/common/health.py`（142 行）—— `/api/v1/health/`（liveness，恒 200，零 DB 查询，用 `assertNumQueries(0)` 钉住）与 `/api/v1/ready/`（readiness：DB / 目录可写 / 迁移，失败 503 + 逐项 `ok`，`DEBUG=False` 下抹掉 detail）。两者 `AllowAny` 且**不限流**：宿主必须在任何用户登录前就能轮询，而探针被 429 时调用方分不清「后端没起来」与「被限流」。
- `apps/common/shutdown.py`（220 行）—— SIGTERM/SIGINT 处理器 + `POST /api/v1/system/shutdown/`（回环来源 + 一次性令牌双闸门，未配令牌返回 404）。
- `requirements/build.txt`、`pyproject.toml`、`.python-version`；T1 层测试 24 例（`test/backend/test_{health_probes,login_throttle,shutdown}.py`）。

**实施中发现的新问题（原报告未覆盖）**

1. **Windows 上 `child.kill('SIGTERM')` 不触发任何 Python 处理器**（Node 用 `TerminateProcess` 实现）。`backend.ts` 的 `stopBackend()` 读起来像已实现优雅关闭，但后端那半根本不存在 —— 打包版此前退出时**从不关数据库连接**。这是 P0-3 采用 HTTP 令牌端点而非纯信号处理的直接原因。
2. **`whitenoise` 声明位置错误**：`standalone.py:116` 依赖它、`lq_dataprase.spec:197` 显式列它，但它只在 `production.txt`，而 README 让用户 `pip install -r requirements/base.txt` → 桌面版依赖声明缺失，靠「环境里恰好装了」侥幸通过。已移入 `base.txt`。
3. **venv 实测 Django 6.0.5**，而 README / `apps/CLAUDE.md` 都写「Django 4.2」，`requirements` 写 `>=4.2,<7.0` —— 差两个大版本，且流水线无从察觉。
4. **`AGENTS.md` 指向一个不在仓库里的文件**：它把 `.claude/CLAUDE.md` 列为「会话开始必读」，但 `.gitignore:148` 附近有意忽略了 `.claude/CLAUDE.md`、`apps/CLAUDE.md`、`frontend/CLAUDE.md`（注释：「AI 助手与样式指南文档」）。新克隆者会拿到一个指向不存在文件的入口。**属仓库策略问题，未处理，待决策。**
5. **本机跑后端全量必须带 `CODEBUDDY_SAFE_DELETE_ENABLED=0`**：沙箱的 bulk-delete guard 会抛 `SystemExit`（不继承 `Exception`，各测试的 `except OSError` 接不住），一次跑出 52 errors + 9 failures 且两次跑红数不同。带上后同一棵树 1459 例全绿。已写进 `docs/tasks/lessons.md`。

**验证**：后端全量 1459 例 OK（skipped=7）· 新增 T1 24 例 · `npm run build` ✓ · vitest 118 例 ✓ · `lint:e2e` ✓ · `electron:build:ts`（strict）✓ · 真实 HTTP 探针 200/200/404 ✓ · 优雅关闭端到端 200 → **进程 100ms 内自行退出，未被强杀** ✓。

**未完成**：全量 e2e 未跑（项目约定需先征询；且本沙箱不允许 spawn `cmd.exe`，非 slot 模式必然在 `global-setup.ts` 报 `EBUSY` —— 但 webServer 已成功起 Django+Vite 并进入 globalSetup，**这本身证明新探针通过了**）。P1 各项（`analysis_views.py` 690 行、统计 service 双包、`get_bin_column_name` 6 处、视图错误三套格式、N+1）本轮未动。
