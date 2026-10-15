# 图标体系设计：母标志 · 应用图标家族 · 界面图标体系

- 日期：2026-10-15
- 状态：待复核
- 范围：A（母标志 + 派生资产家族 + 运行时接入）与 B（界面图标体系），两块各一轮，A 先落地
- 取证脚本与像素件：`tasks/extract_ico_frames.mjs`、`tasks/measure_ico_frames.py`、`tasks/_measure_tail.py`、`tasks/_rasterize_cmp.cjs`、`tasks/_pixel_sheet.py`（均为本轮临时件，实施时把要留的校验能力搬进 `scripts/`，其余清理）

---

## 0. 决策摘要

| # | 决策 | 结论 |
|---|---|---|
| D1 | 母标志图形 | **沿用现有闪电轮廓**，不引入晶圆/字母/柱状新母题 |
| D2 | 渲染方式 | **去模糊、单色 `currentColor`**，渐变只出现在底板上 |
| D3 | 尾针几何 | 尾针左界 `x=23.925 → 19.4`（48 画布），其余顶点一字不改 |
| D4 | 家族形制 | 双形制：应用图标 = 渐变圆角底板 + 反白/深墨符号；界面 = 同一实心符号，颜色取 `--brand` |
| D5 | 16px 简化几何 | **不做**。保持单一形状，16px 的糊作为显式取舍记录在 §8 |
| D6 | Night 底板墨色 | 用 `--p-slate-950 #131327`，**不用** `--on-brand:#ffffff`；连带修 token 文档 |
| D7 | 帧留白 | 母版 viewBox 零留白；留白由生成脚本按帧尺寸注入：16px→2%，24–32px→6%，≥48px→8% |
| D8 | 系统托盘 | **本轮不做**，属新生命周期语义，见 §10 偏差报备 |
| D9 | 界面图标 | 不新建 `Icon.vue`；把死代码 `constants/icons.ts` 改造成唯一注册表 + 尺寸 token 类 |
| D10 | emoji | 分四类，只治理其中两类（见 §5.2），徽章字形与视图控制字形明确保留 |

---

## 1. 证据基线

### 1.1 现状（已实测/已核行号）

- 现用品牌图形是 `frontend/public/favicon.svg`：48×46 画布，一枚闪电轮廓，颜色由 **16 个高斯模糊椭圆**（`stdDeviation` 7.659 / 4.596）经 `mask` 裁进轮廓得到。色值 `#863bff / #7e14ff / #47bfff / #ede6ff`，全部不在 `design-tokens.css` 的 primitive 色阶内。
- 应用图标由 `scripts/gen-icon.ico.js` 生成：读 `favicon.svg`（:24），逐尺寸 `setViewportSize` + `screenshot({omitBackground:true})`（:84–98），手写 Vista+ ICO 容器（:37–61），帧集 `[256,128,64,48,32,16]`（:27）。:97 有 `waitForTimeout(150)`，注释「let SVG blur filters rasterize」。幂等判据是 mtime（:29–34）。
- 接入缺口：`electron/main.ts:223–236` 的 `new BrowserWindow` 选项里**没有** `icon`；全仓 `electron/` 无 `Tray` / `AppUserModelID` / `nativeImage`（唯一命中是 `main.ts:459` 的 macOS 注释）。`lq_dataprase.spec:457` 为 `icon=None`。`electron-builder.yml` 只有 `:55 icon: build/icon.ico`，**没有** `installerIcon` / `uninstallerIcon`。
- 界面里没有 Logo：`Sidebar.vue:5–6` 与 `LoginPage.vue:6–10` 用 EP `TrendCharts`，`ConnectPage.vue:5–6` 用 EP `Connection`，`AppAboutDialog.vue:12` 与 `docs/user-guide/template.html:233` 用 emoji `📊`。
- `frontend/src/constants/icons.ts` 导出 7 个 EP 图标映射，`grep -rn "constants/icons" frontend/src frontend/test` **零命中** → 死代码。
- `el-icon :size` 字面量取值 12 种：18×5、14×5、13×3、64×2、48×2、22×2、20×2、12/16/28/56/60 各 1。无 token。
- 指南自相矛盾：`ui-design-guide.md:360` 要求身份块图标「EP 矢量图标，不用 emoji」，`:309` 却允许卡头「可带 emoji 图标」。

### 1.2 本轮新测的像素指标

