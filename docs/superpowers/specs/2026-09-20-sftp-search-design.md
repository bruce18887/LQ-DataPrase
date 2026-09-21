# SFTP 浏览器搜索子系统（2026-09-20）

> 来源：用户需求「为 SFTP 浏览器做一个功能强大的搜索功能，参考 `DataPrase-SFTP Searcher/`」。
> 6 项决策已逐项拍板（见 §1.2）。实现计划另出（writing-plans）。
> 本文 file:line 为 2026-09-20 HEAD 快照，均已回读源码核实。
> 2026-09-21 按后端实施（Task 1–9）回写若干处：§2.5、§2.6、§3.1、§3.2、§3.3、§3.4、§3.5、§3.6、§4.1、§6、§7。
> 其中 §3.5 一条**纠正了本文原来的一个前提**。新增引用以函数名为准（行号会随实施漂移）。
> 同日再纠一次：**上一轮那条 §3.5「纠正」（真数据 56/56 在 `[DATA]` 与表头间夹空行、参考工具对
> 真数据必然读出 0 值）本身是错的——空行方位记反了，它在标记之前（49/56），标记之后紧跟表头
> （56/56）**。§2.6 与 §3.5 已按原始字节复算结果改写，`scanners.py` 的跳过空行降级为防御性容错。

## 1. 需求与决策

### 1.1 用户原文

「为我当前项目的 SFTP 浏览器想一个功能强大的搜索功能，功能上可以参考一点
`C:\\Users\\Administrator\\Desktop\\DataPrase\\LQ-DataPrase\\DataPrase-SFTP Searcher`」

过程中的两条补充要求：

- 「如果我需要递归指定路径所有文件夹呢」→ 递归深度不设实用上限，改为条目预算 + deadline 兜底。
- 「我想要长期驻留」→ 搜索结果与运行状态跨路由/跨页面驻留，所有权从组件移到 Pinia store。

### 1.2 已拍板决策（2026-09-20，AskUserQuestion）

| 决策点 | 结论 |
|---|---|
| 搜索核心命中条件 | **三层合一**：作用域 + 元数据过滤为底座，其上叠加单一命中模式（仅文件名 / 内容含 / 列值含），可组合 |
| 搜索量级 | **差异极大两者都有**（几十～十万级），设计必须能自适应降级，不得假定量级固定 |
| 结果落地动作 | **勾选后下载 / 下载并解析** + **导出结果 + 保存搜索预设**（未选「看命中上下文」「送入文件关联」） |
| 并发模型 | **独占传输 + 内部并行**：搜索算一种传输、与下载互斥；搜索内部自开 N 条临时连接并行扫（默认 4，上限 8），不碰池连接 |
| 架构方案 | **方案 A，含服务端 grep 加速档**（能力探测 + 透明回落） |
| 驻留边界 | **本次应用生命周期内驻留**（跨路由/跨页面/后台常驻），不跨应用重启；要长期保留用「存为预设」复跑 |
| 递归控制 | **排除模式 `prune_dirs` + 浅递归档位**（`self`/`children`/`all`/`custom`） |
| pool 无锁前提 | **本次一并补 per-user `RLock`**（§2.5 核实其无锁前提在桌面版已失效） |

## 2. 现状与根因

### 2.1 后端：零搜索能力

- `apps/sftp/` 无 `services/` 子包，业务逻辑扁平放置。现有 13 个端点
  （`apps/sftp/views.py:43` `SftpViewSet(SftpConfigMixin, viewsets.GenericViewSet)`、
  `apps/sftp/config_views.py:16`），**没有任何一个与搜索相关**。
- 唯一列目录接口 `list_files`（`apps/sftp/views.py:212`）是**单层** `sftp.listdir_attr(path)`，
  返回 `{path, items:[{name,is_dir,size,mtime}]}`，无 `recursive` 参数、无分页，排序在内存做。
- 唯一已存在的递归遍历是 `apps/sftp/views.py:537` `_collect_files()`——目录下载专用：
  深度优先递归、跳过 `.` 开头条目、`only_data` 时排除非 `.csv` 与汇总 CSV
  （`_is_summary_csv` 从 `apps.datafiles.views` 导入，见 `apps/sftp/views.py:11`）。
  它**无深度上限、无节点上限、无取消检查**，且耦合在视图方法上，不宜直接改造为搜索引擎。
- **600 行硬上限**（`.claude/CLAUDE.md` 末段）：`apps/sftp/views.py` 现 **561 行**，仅剩 39 行余量。
  搜索**必须开新模块**，沿用 `config_views.py` 的 mixin 抽离手法。

### 2.2 长任务模式：全项目只有 SSE 一种

- 排除项（均已核实）：**Celery** 在打包版被移除（`config/settings/standalone.py` 明示 standalone
  模式去除 celery），且 `apps/` 下 `shared_task|@app.task|delay(` 零命中；**WebSocket/channels** 零命中；
  **线程 + 轮询 job store** 不存在（无任务模型、无 progress 字段）。
- `StreamingHttpResponse` 在 `apps/` 下**只有 `apps/sftp/views.py` 使用**。现成可复用件：
  `apps/sftp/downloads.py:328` `download_events_to_sse(events)`（已与业务无关，可直接 import）、
  `apps/sftp/downloads.py:44` `clamp_timeout()` 的钳位范式、SSE 响应头
  `Cache-Control: no-cache` + `X-Accel-Buffering: no`。
- 取消链路现状：前端 `AbortController.abort()` → fetch 中断 → 后端生成器收 `GeneratorExit`
  （`apps/sftp/downloads.py:166-170` 单文件版、`:307-312` 目录版）→ 清半截文件 + `pool.invalidate`。
  `postSse` 把 AbortError 静默吞掉（`frontend/src/api/sftp.ts:210` 起），所以
  **取消后必须显式复位状态 ref**（`frontend/src/pages/sftp/SftpBrowser.vue:149` `startCooldown`、
  取消冷却 1.2s 的注释说明了为何 abort 后不能立刻开下一次传输）。

### 2.3 连接模型

- `apps/sftp/pool.py:55` `_pool: Dict[object, _Entry] = {}`，**key = user_id，一人一条连接**；
  `:98` `get_connection(user_id)`；`_Entry` 只存 `transport / sftp / last_used`，**没有 `SSHClient`**。
- `apps/sftp/pool.py:17` 自述：「This is **lock-free by design**. The deployment runs gunicorn with
  *sync* workers」，并注明若换成 gthread/gevent 则 **MUST grow a per-user lock**。
- 09-09 已拍板「同时只允许一个下载、不做后端锁」，互斥是**纯前端** computed 实现
  （`frontend/src/pages/sftp/SftpBrowser.vue:171` `transferActive`），后端零锁。
- 凭据可在服务端取回：`apps/sftp/cache.py:134` `get_session(user_id)` 返回含明文密码的 dict，
  故**新开连接无需前端回传密码**。
- 主机密钥契约：`apps/sftp/host_keys.py:182` `open_verified_transport(host, port, username, password)`
  走 TOFU 校验。**任何新开连接的代码都必须经它**。

### 2.4 前端现状

- 页面 `frontend/src/pages/sftp/SftpBrowser.vue` 现 **545 行**（600 上限），**单栏顺序布局**：
  工具栏 → 批量操作 → 进度卡 ×2 → 文件表 → 统计条。**没有目录树**，导航全靠面包屑 + 点目录行。
- 文件表是 `el-table`（`components/SftpFileTable.vue`，193 行），排序走服务端（`sortable="custom"`）。
- 已有搜索框，但只做**当前已加载目录的本地子串过滤**：`SftpBrowser.vue:201` `filteredItems`。
- 已有进度卡 `components/SftpDownloadProgress.vue`（112 行），但它的 `mode` 契约是
  `file | dir` **两种百分比语义**，取消按钮 class `.dl-cancel-btn` 有 e2e 依赖。
- 导出基建现成：`frontend/src/utils/download.ts:41` `downloadBlob(data, filename)`，
  Electron 下已被其它导出功能验证可用。

### 2.5 本次核实出的存量前提失效（重要）

`standalone.py:224` 以 `call_command('runserver', ..., '--noreload')` 启动后端。
已安装 **Django 6.0.5**，其 `runserver` 的 `--nothreading` 是 `action="store_false"
dest="use_threading"`（默认 True），`django/core/servers/basehttp.py:261-264` 在 `threading`
为真时套上 `socketserver.ThreadingMixIn`。

