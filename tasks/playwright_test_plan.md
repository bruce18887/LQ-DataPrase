# Playwright 测试框架方案 + 待测功能清单（待审核）

> 本文档供审核。请在每个条目勾选 ✅(测) / ❌(不测) / ❓(待定)，或直接批注。
> 审核通过后，我再按方案落地测试框架与用例。

---

## 一、框架方案（先定调）

### 1.1 技术选型
项目里目前存在 **两套** Playwright 资产，需要二选一统一：

| 方案 | 现状 | 建议 |
|------|------|------|
| **A. `@playwright/test` (TypeScript)** | 已配置 `frontend/playwright.config.ts` + `frontend/e2e/login.spec.ts`，`package.json` 有 `test:e2e` 脚本 | ✅ **推荐**：与 Vue/Vite 同语言、官方测试运行器、自带断言/夹具/HTML 报告/trace |
| B. Python Playwright | `test/*.py` 下约 15 个一次性 recon/debug 脚本 | ❌ 不作为正式框架，建议归档到 `test/archive/` |

> **请确认**：是否统一采用 **方案 A（TS, `@playwright/test`）**？

### 1.2 目录结构（方案 A 落地后）
```
frontend/
  playwright.config.ts        # 增强：webServer 自动起服务、多浏览器、报告
  e2e/
    fixtures/
      auth.fixture.ts         # 登录态复用（storageState），避免每条用例重复登录
      test-data.ts            # 测试用文件/参数常量
    helpers/
      upload.ts               # 通用上传/选文件助手
    smoke/                    # P0 冒烟：每页能打开
    auth/                     # 登录/登出/路由守卫
    dashboard/
    data/
    analysis/
    batch/
    sftp/
    settings/
    admin/
```

### 1.3 运行前置（**需你确认**）
- **测试账号**：现有用例使用 `admin / admin123`（来自 `seed_users.py`）。是否固定用它？是否需要普通用户账号测权限？
- **服务启动**：测试时需同时起 **Django(8000)** + **Vite(5173)**。是否允许在 `playwright.config.ts` 用 `webServer` 自动拉起？还是约定手动起服务？
- **测试数据**：分析/看板/批次等功能依赖已上传的数据文件。`Data/` 目录是否有可用样例文件可作为上传夹具？需要指定 1~2 个标准样例。
- **数据库**：用例会产生上传/删除等写操作。是否使用独立测试库 / 测试前后清理？

---

## 二、待测功能清单（按模块）

> 标注：**P0**=冒烟必测 / **P1**=核心 / **P2**=增强。每条请勾选保留与否。

### 模块 0｜全局 / 跨页 (Cross-cutting)
- [✅] **P0** 未登录访问受保护路由 → 自动跳 `/login`（路由守卫）
- [✅ ] **P0** 已登录访问 `/login` → 自动跳 `/dashboard`
- ✅[ ] **P1** Token 失效(401) → 自动清除并跳登录（响应拦截器）
- [ ✅] **P1** 侧边栏 8 个导航项均可跳转且高亮正确
- [✅] **P2** 暗黑/明亮主题切换（ThemeToggle）持久化生效
- [✅ ] **P2** Topbar 用户信息 / 登出按钮

### 模块 1｜登录 `/login`（已部分有用例）
- [ ✅] **P0** 页面加载（已有）
- [✅ ] **P0** 空输入禁用登录按钮（已有）
- [✅ ] **P0** 正确账号登录成功跳看板（已有）
- [ ✅] **P1** 错误密码提示「用户名或密码错误」（已有）
- [✅ ] **P2** 登出后 token 清除、回到登录页

### 模块 2｜仪表板 `/dashboard`
- [ ✅] **P0** 页面渲染、无 JS 报错
- [✅ ] **P1** 良率趋势图 (YieldTrendChart) 正常渲染
- [✅ ] **P1** UPH 效率卡片 (UphCard) 显示数值
- [✅ ] **P1** 看板汇总数据来自 `/dashboard/summary/`（无数据时空态正确）

### 模块 3｜数据管理 `/data`
- [✅ ] **P0** 文件列表加载 `/files/`
- [✅ ] **P1** 上传文件 `/upload/`（含进度）
- [✅ ] **P1** 激活文件 `/activate/{id}/`
- [✅ ] **P1** 删除文件 `/files/{id}/`（含确认）
- [✅ ] **P1** 数据浏览/分页/搜索/PassFail 过滤 `/browse/`
- [✅ ] **P2** 历史记录 `/history/`
- [✅ ] **P2** 多种 DataBrowser 视图（AgGrid / Enhanced）

