# 部署入口拦截 PUT/DELETE 取证（2026-11-11）

> 结论先行：应用与 Django 没有按方法拦截。浏览器控制台里的
> `PUT /api/v1/auth/settings/` `ERR_CONNECTION_RESET` 发生在请求到达 Django 之前：
> 链路中间设备放行 GET/POST/OPTIONS，对 PUT/DELETE 直接重置连接，并用自己的 404 页
> 替换 Django 的 404/405。公网入口、账号、令牌与测试数据已脱敏，原值只在运维记录中保留。
>
> 2026-11-11 补充：拿到服务器 SSH 后按 §5 复测，确认应用与服务器本机均正常；
> 拦截点是公网入口的**认证/行为管理网关**（tcpdump 证据与网关指纹见 §9）。

## 1. 环境与范围

- 产品：LQ-DataPrase v0.8.0，HTTP 明文，非 localhost。
- 账号：普通用户角色（非管理员）。管理端页面未实机进入，影响面按 API 层推断。
- 后端指纹：合法响应带 `Server: WSGIServer/0.2 CPython/3.13.17`；
  `GET /api/v1/auth/settings/` 带 token 返回 200。
- 部署基线：`docs/reference/server-deployment.md` 的服务器档写明「没有 nginx，
  Django 自己就是对外进程」。本次观测到的中间设备不在该文档描述的应用栈内，
  属于部署入口的外加层。

## 2. 现象

### 2.1 浏览器控制台

访问登录页、仪表板、数据管理、数据分析、SFTP、权重画图、系统设置时：

| 报错 | 性质 |
|---|---|
| `Cross-Origin-Opener-Policy header has been ignored ... untrustworthy origin` | HTTP 明文导致，非应用错误 |
| `ElementPlusError: [el-pagination] small is about to be deprecated` | 前端代码告警 |
| `[api] Request failed: PUT /auth/settings/ - status=no response, code=ERR_NETWORK, message=Network Error` | **锁定问题** |
| `Failed to load resource: net::ERR_CONNECTION_RESET`（同一 PUT） | **锁定问题** |
| 版本按钮 aria-label 原样显示 `v{{ APP_VERSION }}` | 前端模板小缺陷 |

### 2.2 触发路径

在 `/analysis` 单文件分析页：

- 页面加载后**第一次切换测试项**，图表布局记忆的 800ms 防抖保存触发
  `PUT /api/v1/auth/settings/`，报 `ERR_CONNECTION_RESET`；
- 勾选「显示QQ图」时，勾选状态保存再次触发同一 PUT，同样被重置；
- 之后继续切换测试项不再重复报错（客户端把失败也记进了本地 `knownState`，
  防抖不再发），但**刷新页面后会再次出现**。

调用链：

`frontend/src/composables/useChartMemory.ts:147-160`（flush）
→ `frontend/src/stores/userSettings.ts:100-120`（save）
→ `frontend/src/api/auth.ts:183-185`（`api.put('/auth/settings/')`）。

### 2.3 切换测试项实测

通过「上一个/下一个」与下拉框共切换 10+ 个测试项（含 `Part_No`、`Test_Time`、
泄漏电流类参数等），并勾选直方图 + QQ 图：

- 每次 `POST /api/v1/analysis/histogram/` 均 200；
- 勾选 QQ 图后 `POST /api/v1/analysis/qqplot/` 均 200；
- 图表正常刷新，**没有 JS 异常，没有分析接口的 4xx/5xx，没有数据相关报错**；
- 唯一失败仍是 `PUT /api/v1/auth/settings/`。

## 3. 方法矩阵证据

浏览器与服务器入口同时复现；本机 curl / 原始 TCP 的结果一致：

| 请求 | 观测 |
|---|---|
| `GET /api/v1/auth/settings/`（带 token） | 200；Django 响应头；`Allow: GET, PUT, HEAD, OPTIONS` |
| 未认证 `GET/POST/PATCH/OPTIONS` 同一路径 | Django 401 |
| `PUT` / `DELETE`（带/不带 token；API 路径、`/`、`/index.html`、不存在路径；HTTP/1.0；空体） | `ECONNRESET`，0 字节，无 HTTP 响应 |
| `GET/POST` 不存在路径 | 中间设备 404：双状态行 + `Sorry, Page Not Found` + 大量 NUL 填充 + 无 `Server` 头 |
| `POST/PATCH` 到只允许 GET/PUT 的 settings | Django 405 后紧跟中间设备的 404 页（双状态行） |
| 本机 `PUT http://example.com/` | 405（本机网络不拦 PUT） |

