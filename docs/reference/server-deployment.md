# 服务器形态部署指南（局域网 · 单进程 · 无 nginx）

适用：把 LQ-DataPrase 后端部署到一台局域网服务器上，约 20 人用浏览器访问。
形态依据见 `docs/specs/2026-10-14-server-deployment-first-run-design.md`（单进程 + Django 同源服务 SPA）。

**服务器 OS 已拍板：Linux（2026-10-23）。** 进程模型走**方案 A**：systemd 直接跑
`standalone.py`（单进程、`runserver --noreload`、Django 自己对外发静态与 SPA）。
gunicorn 那一档（方案 B）记在 §6，本轮不做。本文的命令行全部按 bash/systemd 写；
`set X=...` 那种 cmd 写法已经没有了。

## 1. 必须提前准备的东西

| 环境变量 | 必填 | 说明 |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | 是 | 固定 `config.settings.server` |
| `LQDP_SERVER_BASE_DIR` | 是 | 可写**本地盘**。决定 `db.sqlite3` / `media/` / `staticfiles/` 的位置。**不能指网络盘**（WAL 依赖共享内存映射，NFS/SMB 上不安全） |
| `DJANGO_ALLOWED_HOSTS` | 是 | 逗号分隔的具体 IP/主机名，例：`10.0.0.9,server01`。忘记设就不启动；填 `*` 也需要另外设 `LQDP_ALLOW_WILDCARD_HOSTS=1` |
| `SECRET_KEY` | 是 | 不能用 `base.py` 里那个 `django-insecure-…` 开发默认值（它随源码分发，等同没有密钥） |
| `SFTP_CONFIG_KEY` | 是 | Fernet 密钥：`python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`。**必须环境给定，本档不提供从 SECRET_KEY 派生的回落**（见 §5 缺陷说明） |
| `LQDP_BOOTSTRAP_ADMIN_PASSWORD` | 首次启动必填 | 见 §2；建完管理员就可以撤掉 |

生成 `SECRET_KEY`：
```
python -c "from django.core.management.utils import get_random_secret_key;print(get_random_secret_key())"
```

### 1.1 系统包与运行时前置件

| 项 | 要求 | 为什么 |
|---|---|---|
| Python | 3.13.x，与开发机同一大版本 | `requirements/base.txt` 的钉版（Django 6.0.5 / pandas 3.0.3 / numpy 2.4.6 / matplotlib 3.10.9）是按 3.13 的二进制兼容窗口选的 |
| systemd | 发行版自带即可 | §3 的 unit 负责守护与自愈（`runserver` 自己没有） |
| fontconfig + 中文字体 | 例：`apt install fontconfig fonts-noto-cjk` | 导出图形的中文渲染，见 §1.2。**这条不做，导出的图是静默坏的** |
| 数据目录 | 本地 ext4/xfs 可写目录，例 `/srv/lqdp` | 承上表 `LQDP_SERVER_BASE_DIR` |
| Node | 只有构建前端时需要 | 在服务器上 `npm ci && npm run build`，或从 Windows 开发机把 `frontend/dist` 同步过来（§3） |

不需要 Go 工具链，也不需要 `unrar`/`p7zip` 这类外部二进制：`excelize==0.0.9` 在 PyPI 上是
`py3-none-any` 的纯 Python 端口；`py7zr`/`rarfile` 在 `apps/` 里没有运行时导入点。

### 1.2 中文字体：装完必须自证 matplotlib 认得

`apps/export/fonts.py` 的 matplotlib 候选是
`SimHei / Microsoft YaHei / SimSun / Noto Sans CJK SC / Noto Sans CJK JP / DejaVu Sans`。
前三个是 Windows 随附字族，Linux 上都不存在；若 Noto 那两项也没命中，就落到 DejaVu Sans ——
而 DejaVu **没有中文字形**，直方图与箱线图的轴标题、图例会变成一片豆腐块。这不是报错，
是「导出成功但产物不可用」，所以必须主动验。

matplotlib 在 Linux 上通过 `fc-list` 枚举系统字体（读本机装的 3.10.9 源码
`matplotlib/font_manager.py:findSystemFonts` 确认，Windows 分支走的是注册表那一侧），
因此装完字体还要：

