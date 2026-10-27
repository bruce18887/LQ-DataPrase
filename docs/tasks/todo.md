# 任务：端口配置的定案（2026-10-27）

## 结论

**开发启动器（`scripts/dev.mjs` + `scripts/dev-launcher.mjs`）已实现后删除**，只保留它的接线部分。
用户定案的原话是「删壳留接线」。

## 为什么删

需求收敛后剩下两个真实场景，两个都不需要启动器：

1. 「单独启动后端，前端只提供网页」 —— `.venv\Scripts\python.exe standalone.py --host 127.0.0.1 --port 8124`
   一条命令就够。实测 `/` 200（`<title>LQ-DataPrase</title>` + `<div id="app">`）、`/dashboard` 200、
   `/api/v1/ready/` 200，一个进程。前提是 `frontend/dist` 存在（`config/settings/standalone.py` 非冻结时读它）。
2. 「旧方式双击 exe 直接拉起」 —— 现成的，Electron 自己 spawn `resources/LQ-DataPrase.exe --port 0`。

而启动器起的是 `manage.py runserver`（development 档），那份 settings 没注册 `frontend_dist`，
根路径实测 **500 `TemplateDoesNotExist: index.html`** —— 它天生服务不了场景 1。它唯一不可替代的价值
是那两处 Electron 常量的接线，所以留下接线、删掉壳。启动器剩下的便利价值只有「改代码要 HMR」那一档，
用户没选。

## 保留的改动

- `electron/backend.ts`：`DEV_BACKEND_PORT` 由 `const = 8000` 改为 `Number(process.env.E2E_PORT || 8000)`。
  改之前「自定义后端口 + Electron」这个组合是坏的（Electron 硬去 8000 找后端）。
- `electron/main.ts`：dev 渲染 URL 由写死 `'http://localhost:3000'` 改为读 `E2E_FRONTEND_PORT`，兜底 3000。
- `electron/load-failure.ts`：dev 分支的排查文案不再写死 `:3000`，改引用 `attemptedUrl`（实际试过的那个地址）。
- `frontend/test/unit/portWiring.spec.ts`：新增 T2，钉「四个读者读同一对变量名」+ 两处兜底值与
  `standalone.py` / `vite.config.ts` 的默认值同源 + Vite 是 `strictPort`（这条是同源的成立前提）。
- `README.md`：「单独启动后端」与「自定义端口」两节，含 `E2E_*` 用法、`electron:dev` 的 `wait-on 3000` 写死这个坑、
  `ELECTRON_DEV=true` 必须加、以及数据目录的真实落点。

## 顺带量到的两条本机事实（写进 README 了）

- `LQDP_BASE_DIR` 只是锚点（`secret.key` 在那），`data_dir` 由锚点下的 `system_config.json` 决定，
  没配则用内建默认 `~\LQ-DataPrase`（`apps/common/system_config.py` 的 `apply_system_config`）。
  仓库根的 `system_config.json` 指的也是这里 ⇒ **开发态与打包态共用同一个 `db.sqlite3`**，两个后端不要同开。
- `electron-builder.yml` 顶部注释称 user data 在 `%APPDATA%/lq-dataprase` —— 实测那目录只有 Chromium 的
  profile 件（`Cache/Local Storage/Preferences`），没有库也没有 `system_config.json`。**这条注释是过期的**，
  要不要顺手改由用户定（属于文档缺陷，不是行为缺陷）。

## 已随壳一起消失的两个缺陷（无需再修）

- `down` 的竞态假警：两条收摊路径抢跑时会把已消失的进程报成「收不掉，请手查」（实测端口其实干净）。
- 我给后端计划注入的 `PYTHONUTF8=1` 与仓库既有决定冲突：`electron/backend-env.ts` 明写「刻意不设
  PYTHONUTF8=1，治乱码用 `PYTHONIOENCODING=utf-8`」并由 `backendEnv.spec.ts` 钉住。壳删了这条就不存在了；
  **但「自己接管子进程 stdout 时会撞到 cp936 乱码」这个现象是真的**，日后任何 spawn Python 并读管道的代码
  都要按 `PYTHONIOENCODING=utf-8` 那套办。

## 我这次实跑的一个操作失误

第一次跑打包 exe 前没先确认 `data_dir` 的解析结果，于是它落到了与开发实例共用的那个库上，
两个后端挤同一个 SQLite 约 14 分钟。日志 0 条 Traceback/ERROR、无 `Applying` 迁移行、进程已收干净、
临时件已删。**教训是：起第二个后端前先问一句它用的是哪个库文件。**

## 待用户定

- 这批要不要提交（含 `README.md` / `electron/*` / 新 spec / `affected-rules.mjs` 的回退）。
- `electron-builder.yml` 那条过期注释改不改。
- WSL 里的 `lqdp` 还是 `inactive`（我为了腾 8000 停的）：`wsl -u root systemctl start lqdp` 恢复。