关键判据：

1. **不是 Django**：未认证 GET/POST/PATCH/OPTIONS 都能拿到 Django 的 401；
   不存在的路径返回的 404 没有 `Server` 头，正文是固定页 + NUL 填充，
   不是 Django/DRF 的响应形状。
2. **不是客户端网络**：本机对公网 HTTP 站点发 PUT 能得到正常的 405；
   同一台机器对部署入口发 PUT 则被 RST。
3. **不是应用代码**：仓库内没有按 HTTP 方法重置连接的中间件/路由；
   `PUT /auth/settings/` 本应由 DRF 正常处理。Django 的
   `Allow: GET, PUT, HEAD, OPTIONS` 也证明路由本身支持 PUT。

因此：客户端与 Django 之间存在一个 **HTTP 感知的代理/WAF/端口映射器/HTTP 模式隧道**，
它按方法白名单放行 GET/POST/OPTIONS，重置 PUT/DELETE，并替换 404/405 错误页。

外部指纹参考：同样的 `Sorry, Page Not Found` + `Expires: 0` + `Cache-control: private`
错误页在阿里云云防火墙的响应中出现过（见下方「外部参考」）。但本次公网 IP 归属
中国电信四川（AS4134），不能据此认定具体产品；该指纹只作为排查关键词，最终以
§5 的服务器本机/内网复测为准。

## 4. 影响面

| 功能 | 调用点 | 结果 |
|---|---|---|
| 图表布局/勾选/3D 视角记忆 | `frontend/src/composables/useChartMemory.ts:147-160` → `frontend/src/stores/userSettings.ts:100-120` → `frontend/src/api/auth.ts:183-185` | 保存失败，刷新后布局/勾选回默认 |
| 设置页各账号级设置 | 同上 `PUT /auth/settings/` | 保存失败（按 `frontend/src/api/index.ts:206-211`，未标 silent 的请求会弹全局网络错误提示） |
| 个人资料保存 | `frontend/src/api/auth.ts:170-172`（`PUT /auth/profile/`） | 失败 |
| 管理端用户编辑/启用停用/删除 | `frontend/src/pages/admin/UserManagement.vue:327,354,407` | 失败（普通用户账号未实机进入管理页，按 API 层推断） |
| 数据文件激活/删除、批次目录删除 | `frontend/src/api/datafiles.ts:175,178,192,195` | 失败 |
| 分析/导出/SFTP/登录等 POST 通路 | `POST` | 不受影响 |

## 5. 定位与修复顺序

> **2026-11-11 已执行步骤 1–2**：服务器本机、内网 IP、Tailscale 入口的 PUT/DELETE
> 全部正常到达 Django；只有公网入口异常。方法矩阵与 tcpdump 证据见 §9。

1. **服务器本机自测**（端口换成入口实际映射的后端本地端口）：
   - Linux：`curl -i -X PUT http://127.0.0.1:<backend_port>/api/v1/__probe__/`
   - Windows：`curl.exe -i -X PUT http://127.0.0.1:<backend_port>/api/v1/__probe__/`
   - 期望是 Django 的 404。若本机也重置，说明服务器本机装了带 HTTP 方法过滤的
     防护/代理软件（安全狗、云锁、宝塔防火墙、火绒等），查它的拦截日志。
2. **同一局域网另一台机器复测**：PUT 服务器内网 IP。
   若内网正常、公网异常，则问题在外网入口（路由器端口映射 / 花生壳 / frp / cpolar / 云 WAF）。
3. **检查入口设备/服务的 HTTP 方法白名单**：放行 PUT/DELETE；
   如果是 HTTP 模式的内网穿透，改成 **TCP 模式**或改用 VPN。
4. **修复后验收**：清缓存 → 登录 → `/analysis` 切换测试项 → 控制台无
   `PUT /auth/settings/` 报错；刷新后布局/勾选仍保留；设置页保存成功；
   管理端编辑/删除成功（用管理员账号另验）。
5. **兜底方案（不推荐优先做）**：把 settings/profile 的写接口从 PUT 改成 POST，
   需同时改后端路由与测试，且 DELETE 没有等价的 POST 语义；问题根因仍在入口，
   应先修入口。

## 6. 代码侧小问题（可单独提交）

- `frontend/src/pages/dashboard/components/TestItemOverviewSection.vue:114`：
  `el-pagination` 的 `small` 改为 `size="small"`，消掉 Element Plus 3.0 弃用告警。