1. 清一次字体缓存，且要清**服务账号**那份：`rm -rf /srv/lqdp/.mpl`（§3 用 `MPLCONFIGDIR` 把它钉在数据目录里）。
2. 用服务账号跑这条自检，输出里必须出现候选列表中的名字：

```
sudo -u lqdp MPLCONFIGDIR=/srv/lqdp/.mpl /srv/lqdp-src/.venv/bin/python -c \
  "from matplotlib import font_manager as fm; \
   print(sorted({f.name for f in fm.fontManager.ttflist \
                 if any(k in f.name for k in ('CJK','Source Han','WenQuanYi','Noto Sans'))}))"
```

（Windows 侧另验过一次首项解析：`fm.findfont(FontProperties(family='SimHei'))` →
`C:\Windows\Fonts\simhei.ttf`，即 SimHei 仍然第一个命中，既有 PNG 观感不变。）

⚠ 有的发行版把 Noto CJK 打成 `.ttc` 字体集合，而 matplotlib 只读集合的**第一面**
（`findSystemFonts` 把 `.ttc` 当普通 ttf 收，`FontEntry` 里根本没有 face_index 概念 ——
读 3.10.9 源码确认）⇒ 上面可能只列出 `Noto Sans CJK JP` 而不是 `SC`。
候选列表里 JP 排在 SC 之后就是为了这种情况；如果两个都没有，说明字体包没装对或
fontconfig 没索引到，**继续往列表里加名字是没用的**。

## 2. 首次启动会撞的那道互锁（务必先读）

服务器上的库是空的 → 首次启动时 `_bootstrap` 现场创建管理员账号。此时若绑定的是非回环地址
而没设 `LQDP_BOOTSTRAP_ADMIN_PASSWORD`，进程会**直接拒绝启动**并提示原因
（`standalone.py` 里的互锁：内置默认口令 `admin123` 是公开已知的，不能挂到网口上）。

所以第一次启动前先设好一个真实口令。这不是 bug，是设计。

同理，`seed_users` 命令在非开发档也会拒绝执行（它硬编码三个演示口令）。给真实用户开号请走
管理界面「用户管理」，不要用 `seed_users`。

## 3. 启动

### 3.1 环境文件

`/etc/lqdp/server.env`（`chown root:lqdp`、`chmod 640`，服务账号可读即可）：

```
DJANGO_SETTINGS_MODULE=config.settings.server
LQDP_SERVER_BASE_DIR=/srv/lqdp
DJANGO_ALLOWED_HOSTS=10.0.0.9,server01
SECRET_KEY=...
SFTP_CONFIG_KEY=...
LQDP_BOOTSTRAP_ADMIN_PASSWORD=...
MPLCONFIGDIR=/srv/lqdp/.mpl
```

systemd 的 `EnvironmentFile` 不做 shell 展开、也不剥行内注释，所以每行只写 `KEY=值`，
**不要在值后面加 `#` 注释**（那会被当成值的一部分）。首次启动建完管理员后，
把 `LQDP_BOOTSTRAP_ADMIN_PASSWORD` 那一行删掉再重启。

### 3.2 systemd unit

`/etc/systemd/system/lqdp.service`：

