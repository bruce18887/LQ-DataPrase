# 五项体验批：下拉虚拟化 / 两页 admin 重设计 / 重复项选保留 / 介绍书图标 / 磁盘占用

日期：2026-11-13（需求于 2026-11-12 一次报出）
状态：设计定稿，待写实现计划
批次切法：**一份设计稿 + 按风险分 3 批实现**（用户选定）

---

## 0. 五项诉求原文与现状定性

| # | 用户原话 | 现状定性（调查结论） |
|---|---|---|
| 1 | 参数选择框为啥只能看前 300 个测试项，不应该动态加载所有测试项吗 | **不是 bug**，是刻意的性能防护。根因是 EP 2.14 的 `el-select` 不做虚拟滚动 |
| 2 | 用户管理页面和操作审计界面 UI 重新设计，目前的太简陋了，输入框的长度更是不合理 | 「长度不合理」有确定根因：两页所有输入控件**零宽度声明**，全靠 `el-form--inline` 的 flex 收缩 |
| 3 | 数据管理的数据修复按钮，如果有重复文件，只能点击删除，无法选择保留 | 前提有误：截图里「✓ 保留」「删除」是**只读 `el-tag`**，没有 `@click`。选保留这个功能在三层都不存在 |
| 4 | 介绍书的图标再稍微明显一点，介绍书页面打开后标签页没有图标 | 图标是 EP `Reading` 18px `--text-2`，与铃铛/用户同规格；favicon 缺失的根因是 VitePress 产出的 index.html 里**根本没有 `<link rel="icon">`** |
| 5 | 数据管理界面展示当前所有数据的磁盘占用量，为后面每个用户限制占用大小做准备 | 全仓**零**总大小聚合、**零**配额代码；可复用的体积口径实现只在 `scripts/test_data_gc.py` |

---

## 1. 批次与门禁节奏

按 `docs/reference/testing-gates.md` §1 执行，不在此重复判据。

| 批 | 内容 | 每批 commit 前 | 收口 |
|---|---|---|---|
| 批1 | 第 1 项（四下拉迁 v2）+ 第 4 项（intro 图标 + favicon） | `cd frontend && npm run test:e2e:affected` | 见 §7 |
| 批2 | 第 5 项（磁盘占用） | 同上 | 同上 |
| 批3 | 第 3 项（重复项选保留）+ 第 2 项（两页统一 toolbar） | 同上 | 同上 |

批3 改动集必然命中 6 个以上 e2e 模块 ⇒ 按 §3 升全量，这是预期不是异常。批1 改 `frontend/src/constants/`、`src/plugins/` 亦命中全局清单 ⇒ 同样升全量。

**跨批共同要求**（每一项都要满足，不是批3 独有）：
- 前端改动同时维护 light 与 night 两套主题（`.claude/CLAUDE.md:109`）。
- 单个 `.vue`/`.py`/`.ts` 文件不超过 600 行（判据 `scripts/line-limit.mjs` + `frontend/test/unit/lineLimit.spec.ts`）。
- 本批改动触及 UI 页签/列名/按钮/判定口径 ⇒ **触发介绍书维护时机 ②**，见 §6.4。

---

## 2. 批1 · 第 1 项：四个下拉迁 `el-select-v2`（落地时补第五个，见 §2.9）

### 2.1 目标与不变量

用户要的是「下拉里能看到全部测试项」，不是「看到更大的数字」。所以：

- **删除渲染截断**（Task 9A 落地订正，2026-11-13）：`DROPDOWN_RENDER_CAP = 300` 连同 `frontend/src/constants/dropdown.ts`
  整文件删除，无残留消费者 —— 该常量只有 §2.3 那 4 个组件引用；第五个「固定列」下拉本来就没引它（它原先是未封顶的
  v1 实现，见 §2.9，编号以 §2.9 为准，不是 §2.5）。
  **但「四处 footer 提示整条删除」这句与落地不符**，实际状态是三支不同形状，逐条按代码记：
  - `ParamSelector.vue:43-44`（单选）**保留两支措辞** ——「匹配 N 项」/「共 N 项」，class 仍是 `.param-count-hint`；
    单选控件没有「按 Enter 全选匹配」这个动作，无关键词时报全集规模对用户有用。
  - `SerialSelector.vue:28`、`ExportParamSelector.vue:34`（multiple）**只删掉「仅显示前 N」那半句**，
    `match-hint` 那一行（`v-if="kw && matches.length > 0"` ⇒「匹配 N 项，按 Enter 全选」）保留；这两个的 footer
    在无关键词时确实不出字。
  - `TestColumnSelector.vue:26-34` 要单独纠正：它的 `#footer` 里**全选/清空两个按钮是无条件常显的**（只有 `match-hint`
    那行带 `v-if`），所以「另三个下拉无关键词时什么都不显示」这句话不准 —— 那个下拉的 footer 任何时候都有内容。
- **不变量**：过滤/计数/全选的作用对象本来就是完整集合（那份文件的注释 :10 已写明「封顶只作用于渲染」），迁移后仍然如此 —— 本次只把「渲染前 300」换成「渲染全部但虚拟窗口化」。

### 2.2 已核实的库事实（EP 2.14.0，读的是 `frontend/node_modules` 里的已安装产物）

升级 EP 主版本后本表全部要重量，别当定律。

