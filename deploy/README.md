# 服务器部署资产（方案 A：systemd + standalone）

这些文件是 `docs/reference/server-deployment.md` §3/§4 的**可执行正文**：配置只维护在这里，
指南只写判断依据与验收步骤。目标机按 Linux、服务账号 `lqdp`、代码 `/srv/lqdp-src`、
数据 `/srv/lqdp` 写；路径不同就同时改模板与指南，不要只改一边。

| 文件 | 安装到 |
|---|---|
| `server.env.example` | `/etc/lqdp/server.env`（`root:lqdp`、`640`） |
| `lqdp.service` | `/etc/systemd/system/lqdp.service` |
| `lqdp-backup.service` | `/etc/systemd/system/lqdp-backup.service` |
| `lqdp-backup.timer` | `/etc/systemd/system/lqdp-backup.timer` |

## 安装

```bash
cd /srv/lqdp-src
install -d -o lqdp -g lqdp -m 750 /srv/lqdp /srv/lqdp/.mpl
install -d -o lqdp -g lqdp -m 750 /srv/lqdp-backup
install -d -o root -g lqdp -m 750 /etc/lqdp

install -o root -g lqdp -m 640 deploy/server.env.example /etc/lqdp/server.env
$EDITOR /etc/lqdp/server.env
grep -n CHANGE_ME /etc/lqdp/server.env     # 必须无输出，否则说明还有占位值没填

systemd-analyze verify deploy/lqdp.service deploy/lqdp-backup.service deploy/lqdp-backup.timer
install -m 644 deploy/lqdp.service /etc/systemd/system/lqdp.service
install -m 644 deploy/lqdp-backup.service /etc/systemd/system/lqdp-backup.service
install -m 644 deploy/lqdp-backup.timer /etc/systemd/system/lqdp-backup.timer
systemctl daemon-reload
systemctl enable --now lqdp
systemctl enable --now lqdp-backup.timer
systemctl start lqdp-backup.service        # 先手跑一次，别等第二天
journalctl -u lqdp-backup.service --no-pager   # 看到 [backup] ok 才算数
```

首次启动前必须设 `LQDP_BOOTSTRAP_ADMIN_PASSWORD`（绑非回环又没有它时进程会拒绝启动）；
建完管理员后从环境文件删掉该行并 `systemctl restart lqdp`。

前端产物必须位于 `/srv/lqdp-src/frontend/dist`（与 `manage.py` 同树）。
升级顺序固定为 `npm run build` → `systemctl restart lqdp`：只换磁盘文件会继续发旧 `index.html`，
新 chunk 名对不上，浏览器整页空白且没有报错。

## 不要做的事

- **不要把 `lqdp.service` 复制成多份或加 worker**。SQLite 写并发与两处进程内状态
  （解析缓存、SFTP 连接池）都只在单进程下成立，多 worker 换来的是 `database is locked`。
- **不要用 cron 跑 `backup_db`**。cron 拿不到 `EnvironmentFile`，命令会因缺
  `LQDP_SERVER_BASE_DIR` 直接拒跑；用 `lqdp-backup.timer`。
- **不要在环境文件的值后面写 `#` 注释**。systemd 不剥行内注释，`#` 之后的内容会成为值的一部分。
- **方案 B（gunicorn）的模板不在本目录**。启用前先完成指南 §6 的两件先决实验。

## 验收与恢复

首启六条验收、字体自检、SIGTERM 路径与恢复演练见指南 §1.2、§4、§7。
`media/` 不备份也不自动回收，上线前先按保留期把盘配够。
