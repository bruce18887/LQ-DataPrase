# SFTP 浏览器搜索子系统（2026-09-20）

> 来源：用户需求「为 SFTP 浏览器做一个功能强大的搜索功能，参考 `DataPrase-SFTP Searcher/`」。
> 6 项决策已逐项拍板（见 §1.2）。实现计划另出（writing-plans）。
> 本文 file:line 为 2026-09-20 HEAD 快照，均已回读源码核实。

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

### 2.6 参考工具可复用资产

`DataPrase-SFTP Searcher/`（未跟踪目录，2026-09-20 新建的 CLI 原型）：

| 文件 | 能力 | 处置 |
|---|---|---|
| `search/csv_content_searcher.py` | 1MB 大块读 + paramiko prefetch 流水线 + 原始字节多编码匹配 + 命中即停 + 滚动窗口行号计数 + ATE 表头元数据解析 + 编码四探 | **移植为扫描内核主体** |
| 同上 `server_grep_supported` / `search_via_server` / `_build_grep_command` | 服务端 grep 快路径（含 chroot 路径映射验证、GBK `$'..'` bashism） | 移植，但**收紧启用条件**（§3.3） |
| 同上 `search_in_files` / `_open_connection` / `_recycle` | 每 worker 一条独立连接、连接坏了重开并重试一次 | 移植为 `connect.py` |
| `search/file_retriever.py` | 递归遍历 + `fnmatch` + 扩展名/大小/日期过滤 | 移植，但**遍历结构改 BFS**（§3.4） |
| `search/csv_column_reader.py` | `[DATA]` section 定位 + 表头取列 + 前 N 有效值 | 移植为列值模式 |
| `utils/cli_interface.py` | worker 数钳位 1–8、实时 summary、导出、文件名合法性校验 | 取钳位区间与导出思路 |
| `config/sftp_connection.py:21` | `set_missing_host_key_policy(paramiko.AutoAddPolicy())` | **不移植**，必须换成 `host_keys.open_verified_transport()` |

## 3. 方案

### 3.1 模块边界与行数预算

后端全部新增，`apps/sftp/views.py` 的 561 行**一行不动**：

| 文件 | 预算 | 单一职责 |
|---|---|---|
| `apps/sftp/search/contracts.py` | ~170 | `SearchSpec` dataclass、`clamp_spec()` 校验与钳位、`limits_hit` 记录 |
| `apps/sftp/search/connect.py` | ~130 | `SearchSession`：借还 N 条独立连接、降级、`opened/closed` 计数、统一关闭 |
| `apps/sftp/search/walker.py` | ~190 | BFS 目录队列、深度/条目/候选上限、环保护、`prune_dirs`、元数据过滤 |
| `apps/sftp/search/scanners.py` | ~270 | 内容扫描（字节级 + prefetch + 编码探测 + 命中即停）与列值扫描 |
| `apps/sftp/search/shell_grep.py` | ~180 | 两级能力探测、grep 命令构造（全 token `shlex.quote`）、输出解析、exec 通道 |
| `apps/sftp/search/engine.py` | ~290 | `select_engine()` 谓词、阶段机、线程池、事件队列、取消、进度节流 |
| `apps/sftp/search_views.py` | ~200 | `SftpSearchMixin`：`POST /sftp/search/`（SSE）+ 预设 CRUD |
| `apps/sftp/models.py` | +30 | `SftpSearchPreset` + 迁移 |

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
| `max_entries` | 200 000 | 500 000 | **唯一真正防遍历失控的闸**；剪枝命中的目录不计入 |
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
7. 能力探测通过（分两级，见 §3.6）

任一不满足 → 回落 client 引擎，**回落原因必须进 `notice` 事件**，不能让人猜这次是哪档跑的。

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
- 跳过 `.` 开头条目（与 `views.py:537` `_collect_files` 现有行为一致）。
- 单目录 `listdir_attr` 失败 → `error{scope:"dir"}` 事件，**继续搜索**，不终止。
- 剪枝在**进入前**判定，被剪掉的子树不计 `max_entries`。

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

### 3.6 grep 加速档（shell_grep）

- **两级探测**：
  - `grep` 级：`grep --version` 可用 + SFTP/shell 路径映射一致（chroot 验证，参考
    `csv_content_searcher.py:213` 的 probe 手法）→ 支持无时间过滤的查询。
  - `find_xargs` 级：额外要求 `find -newermt` 与 `xargs -0 -r`（GNU 依赖）→ 才支持带时间过滤。
  - 探测不过 → 回落 client，`notice{code:"grep_unavailable", reason}`。
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

`unittest` + `django.setup()`，无 DB。这级吃下搜索最值钱的部分：

- `select_engine(spec)` 决策表——**§3.3 的 7 条条件每条单独钉一个正/反例**，尤其
  「非 ASCII `term` 必须回落」（防静默漏 GBK 文件）、「`fuzzy` 必须回落」、
  「整词 + ASCII 允许 grep」。这些条件存在的理由正是**结果不能取决于服务器恰好有没有 grep**。
- `clamp_spec()`——每个上限的边界值、**未知键必须被拒绝**、`mode=content` 空 `term` 报错、
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
| 大文件扫描耗时长 | 单次搜索分钟级 | `max_scan_bytes` 预算 + 命中即停 + 可取消 + 进度可见 |
| 临时连接消耗服务器 fd/线程 | 影响他人 | `workers` 上限 8，`finally` 无条件关闭，测试断言 `opened == closed` |
| 在制品 SSE 流泄漏占 daemon 线程 | 内存/句柄增长 | threaded runserver 下不冻结应用；`timeout` 兜底 + 显式取消入口常驻 |
| `SftpBrowser.vue` 545 → ~557，逼近 600 | 后续加东西必须先拆 | 本文显式记录；新代码全部落新文件 |
| 前端内存驻留 20 次运行 × 2000 命中 | 渲染进程占用 | `max_matches` 上限 + 会话历史仅存摘要，全量结果只留最近一次 |

## 7. 验收账目

（实施后填写：后端全量测试数、e2e 通过数、grep 档真机人工验证的服务器与结果、
dark/light 截图位置。）
