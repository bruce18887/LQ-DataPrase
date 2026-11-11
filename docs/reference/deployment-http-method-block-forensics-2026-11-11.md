# 部署入口拦截 PUT/DELETE 取证（2026-11-11）

> 结论先行：应用与 Django 没有按方法拦截。浏览器控制台里的
> `PUT /api/v1/auth/settings/` `ERR_CONNECTION_RESET` 发生在请求到达 Django 之前：
> 链路中间设备放行 GET/POST/OPTIONS，对 PUT/DELETE 直接重置连接，并用自己的 404 页
> 替换 Django 的 404/405。公网入口、账号、令牌与测试数据已脱敏，原值只在运维记录中保留。

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

- 2026-11-11：**未修复**。应用代码未改；等待入口设备放行 PUT/DELETE，
  或改为 TCP 模式映射/VPN。
- 复现账号为普通用户；管理端路径未实机进入，按 API 层推断。
- 本报告只记录取证与修复路径；两个前端小问题待单独授权后按
  `docs/reference/testing-gates.md` 选层修复。

## 外部参考

- 相同错误页指纹的公开案例：
  `https://github.com/liujingxing/okhttp-RxHttp/issues/74`
