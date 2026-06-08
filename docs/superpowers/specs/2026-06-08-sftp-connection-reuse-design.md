# SFTP 连接复用 — 消除每次点击的握手延迟

- 日期: 2026-06-08
- 状态: 设计已确认，待写实现计划
- 范围: 仅后端连接复用（不含前端预取、不含目录列表缓存）

## 1. 问题

SFTP 浏览器登录后，每次点击进入目录的响应慢，但用户网速正常。

**根因**：`apps/sftp/views.py:34-47` 的 `_get_connection()` 在每个请求里都新建
`paramiko.Transport` 并完成一次完整 SSH 握手（TCP 三次握手 + SSH 协议协商 +
认证，约 300–500ms，由多个网络往返构成），用完立即 `sftp.close()` /
`transport.close()`。凭据已通过 `apps/sftp/cache.py` 缓存，但**连接本身没有复用**，
因此每次点击都重复付握手代价。这与带宽无关，是连接建立的往返延迟。

`SftpBrowser.vue:98-101` 的注释已记录此根因，但当时仅做了"请求期间屏蔽重复点击"
的体感优化，未根治。

## 2. 目标与非目标

**目标**
- 登录后，每次点击目录的延迟从「握手 + listdir」降为「仅 listdir」。
- 改动集中、最小影响：新增一个 pool 模块 + 调整 `views.py` 的连接获取/释放。

**非目标（明确排除）**
- 前端悬停预取。
- 目录列表缓存（前端或后端）。
- 登录首次握手的优化（用户接受现状）。
- 跨 worker 共享连接（每个 worker 各自持有连接即可）。

## 3. 部署前提

- gunicorn **多 worker**，worker 类型为 **sync**（默认）。
- sync worker 内同一时刻只处理一个请求 → **同一 worker 不会并发访问同一
  `user_id` 的连接** → 连接池**无需加锁**。
- 每个 worker 进程各自维护自己的连接池；N 个 worker 最多 N 条到服务端的连接，
  可接受。

## 4. 架构

### 4.1 新增模块 `apps/sftp/pool.py`（约 60–80 行，无锁）

进程内、按 `user_id` 复用 SFTP 连接。对外接口：

```python
get_connection(user_id) -> paramiko.SFTPClient
    # 取或建连接。复用前校验存活；连接已死或空闲超时则丢弃并用缓存凭据重建。
    # 重建失败（无凭据/握手失败）抛出 SftpPoolError。

invalidate(user_id) -> None
    # 操作出错时调用：关闭并从池中移除该用户连接，使下次 get_connection 重建。

close(user_id) -> None
    # disconnect 时主动关闭并移除。
```

### 4.2 内部结构

```python
_pool: dict[user_id, _Entry]
# _Entry: transport, sftp, last_used (epoch 秒)
```

- **存活校验**：`get_connection` 复用前检查
  `entry.transport.is_active()`。失败 → 视为死连接，丢弃重建。
- **空闲驱逐**：若 `now - last_used > IDLE_TTL` → 关闭重建。
  `IDLE_TTL` 默认 300 秒，可由 `settings.SFTP_POOL_IDLE_TTL` 覆盖。
- **重建**：调用 `apps.sftp.cache.get_session(user_id)` 取凭据（host/port/
  username/解密后的 password），新建 Transport + connect + SFTPClient，写回池。
  无凭据或握手失败 → 抛 `SftpPoolError`（调用方映射为 `not_connected` /
  错误响应）。
- 每次成功 `get_connection` 后更新 `last_used`。
- **无锁**：sync worker 保证同一 user_id 不会并发访问。模块级字典在单进程内
  的读写在 sync 模型下不会交错。（若未来切换到 gthread/gevent worker，需引入
  per-user 锁——本设计不实现，但在模块 docstring 注明此前提。）

### 4.3 异常类型

新增 `SftpPoolError(Exception)`，在 `pool.py` 内定义。
重建失败时抛出，`views.py` 捕获后返回与现有 `not_connected` 一致的 400 响应。

## 5. `views.py` 改动

### 5.1 `_get_connection`
改为：

```python
def _get_connection(self, request):
    try:
        sftp = pool.get_connection(request.user.id)
        return sftp
    except (SftpPoolError, SftpSessionCacheError):
        return None
```

