# LQ-DataPrase E2E 测试（Playwright）

基于 `@playwright/test` 的端到端测试套件。覆盖登录、路由守卫、各业务页面与导出能力。

## 运行

```bash
cd frontend

# 全量（首次会自动安装并拉起 Django:8000 + Vite:5173）
npm run test:e2e

# 按优先级选择性运行
npm run test:e2e:p0      # 冒烟
npm run test:e2e:p1      # 核心
npm run test:e2e:p2      # 增强

# 按模块运行
npx playwright test e2e/analysis
npx playwright test e2e/dashboard

# 有界面 / 调试
npm run test:e2e:headed
npm run test:e2e:ui

# 查看报告
npm run test:e2e:report
```

### 环境前置
- 后端依赖：`.venv` 中安装 `requirements/base.txt`（需 matplotlib 等）。
- 种子账号：`python manage.py seed_users`（admin/admin123、user/user123、viewer/viewer123）。
- 样例数据：`Data/SampleData/`（已随仓库提供）。
- 浏览器：使用 Edge（`channel: 'msedge'`）。如未安装可改 `playwright.config.ts`。

### 环境变量
| 变量 | 作用 | 默认 |
|------|------|------|
| `PW_NO_WEBSERVER=1` | 不自动拉起前后端（已手动启动时用） | 关闭 |
| `PYTHON_BIN` | 指定后端 Python 解释器 | `.venv/Scripts/python.exe` |
| `PARAM_SAMPLE_COUNT` | 分析页图表抽样参数个数 | 5 |

## 目录结构

```
e2e/
  fixtures/
    test-data.ts      # 账号、样例文件、路由、常量
    auth.setup.ts      # 登录 admin/user → 导出 storageState（setup 项目）
  helpers/
    auth.ts            # uiLogin / loginAs / logout
    nav.ts             # gotoApp / navByMenu / sidebarLink / collectConsoleErrors
    charts.ts          # expectChartRendered / waitForCanvases / waitLoadingGone
    upload.ts          # uploadFile / expectUploadSuccess
    params.ts          # selectAnalysisFile / listParams / selectParam / sampleN
    download.ts        # captureDownload（保存到 .downloads/ 供人工比对）
  smoke/  auth/  global/  dashboard/  data/  analysis/  batch/  sftp/  settings/  roadmap/  admin/  exports/
  .auth/        # storageState（gitignore）
  .downloads/   # 导出文件落地（gitignore）
```

## 关键约定

### 标签与选择性运行

每个 `test.describe` 声明了结构化 `tag`（例如 `{ tag: ['@p0', '@analysis'] }`），Playwright UI 会渲染为可点击的筛选 chip。

CLI 运行：
```bash
npm run test:e2e:p0          # --grep @p0，仅冒烟
npm run test:e2e:p1          # --grep @p1
npm run test:e2e:p2          # --grep @p2
npx playwright test e2e/dashboard   # 仅仪表板模块
```

### UI 模式（可视化筛选）

**方式一：Playwright 内置 UI**

先手动启动后端（保持运行），再开 Playwright UI：
```bash
# 终端 1：启动 Django（保持运行）
cd /d C:\Users\Administrator\Desktop\DataPrase\LQ-DataPrase
.venv\Scripts\python.exe manage.py runserver 8000 --noreload

# 终端 2：启动 Vite（保持运行，或让 Playwright webServer 自动起）
cd /d C:\Users\Administrator\Desktop\DataPrase\LQ-DataPrase\frontend
npm run dev

# 终端 2（或终端 3）：开 Playwright UI（禁止自动起后端避免冲突）
$env:PW_NO_WEBSERVER='1'
npm run test:e2e:ui
```

Playwright UI 打开后：
- 左侧测试树按模块/优先级分组
- 顶部搜索 `@p0` 只看冒烟、`@analysis` 只看分析
- 点击单个用例或整组运行
- 右侧查看步骤截图/trace/日志

**方式二：VSCode 扩展**
安装推荐扩展 `ms-playwright.playwright`（已加入 `.vscode/extensions.json`）。

侧边栏「测试」面板自动发现所有用例，显示为树形结构：
```
LQ-DataPrase E2E
├── @p0 @smoke 冒烟 - 页面可达
│   ├── 仪表板 (/dashboard) 正常加载且无报错
│   ├── 数据管理 (/data) 正常加载且无报错
│   └── ...
├── @p0 @auth 认证与路由守卫
│   ├── 未登录访问受保护路由 → 跳转 /login
│   ├── 正确账号登录成功跳转看板
│   └── ...
├── @p1 @analysis 单参数分析
│   ├── 抽样 5 个参数逐个断言直方图
│   └── 开启 QQ 图后渲染 QQ 图与正态性标签
└── ...
```

