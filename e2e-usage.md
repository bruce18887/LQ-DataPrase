# E2E 测试操作指南

## 快速开始

### 1. 启动后端

```powershell
cd C:\Users\Administrator\Desktop\DataPrase\DataPhrase_Django
.venv\Scripts\python.exe manage.py runserver 8000 --noreload
```

### 2. 跑测试

```powershell
# 全量
$env:PW_NO_WEBSERVER='1'
npm --prefix frontend run test:e2e

# 只看 P0（冒烟，28 条，约 15s）
npm --prefix frontend run test:e2e:p0

# 只看某个模块
npx playwright test --config=frontend/playwright.config.ts --project=Edge --grep "@analysis"
```

### 3. 查看结果

```powershell
npm --prefix frontend run test:e2e:report
# 浏览器打开 http://localhost:9323
# 左侧 Failed/Passed/Skipped 点进去看截图和视频
```

---

## Playwright UI 模式

```powershell
$env:PW_NO_WEBSERVER='1'
npm --prefix frontend run test:e2e:ui
```

打开后：
- 顶部搜索栏输入 `@p0`、`@analysis`、`@exports` 筛选
- 点击单个用例或整组运行
- 右侧查看步骤截图、trace、日志

---

## 按条件筛选

| 命令 | 效果 |
|------|------|
| `--project=P0` | 仅冒烟 |
| `--project=P1` | 仅核心 |
| `--project=P2` | 仅增强 |
| `--grep "@analysis"` | 仅分析模块 |
| `--grep "@exports"` | 仅导出 |
| `--grep "@p0 @auth"` | 冒烟 + 认证 |

---

## 常用流程

```
启动后端 → PW_NO_WEBSERVER=1 → 跑测试 → 看报告
                    ↓
              绿了 → 看报告确认
              红了 → playwright-report/data/*.png 看截图
                    → *.md 看错误上下文
                    → 修代码 → 重跑
              跳过了(skip) → 环境不满足（正常，见 README）
```

---

## 测试文件在哪

```
frontend/e2e/
  smoke/       冒烟（每页可达）
  auth/        登录/登出/路由守卫
  global/      导航/主题/角色
  dashboard/   仪表板
  data/        数据管理/上传/浏览
  analysis/    数据分析（最密集）
  batch/       批次报表
  sftp/        SFTP
  settings/    系统设置
  roadmap/     路线图
  admin/       用户管理
  exports/     Gage/Buyoff 导出
```

---

## 预植入数据

测试不通过 UI 上传文件。`globalSetup` 自动把 `Data/SampleData/` 下 11 个 CSV 导入数据库。

手动重置：
```powershell
.venv\Scripts\python.exe manage.py seed_test_data --clear
```
