# LQ-DataPrase Django 后端架构文档

## 命名约定

- 文件名 / 函数 / 变量：snake_case
- 类名：PascalCase
- 常量：UPPER_SNAKE_CASE
- API 端点：snake_case（`/api/v1/data_files/`, `/param_trend/`）

## 开发指南

### 启动

```bash
pip install -r requirements/base.txt
python manage.py migrate
python manage.py seed_users        # 初始化测试用户
python manage.py seed_test_data    # 生成测试数据
python manage.py runserver         # → http://localhost:8000
celery -A config worker -l info    # 另一个终端
redis-server                       # 如需 Celery
```

### 添加解析器

1. `apps/datafiles/parsers/` 创建文件
2. 继承 `BaseATEParser` 实现 `can_parse` / `parse` / `get_metadata`
3. 在 `apps/datafiles/services.py` 注册

### 添加分析功能

1. `apps/analysis/views.py` 的 `AnalysisViewSet` 添加 `@action`
2. 复杂统计逻辑放 `apps/analysis/services/`

### 运行测试

```bash
python manage.py test              # 全部
python manage.py test apps.accounts
```

### API 文档

Swagger UI: `http://localhost:8000/api/schema/swagger/`

任何后端改动都要测试api接口

## 架构实况（2026-10-15 评审后更新）

### 异步与并发：**没有任务队列，是进程内池**

**本项目不使用 Celery，也没有任何 broker。** 2026-10-15 架构评审（P0-1）把 Celery 从项目整体删除：
全仓从未有过一个 `@shared_task`，而两个交付档（`standalone.py` / `server.py`）本来就把它从
`INSTALLED_APPS` 里摘掉了——留着的设置只是让每个读者误以为运行时依赖一个 broker。

真实的异步形态是**在 Web 进程内**起池：

| 位置 | 池类型 | 用途 | 约束 |
|------|--------|------|------|
| `apps/export/export_batch_charts_xlsx.py` | `ProcessPoolExecutor` | 批量导出时并行渲染 matplotlib 图表 | Windows 走 spawn；**worker 禁读 Django/DB**，故 `apps/export/charts.py` 不允许出现 Django import，读用户设置必须放 `apps/export/user_prefs.py` 并在主进程钳位成纯标量后再入 task dict |
| `apps/sftp/search/runner.py` | `ThreadPoolExecutor` | SFTP 远程搜索（IO 密集） | 取消用 `shutdown(wait=False, cancel_futures=True)`，不能用 `with` 块（`__exit__` 是 `wait=True`，取消时会把 HTTP 请求挂到扫完） |
| `apps/sftp/search/walker.py` | `ThreadPoolExecutor` | 目录树遍历 | 同上 |

**没有独立 worker 进程，也没有跨请求的持久队列。** 因此：

- 长任务（如批量导出）会**占用一个请求线程**，没有背压、没有重试、没有死信队列。
- 进程退出时池子需要显式收尾——见 `apps/common/shutdown.py` 的优雅关闭。
- 若要引入真正的后台任务，先补 spec：这属于架构变更，不是接线。

### 分层现状：app 级切分清楚，但**没有 repository 层**

10 个 app 按业务领域切分（accounts / datafiles / analysis / dashboard / batch_report /
buyoff / gage / export / sftp / common），命名自解释。但服务端分层只到「app 级」：

- **没有 repository / dao 层**，`apps/*/views/` 直接握 ORM 与 pandas。
- `apps/analysis/`、`datafiles/`、`dashboard/`、`batch_report/` 有 `services/`；`accounts/`、
  `common/`、`export/`、`gage/` 没有，业务逻辑在 views 里。
- `apps/common/` 是跨领域工具集合（exceptions / params / system_config / backup /
  export_naming / file_loading / user_settings / db_pragmas / constants / health / shutdown），
  无 `models.py`、无单一领域归属。

**新增代码的约定**（避免继续恶化）：

1. 视图只做「解析参数 → 校验 → 调 service → 序列化响应」。过滤链、聚合、统计一律下沉到
   `services/`。判据：如果一个 `@action` 方法超过约 60 行，它就有东西该下沉。
2. 不要在 views 里新增 `pd.read_csv` / `pd.read_excel` 调用；数据加载走既有 service。
3. 批量取对象用 `filter(pk__in=...).in_bulk()`，不要在循环里 `.filter()`——**但必须保留
   `owner=request.user` 这类权限过滤条件**，它是防线不是冗余。
4. 错误一律 `raise`（走 `apps/common/exceptions.py` 的全局处理器），不要 `return Response({'error': ...})`
   ——后者会绕开统一格式，前端 `ERROR_CODE_MAP` 需要额外兜底。
5. 单个 `.py` 文件不得超过 600 行（`.claude/CLAUDE.md`）。`apps/analysis/views/analysis_views.py`
   曾在 690 行超限，是「视图内联业务链」的直接症状。
