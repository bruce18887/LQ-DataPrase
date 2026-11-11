# 部署入口 TLS 终结（方案 2）落地 runbook（2026-11-11）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让公网入口的 PUT/DELETE 以密文穿过认证网关，根治 `PUT /api/v1/auth/settings/` 被 RST；公网 URL 的 host:port 不变（http→https），不碰网关、不碰同机 tplms 的 nginx。

**Architecture:** 网关映射不变（公网 `$ENTRY_PORT` → 服务器 `$BACKEND_PORT`）。nginx 在 `$BACKEND_PORT` 上新增一个 TLS server 块接管该端口，反代到挪去 `127.0.0.1:$DJANGO_PORT` 的 Django。取证依据：`docs/reference/deployment-http-method-block-forensics-2026-11-11.md` §9.6 实测 TLS ClientHello 原样穿过网关。

**Tech Stack:** nginx（服务器已装，tplms 在用 :80）、openssl 自签证书（IP SAN，10 年）、Django settings 一行、`apps/accounts/audit.py` 一处。

---

## 为什么不是「应用零改动」：核实出的三处适配

写本 runbook 前在仓库里核实过，纯 nginx 反代会引入两个回归和一个体积陷阱，必须一起处理：

1. **分页 next 链接会变 http（混合内容被浏览器拦）**：DRF `PageNumberPagination` 的 `next/previous` 是绝对 URL，前端 `frontend/src/utils/paging.ts:38` 的 `collectAllPages` 跟着 `next` 走（管理页用户列表、审计页）。反代后 Django 不知道外层是 https，`next` 会拼成 `http://` → https 页面里被浏览器拦掉，翻页断在第二页。修法：`SECURE_PROXY_SSL_HEADER` 一行 + nginx 传 `X-Forwarded-Proto`。
2. **审计 IP 会全变 127.0.0.1**：`apps/accounts/audit.py:85-86` 的 `_client_ip` 只读 `REMOTE_ADDR`，反代后恒为回环。修法：回环来源时取 XFF **最右**一条（nginx 追加的真实客户端地址；左侧条目客户端可伪造，不能取）。
3. **nginx 默认 `client_max_body_size 1m` 会拦掉大数据文件上传**：配置里显式置 0（与 Django 直连现状一致）。

另核实过**不需要**处理的：全仓无 WebSocket（SFTP 下载是 fetch + ReadableStream）；API 纯 JWT 认证（`config/settings/base.py:200-202`），无 CSRF/会话 cookie 问题；停机端点 `POST /api/v1/system/shutdown/` 有「回环 + 每次启动随机 token」双闸（`apps/common/shutdown.py:359-396`），服务器未设 token 时恒 404——但反代会让回环闸失效，nginx 配置里仍在边缘直接 404 兜底。

## 填值表（只有部署者知道的值，先填这一段）

下文所有命令都引用这里的变量。**示例值仅占位，执行前全部换成真实值**；之后各步可整段照抄。

```bash
export PUB_IP=203.0.113.10        # 公网入口 IP（同事浏览器地址栏里的 IP）
export ENTRY_PORT=18080           # 公网入口端口（地址栏 : 后面那个）
export BACKEND_PORT=8000          # 网关映射到服务器的端口 = 现在 Django 监听的端口
export LAN_IP=192.168.1.50        # 服务器内网 IP（hostname -I 可查）
export SRC_DIR=/srv/lqdp-src      # 服务器上的源码目录（ps 里 runserver 的工作目录）
export DJANGO_PORT=18000          # Django 挪去的新回环端口，可保持默认
```

约定：Task 1 在**开发机仓库**做；Task 2 起在**服务器**上做（SSH）。服务器操作全部只新增文件/改绑定，不删数据、不动 tplms。

---

### Task 1: 代码适配（开发机仓库，TDD）

**Files:**
- Modify: `config/settings/base.py:31`（`ALLOWED_HOSTS` 之后加一行）
- Modify: `apps/accounts/audit.py:85-91`（`_client_ip`）
- Test: `test/backend/test_audit_writer.py`（`WriterTests` 内加 4 条）
- Test: `test/backend/test_file_pagination.py`（`FilePaginationTests` 内加 2 条）

