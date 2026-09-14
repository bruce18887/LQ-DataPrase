# 分析页左栏宽度下限 + 两张表瘦身（2026-09-14）

> 说明：本次 Review 没有并进 `docs/tasks/todo.md` —— 该文件当前正被另一会话（Excel 加载项
> 任务清单）整体重写，追加进去会互相覆盖。单独成文，内容等价于 todo.md 末尾的 Review 段。

## 现象（用户报）

1920 视口、页面缩放 125% 时，左栏的「📊 范围对比」与「📱 Site统计」看不到右侧列（截图里
只剩 `Low/High` 与 `Site/Yield/Fail/<Min`）。

实测（Playwright 探针，两种缩放路径都复现）：

| 视口 | 左栏宽 | 表格可用宽 | 范围对比内在宽 | Site统计内在宽 |
|---|---|---|---|---|
| 1920 / 100% | 403px | 373px | 404px → 裁 31px（Unit 列被切） | 373px（刚好） |
| 1920 / 125%（=1536 CSS px） | 307px | 277px | 404px → 裁 127px（Gap+Unit 全不可见） | 339px → 裁 62px（>Max 不可见） |

根因：左栏是 `el-col :span="6"`（=25%）且**没有宽度下限**；两张表的列宽由内容决定
（10px 等宽数字、6~12 字符的限值），一旦 25% 掉到 340px 以下就被裁。右栏实测不溢出
（`overflow-x` 无），所以不存在「左右互相挤压」之外的约束。

## 方案（用户在 3 选 1 中选定「保底宽度 + 表格瘦身」）

1. `AnalysisTabLayout.vue`
   - `.left-panel { min-width: 385px }`（= 最宽表 ~319 + 卡片内边距 30 + 余量 36；
     min-width 优先于 el-col 的内联 `max-width:25%`，宽视口仍按 25% 走）。
   - `.right-panel { flex: 1 1 0; min-width: 0 }`：el-col 的 `flex:0 0 75%` 不可收缩，
     左栏被垫高后整行会溢出而被 `content-area` 的 `overflow-x:hidden` 裁掉图表右缘。
   - `@media (max-width: 1120px)` 左栏整行堆叠（复位 el-col 的行方向内联 flex 值）。
2. `RangeComparisonTable.vue`：单位从「每行一列」提到卡头（`📊 范围对比（Unit）`，后端每个
   参数只有一个 `unit`，各行同值），省 49px；单元格内边距 6px → 4px。
3. `SiteStatsTable.vue`：单元格内边距 6px → 4px。
4. `e2e/analysis/table-zoom-fit.spec.ts`：断言口径由「表格内部能滚到最后一列」升级为
   **零溢出 + 列清单精确相等 + 最后一列右缘落在表格内**；覆盖 100% / 应用缩放 125% /
   浏览器 125%（1536 视口）/ 窄视口 1024 堆叠，并在抽样参数中扫出带 `(cut)` 的最宽行标签
   （扫不到不失败，用 `test.info().annotations` 记录覆盖率）。

## 验证

- `npm run build` 绿。
- 新 `table-zoom-fit.spec.ts` **5 passed**（含 `(cut)` 最宽场景：注解确认已覆盖）。
- 探针（实测）：100% / 125% / 125%+裁剪范围 三种情况下两表 `scrollWidth == clientWidth`、
  最后一列右缘不越界；左+右 = 行宽（125% 下 385 + 843 = 1228）。
- 回归：`e2e/analysis` + `e2e/settings` + `e2e/theme` 共 **180 passed / 1 failed / 3 flaky**。
  - 唯一 failed：`legend-color.spec.ts` 的「相关性散点：回归线颜色一致」——**基线（stash 本次
    改动后重建）同样失败**，属既有环境问题，与本改动无关。
  - 3 flaky：`dock-resize`（276 用例基线上也失败）、`wafermap`、`tiny-fail-bar`（后两者为
    上传/时序类既有 flaky，重试通过）。
- 双主题目测：light + night 各截 100% / 125%，卡头单位后缀、5/4 列全可见、行高亮正常。
- 代价：125% 下图表区 921 → 843px（-78px，-8.5%）；100% 下左栏不变（403/1209）。

## 环境说明（重要）

- 8000 端口是**用户自己的 dev server**（`manage.py runserver`，真实数据库
  `~/LQ-DataPrase/db.sqlite3`，95 个文件），未动它。
- e2e 需要用「种子库」（data_dir 钉在项目根），故本次用**临时 alt-port 配置**跑：后端 8001
  （带 `LQDP_SYSTEM_CONFIG_FILE`）+ 前端 3100 preview（`/api` 代理到 8001）。两个临时配置
  已删除；3000/3100/8001 端口已释放。
- 遗留（与本改动无关，建议单独排查）：
  1. `legend-color.spec.ts` 相关性散点用例在本机环境稳定失败（改前改后一致）；
  2. `dock-resize.spec.ts:276`（最大化可复原）基线上同样失败；
  3. 常规 `npm run test:e2e` 仍会因 8000 被 dev server 占用而指向真实数据库（种子文件缺失），
     需要临时配置或先释放 8000。