- `#footer` / `#empty` slot v2 **有**（`select-v2/src/select-dropdown.mjs:160,177`）⇒ 现有四处 footer 提示与 footer 里的全选/清空按钮有落点。
- DOM 类名与 v1 **同名**：`.el-select`、`.el-select__wrapper`、`li.el-select-dropdown__item`（含 `is-selected`/`is-hovering`）、`input.el-select__input` ⇒ 靠这些的定位器不受影响。`.el-input__inner` 两版都不存在。
- **`filter-method` 语义反转**：v1 里它接管过滤；v2 的 `useSelect.mjs:114-132` 判到 filterMethod 合法后让 `isValidOption` 恒 `true` ⇒ `filteredOptions` = 全量 `props.options`，它退化成**纯回调**。失败形状是「过滤没生效但不报错」。我们的四个组件本来就已自己算 `listView`，方向一致，但这条必须写进实现判据。
- **`:options` 元素必须是对象**：`useProps.mjs:25-28` 走 `lodash.get(option, 'label'|'value')`，喂 `string[]` 得到静默空白行；且 `options` 是 required prop。
- **虚拟窗口 DOM 里只有约 8 行**（`height:274` / `itemHeight:34`，`defaults.mjs:100,107`）⇒ 一切「数 `.el-select-dropdown__item` 条数」「`.nth(i)` 取窗口外第 i 项」的定位器必红。
- `@keydown.capture` + Enter 在 v2 仍生效；`tag-max-width` 两版都不存在；v2 无 v1 的 `popup-scroll` emit。四个组件都没用 `remote` / `reserve-keyword` / `#header` / `#label` / `#prefix`。

### 2.3 改动面

**注册面三处**（漏第三处的形状是「产品能跑、单测红」）：
1. `frontend/src/plugins/element-plus.ts:60` 与 `:170` 加 `ElSelectV2`；
2. `frontend/src/constants/element-plus-usage.ts:56` 清单加 `'select-v2'`；
3. `frontend/test/unit/elementPlusUsage.spec.ts:147` 的 `toBe(49)` → `toBe(50)`，`installed` 逐字比对同步。

**四个组件**（行数 281 / 185 / 163 / 179，距 600 都有 >270 余量）：

| 组件 | 现用特性 | 自定义渲染程度 |
|---|---|---|
| `pages/analysis/components/ParamSelector.vue` | 单选、`filterable` `clearable` `filter-method` `popper-class` `#footer` | **需要 `#default`**（高亮分段富文本，:22-35） |
| `pages/data/components/correlation/SerialSelector.vue` | `multiple` `collapse-tags(-tooltip)` `automatic-dropdown` `multiple-limit` `#empty` `#footer` | 纯 label |
| `pages/data/components/browser/TestColumnSelector.vue` | `multiple` `collapse-tags(-tooltip)` `#empty` `#footer`（全选/清空按钮在 footer :25-33） | 纯 label |
| `pages/data/components/export/ExportParamSelector.vue` | `multiple` `collapse-tags(-tooltip)` `#footer` | 纯 label |

全选/反选/清空三处都走 **emit 完整集合**，不读 `el-option` 的 DOM 或 `selected` 态 ⇒ 迁 v2 后逻辑不失效，风险只在 e2e 定位。

### 2.4 承重陷阱：高亮计算不能留在 computed 里

`ParamSelector.vue:150` 的 `highlightSegments` 现在只作用于截断后的 300 项。这不是顺手，是性能批 `d1146dd` 的成果 —— `:97-99` 注释原话记着旧写法「给每个匹配项都建一份 segments 数组（1,702 项的文件上每次击键建 1,702 份），而真正渲染的只有前 N 项」。

**全量渲染后若照旧在 computed 里给所有匹配项算 segments，等于把那一批优化原样回退。**

正解：高亮计算从 `listView` computed 里搬进 v2 的 `#default` 逐条渲染器 —— 虚拟窗口每帧只调用约 8 次，比现在更省。前缀优先排序仍留在全量匹配集上（4,570 项一次 O(n log n) 约 1–2ms，可接受），且必须留在传给 `:options` 之前（`ParamSelector.vue:110-117` 那段「过滤 → 排序 → 截断 → 高亮」的说明改成「过滤 → 排序 → 高亮按需」）。

### 2.5 这是有依据地推翻旧决策

`docs/superpowers/specs/2026-09-09-sftp-mutex-and-file-correlation-design.md:114` 明确写过「不换 `el-select-v2`」，三条理由与今天的消解：

| 09-09 的理由 | 现在 |
|---|---|
| 本仓零先例 | 本次建立先例，且 §2.6 探针先行 |
| `filterMethod` 会接管过滤 | 已核实是**反的**：v2 里它不过滤，而四个组件本来就自己算列表，方向一致 |
| Enter 捕获路径 | `@keydown.capture` 在 v2 仍生效（Enter 绑 input，捕获先到根 div） |

实现计划里要显式引用这条推翻关系，别让后续读者把它当成随意取舍。

### 2.6 探针先行（lessons「仓内没用过的 API 先跑探针」）

动产品代码**之前**，用一份临时 e2e（跑完删除，不进套件）实测四件事：
1. v2 的 `#footer` 在 4,570 项下是否真的可见（`select-dropdown.mjs:177` 是渲染了，但要确认它不在虚拟滚动容器内被裁掉）；
2. `filter-method` 回调时机与「父算 `:options`」的组合是否等价于现行为；
3. Enter 全选（SerialSelector / TestColumnSelector / ExportParamSelector 三处依赖）；
4. 4,570 项下的首屏与滚动耗时（对照迁移前，证明「不冻结」这个前提成立）。