- `frontend/src/components/layout/Topbar.vue:47`：
  普通 HTML 属性里的 `{{ }}` 不会被 Vue 插值，改为
  `:aria-label="'版本 v' + APP_VERSION + '，点击查看详情'"`。
- COOP 告警不用改代码：站点上 HTTPS 后自然消失；保持 HTTP 则接受该告警。

## 7. 复现命令

```bash
# 合法 GET（确认后端与路由正常）
curl -i http://<entry>/api/v1/auth/settings/ \
  -H 'Authorization: Bearer <token>'

# PUT 探针（不写数据；不存在路径也应先到达 Django 再 404）
curl -i -X PUT http://<entry>/api/v1/__probe__/

# 方法矩阵：把 PUT 换成 GET/POST/OPTIONS/DELETE 各跑一次
# 期望：GET/POST/OPTIONS 得到 HTTP 响应；PUT/DELETE 在入口被 RST
```

```bash
# 本机对照：证明客户端网络不拦 PUT
curl -i -X PUT http://example.com/          # 期望 405
```

## 8. 状态

- 2026-11-11（当日修复）：**已修复，方案 2（TLS 终结）落地**。公网入口认证网关仍拦明文
  PUT/DELETE（未动网关），但在服务器映射端口加 nginx TLS 终结、反代到挪去回环的 Django，
  写请求以密文穿过网关。落地步骤与验收见
  `docs/reference/deployment-tls-termination-runbook-2026-11-11.md`。
  - 应用侧配套（本地分支 `feat/tls-proxy-support`，提交 `04f4515`）：base.py 加
    `SECURE_PROXY_SSL_HEADER`（分页 next 认 https）、audit `_client_ip` 取 XFF 最右真实 IP。
    服务器代码落后本地 86 提交、无审计模块，故只外科插入 base.py 一行（审计修复随未来升级生效）。
  - 验收（公网 https 入口，真实账号 + 本地真实客户端路径 + 服务器 hairpin 三方一致）：
    PUT/DELETE 探针拿到 Django 形状 404（不再 RST；明文 PUT 仍 RST 作对照）；
    `PUT /auth/settings/`、`PUT /auth/profile/` 均 200；分页 next 为 https（host:port 正确）；
    浏览器登录→分析页切测试项/勾 QQ 图→**刷新后勾选保留**，控制台零错误、零失败请求；
    tplms/discuzq 无回归。管理端 CRUD 与审计 IP 因复现账号为普通用户、审计未部署而跳过。
  - 公网安全 follow-up（既有形态、非本批引入，另立工单）：登录限流 XFF 伪造（`NUM_PROXIES`）、
    DEBUG=True + 匿名 API 文档/Django admin 暴露（切 `config.settings.server` 档）——见 runbook「公网安全 follow-up」。
- 2026-11-11（修复前快照）：未修复。应用代码未改；入口设备的 PUT/DELETE 白名单仍未放行。
  可用绕过已实测：Tailscale 直连（§9.5）；根治步骤见 §9.7。
- 复现账号为普通用户；管理端路径未实机进入，按 API 层推断。
- 本报告只记录取证与修复路径；两个前端小问题待单独授权后按
  `docs/reference/testing-gates.md` 选层修复。

## 9. 2026-11-11 服务器侧复测与入口定位（SSH）

拿到服务器 SSH 后，按 §5 的步骤 1–2 复测。结论：**应用与 Django 仍然无罪**，
拦截发生在公网入口的认证/行为管理网关上；服务器本机与其它入口均正常。

### 9.1 服务器形态（只读核对）

- 应用服务器为 Ubuntu 26.04；LQ-DataPrase 后端由
  `manage.py runserver 0.0.0.0:<backend_port>` 直接对外（手动启动，不是部署文档里的
  systemd + `standalone.py` 形态；本文不把它当故障原因）。
- `:80` 上的 nginx 属于同一台机器上的另一个项目（tplms），与 LQ-DataPrase 无关。
- `ufw` 未启用；`iptables -S` / `nft list ruleset` 只有 Tailscale 自带规则；
  未安装安全狗、云锁、宝塔防火墙等按 HTTP 方法拦截的软件。

### 9.2 方法矩阵（同一命令，四个入口）

| 入口 | GET / POST / OPTIONS | PUT / DELETE | 结论 |
|---|---|---|---|
| 服务器本机 `127.0.0.1:<backend_port>` | Django 响应 | Django 响应 | 正常 |
| 服务器内网 IP `:<backend_port>` | Django 响应 | Django 响应 | 正常 |
| Tailscale 地址 `:<backend_port>` | Django 响应 | Django 响应 | 正常 |
| 公网入口 | 有 HTTP 响应 | `ECONNRESET`，0 字节 | **异常** |

