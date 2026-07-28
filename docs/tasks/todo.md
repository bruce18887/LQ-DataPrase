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

---

# 任务：Windows 打包方案验证

## 目标
设计并验证一套可在 Windows 上安装的打包方案，输出 NSIS 安装程序与便携 ZIP。

## 方案
- 前端：Vite 构建 SPA → `frontend/dist/`
- Electron：TypeScript 编译 → `frontend/electron-dist/`
- Python 后端：PyInstaller 打包 → `dist/LQ-DataPrase/`
- 最终打包：electron-builder 输出 `out/LQ-DataPrase-<version>-Setup.exe` 与 `out/LQ-DataPrase-<version>-win.zip`
- 配置 `electron-builder.yml`：
  - `electronDownload.mirror` 使用 npmmirror 加速 Electron 下载
  - `publish: null` 禁用自动 GitHub Releases 发布
- 根目录 `package.json` 中通过 `cross-env` 注入 `ELECTRON_BUILDER_BINARIES_MIRROR`，避免 winCodeSign/nsis 从 GitHub 下载超时
- `build/icon.ico` 通过 `scripts/generate_icon.py` 生成 256x256 BMP 编码 ICO，满足 electron-builder 与 rcedit 要求

## 待办清单
- [x] 1. 安装根目录依赖（electron、electron-builder、cross-env）
- [x] 2. 运行 `npm run dist:win` 构建安装包与便携包
- [x] 3. 检查产物版本信息
- [x] 4. 记录构建结果与后续建议

## 验收标准
- [x] `npm run dist:win` 可完整跑通（前端构建 + Electron 编译 + PyInstaller + electron-builder）
- [x] 生成 `LQ-DataPrase-0.1.0-Setup.exe` 与 `LQ-DataPrase-0.1.0-win.zip`
- [x] Setup.exe 文件属性显示正确版本、产品名、版权信息

## Review / 验证记录
- 依赖安装：`npm install` 成功（electron ^33.4.11、electron-builder ^25.1.8、cross-env ^7.0.3）
- 前端构建成功：`vue-tsc -b && vite build` 无错误
- Electron TS 编译成功：`tsc -p ../electron/tsconfig.json` 无错误
- PyInstaller 成功：`dist/LQ-DataPrase/` 生成 `LQ-DataPrase.exe` 与 `_internal/`
- electron-builder 成功（验证目录 `out3` / `out4`）：
  - `LQ-DataPrase-0.1.0-Setup.exe` ≈ 201 MB
  - `LQ-DataPrase-0.1.0-win.zip` ≈ 257 MB
- 版本信息验证：
  - FileDescription: LQ-DataPrase 数据分析平台
  - ProductName: LQ-DataPrase
  - CompanyName: LQ-DataPrase Team
  - FileVersion: 0.1.0
  - ProductVersion: 0.1.0
  - LegalCopyright: Copyright © 2024 LQ-DataPrase

## 注意事项
- 当前工作区中 `out/` 与 `out2/` 目录被 IDE 锁定，无法删除；重启 IDE 后可手动清理
- 首次构建会从 npmmirror 下载 Electron、winCodeSign、nsis 等二进制缓存，后续构建复用缓存会更快
- rcedit 在设置图标时可能报一次 `Unable to commit changes`，但会自动重试并最终成功写入版本信息

---

# 任务：修复 echarts 切换 tab/文件后不渲染

## 目标
解决数据分析页切换 `el-tabs` 标签页或切换数据文件后，ECharts 图表区域常出现空白、不渲染的问题。

## 根因
- `el-tabs` 非活动标签页通过 `display:none` 隐藏，其内部图表容器从有尺寸变为 0 尺寸；重新显示时 ECharts 实例未收到 `resize()` 通知，导致画布/ SVG 尺寸未更新。
- 页面整体被 `<keep-alive>` 缓存，切换路由再返回时触发 `onActivated` 而非 `onMounted`；原 `useChart` 未处理该生命周期，实例绑定在 detached DOM 上可能无法正确重绘。
- 组件使用 `lazyUpdate: true` 时，在隐藏期间调用 `setOption` 的渲染帧被跳过；恢复可见后没有强制重绘。

## 方案
- 在 `frontend/src/composables/useChart.ts` 中增加持续监听的 `ResizeObserver`：
  - 容器从 0 尺寸恢复时，若已有实例则 `resize()` + 用当前 option 重新 `setOption`；
  - 若实例尚未初始化（异步 init 等待中），则触发 `ensureInit()` 并渲染。
- 增加 `onActivated` 生命周期钩子，处理 `<keep-alive>` 重新激活后的实例校验、`resize()` 与重绘。
- 在 `ensureInit()` 中增加 `handle` 非空守卫，避免异步初始化等待期间被重复调用产生多余 observer/轮询。

## 待办清单
- [x] 1. 分析 tab/文件切换不渲染的根因
- [x] 2. 增强 `useChart`：持续监听容器尺寸与可见性变化
- [x] 3. 处理 `<keep-alive>` 重新激活场景
- [x] 4. 前端构建/类型检查通过
- [x] 5. 补充 e2e 回归测试

## 验收标准
- [x] 切换 tab 后再切回，原直方图/QQ 图/箱线图仍正常渲染，不出现空白
- [x] 切换文件后，新文件的图表正常渲染
- [x] `vue-tsc -b && vite build` 无错误
- [x] 新增 e2e 用例通过

## Review / 验证记录
- 前端构建成功：`vue-tsc -b && vite build` 无错误
- 新增 e2e 测试 `e2e/analysis/analysis.spec.ts`：「@p1 切换 Tab 后返回单文件分析直方图仍渲染」通过
- 回归测试 `e2e/analysis/file-switch-param-reset.spec.ts`：「切换文件后直方图应重新渲染（非空白）」通过
- 关键改动文件：`frontend/src/composables/useChart.ts`