探针不过 → 回到设计，不许硬迁。

### 2.7 e2e 改写清单

现状：`helpers/params.ts` 覆盖 ParamSelector 的全部 70 个调用点 / 23 个文件，改 helper 一处即传递性覆盖。SerialSelector 走 `helpers/elplus.ts`。TestColumnSelector 与 ExportParamSelector **在各 spec 内联定位，无 helper**。

会红约 15–20 条，集中在两类：
- **数 DOM 条数 / 取窗口外 nth**：`exports.spec.ts:433-455`（`count()` + `nth(i)` 循环）、`view-data.spec.ts` 的「@p2 显示测试列：输入关键词 + Enter 全选匹配项」与「@p2 系统列按格式权威下发：前缀同名测试项（SITE_CHECK）不误判」两条（本稿设计时记作 `:745-752`/`:807-810`，此后一律按用例标题认它，锚点 `1574012`）、`chart-filter-switches` 的 `listParams().length` 族。改法：按 `testing-gates.md` §2 冲突裁决下沉 —— 「列表完整性」是后端契约（T1 断响应 `results` 的 key 集合），e2e 只留一条「页面渲染出该下拉且可搜到目标项」的接线证明。`exports.spec.ts:540-544` 已有这条先例（注释明写「改从响应 `results` 键取全集、不数 DOM option」）。
- **footer 移出可见窗口**：`file-correlation.spec.ts:198` 一类。

不受影响约 45–50 条（靠 `.el-select` / `.el-select__wrapper` / `.el-select__input` / `.el-select__placeholder` / `aria-label`）。

**顺带修一条既有错判据**（与本项同族，不是范围蔓延）：`helpers/params.ts:26` 用 `.el-select-dropdown__item:visible` 认「当前开着的下拉」，2026-11-10 已实测为**假**（EP 收起走 leave 过渡，`display:none` 等动画才落下，而 `aria-hidden` 同拍翻 `true` ⇒ 过渡帧里会挑中正在退出的上一个）。正解是 `.el-popper[aria-hidden="false"] .el-select-dropdown`。迁 v2 时窗口化会让这条更容易被误触发，一并改掉。

### 2.8 新增测试

- **T2**：`frontend/test/unit/` 加一份纯函数用例，钉「过滤 → 排序 → 映射成 `{label,value}`」的形状，以及**高亮按需**：断言给 4,570 项时 `highlightSegments` 的调用次数是窗口量级而不是全量量级（变异字节探针：把高亮挪回 computed 必须让这条红）。
- **T3**：一条「参数下拉可滚到第 301 项并选中」的接线证明（这条正是用户报的缺陷的守门人）。
- 反向探针：临时把 `DROPDOWN_RENDER_CAP` 的引用改回 300，确认 T3 那条会红 —— 证明它真的在承重。

### 2.9 落地时补的第五个下拉（2026-11-13，用户拍板并入批 1）

Task 7/8 复审时发现的**设计漏项**，不是范围蔓延：`pages/data/components/browser/DataBrowserToolbar.vue`
的「固定列」下拉（迁 v2 之前的那颗 `el-select`，位置以 `1574012^` 为准）是**未封顶的 v1 实现** —— `v-for="c in allCols"` 且没有 `DROPDOWN_RENDER_CAP`，
而 `allCols` 取自表格全部列（`DataBrowserAgGrid.vue` 里 `allCols.value = d.headers ?? []` 那一处）。ETS88_FT 现测 **1,728 列** ⇒ 一打开就挂
1,728 个 `el-option` 实例，正是 §2.1 里 `constants/dropdown.ts:8` 那句「原样挂载即冻结主线程」描述的
那个风险；它也是 Task 7/8 复审里唯一反复红的业务用例（`view-data.spec.ts` 的
「@p1 固定列：多选，后选的列叠加而不是替换已钉住的列」那条，选项首行的 `toBeVisible({ timeout: 15_000 })`
等不到；本稿设计时记作 `:309`/`:322`，此后按用例标题认它）。

本稿 §2 原先只承诺四个下拉、§8「明确不做」里也没有它 ⇒ 属清单漏项。**用户 2026-11-13 拍板并入批 1**，
理由：机制与 §2.3 的四个完全同形（`multiple` + `filterable` + `collapse-tags`，纯 label，工作量约 1 小时），
而「批 1 治好了下拉冻结、但还剩一个从没封顶的下拉」是半截状态。

验收补一条（§7 第 1 条同族）：固定列下拉在 1,728 列的文件上打开后**首屏不冻结**，且 DOM 里只有
虚拟窗口那约 11 行（判据形式与 §2.8 的 T3 一致，不新建夹具）。

---

## 3. 批1 · 第 4 项：介绍书图标 + 标签页 favicon

### 3.1 图标明显度（选型 B：同尺寸只提亮）

`frontend/src/components/layout/Topbar.vue:51` 的 `<el-icon :size="18"><Reading /></el-icon>` **尺寸不动**，颜色从 `.icon-btn` 共用的 `--text-2` 分出 intro 专用类走 `--text`。