**结论：桌面版后端是多线程的，而 `pool.py` 的无锁前提建立在「sync worker 不会并发」之上——
该前提在桌面版现在就不成立。** 具体暴露面：下载 SSE 生成器与 `list_files` 在同一用户下
可分属两个线程、共用同一条非线程安全的 paramiko `SFTPClient`；`channel_timeout`
（`apps/sftp/downloads.py:53` 起）还会互相改同一条 channel 的 socket 超时。
09-09 spec 当时把「下载进行中禁用目录导航」列为范围外、注明「竞态保留现状」，
所以这是一个**已知但未修**的存量缺陷，不是本次新增。

本次一并补 per-user `RLock`（§3.12）。

**该结论已被实施确认，且已修**：Task 1 落地 per-user `RLock`（commit `d99745d`），
锁只覆盖池自身的状态转换。配套的并发测试给假握手加了 0.05s sleep
（`test/backend/test_sftp_pool_lock.py` 的 `BUILD_DELAY`）——**没有这个 sleep 就等于
无锁也测不出红**，写这类测试时必须带上。

### 2.6 参考工具可复用资产

`DataPrase-SFTP Searcher/`（未跟踪目录，2026-09-20 新建的 CLI 原型）：

| 文件 | 能力 | 处置 |
|---|---|---|
| `search/csv_content_searcher.py` | 1MB 大块读 + paramiko prefetch 流水线 + 原始字节多编码匹配 + 命中即停 + 滚动窗口行号计数 + ATE 表头元数据解析 + 编码四探 | **移植为扫描内核主体** |
| 同上 `server_grep_supported` / `search_via_server` / `_build_grep_command` | 服务端 grep 快路径（含 chroot 路径映射验证、GBK `$'..'` bashism） | 移植，但**收紧启用条件**（§3.3） |
| 同上 `search_in_files` / `_open_connection` / `_recycle` | 每 worker 一条独立连接、连接坏了重开并重试一次 | 移植为 `connect.py` |
| `search/file_retriever.py` | 递归遍历 + `fnmatch` + 扩展名/大小/日期过滤 | 移植，但**遍历结构改 BFS**（§3.4） |
| `search/csv_column_reader.py` | `[DATA]` section 定位 + 表头取列 + 前 N 有效值 | 移植为列值模式，其「`[DATA]` 后首行即表头」的读法经复算在真实数据上成立（56/56 表头紧跟标记），照搬即可（§3.5） |
| `utils/cli_interface.py` | worker 数钳位 1–8、实时 summary、导出、文件名合法性校验 | 取钳位区间与导出思路 |
| `config/sftp_connection.py:21` | `set_missing_host_key_policy(paramiko.AutoAddPolicy())` | **不移植**，必须换成 `host_keys.open_verified_transport()` |

## 3. 方案

### 3.1 模块边界与行数预算

后端全部新增，`apps/sftp/views.py` 的 561 行**一行不动**：

| 文件 | 预算 / 实际 | 单一职责 |
|---|---|---|
| `apps/sftp/search/contracts.py` | ~170 / **360** | `SearchSpec` dataclass、`parse_spec()` 校验与钳位、`limits_hit` 记录 |
| `apps/sftp/search/connect.py` | ~130 / **227** | `SearchSession`：借还 N 条独立连接、降级、`opened/closed` 计数、统一关闭 |
| `apps/sftp/search/walker.py` | ~190 / **313** | BFS 目录队列、深度/条目/候选上限、环保护、`prune_dirs`、元数据过滤 |
| `apps/sftp/search/filters.py` | — / **118** | walker 与 `shell_grep` **共享**的条目判定谓词 + glob 常量 + `needs_find`（新增，见下） |
| `apps/sftp/search/scanners.py` | ~270 / **485** | 内容扫描（字节级 + prefetch + 编码探测 + 命中即停）与列值扫描 |
| `apps/sftp/search/shell_grep.py` | ~180 / **421** | 三级能力探测、grep 命令构造（全 token `shlex.quote`）、输出解析、exec 通道 |
| `apps/sftp/search/engine.py` | ~290 / 106 | `select_engine()` 谓词、阶段机、线程池、事件队列、取消、进度节流（实际列只含谓词，阶段机未写） |
| `apps/sftp/search_views.py` | ~200 / 未落地 | `SftpSearchMixin`：`POST /sftp/search/`（SSE）+ 预设 CRUD |
| `apps/sftp/models.py` | +30 / 未落地 | `SftpSearchPreset` + 迁移 |

**预算不是承诺**（2026-09-21 实施快照）：实际普遍超预算（上表加粗列），**全部仍在 600 硬上限内**，
最紧的 `scanners.py` 也还剩 115 行余量。超出的原因是「平价」这件事比预估吃行数——
每条 grep 表达不出来的判据都要么翻译成 glob、要么补一条回落条件。
`apps/sftp/search/filters.py` 是**实施时新增的一行**（本文 2026-09-20 版没有它）：
dot 条目 / 汇总 CSV / 数据 CSV 三条判定 + 它们在 grep 与 find 两侧的 glob 写法 + `needs_find`，
walker 直接调谓词、`shell_grep` 只调这里的 glob 常量，**两档引擎同一套过滤规则的单一事实源**
（§3.3 平价的地基；判据在两处各写一份就会漂移，「换服务器换结果集」重新变成可能）。
测试侧同样因 600 上限拆分：`test/backend/test_sftp_search_parity.py`（§4.1）。

切分着力点：**`walker` / `scanners` / `shell_grep` 只吃 spec、只吐事件，不知道 Django 也不知道彼此**，
可脱离 ORM 单测。`engine.py` 是唯一持有「阶段」概念的地方。

前端：

| 文件 | 预算 | 职责 |
|---|---|---|
| `frontend/src/stores/sftpSearch.ts` | ~190 | 流的所有权、`spec`/`status`/`results`/`progress`/`notices`/`AbortController`、会话内运行历史（留 20 条） |
| `frontend/src/pages/sftp/SftpSearchPage.vue` | ~210 | 路由页，从 store 组装条件区 + 结果区 + 进度 |
| `frontend/src/pages/sftp/components/SearchCriteria.vue` | ~260 | 条件表单（含深度档位、`prune_dirs`、预设选择） |
| `frontend/src/pages/sftp/components/SearchResultsTable.vue` | ~270 | AG Grid 结果表 + 分组开关 + 勾选 + 动作 |
| `frontend/src/pages/sftp/components/SearchProgress.vue` | ~100 | 三态进度（计数 / 百分比 / 不定档）+ 取消 |
| `frontend/src/components/common/ActiveSearchChip.vue` | ~80 | App 级 header 常驻指示器，跨页面可见可控 |
| `frontend/src/api/sftpSearch.ts` | ~150 | 类型 + `POST /sftp/search/` 消费 + 预设 CRUD |
| `frontend/src/utils/sftpSearchExport.ts` | ~80 | CSV 序列化（RFC 4180 转义 + UTF-8 BOM）→ `downloadBlob` |
| `frontend/src/utils/ssePost.ts` | ~60 | 从 `api/sftp.ts:210` 的 `postSse` 提取为共享件 |

两处顺手修正（属于「改进你在其中的代码」，不扩范围）：

1. `postSse` 现埋在 `frontend/src/api/sftp.ts:210` 未导出 → 提到 `utils/ssePost.ts`，
   搜索与现有两个下载流共用一份，避免第三份复制。
2. `api/sftp.ts:110` 与 `:186` 都发送 `only_data`，而 `download_dir`（`views.py:537` 的
   `_collect_files` 调用处）**从不读它**，传值完全无效。本次不改这个既有契约腐化点
   （它需要独立决策：要么后端接、要么前端删），但**搜索以「拒绝未知键」防止同类问题再产生**（§3.2）。

`SftpBrowser.vue` 545 → 约 557 行（+「高级搜索」跳转按钮、+目录行右键菜单项、
`transferActive` 增加 `searchActive` 支路）。**本功能做完后该文件接近饱和**，
后续再往 SFTP 页加东西必须先拆。