- [ ] **Step 1: 写失败测试 —— 审计 IP（追加进 `WriterTests`，复用现有 `_request` 夹具）**

```python
    def test_loopback_proxy_takes_rightmost_xff_entry(self):
        """本机 TLS 反代：REMOTE_ADDR 恒为回环，真实客户端在 XFF 最右一条
        （nginx $proxy_add_x_forwarded_for 追加）；左侧条目客户端可伪造，不许取。"""
        request = self._request(ip='127.0.0.1')
        request.META['HTTP_X_FORWARDED_FOR'] = '203.0.113.9, 198.51.100.7'
        audit.record(request, 'login_success', actor=self.admin, target=self.admin)
        self.assertEqual(AuditEvent.objects.get().ip_address, '198.51.100.7')

    def test_non_loopback_source_ignores_xff(self):
        """直连（非回环）时 XFF 整条都不可信，仍记 REMOTE_ADDR。"""
        request = self._request(ip='10.99.0.31')
        request.META['HTTP_X_FORWARDED_FOR'] = '203.0.113.9'
        audit.record(request, 'login_success', actor=self.admin, target=self.admin)
        self.assertEqual(AuditEvent.objects.get().ip_address, '10.99.0.31')

    def test_loopback_without_xff_unchanged(self):
        """桌面档 Electron 直连回环、没有 XFF：行为与改前逐字相同。"""
        audit.record(self._request(ip='::1'), 'login_success',
                     actor=self.admin, target=self.admin)
        self.assertEqual(AuditEvent.objects.get().ip_address, '::1')

    def test_loopback_with_garbage_xff_rightmost_leaves_null(self):
        """替换后的值仍过 ip_address 校验：最右一条非法 → None，不入库脏值。"""
        request = self._request(ip='127.0.0.1')
        request.META['HTTP_X_FORWARDED_FOR'] = '203.0.113.9, not-an-ip'
        audit.record(request, 'login_success', actor=self.admin, target=self.admin)
        self.assertIsNone(AuditEvent.objects.get().ip_address)
```

- [ ] **Step 2: 写失败测试 —— 分页 https（追加进 `FilePaginationTests`）**

```python
    def test_next_link_is_https_behind_tls_proxy(self):
        """TLS 反代后分页 next 必须是 https：缺 SECURE_PROXY_SSL_HEADER 时
        https 页面拿到 http 链接，浏览器按混合内容拦掉，collectAllPages 断在第二页。"""
        resp = self.client.get('/api/v1/files/', {'page_size': 1},
                               HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['next'].startswith('https://'), resp.data['next'])

    def test_next_link_stays_http_without_proxy_header(self):
        """不带代理头（桌面/直连档）行为不变：仍是 http，不被强制升级。"""
        resp = self.client.get('/api/v1/files/', {'page_size': 1})
        self.assertTrue(resp.data['next'].startswith('http://'), resp.data['next'])
```

- [ ] **Step 3: 跑测试确认红**

Run: `python manage.py test test.backend.test_audit_writer test.backend.test_file_pagination`
Expected: 新增 6 条里 **3 条 FAIL**——`test_loopback_proxy_takes_rightmost_xff_entry`（实得 `127.0.0.1`）、`test_loopback_with_garbage_xff_rightmost_leaves_null`（实得 `127.0.0.1`）、`test_next_link_is_https_behind_tls_proxy`（实得 `http://` 开头）。另 3 条此时已绿——它们钉的是「不许变」的那侧（直连忽略 XFF、无 XFF 回环不变、无代理头仍 http）。

- [ ] **Step 4: 实现 —— `config/settings/base.py` 在 `ALLOWED_HOSTS = …`（line 31）之后加**

```python
# TLS 反代（服务器入口终结）后让 request.is_secure() 认出 https：DRF 分页的
# next/previous 是绝对 URL，缺了它 https 页面会拿到 http 链接被浏览器拦掉。
# 仅在请求带 X-Forwarded-Proto: https 时生效；该头必须由反代覆盖设置，直连档不受影响。
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
```

- [ ] **Step 5: 实现 —— `apps/accounts/audit.py` 的 `_client_ip` 整函数替换为**