- 只提亮这一颗。铃铛与用户菜单保持 `--text-2`，理由：铃铛是通知占位、用户菜单旁已有姓名文字，三者语义权重不同。
- 对比度实测（light `--text` `#1f2937` on `--bg` `#fafbfc`；night `#ffffff` on `#1a1a2e`）两主题都远超阈值，无需再加底色。
- 不加文字标签（用户定过的规矩：原位图标优先，拒新增文字按钮）。

### 3.2 favicon

根因：`docs/intro/.vitepress/config.mts` 有 `base: '/intro/'`（:13）与 `title`（:15），**没有 `head` 数组** ⇒ 构建出的 `dist/index.html` 里没有 `<link rel="icon">`。

改法：`config.mts` 加
```
head: [['link', { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }]]
```
`href` 用**绝对根路径**：`base` 是 `/intro/`，相对写法会被解析成 `/intro/favicon.svg`；而 Django 侧 `config/urls.py:103` 只挂了 `path('favicon.svg', _serve_frontend_file('favicon.svg'))`，绝对路径才命中。`frontend/public/favicon.svg`（604B，闪电母版，light `#2563eb` / night `#f9a825`）已存在，直接复用。

**同时补 `/favicon.ico` 路由**：浏览器每次都会无条件请求 `/favicon.ico`，现在它落 SPA catch-all 或 404。介绍书维护纪律明写「浏览器走读改动章节（桌面 + 420px），控制台零报错」，所以这条不是可选清洁 —— 实现上给 `config/urls.py` 加一条 `path('favicon.ico', ...)`，返回 `favicon.svg`（现代浏览器与 Electron 都吃 SVG；`build/icon.ico` 是打包期产物，不在 web 根下）。

### 3.3 测试分层

- **T1（后端契约，不开浏览器）**：`GET /favicon.ico` 返回 200 且 `Content-Type` 是 image；`GET /intro/` 的响应体含 `rel="icon"`。
- **T3（只有渲染能证明）**：`[data-testid=open-intro]` 的 computed color 在 light/night 两主题分别等于对应 `--text`；同批断言铃铛与用户菜单**仍是** `--text-2`（防止「顺手全提亮」悄悄改规格）。

---

## 4. 批2 · 第 5 项：磁盘占用量

### 4.1 端点

新增 `GET /api/v1/files/usage/`（挂 `apps/datafiles/urls.py`，与 `/files/` 同族）。权限 = 登录用户，数据按 `owner=request.user` 隔离，与现有全部端点一致（`file_views.py:114` 等）。

挂载位置有讲究：`urls.py` 里已有 `files/<int:pk>/` 这类形状，`usage` 不是 int 所以不会被它吞，但**必须排在 `<int:` 那条之前**，并把端点名与既有 `_ALL_ACTIONS`、bulk_delete 等动作名核对不重名（`grep -n "path('files" apps/datafiles/urls.py` 现量后再定）。

返回体：

```
{
  "data_dir": "<MEDIA_ROOT>/data/<username>",
  "bytes":        <逐文件 st_size 加总（表观口径）>,
  "unique_bytes": <按 (st_dev, st_ino) 去重（唯一口径）>,
  "file_count":   <磁盘实际文件数>,
  "db_count":     <DataFile 行数>,
  "db_bytes":     <SUM(file_size) 参考值>,
  "by_type": { "single": {bytes, count}, "batch": {bytes, count} },
  "scanned_at": "<iso8601>"
}
```

### 4.2 口径纪律（这条是本项的硬要求）

`docs/tasks/lessons.md` 2026-10-24 条目规则①：「报体积前先说明口径，并做一次独立交叉核对」。那次三个数互相打脸（25.4GB 表观 / 5.0GB `du` / 0.07MB 错误去重），只有一个是真的。

- **必须用 `os.lstat` 取 inode，不能用 `os.DirEntry.stat()`** —— 后者在本机不填 `st_dev/st_ino`（恒 0），去重会把整棵树压成一个 key。仓内已有正确实现可参照：`scripts/test_data_gc.py:144 walk_inodes()`，它 `:172-176` 的注释就是这条教训的原文。
- **交叉核对写成测试而不是注释**：同一目录用第二种机制（`pathlib.Path.rglob` + `stat()`）独立加总，断言与 `bytes` 相等；并断言「用户数据目录下无硬链接 ⇒ `bytes == unique_bytes`」。将来出现硬链接时这条会红并逼人重新说明口径 —— 这是判据异源，不是自我复制。
- 页面**只显示一个数**（`bytes`）。

### 4.3 数据源为什么选扫盘而不是 DB

`file_size` 的唯一真实写入点是注册那一刻的 `os.path.getsize`（`_helpers.py:123/136`），之后**永不刷新**；文件被外部改动或截断即失真。拿它做配额基线会错，所以以磁盘实扫为准，`db_bytes` 只作参考。

### 4.4 性能

- 扫描范围是 `MEDIA_ROOT/data/<username>/`（每用户子目录由 `_helpers.py:172-185` 决定，天然按 username 分桶）。本机量级参考：`media/ 722M`、`Data/ 930M`（`docs/reference/architecture-review-2026-10-15.md:271`）。
- 前端**异步拉一次**，不阻塞文件列表；后端加 30s 进程内缓存（key = username），上传/删除/修复成功后主动失效。
- 耗时随文件数线性增长。**若实测超 ~300ms**，退路是快照表 + 变更增量更新 —— 那是新机制，本批不建，先实测再决定。这条要写进验收：实现时必须打印实测耗时。

### 4.5 展示