> 分批顺序由 writing-plans 定。本文只钉一条依赖关系：**§3.12 的 pool 锁必须排在最前且单独成批**，
> 因为后面「搜索期间浏览可用」的承诺依赖它；`contracts.py` + `walker.py`（`mode="name"`
> 端到端可跑）是第二个可交付批，届时前端已能第一次真机验证。

### 3.2 SearchSpec 契约

`POST /api/v1/sftp/search/`，请求体（JSON）：

```jsonc
{
  // —— 作用域 ——
  "roots": ["/datalogs/2026Q3"],       // 必填 1~20 条绝对路径
  "depth": "all",                      // "self" | "children" | "all" | "custom"
  "max_depth": null,                   // 仅 depth="custom" 生效，硬顶 64
  "prune_dirs": ["*backup*", "*_old"], // fnmatch 只匹目录 basename，命中则整个子树不进入

  // —— 元数据过滤（三模式共用底座）——
  "name_pattern": "*RT*.csv",          // fnmatch；空/省略 = 不限
  "modified_after": "2026-09-01T00:00",// 本地时间语义，与参考工具一致
  "modified_before": null,
  "min_size": null, "max_size": null,  // 字节
  "data_files_only": true,             // 排除 Sum_*.csv 汇总（复用 _is_summary_csv）

  // —— 命中模式（三选一）——
  "mode": "content",                   // "name" | "content" | "column"
  "term": "ShadowReg2",                // mode=content
  "column_name": "ShadowReg2",         // mode=column
  "column_rows": 10,
  "matching": "substring",             // "substring" | "whole_word" | "fuzzy"
  "case_sensitive": false,
  "first_hit_per_file": true,
  "matches_per_file": 1,
  "one_per_folder": false,

  // —— 执行控制 ——
  "workers": 4,
  "allow_server_grep": true,
  "stop_after_listing": false,
  "max_entries": 200000, "max_candidates": 5000,
  "max_matches": 2000, "max_scan_bytes": 67108864, "timeout": 600
}
```

**变更说明**：`recursive` 布尔被 `depth` 档位**取代并删除**——两个旋钮说同一件事，
其中一个必然变成装饰（`only_data` 就是先例）。

**校验规则**：

- **未知键一律 400 拒绝**（DRF serializer 默认静默忽略，这里必须显式拒绝）。
- `mode` 为 `content`/`column` 时对应必填项缺失 → 400。
- `roots` 为空或超过 20 条 → 400。

**钳位表**（超出即夹到边界并记入 `limits_hit`，不报错）：

| 参数 | 默认 | 硬上限 | 说明 |
|---|---|---|---|
| `roots` | 必填 | 20 条 | |
| `depth` → `max_depth` | `all` = 不限 | 64 | 仅防路径长度爆掉，不作为防失控手段 |
| `max_entries` | 200 000 | 500 000 | **唯一真正防遍历失控的闸**；只有 `prune_dirs` 命中的目录不计入（口径见 §3.4） |
| `max_candidates` | 5 000 | 50 000 | 达上限即停止列举，转 `scanning` |
| `max_matches` | 2 000 | 20 000 | 也是「结果驻留在渲染进程内存」的上限依据 |
| `matches_per_file` | 1 | 20 | |
| `max_scan_bytes` | 64 MiB | 1 GiB | 单文件扫描预算，超出记 `scan_budget_exceeded` 并跳过该文件剩余 |
| `column_rows` | 10 | 50 | |
| `workers` | 4 | 8 | 与参考工具 `cli_interface.py:324` 的 1–8 钳位一致 |
| `term` 长度 | — | 200 字符 | |
| `timeout` | 600s | 30–3600s | 复用 `clamp_timeout` 同款钳位范式 |

**深度默认不限**的理由：用深度上限防失控是错的守卫——它会在目标树恰好深一层时
**静默少结果**，而静默少结果比慢十倍恶劣得多。条目预算与 deadline 和目录形状无关，才是正确的闸。

### 3.3 引擎选择：一个纯函数谓词

`select_engine(spec) -> ("grep" | "client", reason: str)`。**grep 档启用 ⟺ 全部满足**：

1. `mode == "content"`
2. `matching in ("substring", "whole_word")`
3. `term.isascii()`
4. `not one_per_folder`
5. `not stop_after_listing`
6. `allow_server_grep`
7. `depth == "all"` —— **GNU grep 没有 `--max-depth`**，限深的查询在 grep 档表达不出来
   （`--exclude-dir` 只匹 basename，挡不住深层目录里的文件），只能回落。
8. **根目录自身不撞目录排除条件**（`filters.root_collides_with_dir_excludes`）——
   `--exclude-dir` 与 `-prune` **会命中命令行上那个根目录本身**，而 walker 总会进入根目录；
   根 basename 撞上任一 prune 模式（或以 `.` 开头）即回落，否则是**整棵子树安静消失**这种最恶劣的假阴性。
   只有最后一段参与判定（实测 `--exclude-dir=tmp /tmp/ggrep/e` 不受影响），故深层目录名撞模式是平价的。
   `build_command()` 里有**第二道 `ValueError` 闸**，防绕过 `select_engine` 直接拼命令。
9. 需要 find 管道时探测必须有 `find_xargs` 级（`filters.needs_find`）——三类原因：按 **mtime** 选文件、
   按 **size** 选文件（grep 都没有对应原语），以及 `name_pattern` 与「仅 `.csv`」的**交集**
   （`--include` 之间是**并集**，两条 `--include` 装不出「既匹配模式又是 csv」）。
   这类查询走 `find ... | xargs grep` 分支，**「需要 find 却探测不到 find」即回落**。
   原实现这条判据只看时间过滤，size 与求交是 Task 8 补进同一函数的。
10. 能力探测通过（**分三级**，见 §3.6）

任一不满足 → 回落 client 引擎，**回落原因必须进 `notice` 事件**，不能让人猜这次是哪档跑的。

**`prune_dirs` / 汇总 CSV / dot 条目不是回落项：它们可逐字翻译**（Task 8 的平价工作）——
`prune_dirs` → 每个模式一条 `--exclude-dir`；汇总 CSV → `--exclude='[sS][uU][mM]_*'`；
dot 条目 → `--exclude='.*'` **与** `--exclude-dir='.*'` **两条都要**（实测 `--exclude` 只判文件、
`--exclude-dir` 只判目录）。grep 侧 glob 一律大小写敏感，而 walker 判扩展名/前缀时先 `.lower()`，
所以必须写成 bracket 折叠形式，否则 `DATA.CSV` 这类文件名在两档间漂移。
代价就是第 8 条：把 `prune_dirs` 翻成 `--exclude-dir` 之后，那个选项会连命令行上的根目录一起判，
于是「可翻译」多了一条前提条件。判据与 glob 全在 `filters.py`（§3.1），两档共用一份。

三条非显然条件的理由：

- **条件 2（排除 `fuzzy`）**：grep 没有子序列匹配原语。
- **条件 3（非 ASCII 排除）**，两个理由叠在一起：
  - 本域中文名测试项的 CSV 常是 **GBK 编码**，而 grep 只会拿 UTF-8 字节去匹
    → **静默漏掉所有 GBK 文件**。静默漏结果是不可接受的失败模式。
  - 参考工具的补法是追加 `$'\\x..'` 形式的 GBK needle（`csv_content_searcher.py:303-309`），
    那是 **bash 专有语法**，dash/sh 下语义不同 —— 把正确性押在远端 shell 是哪个上，
    等于让结果取决于环境。
- **条件 4**：grep 没有「每目录只取第一个」原语，硬凑要后处理，加速收益即失。

**条件 3 顺带解决了整词的跨语言语义分歧**：`grep -w` 在 `LC_ALL=C` 下把 CJK 字节视为
非 word 字符，而 Python `re` 的 `\b` 把 CJK 视为 word 字符 —— 两者对中文整词判定不等价。
非 ASCII 既已整体排除，整词只需在 ASCII 上工作，而 §3.5 的字节级整词实现与 `grep -w`
在 ASCII 上语义一致，两档引擎因此仍给出同一结果集。

**正则一期不做**（刻意取舍，非省事）：`grep -E`（POSIX ERE）与 Python `re` 语义不等价，
而引擎是自动降级的——同一查询会因服务器恰好有没有 grep 而给出不同结果集。
**「结果取决于环境」是比缺功能更糟的性质**。若后续要做，必须连带「regex 时禁用 grep 档」的约束一起做。