```
[Unit]
Description=LQ-DataPrase 后端（服务器形态 · 方案 A：单进程 standalone）
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=lqdp
Group=lqdp
WorkingDirectory=/srv/lqdp-src
EnvironmentFile=/etc/lqdp/server.env
ExecStart=/srv/lqdp-src/.venv/bin/python standalone.py --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
TimeoutStopSec=20
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

第一次拉起：

```
systemctl daemon-reload
systemctl enable --now lqdp
journalctl -u lqdp -f          # 看 bootstrap 与访问日志，见 §7 验收
```

关于这个 unit 的四个决定：

- **只跑一个进程，不要复制成多个。** SQLite 的写并发与两处进程内状态
  （解析 LRU 缓存、SFTP 连接池）都只在单进程下成立；多 worker 换来的是
  `database is locked`。
- **`Restart=always`** 是 `runserver` 自己缺的那块（无守护、无请求超时、无 worker 自愈）
  的补偿；进程崩了 5 秒后回来，SQLite 的 WAL 在下次打开时自行回滚未完成的写。
- **`TimeoutStopSec=20` 够用**：`standalone.py` 在起服务前就装了 SIGTERM/SIGINT 处理器
  （`apps/common/shutdown.py`），收到停止信号会先关闭所有数据库连接（SQLite 由此
  checkpoint WAL 并释放文件锁）再退出，整个动作是百毫秒级。Linux 上**不需要**
  `POST /api/v1/system/shutdown/` 那条通路 —— 那是为 Windows 准备的（那里的 SIGTERM
  根本不会作为信号送达），服务器档也不必设 `LQDP_SHUTDOWN_TOKEN`（不设则该路由 404）。
- **`MPLCONFIGDIR` 要显式给**：服务账号通常没有可写的家目录，matplotlib 会退回一个临时
  目录当配置与缓存并打一条警告 —— 字体缓存因此留不下来，每个新进程都要重扫一遍系统字体。
  指到数据目录下一个固定位置最省事。
  `PrivateTmp=true` 之类可以继续加，但注意「设置 → 存储路径」显示的临时目录会变成那个私有 `/tmp`。

`standalone.py` 一条命令就把「迁移 + 建管理员 + 起服务」做完了；它对 settings 档用的是
`os.environ.setdefault`，所以上面环境文件第 1 行就能把桌面档换成服务器档，**无需改代码**。

前端产物必须先构建：服务器档从**源码树里的** `frontend/dist` 同源发送 SPA
（`config/settings/server.py` 按代码位置算这个路径，**不看** `LQDP_SERVER_BASE_DIR`，
所以 `dist` 必须和 `manage.py` 在同一棵目录里；实测：`/` 返回 200（1719 字节的 `index.html`），
前端路由 `/pages/analysis` 同样 200，不会 404）。没有 nginx，静态资源也归 Django 发。
目录不存在时会在启动时给一条可见警告，届时浏览器打开根路径会 404。

**升级前端的正确顺序：`npm run build` → 重启服务。**
`DEBUG=False` 下 Django 的缓存模板加载器会把 SPA 的 `index.html` 常驻进程内存，只换磁盘文件的话，
进程仍在发旧 HTML，而旧 HTML 引用的 chunk 名已被新构建替换 → **整页空白且没有任何报错**
（2026-10-14 实测：`#app` 零子节点，`document.scripts` 还指向上一次的 hash）。

另注意构建模式：给 Electron 用的产物必须是 `npx cross-env VITE_ELECTRON=true npm run build`（相对 base），
普通 `npm run build` 产出绝对路径 `/assets/...`，在 `file://` 下同样静默白屏。服务器档走 http 同源，两者都能用。

**进程模型 = 方案 A（已拍板）**：`runserver --noreload` 默认是**多线程**的
（读本机 Django 6.0.5 源码确认：只有 `--nothreading` 会把它关掉），20 人档够用，
但它是 Django 的开发服务器 —— 没有 TLS、没有慢客户端隔离、没有请求超时，
绑定端口时会固定打一条
`WARNING: This is a development server. Do not use it in a production setting.`
（不想要就在环境文件里加 `DJANGO_RUNSERVER_HIDE_WARNING=true`：该分支在 `runserver` 的
`on_bind()` 里，只影响这一条横幅）。
接受这些缺口的理由是单进程与 SQLite/进程内状态的兼容性，代价由 `Restart=always` 兜一半。
想换成 gunicorn（方案 B）的条件见 §6。

首启日志里还会有一条 `RuntimeWarning: Accessing the database during app initialization`。
它不是部署故障：`apps/jobs/apps.py` 的 `ready()` 在**服务启动路径**上会查一次库，
把上次崩溃/重启留下的 `running` 僵尸作业判成 `error`（否则前端会永远轮询一个已死的作业）。
判据取的是 `manage.py` 的第二个词去撞「离线命令」名单，而 `python standalone.py --host …`
的第二个词是 `--host`（或根本没有），名单里都没有 ⇒ 每次开机都会打这条警告。取舍写在 `apps/jobs/apps.py`
的模块头里：宁可多做一次无害 UPDATE，也不留一个永远 `running` 的作业。


## 4. 备份

只备三样，`media/` **不备**（原始数据在另一台服务器上且那边自带备份，本服务器的 media 是缓存）：

```
cd /srv/lqdp-src
.venv/bin/python manage.py backup_db                        # 备到 <BASE_DIR>/backups，默认保留 14 份
.venv/bin/python manage.py backup_db --dest /srv/lqdp-backup --keep 30
LQDP_BACKUP_KEEP=30 .venv/bin/python manage.py backup_db     # 保留份数也可以走环境变量
```