数据管理页 tab 条那一行右侧一条轻量 chip：`磁盘占用 1.2 GB · 3,412 个文件`，hover 出单文件/批次拆分。落点 `pages/data/components/FileListToolbar.vue`（现在只有 `{{ total }} 个文件`）。字号走 `--p-fs-*` token（`e2e/global/fonts.spec.ts:155` 禁新增硬编码 px 字号）。

### 4.6 差值露出（决策 C）

`db_bytes` 与 `bytes` 的差**不进 chip**、不做第二个指标。仅当差值超过阈值时，在数据修复对话框的一致性卡片区追加一行「清单与磁盘不一致（差 X MB），可重新扫描」。阈值判据写成一条恒等式而不是散文：`abs(bytes - db_bytes) / max(bytes, 1) > 0.05`（分母取 `bytes` 是因为它是真值；`max(...,1)` 防空目录除零）。理由：`file_size` 注册后不刷新是已知事实，但常态下差值为零，常驻显示只会让人看不懂。

### 4.7 配额准备做到哪一步（决策 B）

本批**只落「当前用户 + 口径正确的真实字节」**。逐用户列表与上限判定留给配额批 —— 那时才能连判定一起验；现在做只读列表容易和将来的真判定口径不一致。全仓当前 `quota` / `storage_limit` 零命中，本批不新增字段。

### 4.8 测试

- **T1**：端点返回体字段齐全；空目录返回 `bytes=0` 不报错；owner 隔离（A 用户看不到 B 用户的量）；上传后缓存失效、新文件被计入；口径交叉核对（§4.2）。
- **T3**：chip 在数据管理页渲染且数字非空（一条接线证明，不在浏览器里重算体积）。

---

## 5. 批3 · 第 3 项：重复项选保留

### 5.1 现状（三层都不存在，不是 UI 没做好）

- 前端 `pages/data/components/DuplicateFilesCard.vue:20-30` 那两个「✓ 保留」「删除」是 `el-tag`，**无 `@click`**；:29 的文案是纯插值，把后端既定策略渲染成预测。
- 提交 payload 不含任何 id：`api/datafiles.ts:210-217` 只 POST `{action:'delete_duplicates'}`。
- 后端 `_helpers.py:343 _delete_duplicate_files(user)` 硬编码 `group['files'][1:]`（`_group_duplicates` 的 `files` 按 id 升序，:309）。
- 删除是物理删：`_helpers.py:226-231` `os.remove` + `df.delete()`，无软删除/回收站，随后 `evict_parse_cache_for_paths`。
- 重复判定口径是 `(filename, file_size)` **精确相等**（`_helpers.py:314`），全仓 `DataFile` 无 hash 字段。

### 5.2 前端（选型 B：radio 列表 + 一键策略 + 实时汇总）

`DuplicateFilesCard.vue`（141 行）的 tag 行改成 radio 行，每行显示 `保留/将删除` + `#id` + 归属（`[单文件]` / `[批次名]`）+ 导入时间 + 大小。`created_at` 已在 payload 里（`_helpers.py:327`），**不用改查询**。

状态：
- `keepChoice: Map<groupKey, fileId>`，默认 = `files[0].id`（等于现状行为，未改选零成本）；
- `touched: Set<groupKey>` 记录用户改选过的组；
- 顶部「默认保留：最早导入 / 最新导入 / 体积最大」+「应用到全部 N 组」，**只覆盖未 touched 的组**。三个策略的**并列裁决一律是 id 最小**（`created_at` 相同或 `file_size` 相同时必须有确定值，否则「应用到全部」两次点出不同结果，e2e 无法断言）；「最早/最新」比 `created_at`，「体积最大」比 `file_size`。

底部：
- checkbox 文案 → 「我已确认按以上选择删除」（`deleteConfirmed`，:73，groups 变化时重置的既有行为保留）；
- 按钮文案实时 → 「按选择删除 N 个（共 X MB）」，N 与 X 由前端按当前选择算。

**护栏强度是设计硬要求不是可选优化**：用户已明确否掉 `.trash`（理由见 §5.5），所以「数量汇总 + 确认文案」是不可撤销操作上唯一的闸。实现时按钮文案里的数字必须来自当前选择，不许写死「全部」。

### 5.3 后端契约

`POST {action:'delete_duplicates', keep_ids:[40198, 40756, …]}`，`_delete_duplicate_files(user, keep_ids)`：

1. 仍按 `_group_duplicates(user)` 重新分组（`owner=user` 那道越权防线保留，`_helpers.py:309`；docstring :355 明写它是越权防线不是冗余条件）；
2. 每组：`keep_ids` 含该组某项 → 删其余；不含 → 按默认保留最早（兼容旧行为）；
3. **校验**：`keep_ids` 里任何 id 不属于当前用户的任何重复组 ⇒ `400 invalid_keep_id`。**不能静默忽略** —— 静默忽略等于按默认删掉了用户以为改选过的那份，这正是本项要修的缺陷的变体；
4. 逐文件 `transaction.atomic()` 保留（中途失败不回滚已删的，幂等性保留）。

### 5.4 删除作用范围（决策 A：只删已展示的组）

