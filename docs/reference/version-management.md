# 版本管理规范

## 单一事实源

**应用版本号唯一定义在 `frontend/package.json` 的 `version` 字段**（semver 格式 `x.y.z`，当前 `0.2.0`）。

所有消费端均从该文件读取，无需也不应修改其他位置：

| 消费端 | 读取方式 | 作用 |
|--------|---------|------|
| UI 版本徽章 / 关于对话框 | `vite.config.ts` 构建时注入 `__APP_VERSION__`（读 `frontend/package.json`） | 界面显示 `v0.x.y` |
| 安装包 / 便携版命名 | electron-builder `artifactName: ${version}`（`directories.app: frontend`，天然读该文件） | 产物 `out/LQ-DataPrase-0.x.y-Setup.exe` |
| Electron `app.getVersion()` | 打包时写入 | 与注入值同源 |

**根目录 `package.json` 的 `version` 字段（固定 `0.0.0`）仅作 npm 元数据，不参与应用版本**，发版时不要修改（文件中已有 `_versionNote` 说明）。

## 发版流程

1. 确认功能完成、测试通过。
2. 修改 `frontend/package.json` 的 `version` 字段（参考 semver：功能新增 `+0.1.0`，缺陷修复 `+0.0.1`）。
3. 同步 `frontend/package-lock.json` 顶部两处 `version` 字段（`npm install` 也会自动同步，手动修改后请确认一致）。
4. 运行完整构建：`npm run dist:win`（或 `build.bat`）。
5. 发布产物 `out/LQ-DataPrase-<version>-Setup.exe` / `out/LQ-DataPrase-<version>-win.zip`，与 UI 显示版本一致。

## 历史背景

- v0.1.0 → v0.2.0 升级时曾只修改 `frontend/package.json` 一处，导致 UI 显示 0.1.0 而安装包命名为 0.2.0 的错位。本规范于 0.2.0 建立，统一版本来源，避免再次发生。
- 后端（Django / PyInstaller）对用户不可见，不维护独立版本号，跟随前端版本。