```python
def _client_ip(request):
    raw = (request.META.get('REMOTE_ADDR') or '') if request else ''
    if raw in ('127.0.0.1', '::1'):
        # 本机反代转发时 REMOTE_ADDR 恒为回环；XFF 最右一条是 nginx 追加的
        # 真实客户端地址，左侧条目可被客户端伪造，不能取。
        xff = request.META.get('HTTP_X_FORWARDED_FOR') or ''
        if xff:
            raw = xff.split(',')[-1].strip()
    try:
        ipaddress.ip_address(raw)
    except ValueError:
        return None
    return raw
```

- [ ] **Step 6: 跑测试确认绿**

Run: `python manage.py test test.backend.test_audit_writer test.backend.test_file_pagination`
Expected: 全部 OK，0 failures。

- [ ] **Step 7: 批内门禁**

Run: `cd frontend && npm run test:e2e:affected`
Expected: 末行 `RESULT: PASS`。**注意**：本批命中 `config/` 全局清单（testing-gates.md §3），门禁会升全量（池 4 slot + 后端全套，6–8min 级）——这是规则不是意外。判绿只认末行 `RESULT:`，输出整段落盘再 grep，不用 `tail` 截。

- [ ] **Step 8: 本地提交（不 push —— origin 是公开仓库）**

```bash
git add config/settings/base.py apps/accounts/audit.py test/backend/test_audit_writer.py test/backend/test_file_pagination.py
git commit -m "feat(server): 支持 TLS 反代入口——分页 next 认 https、审计取 XFF 最右真实 IP"
```

---

### Task 2: 把代码带上服务器

**Files:** 服务器上 `config/settings/base.py`（必做）、`apps/accounts/audit.py`（**仅当服务器已有该文件**）

> **实测形态（2026-11-11）**：服务器代码可能远落后于本地 master（本次实测落后 86 个提交，`apps/accounts/audit.py` 在服务器上**不存在**——审计功能尚未部署到该服务器）。因此**不许整文件覆盖**：那会把本地其余改动拖进旧代码。做法是按服务器自己的文件锚点外科插入；服务器没有的文件跳过，其修复随未来升级自然生效。

- [ ] **Step 1: 比对版本，决定同步范围**

Run（服务器）: `ls "$SRC_DIR/apps/accounts/audit.py" 2>/dev/null; grep -n "ALLOWED_HOSTS = " "$SRC_DIR/config/settings/base.py"`
Expected: 看到 base.py 的 `ALLOWED_HOSTS` 锚点行；audit.py 存在与否决定它要不要同步。

- [ ] **Step 2: base.py 外科插入（锚点 = 服务器文件里的 `ALLOWED_HOSTS = …` 行）**

在该行之后插入与 Task 1 Step 4 逐字相同的 4 行（3 行注释 + `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')`）。用编辑工具或 `python3` 脚本按锚点插入，**不要** scp 整文件覆盖。服务器工作树本就有本地改动（实测），插入后 `git diff` 应只有这一处。

- [ ] **Step 3: audit.py（仅当文件存在）**

按 Task 1 Step 5 整函数替换服务器版本的 `_client_ip`；文件不存在则跳过并记录「审计 IP 修复待服务器升级后生效」。

- [ ] **Step 4: 确认到位**

Run（服务器）: `grep -n "SECURE_PROXY_SSL_HEADER" "$SRC_DIR/config/settings/base.py"`
Expected: 命中。若 audit.py 存在：`grep -n "HTTP_X_FORWARDED_FOR" "$SRC_DIR/apps/accounts/audit.py"` 也命中。

---

### Task 3: 服务器现状确认（只读，不改任何东西）

- [ ] **Step 1: 看清当前 Django 启动形态**

Run: `ps aux | grep -E "runserver|standalone" | grep -v grep`
Expected: 看到 `0.0.0.0:$BACKEND_PORT` 的 runserver。**记下完整命令与环境变量**（settings 档、venv、有没有 `--noreload`）——Task 6 只改绑定地址，其余逐字保留。若用了 `DJANGO_SETTINGS_MODULE=config.settings.server`，确认 `DJANGO_ALLOWED_HOSTS` 含 `$PUB_IP` 与 `$LAN_IP`（development 档默认 `*` 则无需动）。