| 指标 | 现用 ico 16px 帧 | 去模糊单色版 16px 帧 |
|---|---|---|
| 实心像素里的不同色阶数 | **100** | **1** |
| 同指标 @256px / @32px | 4064 / 379 | 1 / 1 |
| 底部 25% 区最宽行 | 3px | 4px |
| 底部 25% 区最宽行 @32px | 6px | 8px |
| 剪影 bbox | 16×16（零留白） | 16×16（同口径）／14×14（若留 8% 白） |
| 总实心像素 @16px | 104 | 106（同口径）／77（留 8% 白，**−27%**） |

**两条被推翻的说法，在此更正并留档：**

1. `partial alpha 17.6%` **不能**作为"模糊糊边"的证据 —— 单色硬边图形在 16px 也测得 16.4%，那只是抗锯齿边缘的正常量。能区分的是**色阶数（100 vs 1）**。
2. 早期一次测量得出"加宽尾针反而更差"，是**混淆变量**造成的：那一版额外加了 8% 留白。补齐同口径后，加宽是正向的，但只值 1–2 个像素。

---

## 2. 母标志规范

### 2.1 几何

48×46 画布，单一闭合路径，零描边：

```
M25.946 44.938c-.664.845-2.021.375-2.021-.698
L19.4 33.937a2.26 2.26 0 0 0-2.262-2.262H10.287
c-.92 0-1.456-1.04-.92-1.788l7.48-10.471
c1.07-1.497 0-3.578-1.842-3.578H1.237
c-.92 0-1.456-1.04-.92-1.788L10.013.474
c.214-.297.556-.474.92-.474h28.894c.92 0 1.456 1.04.92 1.788
l-7.48 10.471c-1.07 1.498 0 3.579 1.842 3.579h11.377
c.943 0 1.473 1.088.89 1.83L25.946 44.94z
```

相对现 `favicon.svg` 有**两处**不同：`V33.937` → `L19.4 33.937`（尾针左界，使尾针从 2.02 单位宽即 4.2% 画布变 4.5 单位宽即 9.4%），以及闭合顶点 `L25.947 44.94` → `L25.946 44.94`（0.001 单位，把闭合点 x 与起点 `M25.946` 对齐 —— 旧文件这两处本就差 0.001）。顶点数、台阶数、圆角半径、倾斜方向全部保持。

**本节那一串 `d` 是权威值**：`gen-icon.ico.js` 读的母版、以及 `AppLogo.vue` 里复制的那一份，都必须与此逐字符一致，由 T2 同源断言钉住。

### 2.2 颜色与形制

| 形制 | 用在 | 填充 |
|---|---|---|
| 实心符号（单色） | 侧栏、登录页、连接页、关于对话框、文档站 | `currentColor`，宿主色 = `var(--brand)` |
| 底板符号 | `.ico` 全帧、`icon.png`、NSIS 安装器 | Light：`--grad-brand` 底 + `#ffffff` 符号；Night：`--grad-brand` 底 + `#131327` 符号 |

- **不做描边版**。此标志的识别度全在实心剪影，描边会退化成空心轮廓。
- 底板圆角率 22%（相对帧边长），与 `--p-radius-xl 16px` 在 64px 档等值，小尺寸下按圆角率而非固定半径。
- Night 底板墨色定为 `--p-slate-950 #131327`：白压 `#f9a825` 的对比只有约 1.9:1，`--on-brand:#ffffff`（`design-tokens.css:70` 与 `:114` 两处同值）在 night 下不成立。**连带动作**：在 `ui-design-guide.md` §3.3 品牌表加一行注记 —— `--on-brand` 仅适用于 Light 渐变底；Night 底板上的前景色用 `--p-slate-950`。
- **该缺陷在应用内已有一个现网实例**：`Sidebar.vue:147–157` 的 `.logo-icon` 是 `background: var(--brand); color: #fff` 的 40×40 实色底板，night 下正是"白符号压金黄底"。所以侧栏品牌位**保留底板形制**（它本来就是应用图标语言），但 night 前景改深墨。

### 2.3 最小尺寸与留白

- 界面内符号最小 16px（身份徽章档），低于此改用底板形制或不显示。
- 帧留白按 D7 注入，母版 viewBox 保持零留白 —— 留白写进母版会让所有帧一起缩小，实测 8% 留白使 16px 帧总墨迹掉 27%。