### 模块 4｜数据分析 `/analysis`（功能最密集，重点）
- [✅ ] **P0** 选择文件 + 参数后页面正常进入分析
- [✅ ] **P1** 单参数 Tab：直方图 `/analysis/histogram/` + 统计摘要 + 箱线图
- [✅ ] **P1** QQ Plot `/analysis/qqplot/`（切换参数刷新）
- [✅ ] **P1** 趋势与失效 Tab：参数趋势 `/analysis/param_trend/`、Pareto、良率趋势 `/analysis/yield_trend/`
- [✅] **P1** 分布对比 Tab：箱线图分组、多 Lot 对比 `/analysis/multi_lot/`
- [✅ ] **P1** 相关性工具 Tab：散点相关 `/analysis/correlation/`、相关矩阵 `/analysis/correlation_matrix/`、文件间相关
- [✅ ] **P2** Wafer Map `/analysis/wafer_map/`
- [✅ ] **P2** 序列分布 `/analysis/serial_distribution/`
- [✅ ] **P2** 分区良率 `/analysis/zonal_yield/`
- [✅ ] **P2** Site 统计表 / Range 对比表 `/analysis/site_range_comparison/`
- [✅ ] **P2** UPH 计算 `/analysis/uph/`（含手动测试时间）
- [✅ ] **P2** 批量导出面板 (BatchExportPanel)

### 模块 5｜批次报表 `/batch`
- [✅ ] **P1** 扫描目录 `/batch-report/scan_directory/`
- [✅ ] **P1** 导入文件 `/batch-report/import_files/`
- [✅ ] **P1** 生成报表并下载 `/batch-report/generate_report/`（blob 下载校验）
- [✅ ] **P2** 批次列表 `/batch-report/list_batches/`

### 模块 6｜SFTP 浏览器 `/sftp`
- [✅ ] **P1** 连接 `/sftp/connect/` / 断开 `/sftp/disconnect/`（**需测试 SFTP 服务器，可能 mock**）
- [✅ ] **P2** 列目录 `/sftp/list_files/`、下载 `/sftp/download/`
- [✅ ] **P2** 配置保存/读取 `/sftp/configs/`、`/sftp/save_config/`
- [✅ ] ❓ 是否有可用 SFTP 测试环境？无则建议 **mock 接口** 或跳过

### 模块 7｜系统设置 `/settings`
- [✅ ] **P1** 读取/更新个人资料 `/auth/profile/`
- [✅ ] **P2** 读取/更新设置 `/auth/settings/`

### 模块 8｜功能路线图 `/roadmap`
- [✅ ] **P2** 页面渲染、P1 任务管理器 (P1TaskManager) 列表显示

### 模块 9｜用户管理 `/admin/users`（管理员）
- [✅ ] **P1** 非管理员无法访问 / 看不到入口（`isAdmin` 权限）
- [✅ ] **P2** 用户增删改查

### 模块 10｜导出 / Gage / Buyoff（多为下载类接口）
- [✅ ] **P2** Gage 汇总下载 `/gage/generate_summary/`（blob）
- [✅ ] **P2** Buyoff 识别共性项 `/buyoff/identify_common_items/` + 生成表单 `/buyoff/generate_form/`（blob）
- [✅ ] ❓ 这些主要是后端导出能力，是否纳入 E2E 还是仅做接口冒烟？

---

## 三、测试策略建议（待确认）
1. **登录态复用**：用 `storageState` 全局登录一次，业务用例直接复用，互不重复登录。 A:YES
2. **分层**：P0 冒烟（每页可达 + 无控制台报错）先全覆盖 → P1 核心交互 → P2 增强。   A:YES
3. **下载类接口**：用 Playwright `download` 事件校验文件名/非空，不校验文件内容细节。 A:我会在本地保存导出的文件后续测试校验导出的与预期文件内容是否一致。
4. **图表断言**：ECharts 渲染断言到「canvas 存在 + 无空态/无报错」层面，不做像素级比对（除非你要视觉回归）。 A:需要至少5个随机测试项参数，关注dom元素是否存在、是否可见、是否正确渲染等。
5. **数据依赖**：优先用固定样例文件做夹具，保证可重复。 A:YES

---

## 四、需你拍板的问题（汇总）
1. 统一用 **TS `@playwright/test`**（方案 A）？旧 `test/*.py` 归档？ A:YES,但暂时保留旧代码打包好，后续再考虑是否删除
2. 测试账号：`admin/admin123` 固定？是否需要普通用户账号？ A:YES
3. 是否允许 `webServer` 自动拉起 Django+Vite？ A:YES
4. 指定 1~2 个标准样例数据文件（`Data/` 下哪个？）。 A:数据文件都在Data\SampleData目录下
5. SFTP / 导出类（Gage/Buyoff）：真实环境测、mock、还是仅接口冒烟？ A:真实环境
6. 覆盖范围：先做 **P0+P1**，P2 后续？还是一次全做？ A:一次性全做，但加入参数，可以根据需要选择性测试

---
*审核完成后，我将据此创建 `frontend/e2e/` 下的框架骨架与用例，并提供 `npm run test:e2e` 一键运行。*