`fuzzy`（子序列匹配，参考工具 `content_searcher.py:129` 版本）保留：线性扫描无回溯风险，
仅 client 引擎支持 → 自动触发回落并 `notice`。

**grep 档的代价必须写清**：它一次性完成列举 + 匹配，因此**没有 `listing` 阶段、没有候选清单、
进度恒为不定档**（服务端不知扫描总数，参考工具 `csv_content_searcher.py:291` 即返回 `None`）。
命中仍逐行流式回来，UI 看到的是命中持续出现。

### 3.4 遍历器（walker）

**BFS 工作队列，不用参考工具 `file_retriever.py:62` 那样的深度优先递归。**
区别在深树上很实在：DFS 会一头扎进第一个子树直到叶才吐第一个文件；BFS 让 `workers` 个线程
从「待访问目录」队列取目录，所以**候选从搜索一开始就在往 UI 流**，取消也只是不再消费队列。

- 环保护：已访问目录路径集合 + `sftp.realpath()` 归一。SFTP 协议判 symlink 不可靠，靠这个兜。
- 跳过 `.` 开头条目（与 `views.py:537` `_collect_files` 现有行为一致）；**dot 条目照吃预算**，
  它只是不成为候选，列目录的代价一分没省。
- 单目录 `listdir_attr` 失败 → `error{scope:"dir"}` 事件，**继续搜索**，不终止。
- **`max_entries` 的口径（实施修正，commit `c813a78`）：计入所有实际看到的非剪枝条目**，包括被
  `name_pattern` / 大小 / 时间过滤掉的文件与 dot 条目；**唯一豁免**是 `prune_dirs` 命中的子树
  （剪枝在进入前判定）。把预算只记在候选上等于给它换个名字叫「候选上限」，
  而「剪掉最外层」也会因为预算照烧而变成白剪。
- `name_pattern` 与 `prune_dirs` 的匹配用 **`fnmatch.fnmatchcase`** 而非 `fnmatch.fnmatch`：
  后者在 Windows 上经 `os.path.normcase` 变成大小写不敏感，同一份条件在开发机与生产机
  （大小写敏感的 POSIX）会给出不同结果；且 grep 的 `--include`/`--exclude-dir` 本就大小写敏感，
  **两档同语义**才谈得上 §3.3 的平价。

### 3.5 扫描内核（scanners）

移植参考工具 `csv_content_searcher.py` 的 `_search_single_file`（`:407`）全套：

- `CHUNK_SIZE = 1 MiB`、`MAX_INFLIGHT = 64`（prefetch 流水线，约 2 MB 在途）
- `LINE_CONTEXT = 4096` 滚动窗口 + 换行计数 → 得行号
- 原始字节匹配，**不逐行 decode**；`_build_needles`（`:496`）：ASCII 走单 needle + 可选大小写折叠，
  非 ASCII 追加 utf-8/gbk/utf-16-le/utf-16-be 多 needle
- `_extract_line`（`:528`）跨 chunk 边界取整行；`content` 截断 200 字符
- `_parse_head`（`:535`）抽 `TestFile` / `StartTime` / `PtsModifyTime`，遇 `[DATA]` 即停，
  **head 被 chunk 截断时丢掉最后半行**（防截断污染取值）
- `_detect_encoding` / `_decode_line`（`:573`）utf-8 / gbk / gb2312 / utf-16 四探
- 元数据只在命中后才解析
- **`whole_word` 在原始字节上实现**：命中位置前一字节与后一字节均不属于
  `[A-Za-z0-9_]` 才算整词。这与 `LC_ALL=C grep -w` 在 ASCII 上的判定字面一致，
  是两档引擎结果可比的必要条件。**不得改用 `re` 的 `\b`**（Unicode 语义不同）。
- 连接级异常（`paramiko.SSHException` / `SFTPError` / `EOFError` / `OSError`）**向上抛**，
  由 `connect.py` 决定回收重连；文件级异常就地记 `error{scope:"file"}` 并继续

`mode="column"` 移植 `csv_column_reader.py`：定位 `[DATA]` → 表头取列索引 → 前 N 个非空值。

**「`[DATA]` 之后的第一行就是表头」这个前提在真实数据上成立**，实现照此读即可。（Task 7
期间一条相反的报告——「真数据在标记与表头间夹空行，照此读会对所有真实数据读出 0 值」——
经原始字节复算被推翻：**方位记反了**，见下表。）

复算判据：`Data/` 递归 122 个 `.csv`（另有 7 个 `.txt`，均无标记），按 `rb` 逐行读、
大小写不敏感匹配行首 `[data`，取标记行的**下一行**分类（「表头」= 非空且含逗号的行；另抽样
4 个文件逐字核对，确认形如 `Serial_No,Part_No,Dut_No,…`。56 个文件无一落入「其它」档）：

| 计数项 | 实测 |
|---|---|
| 含 `[Data]` 标记的文件 | 56 |
| 标记的下一行即表头 | **56** |
| 标记的下一行为空行 | **0** |
| 其它形态 | 0 |
| 标记的**上一行**为空行 | **49** |

空行在标记**之前**（49/56），不在标记之后。两条推论：

- 参考工具 `csv_column_reader.py` 的读法在真实数据上是**正常**的，「必然读出 0 值」不成立。
- 实现里「进入 `[DATA]` 后跳过空行」那段**不是**对实测数据的适配，而是**防御性容错**
  （未知生产者或手工编辑的文件可能在标记与表头之间留空行）。对真实数据无可观察影响，
  故**行为保留、只改注释所声称的依据**（`scanners.py`）。

真数据冒烟（直接调 `scanners.read_column` 扫 `Data/` 那 56 个含标记的文件，各取其表头里的
一列）：**56/56 读到列值，且 56/56 拿到 `TestFile` / `StartTime` 元数据，0 例读空。**

两条经核实成立的事实：

- 真表头之后紧跟 `Unit` / `Min` / `Max` 三行 → **已拍板跳过**（2026-09-21 用户决定）。
  实现见 `scanners.py` 的 `LIMIT_ROW_TOKENS` / `LIMIT_ROW_SKIP_MAX`：判据是**首格**命中
  `{unit, units, min, max}`（那三行的测试列里装的是各自的单位与限值，只有前置系统列才是
  字面 token），且只认表头下**紧邻**的最多三行，断档即停。这是**对参考工具的有意偏离**。
  语义代价一并拍板接受：某列只在单位/限值行有内容 → 该文件不再算命中（命中必须有真读数）。
  复测口径（2026-09-21 全量重跑）：`Data/` 的 122 个 csv 里 **56 个含 `[Data]` 标记**，
  这 56 个**全部**是「标记后 1 行即表头」且「表头后三行首格恰为 `Unit`/`Min`/`Max`」
  （56/56，无一例外）。位置判据的第二来源：`apps/datafiles/parsers/base.py:154-155`
  的 `unit/min/max_offset = 2/3/4`、`data_offset = 5`。测试见
  `test_sftp_search_scan.ColumnTests` 的 `test_unit_and_limit_rows_are_skipped` 等四条。
- 列名匹配是**大小写敏感 + 精确相等**。spec 与计划均未表态，实现取保守侧：
  表头里没有这一列 = 这个文件正常没有结果（不报错、不刷日志），不做任何模糊匹配——
  模糊匹配会把不同测试项的数值混成同一列。

### 3.6 grep 加速档（shell_grep）

- **三级探测**（`shell_grep.probe`；本文 2026-09-20 版是两级，实施补了中间那级。**三级不过分别回落**）：
  - `grep` 级：`grep --version` 可用 + SFTP/shell **路径映射一致**（chroot 验证）→ 才支持无时间过滤的查询。
    映射不过即整档作废：chroot 下 grep 一个错路径不是「慢」，是**假阴性**。参考
    `csv_content_searcher.py:213` 的 probe 手法，实现有意偏离：直接测 root 本身而非取一个条目再验，
    判别力相同而省一次 SFTP 往返（探测只有一个 transport 可用）。
  - **选项级（实施新增）**：真跑一次 `printf '' | LC_ALL=C grep -q -F -e zz --exclude=zz
    --exclude-dir=zz --include=zz`，退出码 >1 即不过。grep 档的文件选择平价**全靠这三条**（§3.3），
    所以 **`has_grep` 的含义随之变严**：不只是「远端有 grep」，而是「有 grep 且认这三个选项」。
    少了这一级会怎样：探测通过而选项不存在 → 命令以退出码 2 结束 → 一整趟白跑。
    这三条语义是 **GNU 实现细节而非 POSIX**，故必须实测，不能假定。
  - `find_xargs` 级：额外要求 GNU `find -newermt` 与 `xargs -0 -r` → 才支持带**时间/大小**过滤
    与「`name_pattern` ∩ 仅 `.csv`」求交的查询（§3.3 条件 9）。**这一级只挡需要 find 的那类查询**，
    缺它时其余查询仍可用 grep。
  - 探测不过 → 回落 client，`notice{code:"grep_unavailable", reason}`。