- [ ] **Step 2: 确认端口与 nginx 现状**

Run: `ss -tlnp | grep -E ":$BACKEND_PORT |:80 " && nginx -v && ss -tlnp | grep ":$DJANGO_PORT " || true`
Expected: `$BACKEND_PORT` 被 python 占用、`:80` 被 nginx 占用（tplms，**不动它**）、`$DJANGO_PORT` 空闲（最后一条 grep 无输出）。

---

### Task 4: 自签证书（IP SAN，10 年）

**Files:** Create `/etc/nginx/ssl/lqdp.crt`、`/etc/nginx/ssl/lqdp.key`

- [ ] **Step 1: 生成**

```bash
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout /etc/nginx/ssl/lqdp.key -out /etc/nginx/ssl/lqdp.crt \
  -days 3650 -subj "/CN=LQ-DataPrase" \
  -addext "subjectAltName=IP:$PUB_IP,IP:$LAN_IP,IP:127.0.0.1"
sudo chmod 600 /etc/nginx/ssl/lqdp.key
```

SAN 必须覆盖同事实际输入的地址：公网 IP 走网关，内网 IP 走直连，两个都写进去。

- [ ] **Step 2: 核对 SAN**

Run: `openssl x509 -in /etc/nginx/ssl/lqdp.crt -noout -ext subjectAltName`
Expected: 列出 `$PUB_IP`、`$LAN_IP`、`127.0.0.1` 三个 IP。

---

### Task 5: 写 nginx TLS server 块（先只校验，不 reload）

**Files:** Create `/etc/nginx/conf.d/lqdp-tls.conf`（独立文件，不碰 tplms 的任何配置）

- [ ] **Step 1: 写入配置（@TOKEN@ 由下一步替换）**

```bash
sudo tee /etc/nginx/conf.d/lqdp-tls.conf > /dev/null <<'EOF'
server {
    listen @BACKEND_PORT@ ssl;
    server_name _;

    ssl_certificate     /etc/nginx/ssl/lqdp.crt;
    ssl_certificate_key /etc/nginx/ssl/lqdp.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    # 上传不设限，与 Django 直连现状一致（nginx 默认 1m 会拦掉大数据文件）
    client_max_body_size 0;

    # 旧 http 书签打到 TLS 端口时 nginx 原生回 400，这里 301 到 https。
    # 用 $http_host 原样保留客户端输入的 host:port（公网端口与本机端口可能不同）
    error_page 497 =301 https://$http_host$request_uri;

    # 桌面专属停机端点不许从公网碰（反代会让回环闸失效，边缘直接 404 兜底）
    location = /api/v1/system/shutdown/ { return 404; }

    location / {
        proxy_pass http://127.0.0.1:@DJANGO_PORT@;
        # 必须 $http_host（带端口）：DRF 分页 next 用它拼绝对 URL，$host 会丢端口
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        # 大文件导出/下载流式转发，不落 nginx 临时盘
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
EOF
sudo sed -i "s/@BACKEND_PORT@/$BACKEND_PORT/g; s/@DJANGO_PORT@/$DJANGO_PORT/g" \
  /etc/nginx/conf.d/lqdp-tls.conf
```

- [ ] **Step 2: 只校验，不 reload**

Run: `sudo nginx -t`
Expected: `syntax is ok` / `test is successful`。**此时不要 reload**——`$BACKEND_PORT` 还被旧 Django 占着，reload 会 bind 失败；接管动作在 Task 7。

---

### Task 6: Django 换绑回环（与 Task 7 连着做，中断窗口只有几秒）

- [ ] **Step 1: 停旧进程**

在原来启动 runserver 的终端 Ctrl+C（找不到终端就 `kill <PID>`，PID 来自 Task 3 Step 1；SIGTERM 即可，不要 `kill -9`）。

- [ ] **Step 2: 用原命令换绑重启（优先复用服务器自己的启动脚本）**

