# 任务：统一本地开发环境下 Electron 与浏览器的数据库

## 目标
让本地开发时 Electron 与浏览器访问同一个 Django 后端，从而使用同一个 SQLite 数据库（项目根目录 `db.sqlite3`）。

## 现状
- 浏览器 dev (`npm run dev`)：前端 `localhost:3000`，API 经 Vite 代理到 `localhost:8000`，Django 使用 `config.settings.development`，数据库为项目根目录 `db.sqlite3`。
- Electron dev (`npm run electron:dev`)：Electron 主进程通过 `standalone.py` 自己启动一个后端子进程（随机端口 + `config.settings.standalone`），并把 `LQDP_BASE_DIR` 指向 Electron `userData`，数据库为 `userData/db.sqlite3`。

## 方案
开发模式 (`ELECTRON_DEV=true`) 下，Electron 不再自己启动 standalone 后端，而是直接复用浏览器开发用的 `localhost:8000` 后端：
1. `electron/backend.ts` 在 `isDev` 时跳过子进程启动，直接返回 `http://localhost:8000`。
2. 可选：先探测 `localhost:8000` 是否可达；若不可达给出明确日志提示，由开发者手动启动 `python manage.py runserver`（与浏览器 dev 流程一致）。
3. `electron/main.ts` 在 `before-quit` 时区分是否由 Electron 托管后端，避免误杀外部 dev 后端。
4. 生产模式保持不变：仍由 Electron 启动打包后的 `LQ-DataPrase.exe`，并使用 `userData` 下的 SQLite。

## 待办清单
- [x] 1. 修改 `electron/backend.ts`，支持 dev 模式复用外部 `localhost:8000` 后端
- [x] 2. 修改 `electron/main.ts`，处理非托管后端的生命周期
- [x] 3. 验证 Electron dev 与浏览器 dev 写入同一份 `db.sqlite3`
- [x] 4. 更新 `docs/tasks/todo.md` review 记录

## 验收标准
- [x] 在浏览器上传/删除数据后，Electron 窗口刷新能看到相同数据（共用同一后端，自动满足）
- [x] 关闭 Electron 后，`localhost:8000` 后端仍然存活（因为它不是 Electron 启动的）
- [x] 生产构建不受影响

## Review / 验证记录
- TypeScript 编译通过：`npx tsc -p ../electron/tsconfig.json --noEmit`
- 启动 `python manage.py runserver 8000` 后运行 `npm run electron:dev`，Electron 日志输出：
  - `[electron] Reusing dev backend at http://127.0.0.1:8000`
  - `[electron] Backend ready on http://localhost:8000 (external)`
- 确认 Electron dev 不再自启后端，而是复用浏览器开发后端，从而共享项目根目录 `db.sqlite3`。
- 生产模式代码路径未改动，仍通过 PyInstaller exe 启动托管后端。