- **`--include` 必须全部排在 `--exclude` 之前，这是命令构造的硬约束，不许调换。**
  本文与计划原以为「GNU grep 里 `--exclude` 压过 `--include`」——**实测是错的**：
  grep 3.0 把 `--include`/`--exclude` 当作**一张按 argv 顺序求值的规则表，最后命中的那条决定去留**。
  include 全先发、exclude 全后发，是「最后命中者」与「exclude 恒压 include」**两种语义下唯一同解**的排法；
  排反的后果实测过：16 个文件全被放回来，而 walker 侧只有 6 个。目录侧是独立命名空间
  （`--exclude-dir` 只判目录，与文件规则无交叉，实测）。
- **两档文件选择的平价已真跑取证**：本机 GNU grep 3.0 + findutils 4.10，对 13 个代表性 spec
  逐条比对两档保留的文件/目录集合，**结果全部相等**。自动化侧另有
  `test_sftp_search_parity.py`（把发出去的命令用 `fnmatch` 复算一遍，与 walker 判定逐个比），
  它钉的是「命令不会漂移」，真跑钉的是「复算所用的语义本身是对的」，两者不可互替。
- **执行通道**：池 `_Entry` 无 `SSHClient`，故走 `transport.open_session()` 自行开会话。
  grep 档只跑**一条** exec 通道（本质是一条命令），与 `workers` 无关。
- **注入防护不变量**：`shell_grep.py` 是**全项目唯一**拼 shell 命令字符串的地方。
  每个插值 token 过 `shlex.quote`；`term` 用 `-F`（固定串）配 `-e <quoted>`；
  `name_pattern` 走 `--include=<quoted>`；路径走 `shlex.quote`。

### 3.7 连接层（connect.py）

`SearchSession(user_id, workers)`：

- 凭据取自 `cache.get_session(user_id)`（`apps/sftp/cache.py:134`），**前端不回传密码**。
- 每条连接经 `host_keys.open_verified_transport()`（`apps/sftp/host_keys.py:182`）建立。
  **不移植参考工具的 `AutoAddPolicy`**——它会破坏 `test/backend/test_sftp_host_keys.py`
  钉住的「密钥不匹配时拒绝且不发凭据」契约。
- 借还：`queue.Queue`，坏连接回收重开一次（参考 `_recycle`），重开失败则该文件记
  `error{scope:"file"}` 跳过。
- **配额降级**：开第 k 条失败 → 降到 k−1 继续，并报 `notice{code:"workers_reduced", actual}`；
  一条都开不出来 → `workers=1` 用单连接，搜索照跑只是慢。**必须上报实际并行数**，
  否则用户看到的并行数是假的。
- **读超时机制（已核实，勿凭直觉实现）**：本项目装的是 **paramiko 5.0.0**，
  `Transport.__init__(sock, default_window_size, default_max_packet_size, ...)`
  **已无 `default_timeout` 参数**，所以「给连接设 socket 超时」这条路不存在。
  超时只能设在 channel 上 —— 直接复用现成的
  `apps/sftp/downloads.py:53` `channel_timeout(sftp, seconds)`（设 `channel.settimeout`、
  退出时恢复原值、异常路径由 `contextmanager` 保证恢复）。搜索专用常量
  `READ_TIMEOUT_SEC = 15`，作用域是**单个文件的扫描**，不复用下载的 `clamp_timeout`。
  在临时连接上设它没有污染风险（该连接此刻只属于一个 worker），
  这也正是「绝不拿池连接做扫描」的又一个理由。
- `finally` 无条件关闭全部连接；暴露 `opened` / `closed` 计数供测试断言无泄漏。
- **绝不用池连接做扫描**：`channel_timeout` 会改共享 channel 的 socket 超时，污染浏览与下载。

**两条推论**：

1. **搜索期间面包屑导航照常可用**——浏览走池连接、扫描走临时连接，不同 channel。
2. 互斥只需挡「搜索 vs 下载」这一对，不需要挡导航。

### 3.8 SSE 事件协议

```
hello       {engine:"client"|"grep", engine_reason, workers_actual, roots}
stage       {stage:"listing"|"scanning"|"done", candidates, matches}
candidates  {items:[{path,name,size,mtime}], total_so_far}   // 批合成：200 项 或 200ms 先到
match       {items:[{path,name,size,mtime, line, snippet,
                     test_file, start_time, pts_modify_time,   // mode=content
                     values:[...]}]}                            // mode=column
progress    {stage, done, total|null, elapsed_s, files_scanned, bytes_scanned}
notice      {code, message}          // 降级/截断，见下
error       {scope:"file"|"dir"|"fatal", path, message}
done        {matched, scanned, elapsed_s, truncated, limits_hit:[code], engine}
```

- **进度分母按阶段变**：`listing` → `total: null`（不定档 + 计数）；`scanning` → 分母 = 候选数
  （百分比）；`grep` 档全程 `total: null`。所以进度组件必须三态，
  `SftpDownloadProgress.vue` 的 `file|dir` 双百分比契约套不上，另建组件。
- **grep 档不发 `stage:"listing"`，也不发 `candidates` 事件**（它没有候选阶段，
  只有命中流）。`stage` 序列为 `scanning → done`。前端结果表在 grep 档下
  从空表开始只增命中行，不显示候选计数。
- **上限一律显式告知**。每个钳位对应一个 `notice` 码，汇总进 `done.limits_hit`：
  `truncated_depth` / `truncated_entries` / `truncated_candidates` / `truncated_matches` /
  `scan_budget_exceeded` / `grep_fallback` / `workers_reduced` / `dir_unreadable`。
- 事件批合成：`candidates` 与 `match` 攒到 **200 项或 200ms**（先到者）再 flush，
  避免十万条目把 SSE 变成瓶颈。

### 3.9 取消与生命周期

阶段机：`probe → LISTING → SCANNING → DONE`。生成器以 `queue.get(timeout=0.2)` 排空 worker
塞进来的事件——0.2s 封顶轮询保证取消延迟有界。

1. **`ThreadPoolExecutor` 绝不能用 `with`**。其 `__exit__` 会 `shutdown(wait=True)`，
   取消时会把 HTTP 请求挂住直到几千个文件扫完。必须显式 `shutdown(wait=False, cancel_futures=True)`。
2. **worker 收不到 `GeneratorExit`**，只认 `threading.Event`。取消 = 三件事：
   `cancel_event.set()` → `shutdown(wait=False, cancel_futures=True)` → 关闭全部临时连接
   （连接一关，卡在 `read()` 上的 worker 立刻拿到异常返回）。
3. **最坏取消延迟 = `READ_TIMEOUT_SEC` = 15s**（卡在 `read()` 上的 worker 要等 channel
   超时抛异常才脱身，见 §3.7），写进本文而非含糊过去；期间前端按已取消处理、不阻塞用户。
   注意 `close_all()` 会关掉 transport，通常让卡住的读**立刻**报错返回，所以 15s 是
   上界而非典型值。
4. 生成器收到 `GeneratorExit` 后不得再 `yield`（RuntimeError）。清理全在 `finally`。
5. **前端不再于导航时 abort**（与 §1.2 驻留决策一致）：仅「显式取消」与「退出应用」才 abort。
   后端 `timeout` 是在制品泄漏的兜底（threaded runserver 下每条流占一个 daemon thread，
   不是占死一个 worker，故不会冻结应用）。

### 3.10 数据模型与预设