```bash
cd "$SRC_DIR"
# 首选：服务器若有启动脚本（实测有 start_backend.sh，会 source .env 保留 SECRET_KEY 等环境），
# 直接用它换绑，并脱离 SSH 会话保活（实测服务器无 tmux/screen，旧进程挂在某个 SSH 终端上）：
nohup ./start_backend.sh "$DJANGO_PORT" 127.0.0.1 > "$HOME/lqdp-backend.log" 2>&1 &
# 没有脚本时才裸起：与 Task 3 记下的原命令完全一致，只把绑定换成 127.0.0.1:$DJANGO_PORT，
# 原来的 settings 环境变量、venv、--noreload 等一律保留。
```

注意：换绑后**必须**确认新进程的环境变量与原进程一致（`tr '\0' '\n' < /proc/<新PID>/environ | grep DJANGO`），尤其 `DJANGO_SETTINGS_MODULE` 与 `SECRET_KEY` 来源——丢了环境会换档/换库。

- [ ] **Step 3: 确认新绑定活着**

Run: `curl -i http://127.0.0.1:$DJANGO_PORT/api/v1/health/`
Expected: `HTTP/1.1 200 OK`，`Server: WSGIServer/…`。

---

### Task 7: nginx 接管端口

- [ ] **Step 1: reload**

Run: `sudo nginx -t && sudo systemctl reload nginx`
Expected: test successful；reload 不断连接，tplms 的 :80 不受影响。

- [ ] **Step 2: 确认监听**

Run: `ss -tlnp | grep -E ":$BACKEND_PORT |:80 "`
Expected: `$BACKEND_PORT` 现在是 nginx，`:80` 仍是 nginx（tplms）。

---

### Task 8: 验收（判据来自取证文档 §5.4 + 本批新增）

- [ ] **Step 1: 命令行矩阵（整段输出落盘再 grep，别用 tail 截）**

```bash
# 关键判据：公网入口 PUT 不再 RST，拿到 Django 形状的 404
curl -ik -X PUT https://$PUB_IP:$ENTRY_PORT/api/v1/__probe__/
# DELETE 同验
curl -ik -X DELETE https://$PUB_IP:$ENTRY_PORT/api/v1/__probe__/
# 分页 next 必须是 https（先登录取 token，再验 next；库里需 >1 个文件）
TOKEN=$(curl -sk -X POST https://$PUB_IP:$ENTRY_PORT/api/v1/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"<账号>","password":"<口令>"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access"])')
curl -sk "https://$PUB_IP:$ENTRY_PORT/api/v1/files/?page_size=1" \
  -H "Authorization: Bearer $TOKEN" | grep -o '"next":"[^"]*"'
# tplms 无回归：与改前形状一致
curl -i http://127.0.0.1:80/
```

Expected: PUT/DELETE 返回 `HTTP/1.1 404` 且带 `Server: WSGIServer` 头（**不是** `ECONNRESET`、不是无 Server 头的网关 404 页）；`"next":"https://…"`；tplms 响应与改前一致。

- [ ] **Step 2: 浏览器清单（同事视角，首次访问接受一次证书警告）**

1. `https://$PUB_IP:$ENTRY_PORT` → 警告页点「高级 → 继续前往」→ 登录成功；
2. `/analysis` 切换测试项 + 勾选「显示QQ图」→ 控制台**无** `PUT /auth/settings/` 报错；
3. 刷新页面 → 布局/勾选保留（取证文档 §2.2 的原症状消失）；
4. 设置页保存、个人资料保存成功；
5. 管理员账号：用户编辑/停用/删除成功（**用临时测试账号验删除，别删真实用户**）；审计页翻页超过 20 条不断（验 next 链路），新审计行的 IP 是**真实客户端 IP** 而不是 127.0.0.1——**服务器版本若尚无审计功能（实测可能），此两项跳过，随未来升级再验**；
6. HTTP 明文导致的 COOP 告警消失（https 后自然消失，取证文档 §6）。

- [ ] **Step 3: 把结果回写取证文档 §8 状态**

`docs/reference/deployment-http-method-block-forensics-2026-11-11.md` §8 的「未修复」改为已修复 + 修复方式 + 验收日期。

---

### Task 9: 回滚预案（任何一步不对都可整体退回原状）

- [ ] **回滚命令（原状 = 明文 HTTP 直连，分钟级）**

```bash
sudo rm /etc/nginx/conf.d/lqdp-tls.conf
sudo nginx -t && sudo systemctl reload nginx
# Django 停掉，用 Task 3 记下的原命令（0.0.0.0:$BACKEND_PORT）重启
```

