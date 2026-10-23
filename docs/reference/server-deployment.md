# 服务器形态部署指南（局域网 · 单进程 · 无 nginx）

适用：把 LQ-DataPrase 后端部署到一台局域网服务器上，约 20 人用浏览器访问。
形态依据见 `docs/specs/2026-10-14-server-deployment-first-run-design.md`（单进程 + Django 同源服务 SPA）。

## 1. 必须提前准备的东西

| 环境变量 | 必填 | 说明 |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | 是 | 固定 `config.settings.server` |
| `LQDP_SERVER_BASE_DIR` | 是 | 可写**本地盘**。决定 `db.sqlite3` / `media/` / `staticfiles/` 的位置。**不能指网络盘或映射盘**（WAL 依赖共享内存映射，SMB 上不安全） |
| `DJANGO_ALLOWED_HOSTS` | 是 | 逗号分隔的具体 IP/主机名，例：`10.0.0.9,server01`。忘记设就不启动；填 `*` 也需要另外设 `LQDP_ALLOW_WILDCARD_HOSTS=1` |
| `SECRET_KEY` | 是 | 不能用 `base.py` 里那个 `django-insecure-…` 开发默认值（它随源码分发，等同没有密钥） |
| `SFTP_CONFIG_KEY` | 是 | Fernet 密钥：`python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`。**必须环境给定，本档不提供从 SECRET_KEY 派生的回落**（见 §5 缺陷说明） |
| `LQDP_BOOTSTRAP_ADMIN_PASSWORD` | 首次启动必填 | 见 §2 |

生成 `SECRET_KEY`：
```
python -c "from django.core.management.utils import get_random_secret_key;print(get_random_secret_key())"
```

## 2. 首次启动会撞的那道互锁（务必先读）

服务器上的库是空的 → 首次启动时 `_bootstrap` 现场创建管理员账号。此时若绑定的是非回环地址
而没设 `LQDP_BOOTSTRAP_ADMIN_PASSWORD`，进程会**直接拒绝启动**并提示原因
（`standalone.py` 里的互锁：内置默认口令 `admin123` 是公开已知的，不能挂到网口上）。

所以第一次启动前先设好一个真实口令。这不是 bug，是设计。

同理，`seed_users` 命令在非开发档也会拒绝执行（它硬编码三个演示口令）。给真实用户开号请走
管理界面「用户管理」，不要用 `seed_users`。

## 3. 启动

```
set DJANGO_SETTINGS_MODULE=config.settings.server
set LQDP_SERVER_BASE_DIR=D:\lqdp-server
set DJANGO_ALLOWED_HOSTS=10.0.0.9,server01
set SECRET_KEY=…
set SFTP_CONFIG_KEY=…
set LQDP_BOOTSTRAP_ADMIN_PASSWORD=…

python standalone.py --host 0.0.0.0 --port 8000
```

`standalone.py` 一条命令就把「迁移 + 建管理员 + 起服务」做完了；它对 settings 档用的是
`os.environ.setdefault`，所以上面第 1 行的环境变量就能把桌面档换成服务器档，**无需改代码**。

前端产物必须先构建：服务器档从源码的 `frontend/dist` 同源发送 SPA（没有 nginx，静态资源也归
Django 发）。目录不存在时会在启动时给一条可见警告，届时浏览器打开根路径会 404。

**升级前端的正确顺序：`npm run build` → 重启服务。**
`DEBUG=False` 下 Django 的缓存模板加载器会把 SPA 的 `index.html` 常驻进程内存，只换磁盘文件的话，
进程仍在发旧 HTML，而旧 HTML 引用的 chunk 名已被新构建替换 → **整页空白且没有任何报错**
（2026-10-14 实测：`#app` 零子节点，`document.scripts` 还指向上一次的 hash）。

另注意构建模式：给 Electron 用的产物必须是 `npx cross-env VITE_ELECTRON=true npm run build`（相对 base），
普通 `npm run build` 产出绝对路径 `/assets/...`，在 `file://` 下同样静默白屏。服务器档走 http 同源，两者都能用。

**进程模型未定**：`runserver --noreload` 不是长期服务进程（无 TLS、无慢客户端隔离、无守护）。
正式的进程托管形态（waitress / gunicorn / IIS）取决于服务器 OS 何时拍板，见 §6。

## 4. 备份

只备三样，`media/` **不备**（原始数据在另一台服务器上且那边自带备份，本服务器的 media 是缓存）：

```
python manage.py backup_db                 # 备到 <BASE_DIR>/backups，默认保留 14 份
python manage.py backup_db --dest D:\bak --keep 30
```

- 用 `VACUUM INTO` 而不是复制文件：库跑在 WAL 下，未 checkpoint 的提交帧只在 `-wal` 侧文件里，
  复制主库文件会得到一个连表都没有的库。
- `secret.key`：**桌面/打包档**下它是根密钥的唯一副本（刻意不随 `data_dir` 迁移），
  缺了命令会直接报错拒绝交付 —— 漏了它，恢复出来的实例 JWT 签名与所有派生密钥都对不上。
- **服务器档没有 `secret.key` 文件**：本档要求 `SECRET_KEY` 与 `SFTP_CONFIG_KEY` 由环境变量
  给定，所以 `backup_db` 不会（也无法）把它们放进备份，跑完会出一条警告。**这两个变量的备份
  责任在部署配置那一侧**（systemd unit / 环境文件 / 密钥管理器），请与库备份同等对待：
  缺任何一个都恢复不出可用实例。
- 备份目录同样必须是本地盘。
- 定时调度待 OS 拍板后接（Windows 计划任务 / cron）。
- **没做过恢复演练的备份等于没有备份**。

恢复：停进程 → 用备份覆盖 `db.sqlite3` + `secret.key` + `system_config.json`（若有）→
`python manage.py migrate --run-syncdb` → 起进程 → 验证能登录且 SFTP 连接可用。

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
   在服务器形态只对管理员成立。

## 6. 还等哪些拍板

- 服务器 OS（Linux / Windows Server）→ 决定进程托管形态与备份调度方式，也决定导出图形链路的
  进程启动语义要不要改（现有注释按 Windows spawn 写）。
- 无 TLS 的安全姿态（§5.1）。
- 自助找回密码：现状只有管理员能给别人重置口令（`/api/v1/auth/users/{id}/reset_password/`），
  没有「忘记密码」入口。20 人共用一台服务器时这是运营摩擦。