```python
class SftpSearchPreset(models.Model):
    owner = ForeignKey(User, CASCADE, related_name='sftp_search_presets')
    name  = CharField(max_length=80)
    spec  = JSONField()          # 完整 SearchSpec，含 roots
    created_at / updated_at
    # Meta: unique_together (owner, name)；ordering ['-updated_at']；每人上限 50 条
```

- 端点：`GET /sftp/search_presets/` · `POST /sftp/search_presets/save/`（`{name, spec, overwrite?}`）
  · `POST /sftp/search_presets/delete/`（`{id}`）。CRUD 形状仿 `config_views.py` 的 `SftpConfigMixin`。
- 载入预设**不预校验 roots 是否仍存在**；`roots` 失效在运行时表现为
  `error{scope:"dir"}`，比多一次探测调用更简单且语义一致。
- 跨用户隔离：他人预设不可见、不可改、不可删（仿 `apps/sftp/tests.py:287`
  `SftpConfigOwnerIsolationTests` 的既有契约）。

**`workers` 与 `timeout` 不进系统设置页**，放搜索面板「高级」区。项目刚做过一轮
「无人消费的设置」整改（commit `7a9da16`），反方向同样有害：全局设置管一个只有 SFTP 搜索
用的旋钮，会让设置页与面板两处各执一词。参数该长在它控制的东西旁边。

### 3.11 错误处理与 API 约定

- **端点形式**：`SftpSearchMixin` 上加 `@action(detail=False, methods=['post'])`，
  与 `SftpViewSet`（`views.py:43`）现有风格一致。
- **错误格式在此表态**（现有代码两套并存：视图手写 `{'error': msg}` 与
  `custom_exception_handler` 的 `{code, message, detail}`）：
  - 流开始**前**的校验失败 → HTTP 400 `{"error": msg}`，与 `views.py` 现有十余处同形，
    `utils/ssePost.ts` 本来就只读 `err.error`。
  - 流开始**后**的错误**只能**是带内 `error` 事件；生成器内绝不抛 DRF 异常
    （异常处理器拿不到流，只会留下半截 SSE）。
  - 未连接复用现有哨兵 `{"error": "not_connected"}`。
- **任何 `except` 不得静默**：必留 WARNING 日志，沿用
  `test/backend/test_sftp_guards.py:224-252` 钉住的既有要求。
- SSE 响应必须带 `Cache-Control: no-cache` + `X-Accel-Buffering: no`。
- 流式走原生 `fetch` + `api.defaults.baseURL` 拼接（Electron `file://` 兼容），
  带 `Authorization: Bearer`；不走 axios（全局 30s 超时会掐断长任务）。

### 3.12 pool per-user RLock（一并修）

`apps/sftp/pool.py` 增加 per-user `threading.RLock`，把 `get_connection` 的
「检查存活 → 复用或重建 → 更新 `last_used`」整段临界区保护起来；视图侧在
**使用连接执行操作期间**持锁的形态不做（会把下载这种长任务串行化整条连接，
且 09-09 的前端互斥已经覆盖了下载之间）。

范围严格限定为：**保护池自身的状态转换**，使 threaded runserver 下并发的
`list_files` / `invalidate` / `close` 不再踩踏同一个 `_pool` 字典与同一条 transport 的
建立/销毁过程。paramiko `SFTPClient` 的**并发操作**仍由「一人一条 + 前端传输互斥 +
搜索走独立连接」这三条共同规避。

该改动独立成一次提交，便于回退与单独评审。

### 3.13 前端交互细节

**roots 的三个入口**（项目无目录树，不为此新建一棵）：

1. `SearchCriteria` 打开时**预填当前面包屑路径**；
2. 「使用当前目录」按钮（面包屑变化后刷新）；
3. `SftpFileTable` 目录行右键菜单 →「在此目录搜索」，带该路径直接进搜索页。

**深度档位**是四选一单选：`仅当前层` / `含下一层` / `全部递归`（默认）/ `自定义`
（选它才露出 `max_depth` 数字框）。`prune_dirs` 是标签式输入（回车加一个 fnmatch 模式）。

**`one_per_folder` 放显眼位置，不藏进「高级」**——全递归时它才是真正回答
「哪些文件夹里有这个测试项」的开关，勾上即把扫描量除以每目录文件数。

**结果分组**：候选/命中数 > 200 时自动切「按文件夹分组」，组头显示
`目录 · N 个命中 · 展开/折叠`，路径列中段省略 + tooltip 全路径。可手动切回扁平。

**四条硬约束**：

- **命中片段高亮禁止 `v-html`**。`term` 是用户输入，走 `v-html` 就是自造 XSS 面。
  必须拆成前/命中/后三段 `<span>` 文本节点拼接。
- `partial` 状态（`limits_hit` 非空）的黄色提示条**常驻且不可手动关闭**，
  离开搜索页前必须让用户看见过——搜出 5000 而真实有 40000 时静默返回，比慢十倍更伤信任。
- 新 UI 全部走语义 token（`--text-2` / `--border-2` / `--brand` / `--error`），
  **不新增任何字面色**，dark + light 两套都过一遍截图（`.claude/CLAUDE.md` 硬规则）。
- 结果表用 **AG Grid**（项目既有依赖，见 `DataBrowserAgGrid.vue` / `FileCorrelationTable.vue`，
  自带虚拟滚动，且 Calibri 字族与 `--p-fs-*` 九档 token 已在它身上接好
  —— commit `6657c93` / `6b1d82f`）。5000 行在 `el-table` 会明显发涩。

**与现有搜索框的关系**：工具栏那个本地过滤框**保留不动**（零延迟、当前目录即时过滤，
是它该有的样子），不替换、不做两套结果视图。

**搜索页怎么知道「未连接」**：项目**没有**连接状态端点，也不为它新建一个。
搜索页不做前置探测，而是让 `POST /sftp/search/` 在会话缺失时返回
`400 {"error": "... not connected ..."}`，页面据此显示「请先在 SFTP 浏览器建立连接」
+「去连接」跳转。辅助提示可复用现成的 `GET /sftp/last_visit/` 的 `can_auto_connect`。
理由：加一个只读状态端点会引入「前端缓存的连接态与服务端真实态不一致」这个新问题，
而失败路径本来就必须实现——少写一条会漂移的路，比少写一个端点更划算。

## 4. 测试与验证

四级，前三级设施项目里已有。

### 4.1 纯逻辑单测 → `test/backend/test_sftp_search_*.py`

按被测模块分文件（每个测试文件对应一个后端搜索模块，便于失败定位与单独跑）：
`test_sftp_search_contract.py`（契约与钳位）、`test_sftp_search_engine.py`（引擎选择谓词）、
`test_sftp_search_connect.py`（连接借还/降级/泄漏）、`test_sftp_search_walk.py`（遍历与过滤）、
`test_sftp_search_scan.py`（扫描内核）、`test_sftp_search_grep.py`（命令构造与探测）、
`test_sftp_search_engine_stream.py`（阶段机与取消）、`test_sftp_pool_lock.py`（§3.12）。
共享内存夹具在 `test/backend/sftp_fake.py`。
另有一个文件不按模块切：`test_sftp_search_parity.py`（§3.6 的结果集平价断言）——
它要同时引 `shell_grep` / `filters` / `walker` 三方，留在 grep 那个文件里两边都撞 600 上限。

`unittest` + `django.setup()`，无 DB。这级吃下搜索最值钱的部分：

- `select_engine(spec)` 决策表——**§3.3 的每条条件（实施后为 10 条）单独钉一个正/反例**，尤其
  「非 ASCII `term` 必须回落」（防静默漏 GBK 文件）、「`fuzzy` 必须回落」、
  「整词 + ASCII 允许 grep」。这些条件存在的理由正是**结果不能取决于服务器恰好有没有 grep**。
  实施还钉了**判断顺序**：spec 侧那几条先判、`probe.reason` 后判，否则非 ASCII 查询会拿到
  一句「服务器上没有 grep」，把真原因藏掉（`engine.py` `select_engine` docstring）。
- `parse_spec()`——每个上限的边界值、**未知键必须被拒绝**、`mode=content` 空 `term` 报错、
  `depth` 档位到 `max_depth` 的映射。
- 字节匹配内核：utf-8 / gbk / utf-16-le / utf-16-be × ASCII / 中文 × 大小写；
  `_extract_line` 跨 chunk 边界；行号计数正确性。