**返回值从 `(transport, sftp)` 改为单个 `sftp`**（transport 生命周期归 pool）。
所有调用点相应改为 `sftp = self._get_connection(request)`，判断
`if not sftp:` 返回 `not_connected`。

### 5.2 移除所有 close，成功路径不关连接
删除以下方法成功路径里的 `sftp.close()` / `transport.close()`：
- `list_files`
- `download`
- `download_dir`（注意：SSE generator 的 `finally` 里也不再 close，改为不处理，
  连接留池复用；仅在异常时 invalidate）
- `download_batch`
- `_single_download_parse`
- `_batch_download_parse`

### 5.3 异常路径改为 invalidate
所有 `except` 分支里原本的 `sftp.close(); transport.close()` 改为：

```python
pool.invalidate(request.user.id)
```

让可能损坏的连接被丢弃、下次重建。

### 5.4 `disconnect`
在 `delete_session` 之后加：

```python
pool.close(request.user.id)
```

确保用户主动断开时连接立即释放，不残留在池中。

### 5.5 download_dir 的 SSE 注意点
`download_dir` 用 `StreamingHttpResponse` + generator，下载耗时可能较长。
其间连接被该请求独占——sync worker 下这是天然串行，无并发问题。generator
正常结束后**不关闭**连接（留池复用）；若中途异常，在 `finally` 里
`pool.invalidate(user_id)`（因为流式过程中连接状态可能已不可靠）。

## 6. 数据流（点击目录）

```
点击文件夹
  → 前端 listFiles(path) → GET /sftp/list_files/?path=...
  → views.list_files
  → pool.get_connection(user_id)
       命中且存活 → 直接返回已有 sftp（无握手）   ← 关键收益
       未命中/已死 → cache.get_session 取凭据 → 重建（偶发一次握手）
  → sftp.listdir_attr(path)   ← 仅此一次网络往返
  → 返回 items
```

复用命中时，延迟从「握手(多往返) + listdir」降为「仅 listdir(单往返)」。

## 7. 错误处理

| 场景 | 行为 |
|------|------|
| 池中无连接、缓存有凭据 | 重建连接，正常返回 |
| 池中无连接、缓存无凭据（会话过期） | 抛 SftpPoolError → 400 not_connected，前端提示重新连接 |
| 池中连接已被服务端踢掉（is_active 假） | 丢弃 → 用缓存凭据重建 |
| 连接空闲超过 IDLE_TTL | 主动重建 |
| listdir/get 操作中途失败 | invalidate(user_id)，返回错误响应；下次请求重建 |
| 用户 disconnect | pool.close 释放连接 |

## 8. 测试

E2E / 集成测试放在 `test/` 目录（遵循项目约定）。

- **复用验证**：mock paramiko，断言连续两次 `get_connection(same_user)` 只触发
  一次 `Transport.connect`（第二次复用）。
- **死连接重建**：令 `transport.is_active()` 返回 False，断言重新 connect。
- **空闲驱逐**：将 `last_used` 调到超过 TTL，断言重建。
- **invalidate**：调用后池中无该 user，下次 get 重建。
- **无凭据**：`get_session` 返回 None 时 `get_connection` 抛 SftpPoolError。
- **多用户隔离**：user A、user B 各自独立连接，互不影响。
- **views 集成**：连续两次 `list_files` 请求只建一次连接（验证端到端复用）。

## 9. 文件清单

- 新增 `apps/sftp/pool.py`（约 60–80 行）
- 修改 `apps/sftp/views.py`（`_get_connection` + 约 8 处 close/except + disconnect）
- 新增测试 `test/`（pool 单元测试 + views 复用集成测试）

均在 600 行单文件上限内。

## 10. 风险

- **服务端 idle 超时**：SSH 服务端可能在若干分钟无活动后断开。已由
  `is_active()` 存活校验 + 重建覆盖，用户无感（偶发一次重建握手）。
- **worker 类型变更**：若将来改用 gthread/gevent worker，无锁假设失效，会出现
  paramiko 并发问题。已在 docstring 注明前提，需届时补 per-user 锁。
- **连接泄漏**：worker 进程退出时操作系统回收 socket；空闲驱逐 + invalidate
  覆盖运行期回收。可接受。