### 2.4 禁止用法

不得加投影/外发光/模糊（这是本轮移除的东西）；不得拉伸非 48:46 比例；不得在底板上使用非 `--grad-brand` 的渐变；不得用 `TrendCharts` / `Connection` / `📊` 代替品牌位。

---

## 3. 派生资产家族与生成管线

| 资产 | 路径 | 生成方式 | 消费者 |
|---|---|---|---|
| 母版 | `frontend/public/favicon.svg` | 手写，**同名替换内容** | `gen-icon.ico.js`、浏览器标签、`config/urls.py:88` |
| Windows 图标 | `build/icon.ico` 6 帧 | `gen-icon.ico.js` | `electron-builder.yml:55`、`afterPack.js:162–171` rcedit |
| 通用位图 | `build/icon.png` 256² | 同上 | 人工放置 |
| 安装器图标 | 复用 `build/icon.ico` | 新增 `installerIcon` / `uninstallerIcon` | NSIS |
| 文档站图标 | `docs/user-guide/favicon.svg` | 从母版复制 | 新增 `<link rel="icon">` |

**同名替换 `favicon.svg` 是刻意的**：`gen-icon.ico.js:24`、`config/urls.py:88`、`test_static_assets.py:97–103` 三处消费者一律不动。

### 3.1 `gen-icon.ico.js` 要改的三处

1. **注入按尺寸的留白**：渲染时把母版包进 `<g transform="translate(p,p) scale(...)">`，`p` 按 D7 取值。母版本身零留白。
2. **强制 light 配色**：渲染前 `page.emulateMedia({ colorScheme: 'light' })`。母版会带 `@media (prefers-color-scheme: dark)` 分支（见 §3.2），不锁定的话，构建机在深色系统下会截出金色 `.ico` —— 同一份源码产出两种图标，且没人会立刻发现。
3. **构建期自检**：渲染每帧后在页面内用 canvas 读回像素，断言①实心色阶数 ≤ 2；②16px 帧剪影 bbox ≥ 15×15。任一不满足即非零退出。这条是 §1.2 指标的守门版，防止将来有人把模糊或渐变加回来。

现脚本在 playwright 加载失败时只 `console.warn` 并 `return`（:72–81，注释「packaging is never blocked by an icon」）—— **保留**这个降级行为，但自检失败与降级是两回事：自检失败必须红。