VSCode 操作：
- **筛选**：面板顶部搜索 `@p0` 只显示冒烟；`@analysis` 只看分析模块
- **运行**：右键任一节点 → Run Test / Debug Test
- **调试**：在用例代码设断点 → Debug Test，Playwright 会停在断点处
- **查看**：失败用例自动附带截图 + trace，点击即可查看

### 预植入数据集

测试启动前，`globalSetup` 自动执行：
1. `python manage.py seed_users` — 创建 admin / user / viewer
2. `python manage.py seed_test_data --clear` — 把 `Data/SampleData/` 下全部 CSV 导入 DataFile 表

各用例直接使用数据库中的已解析文件，无需通过 UI 逐个上传。若需重置数据：
```bash
python manage.py seed_test_data --clear
```

### 登录态
- 大多数“仅需登录”的用例：项目级注入 `admin.json` storageState（仅含 token），无需重复登录。
- **角色相关用例**（管理员菜单可见性、Topbar 用户名/角色）：应用启动**不**会用 token 重新拉取 profile，故 `user`/`isAdmin` 为空。
  这类用例须在文件顶部 `test.use({ storageState: { cookies: [], origins: [] } })` 清空登录态，再用 `loginAs(page, role)` **实时 UI 登录**（同会话内不要刷新页面，否则角色丢失）。

### 已验证选择器（实测）
- 登录：输入 `getByPlaceholder('用户名'|'密码')`；按钮 `button.login-button`（文本是「登 录」含空格）。
- 主布局容器：`.main-layout`；侧边栏：`aside.sidebar`；侧边栏菜单项：`sidebarLink(page, '菜单名')`，激活态含 class `active`。
  - 菜单名（exact）：仪表板 / 数据管理 / 数据分析 / 批次报表 / SFTP浏览器 / 系统设置 / 功能路线图 / 用户管理。
  - ⚠️ Topbar 面包屑里有同名 link，断言菜单务必限定 `aside.sidebar`。
- 分析页（2026-09-05 起每个 tab 独立选文件）：文件选择器一律按契约属性
  `[data-file-picker="single|wafer|correlation|multi"]`（用 `filePicker(page, scope)` /
  `pickTabFile(page, scope, name)`，**调用前先切到该 tab**，lazy pane 未挂载时选择器不在 DOM 里）；
  数据控件按 `[data-filter="outlier-handling|iqr-multiplier|ignore-no-limit|ignore-no-test-value|data-only-bin1|only-fail-test-item|only-low-cpk"]`
  （用 `filterControl(page, name)` / `pickOutlierMode` / `pickSensitivity`）；
  ⚠️ 这些属性**每个 tab 一份**，`filterControl` 已限定在 `.el-tab-pane:visible` 内，自定义定位器
  也必须加可见 pane 限定，否则访问过两个 tab 后会撞上 strict mode。参数选择器仍是
  `.param-selector .el-select`（filterable，popper class `param-select-dropdown`）；选项
  `.el-select-dropdown__item`。不得再用「页面上第几个 .el-select」这类位置定位。
- 分析页切文件后读数据（2026-09-05）：切换窗口内 UI 仍显示**上一个文件**的图表/范围表
  （遮罩不在，`waitLoadingGone` 拦不住），直接读值会拿到旧数据 —— 实测读到过残留文件
  恒定列的 1/1 范围。读数值/参数列表前用 `selectAnalysisFile`（已内置等待新文件计算
  请求发出）或 `pickTabFileAndWaitCompute(page, scope, name)`；要绝对严谨先等初始加载完
  再切（见 `custom-limit-cpk.spec.ts:130` 的注释）。
- ECharts 图表：断言 `canvas` 可见且尺寸 > 0（用 `expectChartRendered`）。
- ElMessageBox 确认框 teleport 到 body，按钮文本「确定」「取消」「删除」等，全局可定位。
- 下载：`captureDownload(page, () => 点击导出, '子目录')`。

### 已知应用问题（测试中发现，未修改源码）
1. **登录错误被吞**：`api/index.ts` 全局响应拦截器对任何 401 都 `window.location.href='/login'`，
   导致登录接口 401 时 `LoginPage` 内联 `error-msg` 来不及显示。测试改为断言“停留登录页 + 未获 token”。
2. **刷新丢失身份**：App 启动不重新拉取 `/auth/profile/`，刷新后 `user=null`、管理员菜单消失（见“角色相关用例”约定）。
