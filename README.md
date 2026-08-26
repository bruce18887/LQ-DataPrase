# LQ-DataPrase

LQ-DataPrase 是一款面向半导体 ATE（自动测试设备）量产数据的桌面端分析平台，支持 CP/FT 测试数据的上传、解析、可视化与报表导出。项目采用 **Vue 3 + Django** 前后端分离架构，并提供 **Electron** 桌面安装包，可在 Windows 环境下一键部署使用。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3.5 + TypeScript + Vite 8 + Element Plus 2 + ECharts 6 + ag-Grid + Pinia |
| 后端 | Django 4.2 + Django REST Framework + SimpleJWT + Celery |
| 数据库 | PostgreSQL（生产）/ SQLite（开发） |
| 缓存/任务队列 | Redis |
| 桌面打包 | Electron 33 + electron-builder + PyInstaller |
| E2E 测试 | Playwright |

---

## 主要功能

- **数据文件管理**：上传 `.csv` / `.std` 等 ATE 原始数据文件，支持 CTA8290D、CTA8280F、ETS88、STS8200 等格式自动识别与解析。
- **Dashboard 仪表板**：展示良率（Yield）、分 Bin 分布、Site 良率、Cpk 概览、失效项排行等关键指标。
- **数据分析**：直方图、箱线图、QQ 图、晶圆图（Wafer Map）、参数趋势、相关性分析、Pareto 分析、多 Lot 对比等。
- **批次报表**：按 Lot/Wafer/Batch 聚合生成统计报表。
- **Buyoff / Gage R&R**：支持 Buyoff 表单与量具重复性&再现性分析。
- **SFTP 浏览器**：连接远程 SFTP 服务器浏览并下载测试数据。
- **数据导出**：一键导出 Excel、PPT、CSV 等格式分析报表。
- **双主题**：支持浅色 / 深色两套主题。
- **权限管理**：基于角色的访问控制（管理员 / 用户 / 浏览者）。

---

## 项目结构

```
LQ-DataPrase/
├── apps/                    # Django 后端应用
│   ├── accounts/            # 用户认证、权限、个人设置
│   ├── datafiles/           # 文件上传、解析、管理
│   ├── analysis/            # 数据分析核心（统计计算、视图接口）
│   ├── dashboard/           # 仪表板数据接口
│   ├── batch_report/        # 批次报表
│   ├── buyoff/              # Buyoff 管理
│   ├── gage/                # Gage R&R 分析
│   ├── export/              # Excel/PPT/CSV 导出
│   └── sftp/                # SFTP 配置与浏览
├── config/                  # Django 配置（settings/urls/celery）
├── frontend/                # Vue 3 前端工程
│   ├── src/
│   │   ├── api/             # Axios API 封装
│   │   ├── pages/           # 页面组件
│   │   ├── components/      # 通用组件
│   │   ├── stores/          # Pinia 状态管理
│   │   ├── router/          # Vue Router
│   │   └── styles/          # 主题与全局样式
│   └── e2e/                 # Playwright E2E 测试
├── electron/                # Electron 主进程/预加载脚本
├── requirements/            # Python 依赖
├── test/                    # 后端测试与调试脚本
├── docs/                    # 设计文档与规格说明
├── manage.py                # Django 管理入口
├── standalone.py            # PyInstaller 独立启动入口
├── electron-builder.yml     # Electron 打包配置
└── build.bat                # Windows 一键打包脚本
```

---

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 20+
- Redis 7+（可选，Celery/SFTP 缓存需要）
- PostgreSQL 14+（可选，开发默认使用 SQLite）

### 1. 克隆仓库

```bash
git clone https://github.com/bruce18887/LQ-DataPrase.git
cd LQ-DataPrase
```

### 2. 后端启动

```bash
# 创建并激活虚拟环境
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 安装依赖
pip install -r requirements/base.txt

# 初始化数据库与测试数据
copy .env.example .env
python manage.py migrate
python manage.py seed_users        # 创建测试用户
python manage.py seed_test_data    # 生成示例数据

# 启动开发服务器
python manage.py runserver
```

默认后端地址：`http://localhost:8000`

如需 Celery 异步解析：

```bash
redis-server                       # 另起终端启动 Redis
celery -A config worker -l info    # 另起终端启动 Celery
```

### 3. 前端启动

```bash
cd frontend
npm install
npm run dev
```

默认前端地址：`http://localhost:3000`

开发账号（由 `seed_users` 生成）：

| 角色 | 用户名 | 密码 |
|------|--------|------|
| 管理员 | admin | admin123 |
| 普通用户 | user | user123 |
| 浏览者 | viewer | viewer123 |

---

## 打包与发布

### Windows 桌面安装包

在项目根目录执行：

```bash
build.bat
```

输出产物位于 `out/` 目录：

- `LQ-DataPrase-<version>-Setup.exe`：安装程序
- `LQ-DataPrase-<version>-win.zip`：便携版压缩包

### 手动构建流程

```bash
# 1. 构建前端
npm run build --prefix frontend

# 2. 编译 Electron TypeScript
npm run electron:build:ts --prefix frontend

# 3. PyInstaller 打包后端
npm run pyinstaller

# 4. Electron Builder 打包桌面应用（electron/electron-builder 依赖在
#    frontend/node_modules 中，由 scripts\electron-builder.cmd 统一解析）
scripts\electron-builder.cmd --win
```