保留份数的优先级是 `--keep` > `LQDP_BACKUP_KEEP` > 14；`--dest` 缺省用 `LQDP_SERVER_BASE_DIR/backups`。
服务器档跑这条会固定多打一行警告（`未携带 secret.key：本次根密钥来自环境变量 SECRET_KEY…`），
那是下面「服务器档没有 secret.key」那条的预期输出，不是失败。

- 用 `VACUUM INTO` 而不是复制文件：库跑在 WAL 下，未 checkpoint 的提交帧只在 `-wal` 侧文件里，
  复制主库文件会得到一个连表都没有的库。
- `secret.key`：**桌面/打包档**下它是根密钥的唯一副本（刻意不随 `data_dir` 迁移），
  缺了命令会直接报错拒绝交付 —— 漏了它，恢复出来的实例 JWT 签名与所有派生密钥都对不上。
- **服务器档没有 `secret.key` 文件**：本档要求 `SECRET_KEY` 与 `SFTP_CONFIG_KEY` 由环境变量
  给定，所以 `backup_db` 不会（也无法）把它们放进备份，跑完会出一条警告。**这两个变量的备份
  责任在部署配置那一侧**（systemd unit / 环境文件 / 密钥管理器），请与库备份同等对待：
  缺任何一个都恢复不出可用实例。
- 备份目录同样必须是本地盘。
- 定时调度用 systemd timer（OS 已拍板 Linux，2026-10-23）。**不要**直接写 cron ——
  cron 拿不到 §3.1 那个环境文件，`backup_db` 会因为缺 `LQDP_SERVER_BASE_DIR` 直接拒跑。

`/etc/systemd/system/lqdp-backup.service`：

```
[Unit]
Description=LQ-DataPrase 库备份（一次性）

[Service]
Type=oneshot
User=lqdp
Group=lqdp
WorkingDirectory=/srv/lqdp-src
EnvironmentFile=/etc/lqdp/server.env
ExecStart=/srv/lqdp-src/.venv/bin/python manage.py backup_db --dest /srv/lqdp-backup
```

`/etc/systemd/system/lqdp-backup.timer`：

```
[Unit]
Description=每天 03:30 备份 LQ-DataPrase 库

[Timer]
OnCalendar=*-*-* 03:30:00
RandomizedDelaySec=600
Persistent=true

[Install]
WantedBy=timers.target
```

```
mkdir -p /srv/lqdp-backup && chown lqdp:lqdp /srv/lqdp-backup
systemctl daemon-reload
systemctl enable --now lqdp-backup.timer
systemctl list-timers lqdp-backup.timer          # 下次触发时间
systemctl start lqdp-backup.service              # 先手跑一次，别等第二天
journalctl -u lqdp-backup.service --no-pager     # 看到 [backup] ok 才算数
```

`RandomizedDelaySec` 避开整点、`Persistent=true` 让关机错过的日子在开机后补跑。

- **没做过恢复演练的备份等于没有备份**。

恢复：停进程（`systemctl stop lqdp`）→ 用备份覆盖 `db.sqlite3` + `secret.key` + `system_config.json`（若有）→
把环境文件导进当前 shell 后补迁移 → 起进程 → 验证能登录且 SFTP 连接可用。

```
set -a; . /etc/lqdp/server.env; set +a
cd /srv/lqdp-src && .venv/bin/python manage.py migrate --run-syncdb
```

## 5. 已知限制（上线前请逐条确认接受）

1. **内网明文传输**。没有 nginx 就没有 TLS，口令与 JWT 在局域网上是明文。可选：接受（受信网段）
   / 找一台反代 / 其它。这是一个安全姿态决定，需要负责人拍板，不由代码默认替您决定。
2. **已存的 SFTP 口令不会跟着库走**。2026-10-14 实测：既有那条存密是用 `base.py` 里写死的
   **开发期默认密钥**加密的；而且开发档与打包档的 KDF 参数不同
   （`apps/sftp/crypto.py:32-33` 的 `dataphrase.sftp.config`/390k vs 打包档
   `config/settings/standalone.py` 里 `SFTP_CONFIG_KEY` 的 PBKDF2 派生块：`sftp-config`/100k），
   **换档即解不开**。服务器档因此要求显式给定 `SFTP_CONFIG_KEY`、不给回落。
   后果：从桌面/dev 搬过来的 `sftp_sftpconfig` 行在新档下解不开 → **请在服务器上重新录入 SFTP 配置**
   （与"服务器从头开始"的既定口径一致）。若要保留旧 token，需要单独做一次 re-key（旧 key 解、新 key 存）。