Task 1 的两处代码改动**无需回滚**：没有反代传头时 `SECURE_PROXY_SSL_HEADER` 不生效、`REMOTE_ADDR` 非回环时 XFF 分支不进——直连档行为与改前逐字相同（Task 1 的两条「不许变」测试钉着）。证书文件留着无害。

## 已知边界（本批不做）

- 自签证书：同事首次访问点一次警告；想彻底无警告需域名 + 正式证书，届时另立工单。
- 服务器仍是手动 runserver（取证文档 §9.1 形态），本批只改绑定地址，不顺手迁 systemd/standalone——那是独立工单。
- 网关本身未动：它仍拦明文 PUT/DELETE。哪天拿到网关权限做了根治（取证 §9.7 方案 1），本 TLS 层可保留（加密仍有价值）也可按 Task 9 退回。
- 审计回环集合未含 IPv4 映射形态 `::ffff:127.0.0.1`（`apps/common/shutdown.py` 的 `_LOOPBACK_ADDRESSES` 含它，且有 Windows 真机教训）。本 runbook 钉死 IPv4 回环绑定（`127.0.0.1:$DJANGO_PORT`）故不受影响；若未来 Django 改双栈监听，需补该形态 + 一条用例（质量复审 Minor #1）。
- `config/settings/server.py` 文件头「无 nginx / 无反向代理」的描述在本批后过时，后续顺手更新。
- DRF 节流 `get_ident` 在 `NUM_PROXIES` 未设时用整条 XFF 拼串做 key：反代后诚实客户端仍按真实 IP 限速，无新回归；攻击者轮换左侧伪造条目可绕 login 限速属 DRF 既有行为（直连同样可绕），要修另立工单评估 `NUM_PROXIES=1` 对直连档的影响，别塞进本批。

## 公网安全 follow-up（质量复审 surfaced，均为服务器既有形态、非本批引入，另立工单）

- **登录 IP 限流可被 XFF 伪造绕过**：DRF `NUM_PROXIES=None` 时 `get_ident` 用整条 XFF 拼串，左侧条目客户端可伪造；**直连 Django 同样可绕**（反代未引入），且每账号 5 次失败锁定（423，`apps/accounts/views.py`）仍在兜底。修法：后端 `REST_FRAMEWORK['NUM_PROXIES']=1`（取最右=网关 IP，关伪造；本拓扑网关 NAT 后公网源本就单一，粒度损失为零），需评估对直连/桌面档影响 + 补测试，另立工单。
- **DEBUG=True + 匿名 API 文档 + Django admin 公网暴露**：服务器跑 dev 档（`tasks.dev_spa`→development，`API_DOCS_ENABLED=True`），`/api/schema/`、`/api/schema/swagger/` 匿名可读全部端点结构，`/admin/`（Django admin）公网可达，DEBUG 报错页泄露路径。正解：切 `config.settings.server` 档（DEBUG=False/文档关/ALLOWED_HOSTS 收敛）。边缘临时硬化（可选）：本块加 `location ^~ /api/schema/ { return 404; }` 与 `location ^~ /admin/ { return 404; }`——**已核实 Vue 管理页走 hash 路由 `/#/admin/users`（`config/urls.py:100` catch-all + `router/index.ts`），边缘拦 `/admin/` 只挡 Django admin、不误伤 Vue 管理页**。
- **nginx 可选硬化（Minor）**：`client_max_body_size` 设大值（如 4g）而非 0（防未鉴权超大 POST 落盘填盘，`proxy_request_buffering` 默认 on）；497 跳转改 `=308`（保方法保体）；`ssl_session_cache shared:SSL:10m`；显式 AEAD cipher + `ssl_prefer_server_ciphers on`；全局 `server_tokens off`（影响 tplms/discuzq，慎动）。
- **审计 IP 归因局限**：网关把源 NAT 成其内网地址，nginx 追加的 XFF 最右一条是网关 IP 而非真实客户端——审计上线后对公网用户只能记到网关 IP（抗伪造但缺真实客户端归因），除非网关注入真实客户端 XFF。审计模块当前未部署到该服务器，暂无实际影响。