- 对不存在的路径，前三种入口返回 Django 的 404；公网入口返回一个无 `Server` 头、
  0 字节、头部畸形的 404（curl 报 `Header without colon`）。
- `PUT /api/v1/auth/settings/`（不带 token）在前三种入口返回 Django 的 401，
  且带 `Allow: GET, PUT, HEAD, OPTIONS`；在公网入口被 RST。

### 9.3 tcpdump：PUT 到网关即被丢弃

在服务器上对 `tcp port <backend_port> or tcp port <entry_port>` 抓包，并从服务器
回打公网入口（hairpin）复现：

- GET：请求字节被转发到 `<backend_port>`，Django 返回 401，响应再被转发回客户端；
- PUT：请求字节只到达网关，**没有**被转发到 `<backend_port>`；网关随后向客户端回
  `RST`（抓包中源为公网入口地址）。
- 同一 TCP 连接上的 GET/PUT 表现不同 ⇒ 不是连接级/L4 拦截，而是 HTTP 方法级。
- NAT 后的源地址是上游认证网关的内网地址（见 9.4），不是应用服务器自身。

### 9.4 网关指纹

- 公网映射/NAT 的下一跳是一台「身份认证系统」设备：
  `GET http://<gateway>/` 返回 200，页面标题「身份认证系统」，登录入口 `/webAuth/`，
  `Server` 头为空，页面 `Last-Modified: 2021-08-14`。
- 它同时承担 NAT/端口映射与 HTTP 过滤；具体型号与管理入口见运维记录。
- 未登录其管理界面，未尝试任何默认口令；本节只记录外部可观测指纹。

### 9.5 已验证的绕过（不改服务器、不改应用）

- 用 Tailscale 直连 `http://<tailnet_addr>:<backend_port>`：
  登录 → `/analysis` → 切换测试项 → 勾选「显示QQ图」；
  `PUT /api/v1/auth/settings/` 返回 200（`POST /api/v1/analysis/qqplot/` 也 200）；
  刷新页面后勾选仍保留；控制台无业务错误（只有 HTTP 明文导致的 COOP 告警）。
- 验收后已把测试账号的图表设置还原（QQ 图未勾选、参数仍为 `Part_No`），
  未改服务器、未改应用代码。

### 9.6 绕过路径实测（同日下午补测）

- **PATCH 不可靠**：带 token 的 PATCH 能到 Django（`/files/999999/` 返回 404、
  `/auth/settings/` 返回 405、`/auth/users/999999/` 返回 403，状态码与 Django 一致），
  但网关会把响应头弄坏（curl 报 `Header without colon`、无响应体）；
  真实浏览器 `fetch` 3s 超时。⇒ **不要只把 PUT 改成 PATCH**。
- **TLS 可以穿过**：从公网入口发 TLS ClientHello，抓包显示 `\x16\x03\x01…`
  原样到达 `<backend_port>`，Django 回 `HTTP/1.1 400 Bad request syntax ('\x16\x03\x01\x06')`；
  网关既没有终止 TLS，也没有按方法重置。⇒ 在 `<backend_port>` 前放 TLS 终结
  （nginx/stunnel，自签或正式证书）可让 PUT/DELETE 以密文通过。
- **POST 正常**：登录、上传、分析、SFTP 等 POST 通路长期验证无问题；⇒ 应用侧
  增加 POST 别名（或 `X-HTTP-Method-Override` 中间件）可作为不碰网关的方案。

### 9.7 修复顺序（未执行，按优先级）

1. 在认证网关上把该入口映射改为**纯 L4/TCP 转发**，或在「行为管理 / HTTP 管控 /
   防火墙」里对该服务器/端口放行 `PUT`/`DELETE`（加入白名单或免认证）。这是根治。
2. 必须保留现有公网 URL、但拿不到网关权限：在 `<backend_port>` 前加 TLS 终结
   （§9.6），让 PUT/DELETE 以密文穿过；自签证书需要用户接受一次警告，
   有域名时用正式证书更好。
3. 远程用户可安装 Tailscale：直连 `<tailnet_addr>:<backend_port>`（§9.5，
   零改动，已验证）。
4. 最后才考虑应用侧把写接口改成 POST 兼容：需同时改前端、后端路由与测试，
   且 DELETE 没有等价的 POST 语义，影响面大；不应先做这条。

## 外部参考

- 相同错误页指纹的公开案例：
  `https://github.com/liujingxing/okhttp-RxHttp/issues/74`