3. **单次 browse 一块最多 500 行**（与账号设置「默认每页行数」的上限同源）。直连接口要更多会被钳回 500。
   2026-10-23 起还要**再按列数钳一次**：单块**目标** ≤ 约 35.5 万个单元格（渲染进程内存预算，见
   `docs/reference/renderer-memory-baseline-2026-10-22.md` §6/§11），但 `blockCap.effectiveBlockSize`
   同时保证**每块不低于 50 行** ⇒ 列数超过约 **7,100**（`355,029 ÷ 50 = 7,100.58`）时**该下限生效（赢）**、
   让位的是单元格预算，
   单块格数**可以超预算**（10,000 列就是 50 × 10,000 = 500,000 格）。所以 4,000 列的文件即使设置 500 行
   也只取 88 行一块；窄文件（列数少）不受影响，仍是纯的行上限。驻留的历史块数同样按单元格预算封顶（最多 20 块）。
   百兆链路下前端默认块 100 行 ≈1.2MB ≈0.1–0.2s，够用；大文件的导出下载才是真流量，导出侧的
   定向压缩尚未做（见 spec §5）。
4. **没有备份过的 media 不恢复**：media 是缓存，丢了就重新从 SFTP 源服务器取。
5. **非管理员看不到存储路径**。桌面形态「设置 → 存储路径」对所有角色展示（那一行写的是用户
   自己的磁盘）；服务器形态这几个字段披露的是**服务器**的目录结构、库文件与配置文件位置，
   所以 `SYSTEM_PATHS_VISIBLE_TO_ALL=False` 让 `GET /api/v1/system/paths/` 对非管理员返回 403，
   该页只显示「存储路径仅管理员可见」。连带影响：用户指南里「去设置页找落盘目录」这条路径
   在服务器形态只对管理员成立。（2026-10-23 本机实跑：管理员带 token `GET` 返回 200 且 `data_dir`
   就是 `LQDP_SERVER_BASE_DIR`；未认证 `GET` 返回 401；`viewer` 角色 `GET` 返回
   **403 `code:"forbidden"`**，而同一个 viewer 的 token 读 `/api/v1/auth/profile/` 是 200
   —— 有这条对照，403 才只能是权限闸门，不是账号失效。）
6. **`media/` 没有自动回收通路**。全仓唯一的清理命令是
   `apps/jobs/management/commands/prune_jobs.py`，它只删 7 天前处于 done/error/cancelled
   的**作业产物**，不动 SFTP 取回的数据文件；`requirements/*.txt` 与 `config/settings/server.py`
   里也没有任何 cron/beat 入口。所以磁盘按**取回量 × 保留期**线性增长（按每天几十 GB 估，
   30 天就是 TB 级），不是按「缓存窗口」自动收敛。上线前要么按保留期把盘配够，
   要么先定「取回文件何时可删」这条策略并做成一个管理命令。
   作业产物那一半可以先自动化：`manage.py prune_jobs --days=N` 挂进 §4 的 timer
   （在 `lqdp-backup.service` 之外另开一个 oneshot 即可），但**取回的数据文件不在它范围内**。

## 6. 已定 / 还等哪些拍板

**已定（2026-10-23）**：

- 服务器 OS = **Linux**；进程模型 = **方案 A**（§3 的 systemd + `standalone.py`）。
- 备份调度 = systemd timer（§4）。
- 作业进程池的启动语义在 Linux 上不再靠平台默认：`apps/jobs/executor.py` 显式钉了
  `mp_context=spawn`（Windows 默认本来就是 spawn，Linux 是 fork；CPython 3.14 起
  Linux 默认还要改成 forkserver）。判据见 `apps/jobs/tests_jobs.py`
  的 `test_pool_mp_context_is_pinned_not_left_to_default` —— 它断言的是「实参存在」，
  所以在 Windows 上也能拦住「删掉这个参数」。

**还等的两件**：