### 打包架构说明

LQ-DataPrase 的桌面包是 **Electron 壳 + PyInstaller 后端** 的组合：

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 UI | Vue 3 SPA | 由 Vite 构建为静态资源 |
| 桌面宿主 | Electron 33 | 负责窗口、菜单、生命周期 |
| 业务后端 | Django 4.2 | 由 PyInstaller 打包为独立可执行文件 |
| 进程通信 | HTTP | Electron 启动后端并本地 HTTP 轮询 |

构建流程的输入输出：

```
frontend/          ──build──>  frontend/dist/          ──┐
electron/          ──tsc───>  frontend/electron-dist/  ├──> electron-builder ──> out/*.exe / out/*.zip
Django + apps/     ──PyInstaller──>  dist/LQ-DataPrase/ ──┘
```

关键配置文件：

- `lq_dataprase.spec` — PyInstaller 配置，声明隐藏导入、数据文件、前端产物等。
- `electron-builder.yml` — Electron 安装包配置，定义产物、NSIS 安装选项、资源拷贝规则。
- `standalone.py` — 独立运行入口，负责启动 Django、自动迁移、创建默认管理员、收集静态文件。

安装后的目录结构：

```
<安装目录>/
├─ app.asar（或 unpacked 文件，asar 已禁用）
│    └─ Vue 前端 + Electron 主进程
└─ resources/
     ├─ LQ-DataPrase.exe      ← PyInstaller 打包的后端
     └─ _internal/             ← Python 运行依赖
```

### 存储路径（Storage Layout v2，2026-08-21 起）

所有运行期文件按用户维度收敛，不再散落于项目目录 / 系统临时目录：

```
%USERPROFILE%\LQ-DataPrase\              ← 数据目录（数据库 + 上传数据，内置默认）
└─ media\data\<用户名>\<single|batch>\   ← 上传/下载的数据文件
%TEMP%\LQ-DataPrase-Temp\                ← 临时目录（导出中间文件、图表缓存，内置默认）
```

- 数据目录与临时目录均为**内置默认值**：无需配置即生效；管理员可在 设置 → 存储路径 中修改，修改后重启生效（数据库与上传数据会自动迁移）。
- `system_config.json` 与 `secret.key` 固定在锚点目录（打包版 = `%APPDATA%\lq-dataprase\`，开发版 = 项目根），不随数据目录迁移——密钥迁移风险大于目录整洁收益。
- 打包版通过 `LQDP_BASE_DIR` 环境变量在 Electron 启动 Python 后端时传入锚点目录；`DataFile.file_path` 以相对 `media/` 的路径存储，数据目录整体迁移时无需重写数据库记录。

开发模式下，Electron 不会自己启动后端，而是检测并复用 `localhost:8000` 的 Django 开发服务器，保证浏览器与 Electron 使用同一个 SQLite 数据库。

### 后端调试窗口

打包后的 Electron 应用默认隐藏后端控制台。如需显示，可使用命令行参数：

```bash
LQ-DataPrase.exe --backend-console
```

或设置环境变量 `LQDP_BACKEND_CONSOLE=1` 后重新打包。

---

## 测试

### 后端测试

```bash
python manage.py test
# 或指定应用
python manage.py test apps.analysis
```

### 前端 E2E 测试

```bash
cd frontend
npm run test:e2e           # 全量运行
npm run test:e2e:p0        # 冒烟测试
npm run test:e2e:ui        # UI 调试模式
```

---

## 配置说明

复制 `.env.example` 为 `.env`，根据环境修改以下关键项：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SECRET_KEY` | Django 安全密钥 | 开发默认（生产必须修改） |
| `DJANGO_DEBUG` | 调试模式 | `True` |
| `DJANGO_ALLOWED_HOSTS` | 允许访问的域名 | `*` |
| `DATABASE_URL` | PostgreSQL 连接字符串 | `postgres://ate_user:ate_password@localhost:5432/ate_analysis` |
| `REDIS_URL` | Redis 连接地址 | `redis://localhost:6379/0` |
| `SFTP_CONFIG_KEY` | SFTP 密码加密密钥 | 开发留空 |

生产环境务必将 `DJANGO_DEBUG=False` 并设置真实的 `SECRET_KEY` 与 `SFTP_CONFIG_KEY`。

---

## API 文档

启动后端后，访问 Swagger UI：

```
http://localhost:8000/api/schema/swagger/
```

所有业务接口统一挂载在 `/api/v1/` 路径下。

---

## 支持的 ATE 数据格式

| 格式 | 说明 |
|------|------|
| CTA8290D | 长川科技 ATE 数据 |
| CTA8280F | 长川科技 ATE 数据 |
| ETS88 | 泰瑞达 ATE 数据 |
| STS8200 | 宏测 ATE 数据 |

新增格式只需在 `apps/datafiles/parsers/` 下继承 `BaseATEParser` 实现 `can_parse()` 与 `parse()` 方法。

---

## 相关文档

- [前端架构文档](frontend/CLAUDE.md)
- [后端架构文档](apps/CLAUDE.md)
- [用户操作指南](docs/user-guide/README.md)
- [ATE 量产测试关键指标](docs/reference/ATE_量产测试关键指标.md)
- [ATE 指标实现指南](docs/reference/ATE_指标实现指南.md)

---

## License

[MIT](LICENSE)
