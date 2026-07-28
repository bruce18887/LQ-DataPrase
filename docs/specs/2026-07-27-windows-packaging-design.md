# LQ-DataPrase Windows 安装包打包方案设计

- 日期: 2026-07-27
- 范围: Windows 桌面端（NSIS 安装包 + 便携版 ZIP）
- 状态: 设计稿，待确认后实施

## 1. 目标

在现有 PyInstaller + electron-builder 基础上，提供两种可安装的 Windows 交付物：

1. **NSIS 安装程序**（`LQ-DataPrase-<version>-Setup.exe`）
   - 双击安装向导，支持选择安装目录、创建桌面/开始菜单快捷方式。
   - 安装后写入 `Add/Remove Programs`，支持卸载。
2. **便携版 ZIP**（`LQ-DataPrase-<version>-win.zip`）
   - 解压即可运行，不写注册表，适合内网、U 盘或快速分发。

不引入自动更新，用户手动下载新版本覆盖安装。

## 2. 当前架构回顾

```
frontend/                Vue 3 SPA
  ├─ src/
  ├─ dist/               ← npm run build
  └─ electron-dist/      ← npm run electron:build:ts
electron/                Electron 主进程 TS 源码
standalone.py            PyInstaller 入口，自举 SQLite + Django
lq_dataprase.spec        PyInstaller spec
build.bat                组合构建脚本
electron-builder.yml     electron-builder 配置
release/                 最终手动整理目录
```

当前构建流程：

```bash
cd frontend
npm run build                         # 1. 构建前端
npm run electron:build:ts            # 2. 编译 Electron
cd ..
build.bat                              # 3. PyInstaller 打包后端
electron-builder --config electron-builder.yml  # 4. 制作安装包
```

当前问题：

- `build.bat` 与 `frontend/package.json` 的脚本都有构建逻辑，职责分散。
- 输出目录不统一：`dist/`（PyInstaller）+ `out/`（electron-builder）+ `release/`（手动复制）。
- 没有便携版输出。
- 版本号硬编码/散落，安装包元数据（图标、版权、厂商）未配置。
- 没有 CI，构建完全依赖本地环境。

## 3. 推荐方案

### 3.1 输出产物

| 产物 | 文件名模板 | 说明 |
|---|---|---|
| 安装包 | `LQ-DataPrase-0.0.0-Setup.exe` | NSIS，x64，仅当前用户安装 |
| 便携包 | `LQ-DataPrase-0.0.0-win.zip` | 解压后运行 `LQ-DataPrase.exe` |

### 3.2 目录与脚本调整

**统一脚本入口**

将构建入口收敛到根目录一个命令：

```bash
npm run dist:win       # 完整构建：前端 → Electron → PyInstaller → 安装包 + 便携包
npm run dist:win:dir   # 只出 unpacked 目录，方便调试
```

实现方式：在根目录 `package.json` 增加 `scripts`，利用 `npm` 调用 `frontend` 子脚本，并用 `cross-env`/`wait-on` 已在 `frontend/package.json` 存在，无需在 root 重复安装。

**输出目录统一**

```
out/
  ├─ LQ-DataPrase-0.0.0-Setup.exe
  ├─ LQ-DataPrase-0.0.0-win.zip
  └─ win-unpacked/          # 解压后的便携/安装目录（调试用）
```

删除手动的 `release/` 整理步骤；electron-builder 配置 `directories.output: out` 已指向该目录。

### 3.3 electron-builder 配置增强