### 3.2 母版 SVG 的写法

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 46">
  <style>.b{fill:#2563eb}@media (prefers-color-scheme:dark){.b{fill:#f9a825}}</style>
  <path class="b" d="…§2.1…"/>
</svg>
```

`@media` 分支只服务浏览器标签这一个消费者；`.ico` 走 §3.1-2 锁定 light，不受影响。

---

## 4. 运行时接入

| 位置 | 现状 | 动作 |
|---|---|---|
| Electron 窗口/任务栏 | `BrowserWindow` 无 `icon` | 加 `icon: nativeImage.createFromPath(...)`；打包态从 `extraResources` 复制来的 `icon.ico` 读，dev 态从仓库 `build/icon.ico` 读；**文件不存在时不设 icon**（不抛错，dev 首启无 ico 是正常态） |
| 任务栏分组/通知 | 无 AppUserModelID | `app.setAppUserModelId(APP_ID)`，`APP_ID='com.lq-dataprase.app'` |
| exe 元数据 | rcedit 已注入 `build/icon.ico` | 不动（`afterPack.js:162–171`） |
| 后端 exe | `lq_dataprase.spec:457 icon=None` | 改 `icon='build/icon.ico'` |
| NSIS | 无 installer/uninstaller 图标 | 加 `installerIcon: build/icon.ico`、`uninstallerIcon: build/icon.ico` |
| 文档站 | 无 favicon，品牌位是 `📊` | 加 `<link rel="icon">`，`:233` 换内联母版 |

`APP_ID` 与 `electron-builder.yml:19` 的 `appId` 是同一份信息的两处，按 `lessons.md:1587`「不要新建第二份」的规矩处理：加一条 T2 断言，读 `electron-builder.yml` 文本比对 `APP_ID`，漂了就红。

---

## 5. 界面图标体系（B）

### 5.1 唯一注册表 + 尺寸 token

- `frontend/src/constants/icons.ts` 从死代码改造成**唯一图标注册表**：`{ 语义名: EP 组件 }`，路由 `meta.icon` 与 `Sidebar.vue` 都从这里取，消灭现在"各自 import EP 图标"的散装状态。不新建 `Icon.vue` 组件（YAGNI：EP 组件已经是统一接口）。
- 尺寸不再写 `:size` 字面量。`el-icon` 未传 `:size` 时继承宿主 `font-size`，所以用 7 个工具类承载 token：

| token | 值 | 收编的现有 `:size` 字面量 | 现场证据 | 用途 |
|---|---|---|---|---|
| `--icon-inline` | 14 | 12, 13, 14 | 14×5、13×3 | 按钮/链接/chip 前后缀 |
| `--icon-control` | 16 | 16 | 16×1、`Topbar.vue:9` | 表单 prefix/suffix、表格操作、身份徽章 |
| `--icon-nav` | 18 | 18 | 18×5 | 侧栏菜单、工具栏 |
| `--icon-page` | 21 | 20, 22 | 20×2、22×2 | 页头（`ui-design-guide.md:403` 已定 21） |
| `--icon-logo` | 28 | 28 | `Sidebar.vue:6` | 侧栏品牌位 |
| `--icon-empty` | 48 | 48, 60 | `FileUploadArea.vue:12`、`FileManager.vue:10`、`SftpFileTable.vue:100` | 空态、拖拽区大面积 |
| `--icon-hero` | 64 | 56, 64 | `LoginPage.vue:7`、`ConnectPage.vue:6`、`ConsistencyCheckDialog.vue:84` | 品牌位与大结果态 |

12 种字面量 → 7 档。两处需要连带改指南，因为指南与代码已经漂了：

- `:341` 写"空状态图标 **34** 半透明"，但 `grep ':size="34"'` 全仓 **0 命中**，实测空态/大面积档是 40/48/60/64。取 **48**（现有用次最多），并把 `:341` 的 34 改为 48；照抄 34 等于凭空造一档没人用的。
- `:403` 的 21 与代码里的 20/22 并存 → 按指南取 21，代码向文档对齐。

**与既有决定的关系（避免误读）**：`docs/tasks/todo.md:2365` 那条"4 处 >32px 装饰大字保留字面量 + `@type-scale-one-off` 标记"，管的是 **CSS `font-size`**（现场：`UserManagement.vue:318` 36px、`LoginPage.vue:363` 48px、`ExportEmptyState.vue:24` 40px、`NotFoundPage.vue:30` 96px），配套的守门是"`frontend/src` 内不得再出现字面量**字号**"。本节规则管的是 **`el-icon` 的 `:size` prop**，是另一个属性，两者不冲突，§7 的新守门也不得重复实现旧守门。

但现场有一处**双机制互相覆盖**必须一并处理：`LoginPage.vue:7` 写 `:size="64"`，同文件 `:363` 又给 `.logo-icon` 写 `font-size:48px` —— 两个值在争同一个尺寸。统一到工具类时以归档后的 token 为准并删掉另一处；逐处归档的判据是"该图标承载的是品牌位 / 空态大面积 / 大结果态"三选一。

### 5.2 emoji 分四类，只治两类

| 类 | 例 | 处置 |
|---|---|---|
| **A 徽章字形**（承载分级信息） | `✓ ● ◆ ▼ ▲`（`ui-design-guide.md:279` 明文规定 CPK 族 A✓/B●/C◆/D▼） | **保留**，登记白名单。这不是"缺图标"，是刻意的字形系统 |
| **B 视图控制字形** | `⤡ ⤢ ↑ ↓ ↔ ▶ ◀` | **保留**，但受 `lessons.md:378`「字形要语义自明」约束（`⤡`/`⤢` 成对镜像那条已在用） |
| **C 装饰性 emoji 前缀** | `📊 📋 📦 📄 📥 📁 📂  📈  💾 ⚙  👥 🔒 👤 👁 📱 🏭  🔬 🔥 📐 🔗 🎭  🔍 ✅  ⚡  ⛔  🔁` | **治理**：品牌位（`AppAboutDialog.vue:12`、`template.html:233`）换母标志；tab label 与卡头**一律删 emoji 前缀、不补图标**（tab 已有中文标题，图标不增信息）；状态/告警类（`⚠ ✅ `）换 EP 矢量 |
| **D 同义分歧** | `Upload`/`UploadFilled`、`Setting`/`Tools`、`Refresh`/`RefreshLeft`/`🔄`/`🔁` | **归一**：动作按钮一律 `Upload`/`Download`，`UploadFilled` 只留给拖拽区大面积；`Setting`=设置页/齿轮动作，`Tools`=工具箱聚合（`FileListToolbar.vue:51` 属后者，保留）；刷新统一 `Refresh`，`RefreshLeft` 只用于"回退/撤销"语义 |

`FileManager.vue:142` 同一文件同时 import `Upload` 与 `UploadFilled` 是 C/D 类混用的实例，按上表拆开。

### 5.3 品牌位落位

| 位置 | 现在 | 改成 |
|---|---|---|
| `Sidebar.vue:5–6` | `TrendCharts` 28 | 母版符号，**保留该处既有的 40×40 `var(--brand)` 底板形制**（`.logo-icon` 现状即如此），但 night 下的前景色由 `#fff` 改 `--p-slate-950` —— 见下方"现网实例" |
| `LoginPage.vue:6–10` | `TrendCharts` 64 | 母版 `--icon-hero` |
| `ConnectPage.vue:5–6` | `Connection` 56 | 母版 `--icon-hero`（与登录页同一条首屏流程，品牌位应一致） |
| `AppAboutDialog.vue:12` | `📊` | 母版 `--icon-hero` |
| `Topbar.vue:8–10` 身份块 | EP 图标 16 | **不动**，它承载的是"当前页面"语义，不是品牌 |

### 5.4 指南一致性修复

三处都要改，且必须与代码同批，否则文档仍在许可旧写法：

| 指南 | 问题 | 动作 |
|---|---|---|
| `:309` vs `:360` | `:360` 要求身份块图标「EP 矢量图标，不用 emoji」，`:309` 却允许卡头「可带 emoji 图标」 | 删 `:309` 的许可，统一为"卡头不用 emoji" |
| `:341` | 「空状态图标 34 半透明」，但 `:size="34"` 全仓 0 命中，实测是 40/48/60/64 | 34 → **48**，与 `--icon-empty` 对齐 |
| `:403` | 「页头图标 21px」，代码却是 20/22 | 文档不动，代码向 21 对齐（`--icon-page`） |

### 5.5 明确不动的

- `theme-color` meta（`index.html:8`、`stores/theme.ts:35–38`）取 `--bg` 是**正确的**：它染的是浏览器 UI 底色，不是品牌位。不改。
- Excel 加载项 ribbon 图标（`Ribbon.cs:33–45` 的 `imageMso` + `:132–155` 自绘 `⚙`）不动。`lessons.md:916–925` 已记录 `imageMso` 只能实机肉眼看、离线判不出来，属另一条验证通路。

---

## 6. 死资产处置

| 资产 | 状态 | 动作 |
|---|---|---|
| `scripts/generate_icon.py` | 无任何调用方（`package.json`/`build.bat`/`*.spec`/`scripts/*` 全 grep 零命中），且会把 6 帧紫闪电覆盖成 1 帧 `#1890ff` 柱状图 | **删除** |
| `frontend/public/icons.svg` | 社交图标精灵图（bluesky/discord/github/x），源码零 `<use>`，但 `config/urls.py:89` 在路由它、`test_static_assets.py:104–109` 在断言它 | **三处一起删**（文件 + 路由 + 测试）。注意它不是"零引用"，只删文件会让后端测试红 |
| `frontend/src/constants/icons.ts` | 零 importers | **不删**，改造成 §5.1 的注册表 |

删除动作单独成批，且需要显式批准（改仓库既有资产与删测试是两回事）。

---

## 7. 测试与验收

按 `.claude/CLAUDE.md` 的"先选层再写断言"：

**T2 前端纯函数层**（`frontend/test/unit/`，毫秒级）
1. 注册表完整性：`router/index.ts` 每个 `meta.icon` 都在注册表里且解析为组件；注册表无未使用项。
2. `APP_ID === electron-builder.yml` 的 `appId`（读文件正则）。
3. 尺寸守门：扫 `frontend/src/**/*.{vue,ts}`，`el-icon` 上不得再出现 `:size="<数字>"`。**只查 `:size` prop** —— 字面量 `font-size` 已由 `todo.md:2365` 那批的既有守门覆盖，不得重复实现两条同性质检查。
4. emoji 白名单：C 类字符不得出现在 `.vue` 的模板文本节点里；A/B 类白名单内放行。

**T1 后端契约层**（`test/backend/test_static_assets.py`）
5. `favicon.svg` 仍返回 `image/svg+xml`（已有，回归保护）。
6. 删除 `test_icons_svg_served_as_svg`（随 §6 的 `icons.svg` 一并移除）。

**T3 e2e**（只留接线证明，不逐组合点按钮）
7. 一条：侧栏品牌位渲染出 `<svg>` 且非空，night 主题下其计算 `color` = `rgb(249, 168, 37)`、light 下 = `rgb(37, 99, 235)`。

**构建期自检**（§3.1-3，非测试层但承重）
8. 每帧实心色阶 ≤ 2；16px 帧 bbox ≥ 15×15。

**人工验收**（无法自动化的部分，必须明说）
9. 打包后在 Windows 任务栏、桌面快捷方式、Alt+Tab、安装向导四处肉眼看图标；卸载后确认快捷方式图标不残留为默认。这一条没有自动化通路，验收清单里标"人工"。

---

## 8. 显式取舍

| 取舍 | 代价 | 理由 |
|---|---|---|
| 不做 16px 简化几何 | 16px 帧仍是一团白（12 顶点 3 台阶超出 16px 信息容量） | 简化版会在 16px 之外与主标志不是同一形状，"单一形状"的价值高于那 1–2 像素 |
| 不做 NSIS `installerSidebar.bmp` / header | 安装向导侧栏仍是默认 | 需要单独设计 52×314 / 164×314 位图，收益低；`docs/specs/2026-07-27-windows-packaging-design.md:143–151` 里它本来就标"可选"且从未创建 |
| 不做托盘 | 无常驻入口 | 见 §10 |
| 尾针加宽只值 1–2 像素 | — | 不改形状性格，把尾针从"必然化开"提到"勉强站住"，仍值得 |

---

## 9. 分批实施

1. **批 1 · 母标志与家族**：替换 `favicon.svg` → 改 `gen-icon.ico.js`（留白注入 + 锁 light + 自检）→ 重生成 `build/icon.ico` → 目视 + 指标复核。
2. **批 2 · 运行时接入**：Electron 窗口 icon + `setAppUserModelId` + `extraResources`；`lq_dataprase.spec:457` icon；`electron-builder.yml` installer/uninstaller 图标。验收要真打包一次 `npm run dist:win:dir`。
3. **批 3 · 界面品牌位**：§5.3 五处落位（含侧栏 night 深墨修正）+ `ui-design-guide.md` §3.3 的 `--on-brand` 注记 + 文档站 favicon。`:309`/`:341`/`:403` 三处**不在本批** —— 按 §5.4 它们必须与 emoji 治理同批，否则文档仍在许可旧写法。
4. **批 4 · 注册表与尺寸 token**：§5.1 全量迁移 + T2 守门 3 条 + 指南 `:341`/`:403` 与 token 对账。
5. **批 5 · emoji 治理**：C 类删/换 + D 类归一 + T2 白名单断言 + 指南 `:309` 修复。按页分批，每批跑 `npm run test:e2e:affected`。**前置**：先产出逐处站点清单（本轮只统计到"约 40 种、300+ 次"的量级，没有逐处核实），否则计划里全是占位符。
6. **批 6 · 死资产清理**：§6 三项（需单独批准）。

批 4 与批 5 会大面积改 `.vue` 模板；按 `project-ui-design-workflow` 的约定，**先收拢选择器契约再动版式** —— 若现有 e2e 有按 emoji 文案定位 tab 的（`SettingsPage.vue:11–34` 的 7 个 emoji tab label 是高风险点），必须先迁移定位器到稳定属性并单独成批，否则批 5 之后"定位器坏了"与"功能坏了"混在一起无法判读。

---

## 10. 与已批准范围的偏差（报备）

批准 A 档时选项文本含"**托盘**"。本设计把它移出，理由：托盘不是图标问题而是生命周期问题 —— 一旦有托盘，就要定义"点关闭按钮是退出还是最小化到托盘""托盘右键菜单有哪几项""通知走托盘还是走 Windows toast"，这三条都会改用户已有的关窗行为，属于新功能而非图标接入，且现有 `electron/main.ts` 没有任何常驻/后台语义可以承接。

若仍要托盘，请单独说一声，我按新需求出生命周期设计，而不是在批 2 里顺手塞一个 `new Tray()`。