**现状语义要重定**：GET 只给前端 50 组（`_helpers.py:334 _find_duplicate_groups(user, limit=50)`），而 POST 端 `browse_views.py:337-338` 的 docstring 明写「Actions always recompute the full affected set server-side (not the GET's 50-row display slice)」，前端 `truncatedNote`（`DuplicateFilesCard.vue:79-83`）也在说「删除操作将作用于全部」。

用户选不了保留的根因正是「看不见却要被动」，所以本批把它改成**删除范围严格等于已展示的组**：

- `limit=50` 不动（组数在实践中很小，截图那批只有 4 组；提上限要连带做分页渲染，成本不对称）；
- `_delete_duplicate_files` 只处理前 50 组，返回 `deleted_count` 与 `remaining_groups`；
- `truncatedNote` 文案从「删除操作将作用于全部」改成「共 N 组，本批处理前 50 组，另有 M 组未处理 —— 重新检查后可继续」；
- 按钮数量汇总只算已展示组。

**这是一次语义反转，不是修 bug**，所以：现有测试里没有任何一条钉住「作用于显示切片之外」（`apps/datafiles/tests.py:1228-1305` 五例逐条核过，最接近的 `test_delete_duplicates_keeps_earliest` :1255 只钉「保留 id 最小」）⇒ 旧行为没有测试承重，新行为必须补一条：构造 51 组，断言删除后第 51 组**仍在**。

### 5.5 为什么否掉 `.trash`

三个候选里用户选了保持物理删。被否的回收站方案（删前移入 `MEDIA_ROOT/.trash/<日期>/` 保留 7 天）的真实代价：`.trash` 落在 MEDIA_ROOT 里会被 `_scan_orphaned_disk`（`_helpers.py:525-552`）当孤儿报出来，必须连带改数据修复页、`scripts/test_data_gc.py` 白名单、回收脚本禁区三处 —— 修一个功能引入一批新假阳性。第三个候选「只删 DB 行保留磁盘文件」与第 5 项（要控占用）方向相反，且会造出大量孤儿。

### 5.6 测试

- **T1**：默认保留最早（既有 :1255 保持绿）/ 指定保留最新 / `keep_ids` 不存在 → 400 / `keep_ids` 指向别的组 → 400 / `keep_ids` 指向他人文件 → 400（owner 防线）/ 非管理员 → 403（既有 :1218）/ 51 组时第 51 组不被删（新语义）/ 同名不同大小不算重复（既有 :1241 保持绿）。
- **T3**：`e2e/data/repair-center.spec.ts:211` 那条走查改造成「改选保留项 → 删除 → 终态断言**留下的是被选那一份**」。现有版本只断「终态剩 1 条」（:254），断不出选的是哪条 —— 这正是这个缺陷能长期存在的原因。

---

## 6. 批3 · 第 2 项：两页统一 toolbar（选型 B）

### 6.1 现状根因

- **输入框长度**：两页所有输入控件**零宽度声明**（`AuditLogPage.vue:10` el-select、`:20` el-input、`:28`/`:36` 两个 el-date-picker；`UserManagement.vue:153/156/159` 添加表单三件），全靠 `el-form--inline` 的 inline-flex 收缩，宽度随内容浮动。这与 `docs/tasks/lessons.md` 2026-10-23 条目**同形状**（控件默认 `flex: 0 1 auto` 允许收缩，收缩下限只有内边距 ⇒ 被文案挤没）。那条的规则①：「`toBeVisible` 不是几何判据，『可见』允许『只剩一条缝』；写控件可用性判据时按**实测盒宽**断，阈值从修复后的恒等式推」。
- **简陋**：KPI 四张大卡用 emoji（`UserManagement.vue:5/12/19/26` 👥✅🔒🛡️）；「添加用户」是 `el-divider` + 裸 `<h3>➕ 添加用户</h3>` + 页底 `el-form inline`（:148-168），卡片占满整行而控件缩一角、「添加」按钮孤立；而编辑走的是 `el-dialog`（:111-146）⇒ 同一件事两套形态。
- 只有列宽是写死的：UM `:36-73`、AL `:67-86`。UM 操作列 `min-width="340"` 的推导注释（:64-72，按已装 EP 2.14.0 dist CSS 实测）**不动**，它与视口无关。

### 6.2 目标形态

两页都改成**一条工具栏**（左条件、右动作），与分析页 2026-09-07 拍板的 `.dp-analysis-toolbar` 同族：

- **操作审计**：`全部事件 ▾ | 操作者或目标账号 | 起 | 止 | 重置` 在左，`查询` 在右；表格与分页形态不变。不加「导出」（mockup 里画了，本批不纳入）。
- **用户管理**：KPI 四张大卡收成一行 chip（emoji 换 EP 图标）；工具栏左 = `搜索用户名/显示名` + `全部角色 ▾`（**决策 D：加，走纯前端过滤** —— 列表已是 `collectAllPages` 全量拉取，零后端改动），右 = `新增账号`；「添加用户」从页底内联表单移进对话框，与编辑共用一个 `UserFormDialog.vue`。

**字形选择不是自由项**：用户定过的规矩是「图标语义要唯一，不要长得像其它常见功能」（当年 ⤓ 因形似下载箭头被误读为导出而作废）。四个 chip 的候选按此约束定，实现时先在真浏览器里看图再拍：总用户 `UserFilled` / 活跃 `CircleCheck` / 锁定 `Lock` 三条语义直白；**管理员那颗待定** —— 现在是 🛡️，EP 无 Shield，`Medal`（领奖台，语义偏「成就」）与 `Stamp`（印章，语义偏「官方」）都要看一眼才敢用。

**同一条改动的连带项**：角色列现在也在用 emoji（`UserManagement.vue:41` 的 `roleIcon(row.role)`）。KPI 换成矢量图标而角色列仍留 emoji，是比现状更刺眼的不一致 ⇒ 本批一并把 `roleIcon` 换成 EP 图标（`UserFilled` / `Medal` 或上面选定的那颗），保持「一页一套图标语言」。

**控件定宽判据抄仓内唯一逐控件给了值的实现**：`pages/sftp/components/SearchCriteria.vue:542` 的 `.sc-root-input { flex: 1 1 260px; min-width: 180px; }` 一族（含 `:504` 的 `min-width: 0` 才允许被压短这条）。不新造一套宽度语言。

### 6.3 600 行硬约束驱动的拆分

`UserManagement.vue` 现在 **578/600**，加东西必撞闸（判据 `scripts/line-limit.mjs`，`.vue` 数整个 SFC）。所以重设计自带拆分，不是顺手重构：

- `admin/components/AdminPageToolbar.vue` —— 两页共用的工具栏壳（左 slot / 右 slot + flex 换行 + 定宽 token）；
- `admin/components/UserKpiChips.vue` —— chip 行；
- `admin/components/UserFormDialog.vue` —— 新增/编辑共用对话框（含 `roleLabelHygiene` 要求的 `<el-select v-model="….role">` + `el-option`）。

`AuditLogPage.vue` 250 行可就地改。`frontend/test/unit/audit.spec.ts` 也已 **594/600** ⇒ 新增断言不许往它里塞，要另起文件。

### 6.4 e2e 契约保全（改 UI 会打破什么）

必须继续成立：
- 8 个 `data-testid` 挂在**包裹层**（`audit-event|audit-username|audit-date-from|audit-date-to`、`edit-username|edit-display-name|edit-email|edit-role`），保证 `[data-testid=…] input` 与 `[data-testid=audit-event] .el-select` 两条定位形状可用。注意 `element-plus-e2e-locator-traps` 第①条：`ElInput` 是 `inheritAttrs:false` 且把 attrs 并到原生 input，**testid 写 `<el-input>` 上时 `[data-testid] input` 会命中 0 个** —— 工具栏化之后仍要挂 `el-form-item`（或等价包裹层），不能因为「不在 el-form 里了」就挪到 el-input。
- `.audit-table`（`audit.spec.ts:115/215`）、列序 `td:nth-child(3)` = 操作者（:278）、`.el-pagination__sizes .el-select`、`.el-table__expand-icon`。
- 源码级绊线：`roleLabelHygiene.spec.ts:69-70` 的正则要求 `<el-select v-model="….role">` + `el-option` 在；`auditFormat.spec.ts:101-111,146-168` 要求常量名在、禁 `maxlength="150"` 与 `[20, 50, 100]` 字面量；`e2e/global/fonts.spec.ts:155` 禁新增硬编码 px 字号。

会红要改写：
- `admin.spec.ts:31-33` 用 `.user-management .el-form .el-form-item` + 中文 label 定位页底添加表单 —— 改对话框后 `append-to-body` 会脱离 `.user-management` 祖先，改成对话框作用域定位。
- 按钮/提示文案断言（编辑/禁用/启用/重置密码/解锁/删除/查询/重置/**添加 → 新增账号**）。

### 6.5 顺带收敛两处死规则（同族，不是范围蔓延）

`.el-select .el-input__wrapper` 在 EP 2.14 恒不命中（`theme-chalk/el-select.css` 里该组合出现 0 次，真类名是 `.el-select__wrapper`）。仓内两处死规则：`UserManagement.vue:555` 与 `src/styles/element-plus-theme.css:598`（night 那条）。`AuditLogPage.vue:240-245` 已经改对了并点名这两处待收敛 —— 本批一并清掉，并把 night 主题下 select 触发区的边框/底色改为由 `.el-select__wrapper` 承载。

已实测「删掉正确那条规则，vitest 802 例 + e2e 7 条全绿」⇒ **没有任何判据抓得到这个主题分叉**。所以本批要补一条 T3：night 主题下 `[data-testid=audit-event] .el-select__wrapper` 的 computed `background-color` 与 light 主题不同（证明主题覆写真的生效）。

### 6.6 介绍书联动（CLAUDE.md 维护时机 ②）

本批改了按钮名（添加 → 新增账号）、KPI 形态、筛选控件、以及重复项卡片的交互形态 ⇒ 命中介绍书维护时机 ②「任何改动 UI 页签/列名/按钮/判定口径的批次收口时」。要同步的是：
- `docs/intro/guide/09-admin.md`（用户管理 + 操作审计两章）；
- `docs/intro/.vitepress/theme/components/UsersMock.vue` 与 `AuditMock.vue`（介绍书里有**复刻组件**，不改就是假文档）；
- `docs/intro/.vitepress/theme/components/FileListMock.vue` 与第 3 项的重复项卡片形态；
- 动作：`npm run intro:build` → `node scripts/intro/check.mjs` 必须 PASS → 桌面 + 420px 浏览器走读改动章节、控制台零报错。

---

## 7. 验收判据（收口时逐条现量）

下面每一条的**实测数字一律写进 `docs/tasks/todo.md` 对应批次条目**（`.claude/CLAUDE.md` 任务管理第 5 条「记录结果」），不留在会话里 —— 「台账里的计数一律现跑再引用」是 lessons 2026-10-24 规则③。

1. 参数下拉打开后能**滚到并选中第 301 项**；4,570 项文件下首屏与滚动无冻结（打印实测值）。
2. `grep -rn DROPDOWN_RENDER_CAP frontend/src` 为空；`elementPlusUsage.spec.ts` 绿且计数为 50。
3. `[data-testid=open-intro]` 双主题 computed color = `--text`；铃铛/用户菜单仍 `--text-2`。
4. `GET /intro/` 响应含 `rel="icon"`；`GET /favicon.ico` 返回 200；介绍书页浏览器标签页有图标；控制台零 404。
5. 数据管理页 chip 显示磁盘占用；后端打印扫描实测耗时（>300ms 则回到设计，不偷偷加快照表）。
6. 重复项：改选某组保留项 → 删除 → 终态留下的是被选那一份；51 组时第 51 组未被删；`keep_ids` 非法 id → 400。
7. 两页：每个筛选控件**实测盒宽**达标（阈值从修复后的恒等式推，不凑常数）；light/night 双主题对照通过；night 下 `.el-select__wrapper` 主题覆写有判据。
8. **§2.6 探针的四条结论逐条写回本 spec**（v2 `#footer` 可见性、`filter-method` 组合、Enter 全选、4,570 项耗时）—— 探针跑完就删脚本，结论不写回来等于没跑。
9. KPI 与角色列的图标在真浏览器里看过图（light/night 两主题 + 420px 不适用，admin 页是桌面页），确认不与常见功能近形后才算定稿。
10. `npx vitest run` + `npm run lint:e2e` + `npm run build` 全绿；后端全量按 `testing-gates.md` §1 收口档跑并核对 `RESULT:` 行。
11. `node scripts/intro/check.mjs` PASS。
12. 行数普查不新增超阈件：`frontend/test/unit/lineLimit.spec.ts` 绿。

---

## 8. 明确不做（YAGNI 清单）

| 不做 | 理由 |
|---|---|
| 下拉的远程搜索 / 后端分页 | 后端本来就一次返回全量（`analysis_views.py:139` 无 limit），瓶颈在渲染不在传输；v2 虚拟化已解决 |
| 相关性矩阵的 `CORRELATION_PARAM_LIMIT = 50`（`statistics_views.py:56,238-240`） | 另一个接口的另一件事，与本项无关 |
| `.trash` 回收站 / 软删除 | §5.5 |
| 逐用户占用列表、`storage_limit_bytes` 字段、上传拦截 | 决策 B，留给配额批 |
| 磁盘占用的快照表 + 增量更新 | §4.4，先实测再决定 |
| 审计页「导出」按钮 | mockup 里画了但未纳入（§6.2） |
| 用户管理搜索走后端参数 | 决策 D，列表已全量拉取，纯前端过滤即可 |
| `DataFile` 加内容 hash 字段以改重复判定 | 会牵动上传路径与既有判定测试，本批只改「选保留哪份」，判定口径不动 |
| 介绍书图标改尺寸/换字形 | 用户选了 B（只提亮颜色） |

---

## 9. 决策记录

| 编号 | 决策 | 选定 | 否决项与理由 |
|---|---|---|---|
| 批次 | 设计稿与实现切法 | 一份设计稿 + 按风险分 3 批 | 每项独立走流程（太慢）；5 项一批做完（改动集必然升全量且难定位归属） |
| 1 | 下拉改造范围 | 四个下拉全换 `el-select-v2`；**落地时补第五个「固定列」，2026-11-13 用户拍板并入本批（§2.9）** | 只换参数下拉（同仓两种形态，后人会踩同坑）；分段加载（没治根因，滚到底还是 4,570 个实例） |
| 2 | 两页 UI 力度 | B 统一 toolbar | A 保守（宽度治了但「简陋」没治，且用户否决理由是一致性不是成本）；C 面板化（template 基本重写 + 一批定位器改写） |
| 3 | 保留选择交互 | B radio 列表 + 一键策略 | A 原位点 tag（>2 项时「点一下循环切换」没人会猜到）；C 完整表格（组数少时更空，丢「一组挨在一起」的直觉） |
| 3-删 | 删除语义 | 保持物理删 | `.trash`（§5.5）；只删 DB 行（与第 5 项方向相反 + 造孤儿） |
| A | 删除作用范围 | 只删已展示的组 | 维持「作用于全部」（看不见却被动，正是本项根因）；取全量 + 前端分页（成本不对称） |
| 4 | 图标明显度 | B 同尺寸只提亮到 `--text` | C 加大 20px（与邻居不一致）；D 常驻淡底（比要求的「稍微」更响）；文字标签（用户定过原位图标优先） |
| B | 配额准备 | 只做当前用户 | 逐用户只读列表（将来判定口径易与现在不一致）；本批做完配额 |
| C | 清单/磁盘差值 | 只在超阈时提示 | 完全不显（`file_size` 失真没人看见）；两个数并列（没人看得懂的二阶数字） |
| D | 用户页筛选 | 加前端搜索 + 角色筛选 | 不加（工具栏会很空）；走后端参数（账号规模上千才必要） |
| 5 | 占用数据源 | 磁盘实扫为准，DB 合计作参考 | 只算 DB `SUM`（注册快照，做配额基线会错）；两个都显（同 C 条） |
| 推翻 | `2026-09-09` spec 的「不换 el-select-v2」 | 有依据推翻 | §2.5 三条理由逐条消解 |