- **整词一致性**：同一批字节内容、同一个 ASCII `term`，字节级整词实现与
  `grep -w` 的命令形态必须选出同一组命中位置（§3.5 那条「不得改用 `\b`」的守卫测试）。
- `_parse_head`：遇 `[DATA]` 即停；head 被截断时丢弃最后半行。
- **注入断言**：`term` 给 `x'; touch /tmp/pwn; #`，产物命令串中它必须是一个完整单引号段；
  `name_pattern` 同理；并断言 `-F` 恒在（否则 `term` 会被当正则解释）。
- walker：`max_entries` / `max_depth` / `prune_dirs`（剪枝目录不计预算）/ 环保护 /
  单目录失败隔离。

### 4.2 视图契约 → `apps/sftp/tests_search.py`

`APITestCase` + `mock.patch.object(SftpSearchMixin, ...)` 注入 FakeSftp
（扩展 `apps/sftp/tests_download_dir.py:29` 那套 `FakeSftp`，加 `listdir_attr`
与一棵内存目录树；`fail_after` / `broken` 钩子复用来验降级路径）。断言：

- 未连接 → 400 `not_connected`；spec 校验失败 → 400 **且必须在流开始前**。
- SSE 帧序列：client 档 `hello → stage(listing) → candidates… → stage(scanning) →
  progress… → done`；**grep 档断言不出现 `candidates` 与 `stage:"listing"`**（§3.8）。
  两个 SSE 响应头齐备。
- `GeneratorExit` → 临时连接全部关闭（`session.opened == session.closed`）、无线程残留。
- 预设 CRUD：唯一名、覆盖、每人 50 条上限、跨用户隔离。

### 4.3 真服务器集成 → 复用 `frontend/e2e/helpers/sftp_server.py`

它是纯 argparse 脚本、与 Playwright 零耦合（`subprocess.Popen([sys.executable, ...,
'--root', tmpdir])` + 读 stdout 首行拿端口）。**这一级是唯一能测出并行正确性的**——
参考工具 `csv_content_searcher.py:24-27` 记的「Garbage packet received」这类协议流错乱，
MagicMock 永远测不到。

- fixture 树扩一棵：多层目录 + 同格式多文件 + GBK 编码中文测试项 + `Sum_*.csv` +
  一个 20 万行大文件 + 一个不可读目录（验 `error{scope:"dir"}` 隔离）。
- **最值钱的一条断言：`workers=4` 与 `workers=1` 的结果集必须完全一致。**
- 主机密钥：该脚本每次新生成 RSAKey，故用
  `override_settings(SFTP_HOST_KEY_CHECK='off')` 或每例 `host_keys.forget(host, port)`。

### 4.4 e2e → `frontend/e2e/sftp/search.spec.ts`

`@p1 @sftp` tag + `test.describe.configure({ mode: 'serial' })`（搜索状态按 user 存，
多 worker 并行会互相覆盖，即 lessons R6）。

- 测「进行中 / 互斥 / 取消」的确定性技巧照抄 lessons：`page.route` 处理器里 `setTimeout` 3s
  再 `continue()` 把请求拦在浏览器；abort 后 `route.continue()` 会 reject，**必须 `.catch(() => {})`**；
  断言完 `unroute` 恢复真实链路再验证状态未被取消破坏。
- **驻留专项**（本次需求的核心性质）：起搜索 → 路由跳到数据管理页 → chip 仍显示进行中
  且计数在涨 → 跳回 `/sftp/search` → 结果完整、无重复、无丢失 → 从 chip 取消 → 状态归零。
- 取消冷却 1.2s 之后才允许下一次传输。
- 双主题：dark + light 各截图一次（`.claude/CLAUDE.md` 硬规则）。

### 4.5 一处自动化覆盖缺口（显式承认）

grep 档**无法在自动化里真正测到**：项目的假 SFTP 服务器只实现 SFTP 子系统、没有 shell exec，
所以自动测试只能覆盖「探测失败 → 回落 client 引擎」，测不到「grep 真跑出正确结果」。

处置：**命令构造用纯字符串断言覆盖**（测的是「我们会发出什么命令」）+ **一次真实服务器人工
验证**，验证结果记进本文 §7 验收账目。不给假服务器加 exec 伪造 grep——那是在测自己写的假
grep，价值可疑且维护成本长期为正。

### 4.6 门禁

`python manage.py test` 全量通过（项目以它为准，非 pytest）；
e2e 相关 spec 通过；收尾释放 8000 / 3000 端口。

## 5. 范围外

- ❌ **跨应用重启的结果持久化**（需后端 job 表 + 分块结果存储 + 轮询/重连，与现有单请求 SSE
  范式并存两套长任务模型）。长期保留用「存为预设」复跑。
- ❌ **正则表达式匹配**（理由见 §3.3：两档引擎语义不等价）。
- ❌ 元数据索引先行（方案 B）。搜索是偶发操作，索引需要失效策略，收益不抵复杂度。
- ❌ 搜索与下载并发（保持 09-09 的互斥语义，仅把「搜索」纳入传输的一种）。
- ❌ 多结果集跨会话比对（会话内运行历史只用于回看，不做 diff）。
- ❌ 目录树导航组件（搜索的 roots 靠「预填当前路径 + 使用当前目录 + 右键」三个入口解决）。
- ❌ 修复 `only_data` 既有腐化点（§3.1 已记录，需独立决策）。
- ❌ 前端搜索结果的「一键送入文件关联分析」（用户未选此项）。

## 6. 已知边界与风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| 服务器限 `MaxSessions` | 并行上不去，搜索变慢 | 开不出即降级并 `notice{workers_reduced}`，报真实并行数 |
| 客户端无 shell exec（chroot-only SFTP） | 无 grep 加速，走 client 引擎 | 探测自动回落；`notice{grep_unavailable}` |
| grep 档结果与 client 档在极端输入上可能不同（如文件名含 `:` 破坏 `path:line:content` 解析） | 个别命中被丢弃 | `_parse_grep_line` 解析失败的行必须记 WARNING，不得静默跳过 |
| **软链接语义两档不等价**（实施新发现，**未闭合**）：walker 把 listing 里非 `S_IFDIR` 的条目一律当文件打开（跟随软链接），而 `grep -r` 与 `find -type f` 都**跳过**软链接 | grep 档少结果，且是静默的 | **本地无法取证**（Git Bash 造不出真软链接）→ 列为残留风险，由后端真机验证（计划 Task 11 Step 5）定夺。换 `-R` / `find -L` 只是把分歧挪到「服务器把软链接目录报成 `S_IFDIR` 还是 `S_IFLNK`」那一侧，两个方向都不平价 → **定夺前不要把 `-r` 改成 `-R`**（那是换个分歧，不是消除分歧） |
| 大文件扫描耗时长 | 单次搜索分钟级 | `max_scan_bytes` 预算 + 命中即停 + 可取消 + 进度可见 |
| 临时连接消耗服务器 fd/线程 | 影响他人 | `workers` 上限 8，`finally` 无条件关闭，测试断言 `opened == closed` |
| 在制品 SSE 流泄漏占 daemon 线程 | 内存/句柄增长 | threaded runserver 下不冻结应用；`timeout` 兜底 + 显式取消入口常驻 |
| `SftpBrowser.vue` 545 → ~557，逼近 600 | 后续加东西必须先拆 | 本文显式记录；新代码全部落新文件 |
| 前端内存驻留 20 次运行 × 2000 命中 | 渲染进程占用 | `max_matches` 上限 + 会话历史仅存摘要，全量结果只留最近一次 |

## 7. 验收账目

以下按时间追加：`2026-09-21 Task 11`（后端真机闸门）、`2026-09-21 Task 20`（收尾验证与账目）。

### 2026-09-21 Task 11（预设 CRUD + 后端真机 HTTP 验证）

- **后端全量**：`python manage.py test` → `Ran 1338 tests OK (skipped=7)`
  （开工前 1308；本次 +28 预设契约 `apps/sftp/tests_search_preset.py`、
  +2 SSE `Accept` 回归 `apps/sftp/tests_search.py`）。