修改 [`electron-builder.yml`](file:///c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/electron-builder.yml)：

- 增加 `productName`、`copyright`、`directories`。
- 增加 NSIS 配置：一键安装改为可选目录、创建快捷方式、写入卸载项。
- 增加 `win.target` 第二目标 `zip`，用于生成便携包。
- 增加图标引用（需准备 `build/icon.ico`，至少 256x256）。

示例关键配置：

```yaml
appId: com.lq-dataprase.app
productName: LQ-DataPrase
copyright: "Copyright © 2024 LQ-DataPrase"
directories:
  app: frontend
  output: out
  buildResources: build
files:
  - dist/**/*
  - electron-dist/**/*
extraResources:
  - from: "dist/LQ-DataPrase/"
    to: "."
    filter:
      - "LQ-DataPrase.exe"
      - "_internal/**"
win:
  target:
    - target: nsis
      arch: [x64]
    - target: zip
      arch: [x64]
  icon: build/icon.ico
nsis:
  oneClick: false
  perMachine: false
  allowToChangeInstallationDirectory: true
  createDesktopShortcut: true
  createStartMenuShortcut: true
  shortcutName: LQ-DataPrase
  uninstallDisplayName: LQ-DataPrase
  artifactName: "${productName}-${version}-Setup.${ext}"
```

### 3.4 版本号管理

当前 `frontend/package.json` 版本为 `0.0.0`，根目录 `package.json` 无版本字段。

建议：

1. 将根目录 `package.json` 作为"产品版本源"，设置 `"version": "0.1.0"`。
2. `frontend/package.json` 与根目录保持同步，或在构建时从根目录读取版本。
3. `electron-builder` 使用根目录版本生成安装包文件名。
4. `standalone.py` 启动 banner 中打印版本，便于排障。

### 3.5 图标与品牌资源

新增 `build/` 目录：

```
build/
  ├─ icon.ico          # Windows 安装包/可执行文件图标
  ├─ icon.png          # 通用图标（256x256 以上）
  └─ installerSidebar.bmp  # NSIS 侧边图（可选）
```

### 3.6 PyInstaller 与 Electron 的集成保持不变

- PyInstaller 继续输出 `dist/LQ-DataPrase/LQ-DataPrase.exe` 与 `_internal/`。
- Electron 主进程继续通过 `process.resourcesPath` 找到后端 exe。
- 用户数据继续写入 `%APPDATA%/lq-dataprase/`（Electron userData）。

### 3.7 构建流程（最终版）

```bash
# 1. 安装依赖（首次）
pip install -r requirements/base.txt
npm install                # root 仅需 electron-builder
cd frontend && npm install

# 2. 一键构建
cd ..
npm run dist:win
```

`npm run dist:win` 内部执行：

```bash
cross-env VITE_ELECTRON=true npm run build --prefix frontend
npm run electron:build:ts --prefix frontend
npm run pyinstaller
npx electron-builder --config electron-builder.yml --win
```

其中 `pyinstaller` 脚本替换 `build.bat` 中 PyInstaller 相关部分：

```bash
.venv\Scripts\python.exe -m PyInstaller lq_dataprase.spec --noconfirm
```

保留 `build.bat` 作为 Windows 用户习惯入口，但让其调用新的 npm scripts：

```bat
call npm run dist:win
```

### 3.8 可选：GitHub Actions CI

新增 `.github/workflows/build.yml`：

- 触发条件：push tag `v*` 或手动触发。
- Runner：`windows-latest`。
- 步骤：
  1. Checkout
  2. Setup Python + Node
  3. 安装 Python 依赖与前端依赖
  4. `npm run dist:win`
  5. 上传 `out/` 产物到 GitHub Release。

不纳入本期必做，但为后续留好脚本接口。

## 4. 改动清单

| 文件 | 改动 |
|---|---|
| `package.json` | 增加 `version`、`scripts`（`dist:win`、`dist:win:dir`、`pyinstaller`） |
| `electron-builder.yml` | 增加 NSIS/zip 双目标、图标、元数据、artifactName |
| `build.bat` | 简化为调用 `npm run dist:win` |
| `frontend/package.json` | 保持现有 scripts，必要时同步版本号 |
| 新增 `build/icon.ico` | 应用图标 |
| 新增 `build/icon.png` | 通用图标 |
| 新增 `.github/workflows/build.yml`（可选） | CI 自动构建 |

## 5. 验收标准

- [ ] 执行 `npm run dist:win` 后 `out/` 目录同时出现 `LQ-DataPrase-x.x.x-Setup.exe` 与 `LQ-DataPrase-x.x.x-win.zip`。
- [ ] 安装包双击可完成安装，桌面/开始菜单出现快捷方式，控制面板可卸载。
- [ ] 便携包解压后双击 `LQ-DataPrase.exe` 可直接运行，不写注册表。
- [ ] 两种产物启动后均能正常登录、上传文件、查看分析图表。
- [ ] 应用图标、版本号、版权信息正确显示。

## 6. 风险与注意事项

1. **PyInstaller 构建耗时**：首次打包约 1–3 分钟，后续增量较快。CI 中需预留足够时间。
2. **Windows Defender / SmartScreen**：未签名的 exe 可能触发警告。如需消除，需购买代码签名证书，超出本期范围。
3. **文件体积**：便携包与安装包均会包含完整 Python 运行时与科学计算库，体积预计在 200–400MB。
4. **根目录 `node_modules`**：执行构建时 root 需要 `electron-builder`；若保留 root `node_modules`，需注意与 `frontend/node_modules` 不冲突（当前非 workspace，独立管理）。