- 无 TLS 的安全姿态（§5.1）。
- 自助找回密码：现状只有管理员能给别人重置口令（`/api/v1/auth/users/{id}/reset_password/`），
  没有「忘记密码」入口。20 人共用一台服务器时这是运营摩擦。

**方案 B（gunicorn）什么时候再动**：`requirements/production.txt` 里 gunicorn 是全树唯一
故意没钉版本的一条，注释写明「Windows 上装不上所以量不了」—— Linux 上现在能量了，但方案 A
用不到它，所以本轮**不**钉版本、**不**装。真要换 B 之前必须先解决两件事，否则会把方案 A
躲开的问题一次引进来：

1. spawn 子进程会重跑父进程的 `__main__`，而 gunicorn 的控制台脚本没有 `if __name__` 保护
   ⇒ 子进程可能再去启动一个服务。这条**尚未在 Linux 上实测**，是先决实验，不是结论。
2. `config/wsgi.py` 目前不装 `install_signal_handlers()`，也不跑 bootstrap
   （迁移 / 建管理员 / 静态），换 B 要把这两步显式补上。

## 7. 首启验收（跑一遍再宣布上线）

第 1–5 条都在本机（Windows + 同一份服务器档 + 一次性的 `LQDP_SERVER_BASE_DIR`）实跑过，
期望值就是当时读到的结果；在 Linux 上应当一致，若不一致就是部署问题而不是文档问题。
第 6 条只能真机验（下面单独说）。

```
BASE=http://127.0.0.1:8000      # 或 http://<服务器IP>:8000
PW='<管理员口令>'                # 环境文件里那行用完就删了（§3.1），所以这里手填或从密钥管理器取

# 1) SPA 同源可达（未构建前端产物时这里会 404）
curl -s -o /dev/null -w '%{http_code} %{size_download}\n' $BASE/          # 期望 200，约 1.7KB 的 index.html

# 2) 前端路由不 404（同源 catch-all）
curl -s -o /dev/null -w '%{http_code}\n' $BASE/pages/analysis             # 期望 200

# 3) Host 头校验生效：打一个没登记过的 Host 必须被拒
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: evil.example.com' $BASE/api/v1/system/paths/   # 期望 400
#    （忘记设 DJANGO_ALLOWED_HOSTS 的表现不是 400，是根本不启动，见 §1 那张表）

# 4) 首启管理员可用，且返回的是 `token` 字段（不是 simplejwt 默认的 `access`）
curl -s -X POST $BASE/api/v1/auth/login/ -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"$PW\"}"                       # 期望含 "role":"administrator"

# 5) 管理员能读存储路径
TOK=$(curl -s -X POST $BASE/api/v1/auth/login/ -H 'Content-Type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"$PW\"}" \
  | .venv/bin/python -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -w '\nHTTP %{http_code}\n' $BASE/api/v1/system/paths/ \
  -H "Authorization: Bearer $TOK"                                          # 期望 200，data_dir == LQDP_SERVER_BASE_DIR
#    未认证同一请求应 401；viewer 角色应 403（本机已实跑，含对照：同一 viewer 的 token
#    读 /api/v1/auth/profile/ 返回 200，所以 403 确实出自权限闸门）。建探针账号：
#    curl -s -X POST $BASE/api/v1/auth/users/ -H "Authorization: Bearer $TOK" \
#      -H 'Content-Type: application/json' \
#      -d '{"username":"probe_viewer","password":"<够长的口令>","role":"viewer"}'      # 期望 201

# 6) 优雅停止：SIGTERM 会先关 DB 连接（WAL checkpoint）再退出
systemctl stop lqdp && journalctl -u lqdp -n 20 --no-pager
```

第 6 条的期望：进程秒级退出、端口释放，日志里出现 `Shutting down (signal SIGTERM)`
（由 `apps/common/shutdown.py` 的 `_cleanup()` 打）。**这一条本机复现不了** ——
Windows 上没有真正的 SIGTERM 投递，所以它是「按源码应有」而不是「实测得到」，
真机第一次 `systemctl stop` 时请确认；确认不到就回头看是不是 `TimeoutStopSec` 到点被 SIGKILL 了。

再加两条只能在真机上做的：**导出一次批量图表并打开 PNG 看中文有没有变方块**（§1.2），
以及 **在客户端 Electron 里把后端地址填成这台服务器**跑一遍登录（D1 的那条通路）。