- **预设端点**：`/sftp/search_presets/` · `/save/` · `/delete/` 三个 action 挂在
  `SftpSearchMixin` 上（`@action(url_path=...)` 带斜杠可用，DefaultRouter 走 `re_path`）。
  保存前过 `parse_spec`；每人上限 50（`PRESET_MAX_PER_USER`）；跨用户不可见/不可改/不可删。
- **真机 HTTP 全链路**（`tasks/_sftp_search_http_verify.py`，临时 SFTP 服务器 +
  临时 `runserver` + `http.client` 逐行读真实 socket，连跑两遍 9/9）：
  a. 16/14/13 帧全部 `data: {...}` + 空行，0 例半截 JSON，字节账目 raw=framed；
  b. 首帧 `hello` 末帧 `done`，`match` 批大小 max=89 ≤ 200（`FLUSH_MAX_ITEMS`）；
  c. `X-Accel-Buffering: no` + `Cache-Control: no-cache` 真在响应头上，首帧 +0.000s
     早于服务端自报 `elapsed_s=0.28s`（被缓冲则首帧≈收尾、写批次塌成 1），实测 3 个写批次；
  d. 收到 2 帧后硬断连接：Django→SFTP 的 ESTABLISHED 由 4（d0 完整搜索实测）回落 0，
     服务端留下 `walker`/`shell_grep` 的 WARNING 与 traceback 痕迹，**再发一次搜索成功**
     （13 帧、`done`、命中 1）；
  e. GBK 中文 `漏电电流` 的 snippet 与路径逐字不变形（线上全 `\uXXXX` 转义，非 ASCII 字节 0）。
- **Step 5 抓出并修掉的真实缺陷**：`Accept: text/event-stream` 被 DRF 内容协商判 **406**
  （只有 JSONRenderer 在谈；`fetch` 默认发 `*/*`，所以 test client 与 curl 都测不到）。
  修法是给 `search` action 一个只参与协商的 `SSERenderer`，失败响应仍是 `400 {'error': msg}`。

2026-09-21 更新时仍未闭合的两条：

1. **grep/find 档与 client 档的真机结果集比对**——含 §6 那条软链接分歧的定夺。
   自动化只能证「我们发出的命令等价于 walker 的判定」（§4.5 缺口 + 本机 grep 3.0 真跑比对），
   证不了目标服务器上真跑得出同一结果。
2. ~~**列值模式的 `Unit` / `Min` / `Max` 三行是否应排除**（§3.5）~~ → 同一日用户拍板
   **排除**：已改为跳过表头下紧邻、首格为这三者的最多三行，实现与真数据复测见 §3.5。

### 2026-09-21 Task 20（收尾验证与账目，HEAD `9efbbe2`）

本节数字全部为本机当场复跑所得；凡引用更早结论处均标明出处 commit。

**后端全量复跑**
- `.venv/Scripts/python.exe manage.py test` → `Ran 1338 tests in 475.254s` / `OK (skipped=7)`。
- 与 `f91a2dc` 时的 1338（出处 `52e7fdd`）逐字一致；`git diff f91a2dc..HEAD` 只含
  13 个 `frontend/` 文件（Task 17 前端接线 + Task 18 e2e）→ 证明这两次提交确实没动后端。

**前端类型检查**
- `npx vue-tsc -b --force` → exit 0，无诊断输出。

**@sftp e2e 复现性（两次）**
- 第 1 次（Task 18 实施时，既有结果引用于此）：`npx playwright test --project=P1 --grep @sftp --workers=1`
  → 25 passed / 1 skipped，9.0m（加搜索用例前基线 10 passed / 1 skipped）。
- 第 2 次（本次复跑）：同命令 → **25 passed / 1 skipped，9.0m，与第 1 次完全一致**。
  skipped 那条是 `sftp.spec.ts` 的 env-gated 真实连接用例（无 `SFTP_HOST` 凭据，设计如此）。
  结论：该套 e2e 可复现，不是抖动出来的账。

**后端真机 HTTP 全链路（Task 11 Step 5 结论，出处 commit `52e7fdd`）**
- SSE 分帧 16/14/13 帧全合规、`hello`→`done`、双响应头齐备、硬断后 Django→SFTP 连接数
  回落 0 且再搜成功、中文 snippet 逐字不变形，连跑两遍 9/9；顺带抓出并修了 `Accept:
  text/event-stream` 被 DRF 判 406 的真缺陷。

**打包版冒烟（计划 Step 3）：未执行**。逐条核实过的原因（不是回避）：
- `build.bat` 无条件 `taskkill /F /IM python.exe /T`——共享工作区会连带杀死其它会话的进程；
- 无条件 `rmdir /s /q out` 并删 `dist\LQ-DataPrase`：`out/` 现存历史安装包
  `LQ-DataPrase-0.6.0-Setup.exe`（2026-09-08），0.6.0 的源码状态已不在当前树上，删掉不可恢复；
- `npm run dist:win` = 前端生产构建 + PyInstaller + electron-builder（主程序 ~188 MB）全链，
  为验证跑一次，时长与破坏风险都不可接受。
- **需要的条件**：用户确认 `out/` 产物可弃（或改脚本输出到独立目录），或在独立干净
  机器/worktree 上执行；然后走「连接→搜索→下载→分析」全链路冒烟一次。

**threaded runserver 并发不阻塞（开发形态补证，本次实测）**
- 来源复核：`standalone.py:224` 只传 `--noreload`；本机安装 Django 6.0.5 的
  `--nothreading` 为 `action="store_false"`（dest `use_threading`，默认 True）→
  桌面/打包后端默认多线程（§2.5 结论复核成立）。
- 实测（`tasks/_sftp_search_concurrency_verify.py`，复用 Task 11 脚手架、临时库隔离；
  `tasks/` 在 .gitignore 内，脚本仅存本机不入库）：种入 40×8 MiB（309 MiB）无命中
  文本，一次 content 搜索（workers=1）真实持续 **5.27s**：
  - A 组（默认 threaded）：`hello` 之后、`done` 之前发 6 个普通 API 请求
    （预设列表 / OpenAPI schema），单个 latency **0.02–0.09s**，6 个全部在流仍开着时
    完成（open_after 全真）→ 并发不互相阻塞；
  - B 组（对照组，显式 `--nothreading`，流时长 5.37s）：首个普通请求 latency=**5.36s**，
    直到流的 done 帧到达后才返回 → A 的判据有鉴别力，现象归因 threading。
- 打包版相对该实测只多 PyInstaller 冻结环境这一层，记在「打包版冒烟未执行」缺口下。

**grep 档真机人工验证：仍未闭合（最要紧的残留项）**
- 缺的环境：一台开 shell/exec 的真实企业 SFTP（非 chroot，或 chroot 且路径映射一致），
  其上须有一棵含**真软链接**的目录树——Windows/Git Bash 造不出真软链接，本地无法取证。
  需用户提供：该服务器地址（入账时脱敏）、账号凭据。
- 要做的比对：同一查询在 grep 档与 client 档各跑一次，记录 grep/find 版本、是否 chroot、
  `workers=1` vs `workers=4` 结果是否一致，并据此定夺 §6「grep 跳过软链接 vs walker 跟随」。
- 定夺完成前**不得**把 `grep -r` 改成 `-R`（那只是把分歧挪到服务器报法那一侧，不消除分歧）。

**待用户拍板的产品问题**
1. ~~列值模式把表头之后的 `Unit`/`Min`/`Max` 三行当作数据值取走~~ → **2026-09-21 已拍板
   改为跳过**（论证、判据与真数据 56/56 复测见 §3.5；实现 `scanners.py` 的
   `LIMIT_ROW_TOKENS`，测试 `test_sftp_search_scan.ColumnTests`）。
2. `max_candidates` 默认 5000（契约允许上限 50,000）：用户曾表示要能一次捞上万再分批
   下载——默认值是否上调（或表单直接暴露该参数）**仍待定夺**。

**dark/light 主题走查证据位置**
- Task 17 走查截图 5 张在 `test/screenshots_night/walk17_*.png`（`02_dir_context_menu`、
  `03_chip_on_data_night`、`04_download_disabled_night`、`08_chip_on_data_light`、
  `08_download_disabled_light`）；`test/*` 在 .gitignore 内 → 只存本机，不入库。
- Task 15/16 的走查按计划做过（类型检查 + 手动走查），但走查截图随当时的临时脚手架
  清理删除，**无落盘件**（如实记录）。

