# 3D 站点柱阵（单文件分析）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在单文件分析 tab 增加第 5 张可停靠图表「3D柱状图」（echarts-gl `bar3D`），用同一分母同时表达各 Site 的形状差异与数量差异，并支持旋转/缩放。

**Architecture:** 后端零改动——直接复用 `POST /analysis/histogram/` 的 `site_histograms`（分母是全站 `total_count`）。前端把三件承重逻辑做成**可 T2 直测的纯函数**（bin 裁剪口径 `histogramBins.ts`、grid3D 样式 token `echarts-tokens.ts`、option 构造 `site3dOption.ts`），组件只剩容器与降级分支；`echarts-gl` 只在异步分包里加载，冷启动字节不变。

**Tech Stack:** Vue 3.5 + Vite 8 + Element Plus 2.14 + Pinia 3、ECharts 6.1 + echarts-gl 2.1.0、vitest 5（node 环境 T2）、Playwright 1.60（T3）。

**Spec:** [docs/superpowers/specs/2026-11-04-3d-site-barchart-design.md](../specs/2026-11-04-3d-site-barchart-design.md)（含原型实测截图与六个已踩实的库坑）。本计划相对 spec 有 **5 处收口改动**（共 7 行），全部写在 Task 1 里并同步回 spec 正文。

---

## 全局约束（每个任务都受这些绊线）

| 约束 | 出处 | 执行口径 |
| --- | --- | --- |
| 单文件 ≤600 行 | `.claude/CLAUDE.md` + `frontend/test/unit/lineLimit.spec.ts` | **真闸是 vitest**（`node scripts/line-limit.mjs` 没有 CLI 入口，跑它等于空跑）；且它按 `git ls-files` 扫 ⇒ 新文件要先 `git add` 才被计量 |
| 双主题对称（R7①）/ setOption 不写 `var(--x)`（R7②）/ 禁裸调 `echarts.init`（R7③） | `docs/tasks/lessons.md` 通用规则 | 颜色一律经 `useEChartsTheme()`；建图只走 `useChart` |
| 测试分层 | `docs/reference/testing-gates.md` §2 | 纯函数判据走 T2（`npx vitest run`，秒级）；T3 只留「真 WebGL 出图」与「双主题对比度」两类不可替代的 |
| 本批必然升**全量 e2e 池** | `scripts/affected-rules.mjs:177,194-195`：`frontend/src/utils/`、`package.json`、`package-lock.json`、`frontend/e2e/helpers/` 全是 GLOBAL | 不是可选项，预留 6–8min + 后端 |
| 判绿只认日志末尾 `RESULT:` 行 | `testing-gates.md` §1 硬口径 + 本机实测 | 输出先落 `tasks/<批>/gate.log`，**不要用 `tail` 截**（会把失败用例名整条吞掉）；grep 用 `grep -a` |
| 门禁那轮必须独占机器 | 本机栽过 4 次 | 跑池期间不编辑任何被覆盖的文件、不并行跑别的测试 |
| 提交只在本地，**不 push** | 用户本批指令 | 每个任务末尾 `git commit`，禁止 `git push` |
| 不许碰的他人的活 | 用户 2026-11-04「保持待做」 | `docs/superpowers/specs/2026-11-03-site-ridgeline-design.md`（git 未跟踪）与 `tasks/` 下他人目录：不改、不 `git add -f`、不提交 |

---

## 文件结构（本批新建/修改）

**新建（5 个产品文件 + 6 个测试件：5 个 T2 + 1 个 T3）**

| 文件 | 职责（一句话） |
| --- | --- |
| `frontend/src/utils/echarts-tokens.ts` | ECharts 色 token 的**纯数据**两份 + `grid3DStyle()` 纯函数；零 Vue、零 pinia，可 node 直测 |
| `frontend/src/pages/analysis/composables/histogramBins.ts` | 「哪些 bin 该显示」的唯一口径（clip 边界 + RDL 扩展 + 病态回退），2D/3D 共用 |
| `frontend/src/pages/analysis/composables/site3dOption.ts` | `bar3D` option 纯构造 + 机位/箱体/截面常量单一来源 |
| `frontend/src/pages/analysis/components/Site3DChart.vue` | 薄壳：容器 + `useChart(canvas)` + 三种降级 + 图下提示条 + 复位响应 |
| `frontend/src/pages/analysis/composables/useChartToggles.ts` | 五个图表勾选 + 账号记忆接线（从 SingleParamTab 抽出，为 600 行让位） |
| `frontend/test/unit/histogramBins.spec.ts` | T2：三档口径 + RDL 扩展 + 病态回退 + null 边界 |
| `frontend/test/unit/echartsTokens.spec.ts` | T2：light/night 键集对称 + grid3D 样式取 token 而非写死 |
| `frontend/test/unit/site3dOption.spec.ts` | T2：spec §10 的判据 ①–⑧ |
| `frontend/test/unit/chartLayout.spec.ts` | T2：存量 v1 存档不丢（本批**不**升 `VERSION`）+ 旧账号 toggles 缺 `site3d` 默认关 |
| `frontend/test/unit/site3dWiring.spec.ts` | T2：静态接线绊线（组件不抄机位数、canvas 强制、两条降级分支、槽位与异步分包） |
| `frontend/e2e/analysis/site3d.spec.ts` | T3：只有两条（真出图 / night token），标 `@p1` |

**修改**：`frontend/package.json`+`package-lock.json`、`frontend/src/utils/echarts-theme.ts`、`frontend/src/pages/analysis/composables/{useChartDock.ts,dockGeometry.ts}`、`frontend/src/pages/analysis/components/{HistogramChart.vue,ChartDock.vue,SingleParamTab.vue}`、`frontend/src/composables/useChartMemory.ts`、`frontend/e2e/helpers/params.ts`、`docs/superpowers/specs/2026-11-04-3d-site-barchart-design.md`。

---

## Task 1：先把 spec 里五处会被照抄执行的错处改掉（7 行）

> 为什么第一个任务改文档：本计划下面每个任务都以 spec 为判据源。spec 里「升 `VERSION`」那条**因果写反了**，照它做会让所有用户已存的布局整表丢弃；另几处（`bin_counts` 的 tooltip 语义、night 轴线色的具体值**在两处各写了一份**、§5 的 `axisPointer` 对本图不适用）会在实现时误导读数。

- [ ] **Step 1：改掉 §4 里「升 VERSION」那一行（因果反了）**

打开 [docs/superpowers/specs/2026-11-04-3d-site-barchart-design.md](../specs/2026-11-04-3d-site-barchart-design.md)，把第 61 行整行替换：

```markdown
| `pages/analysis/composables/useChartDock.ts` | `ChartKey` 加 `'site3d'`、`ALL_KEYS`、`defaultLayout` 消费面，**`VERSION` 保持 1** | `isValidLayout` 只校验 `v === VERSION` 且「每个 key ∈ `ALL_KEYS`」（[useChartDock.ts:73-87](../../../frontend/src/pages/analysis/composables/useChartDock.ts)）⇒ **加一个 key 是让旧存档继续合法**，旧 4 图存档原样留下、由 `reconcile` 在需要时追加新格；反过来升档会让 `v !== VERSION` 命中，把**每个用户存过的布局（含本机 localStorage 与账号记忆两条路）整表丢弃**，正是这次要避免的。反方向也提醒一句：将来若从 `ALL_KEYS` **删** key，同一道门会把带那个 key 的存量整表作废。回归由 T2 `chartLayout.spec.ts` 钉住 |
```

- [ ] **Step 2：把 §10 里两条被同时改动的判据改到实际落点**

同一文件，把 §10 的这两处（第 175 行与第 164 行）分别替换。

> ⚠ 这一行**原本**在文件里不是 `- ` 列表项，而是 T3 那条 bullet 下**两个空格缩进**的续行（2026-11-04 勘误轮实测：`git show HEAD:…` 与工作树都是 `  布局存档回归：…`）。替换串必须同样以两个空格开头，否则要么 Edit 不命中、要么把列表形状改掉。动手前先 `sed -n '175p'` 看真实前缀，别照抄本计划里的引文。
>
> ⚠ 复审轮的后续位移：这条判据自称 T2 `chartLayout.spec.ts`，挂在 T3 名下与上面「T3 只留两条」自相矛盾，**已把它整体移到 T2 块末尾**（紧跟「另加 `histogramBins.spec.ts` …」那行之后），两个空格缩进保持不变，T3 块恢复只剩 ①②。所以下一轮再读这份 spec，行号已经不是 175（现约 181），别拿这个号当锚点，用 `grep -n "布局存档回归"` 定位。

```markdown
  布局存档回归：T2 `chartLayout.spec.ts` 断言「旧 `v:1` 四图存档在新代码下 `isValidLayout` 仍判合法」与「旧账号 toggles 缺 `site3d` ⇒ 默认关」。**不升 `VERSION`**（§4），所以这条钉的是「不丢」而不是「迁移」。
```

```markdown
  ④ light/night 两套 token 的**键集逐字相等**，且 3D 用到的那把键两边都有——由 `echarts-tokens.ts` 把两套色提成可导出的纯数据常量后，T2 `echartsTokens.spec.ts` 直接对真值断言（`useEChartsTheme()` 里的 computed 要过 pinia，而 `stores/theme` 的 watch 一初始化就摸 `document`，node 环境量不到）。
```

- [ ] **Step 3：把 §3 的 `bin_counts` 语义写准（后端只给全站点计数）**

§3 表格那行 `bin_counts` 的「用途」列，从 `tooltip 里的 n=` 改为：

```markdown
| `bin_counts` | tooltip 里的 `n=`，**它是该 bin 的全站点计数**（后端按 `total_count` 分母给占比，逐 Site 的原始计数不下发）⇒ 文案必须写「全站点该 bin n=」，不能缩成看着像 Site 级计数的 `n=`。⚠ 两者口径不等：`bin_counts` 之和是非空值数，`total_count` 含 NaN，所以别在界面上承诺「各 bin 相加 = N」 |
```

- [ ] **Step 4：把 night 轴线色的两处同值写法一起改成实测 token 值**

这个数在 spec 里写了**两遍**（§5 表格与 §6.6 的坑 6 正文），只改一处会让稿子自相矛盾——2026-11-04 勘误轮就是靠复审抓到第二处。

§5 表格里 `axisLine.lineStyle.color` 那行的「改成」列尾（现为「light `#eef0f3` / night `rgba(255,255,255,.05)`」）改为：

```markdown
；light `#eef0f3` / night `rgba(255, 255, 255, 0.04)`（这两个数就是 `echarts-theme.ts` 里 `splitLineColor` 两分支的现值，写 `.05` 是当时手抖取整，T3 断言按 `0.04` 逐字比）
```

§6.6 里那句「`axisLine` 恒取极淡底色（light `#eef0f3` / night `rgba(255,255,255,.05)`）」改为：

```markdown
（light `#eef0f3` / night `rgba(255, 255, 255, 0.04)`，与 §5 同一组真值）
```

改完必须验证稿子里再没有旧值：

```bash
grep -n "255,255,255,\.05\|255, 255, 255, 0\.05" docs/superpowers/specs/2026-11-04-3d-site-barchart-design.md
```
Expected：**零命中**（无输出）。

同表 `axisPointer.label.textStyle` 那一行的「改成」列尾追加一句（本图不会渲染那枚胶囊，照抄会写成死配置）：

```markdown
；**本图不适用**——`bar3D` 的 tooltip 走默认 `item` 触发（没有 `trigger:'axis'`），gl 不画 axisPointer 胶囊，所以实现里不写 `grid3D.axisPointer`（写了就是无人消费的死配置）。留这一句是给下一个读 §5 的人：不是漏做，是用不上。
```

- [ ] **Step 5：确认改动只是这几段，没顺手加戏**

```bash
git diff --stat docs/superpowers/
git status --porcelain
grep -nE "toolbox 旁|[^0-9]6 格|第 ① 条|约 300|255,255,255,\.05" docs/superpowers/specs/2026-11-04-3d-site-barchart-design.md
grep -nE "echarts-tokens|useChartToggles|site3dWiring|DockRow" docs/superpowers/specs/2026-11-04-3d-site-barchart-design.md
node -e "const t=require('fs').readFileSync('docs/superpowers/specs/2026-11-04-3d-site-barchart-design.md','utf8');console.log('lines',t.split('\n').length,'CR',t.split('\r').length-1)"
```
Expected：
- 只动两份文档（spec 与 plan），`git status --porcelain` 里**没有** `docs/superpowers/specs/2026-11-03-site-ridgeline-design.md` 的改动（那是另一个会话的待做稿，本批不碰、不提交），`docs/tasks/todo.md` 保持他人那份未提交原样；
- 第一条 grep **零命中**（`toolbox 旁`/`第 ① 条`/`约 300`/`.05` 全改净；`6 格` 用了锚定式，否则会子串命中 §3 的「26 格」——那是正当的分箱口径）；
- 第二条 grep 显示 §4 已登记 `echarts-tokens.ts` / `useChartToggles.ts` / `DockRow`，§10 已登记 `site3dWiring.spec.ts`；
- `CR 0`（这份 spec 在盘上是纯 LF）。行数从 201 涨到 209 属正常——勘误轮之后还有复审轮的补写。

> 勘误轮的 7 行是**第一批**改动；两道复审又暴露出 17 处「改了这行、周边就打架」的裂缝（§12 把复位图标写成「toolbox 旁」而本图禁 toolbox、§6 坑 6 拿原型色冒充 `axisLineColor`、24/26 两套 bin 数并存、布局存档回归那行挂在 T3 名下、§4 漏登记 4 个新建/被改文件、`echarts-theme.ts` 行数写反方向…），一并在 Step 1–4 的同一批里改掉，所以 `git diff --stat` 的规模比 7 行大。**判据是上面那组 grep 零命中 + 只动两份文档，不是某个特定的增删行数。**

> 换行制式的本机事实（2026-11-04 实测，别照印象写）：这份 spec 在盘上是**纯 LF**（0 个 CR），所以小 diff 天然成立；而 `docs/tasks/lessons.md`（2845 个 CRLF）、`docs/tasks/todo.md`（537）、`docs/reference/testing-gates.md`（368）是 **CRLF**——往那几份跟踪 `.md` 追加整节时必须按 CRLF 写，否则 diff 变成整文件重写（lessons 里的老判例仍然有效，只是**不适用于这份 LF 的 spec**）。`core.autocrlf=true` 只让 git 在下次 checkout 时改写工作树，不等于当前盘上就是 CRLF。

- [ ] **Step 6：提交（两份文档分两个 commit，别让计划里的注记混进勘误 commit）**

```bash
git add docs/superpowers/specs/2026-11-04-3d-site-barchart-design.md
git commit -m "docs(specs): 3D 柱阵稿收口——VERSION 不升档（升档会丢弃存量布局）、bin_counts 是全站点计数、night 轴线色两处统一 0.04、复位图标归面板头而非 toolbox"
git add docs/superpowers/plans/2026-11-04-3d-site-barchart.md
git commit -m "docs(plans): 实现计划随 spec 勘误同步（换行制式与 175 行落位的实测更正、Task5 补 tooltip 口径注）"
```

---

## Task 2：装 `echarts-gl`，并把「无 .d.ts 的裸导入能不能过 vue-tsc」量出来

> spec §2 已用 npm registry 核过 `echarts-gl@2.1.0` 的 peer 是 `echarts: ^5.1.2 || ^6.0.0`，本项目 `echarts ^6.1.0` 匹配。该包 **没有 `types`/`typings` 字段**（registry 实测），所以类型面要先量一把再决定是否需要 shim——别凭「以前见过」猜。

- [ ] **Step 1：装依赖**

```bash
cd frontend && npm install echarts-gl@^2.1.0
```
Expected：`package.json` 的 `dependencies` 多出 `"echarts-gl": "^2.1.0"`，`package-lock.json` 随之更新（连带 `claygl`、`zrender` 已在树里）。

- [ ] **Step 2：核实际落下的版本与入口字段**

```bash
node -e "const p=require('./node_modules/echarts-gl/package.json');console.log(p.version,p.main,p.module,JSON.stringify(p.peerDependencies),p.types||'NO-TYPES')"
node -e "console.log('claygl',require('./node_modules/claygl/package.json').version,'zrender',require('./node_modules/zrender/package.json').version)"
wc -c node_modules/echarts-gl/dist/echarts-gl.min.js
```
Expected：`2.1.0 dist/echarts-gl.js index.js {"echarts":"^5.1.2 || ^6.0.0"} NO-TYPES`（无 `types` = 确实不带声明文件）；`claygl 1.3.0`、`zrender 6.1.0` 且 **zrender 不嵌套第二份**（`npm ls` 里是 deduped）；min.js **639,846 B**——与 spec §2 记的字节逐字吻合（整包 `dist.unpackedSize` 是 7,041,402 B / 387 文件，含未压缩 bundle 与 .map，**别拿它当分包预期**）。

- [ ] **Step 3：写一次性探针文件，量裸导入的类型行为**

创建 `frontend/src/__gl_probe.ts`：

```ts
import 'echarts-gl'
export const probe = 1
```

```bash
npx vue-tsc -p tsconfig.app.json --noEmit
```
Expected：**无输出、退出码 0**（`import 'x'` 无绑定 ⇒ TS 不给隐式 any 报错）。2026-11-04 实测：EXIT=0 / 6.26s，且**必须做两条反证**证明这不是 lessons R8① 那种空检查——① `--listFiles` 里探针在程序内（`echarts-gl` 自身不在文件列表：无 .d.ts + `allowJs` 关 ⇒ TS 只解析不加载）；② 往探针塞一句 `export const falsify: number = 'not-a-number'` 必须报 TS2322 / EXIT=2。

**顺带量到的四种导入形态**（决定 Task 7 怎么写，别改回动态）：静态 `import 'echarts-gl'` 在 `.ts` 与 `.vue` 里都干净；`import * as gl from 'echarts-gl'` 与 `import('echarts-gl')` / `await import('echarts-gl')` 都报 **TS7016**。放行前提是本机 `noUncheckedSideEffectImports` 未开启（`@vue/tsconfig` 与 `tsconfig.app.json` 都没有它）——将来升 `@vue/tsconfig` 打开它要重量一遍。TS 解析落点是 CJS `dist/echarts-gl.js`（该包无 `exports` 字段），打包器走 `module: index.js`；日后想按模块粒度引 gl 瘦包会撞上那份 2.1 MB CJS bundle。

- [ ] **Step 4：只有 Step 3 报了 TS7016/TS2307 才加 shim，内容照抄**

```ts
// frontend/src/types/echarts-gl.d.ts
// echarts-gl 2.1.0 不带声明文件（npm registry 实测 types/typings 字段缺失），
// 本批只做 `import 'echarts-gl'` 副作用式注册，不消费它的任何导出类型。
declare module 'echarts-gl'
```
加完再跑一次 Step 3 的命令，Expected：无输出。

> 实测结论：**静态形态不报错 ⇒ 不建这个文件**（不需要 shim 却建 shim 是留死文件）。它确实能治好动态形态的 TS7016（临时建过一次量完删掉了），但本批按 Step 3 的结论走静态形态。

- [ ] **Step 5：删掉探针**

```bash
rm src/__gl_probe.ts
ls src/types/echarts-gl.d.ts 2>/dev/null || echo "无 shim（裸导入本就能过）"
git status --porcelain
```
Expected：只剩 ` M frontend/package.json`、` M frontend/package-lock.json`，外加本会话之外的存量（`?? docs/superpowers/specs/2026-11-03-site-ridgeline-design.md`、` M docs/tasks/todo.md`——都不碰不加）。

- [ ] **Step 6：提交（改动面要说清那一条删除的归属）**

```bash
git diff -- package-lock.json | grep -E '^[-+].*"node":'
git add package.json package-lock.json
git commit -m "build(frontend): 引入 echarts-gl 2.1.0（bar3D/grid3D，peer 与 echarts 6.1 匹配）"
```
Expected：lockfile 只有 20 增 1 删，新增路径只有 `node_modules/echarts-gl` 与 `node_modules/claygl`（`zrender` 已在树里、deduped）；**没有任何既有包的 `version`/`resolved` 被改写**。那 1 条删除是 lockfile 根条目的 `engines.node`：`>=20` → `>=22.12`——`frontend/package.json` 的 `engines.node` 早在 `e384420` 就改成了 `>=22.12` 但当时没重跑 install，这次安装顺手把 lockfile 同步成 package.json 的真值，**不是本批改的语义**，提交说明里带上归属，别让下一个人以为依赖被偷偷升级过。

---

## Task 3：`histogramBins.ts`——把 2D 的 bin 裁剪口径抽成共用纯函数

> spec §8。抽出来后 2D 只是改调用点，3D 用同一个函数，两图口径由**同一次实现**保证，不靠约定。

- [ ] **Step 1：先写失败的 T2 测试**

创建 `frontend/test/unit/histogramBins.spec.ts`：

```ts
/**
 * T2：直方图 bin 裁剪口径（2D 与 3D 共用）。
 *
 * 钉住的是「两图同屏不得各说各话」这一条根（specs/2026-11-04 §8），四条承重：
 * ① 只有 clip 藏柱体——exclude 改的是统计口径、off 什么都不改（把 exclude 写成也过滤，
 *    同屏 2D 与 3D 会与统计卡的 filtered 口径同时错位）；
 * ② RDL 扩展只在 RDL 且规格限齐备时发生，且是**放宽**（把 CL 也放宽，自定义限就白设了）；
 * ③ 边界病态到一格不剩时回退全部（旧 2D 守卫，回退丢了会画空图）；
 * ④ 后端 NaN→JSON null 的边界按「那一侧不裁」处理（R4②）——旧内联写法 `c >= null`
 *    会被 JS 悄悄当 `c >= 0`，本批把这一处**有意改掉**，spec §8 的「逐字节不变」在此让位。
 */
import { describe, expect, it } from 'vitest'

import { activeBinIndices, type BinClipSource } from '../../src/pages/analysis/composables/histogramBins'

/** 26 个中心：underflow + 24 正常 + overflow，与后端 binning.build_bin_grid 同形 */
const CENTERS = Array.from({ length: 26 }, (_, i) => -1 + i * 0.1)

function src(over: Partial<BinClipSource> = {}): BinClipSource {
  return {
    binCenters: CENTERS,
    handlingMode: 'off',
    outlierInfo: null,
    rangeType: 'RDL',
    ...over,
  }
}

describe('activeBinIndices — 只有 clip 动柱体', () => {
  it('off → 全部 26 格都在', () => {
    expect(activeBinIndices(src())).toEqual(CENTERS.map((_, i) => i))
  })

  it('exclude → 与 off 逐字相同（它只切统计口径，不藏柱）', () => {
    const withOutliers = activeBinIndices(src({
      handlingMode: 'exclude',
      outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
    }))
    expect(withOutliers).toEqual(CENTERS.map((_, i) => i))
  })

  it('clip + 有异常值 → 只留 [lower, upper] 闭区间内的中心', () => {
    const kept = activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
    }))
    expect(kept).toEqual(CENTERS.map((c, i) => (c >= 0.2 && c <= 0.8 ? i : -1)).filter((i) => i >= 0))
    expect(kept.length).toBeLessThan(CENTERS.length)
    // underflow（第 0 格 = -1）与 overflow（第 25 格 = 1.5）必须被裁掉
    expect(kept).not.toContain(0)
    expect(kept).not.toContain(25)
  })

  it('clip 但后端说没有异常值 → 不过滤（has_outliers 是前置条件）', () => {
    expect(activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: false, lower_bound: 0.2, upper_bound: 0.8 },
    }))).toEqual(CENTERS.map((_, i) => i))
  })
})

describe('RDL 放宽：原始 Limit 线内的数据不该被当异常值隐藏', () => {
  it('RDL 且两个规格限齐备 → 边界并上规格限（比纯 IQR 宽）', () => {
    const iqrOnly = activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
    }))
    const widened = activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
      lowerLimit: 0, upperLimit: 1,
    }))
    expect(widened.length).toBeGreaterThan(iqrOnly.length)
    expect(iqrOnly.every((i) => widened.includes(i))).toBe(true)
  })

  it('CL 模式不放宽（自定义限就是用户要的窗口）', () => {
    expect(activeBinIndices(src({
      handlingMode: 'clip', rangeType: 'CL',
      outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
      lowerLimit: 0, upperLimit: 1,
    }))).toEqual(activeBinIndices(src({
      handlingMode: 'clip', rangeType: 'CL',
      outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
    })))
  })

  it('RDL 但缺一个规格限 → 不放宽（旧实现要求两个都非 null）', () => {
    expect(activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
      lowerLimit: 0, upperLimit: null,
    }))).toHaveLength(activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: true, lower_bound: 0.2, upper_bound: 0.8 },
    })).length)
  })
})

describe('病态与 null 守卫', () => {
  it('边界反了（lower > upper）→ 回退全部，不画空图', () => {
    expect(activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: true, lower_bound: 9, upper_bound: -9 },
    }))).toEqual(CENTERS.map((_, i) => i))
  })

  it('bound 为 null（后端 NaN→JSON null）→ 那一侧不裁，而不是当成 0', () => {
    const kept = activeBinIndices(src({
      handlingMode: 'clip',
      outlierInfo: { has_outliers: true, lower_bound: null, upper_bound: 0.8 },
    }))
    // 下侧不裁 ⇒ underflow（-1）仍在；`c >= null` 那套旧行为会把负中心全裁掉
    expect(kept).toContain(0)
    expect(kept).not.toContain(25)
  })
})
```

- [ ] **Step 2：跑到它红**

```bash
npx vitest run test/unit/histogramBins.spec.ts
```
Expected：FAIL，报 `Failed to load ...histogramBins`（模块还不存在）。

- [ ] **Step 3：写实现**

创建 `frontend/src/pages/analysis/composables/histogramBins.ts`：

```ts
/**
 * 直方图「哪些 bin 该出现」的唯一口径（纯函数，零依赖）
 * ────────────────────────────────────────────────
 * 从 HistogramChart.vue 的内联实现抽出：2D 与 3D 同屏时，一边裁了柱另一边没裁
 * 就是同界面口径矛盾（specs/2026-11-04 §8；本项目反复修过同类问题）。
 * 有意偏离旧内联实现的一处：bound 为 null 时按「那一侧不裁」处理。旧写法
 * `c >= clipMin` 在 clipMin=null 时被 JS 隐式当 0（R4②：后端 NaN → JSON null），
 * 会把全部负中心柱悄悄藏掉——那条路径现实中要求 has_outliers 为真同时 bound 为 NaN，
 * 走到就是数据本身全坏，但共用函数不能把这坑带给 3D。
 */

export type OutlierMode = 'clip' | 'exclude' | 'off'

/** 后端 `outlier_info` 里本口径要消费的部分（数值可能为 null，见上） */
export interface OutlierBounds {
  has_outliers?: boolean
  lower_bound?: number | null
  upper_bound?: number | null
}

export interface BinClipSource {
  binCenters: number[]
  handlingMode: OutlierMode
  outlierInfo: OutlierBounds | null | undefined
  /** 'RDL' | 'CL' | '3σ' | '4σ' | '6σ' | 'Data Range'：只有 RDL 参与放宽 */
  rangeType: string
  lowerLimit?: number | null
  upperLimit?: number | null
}

function finiteOr(v: number | null | undefined, fallback: number): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback
}

/** 需要藏柱体的档位只有 clip；exclude 只换统计口径，不动柱体 */
function clipBounds(src: BinClipSource): [number, number] {
  const info = src.outlierInfo
  if (src.handlingMode !== 'clip' || !info?.has_outliers) return [-Infinity, Infinity]
  let lo = finiteOr(info.lower_bound, -Infinity)
  let hi = finiteOr(info.upper_bound, Infinity)
  // RDL 模式下原始 Limit 线内的数据不该被当异常值隐藏：边界并上规格限
  if (src.rangeType === 'RDL' && src.lowerLimit != null && src.upperLimit != null) {
    lo = Math.min(lo, src.lowerLimit)
    hi = Math.max(hi, src.upperLimit)
  }
  return [lo, hi]
}

/** 应显示的 bin 下标（升序）；边界病态到一格不剩时回退全部，不画空图 */
export function activeBinIndices(src: BinClipSource): number[] {
  const { binCenters } = src
  if (binCenters.length === 0) return []
  const [lo, hi] = clipBounds(src)
  const kept = binCenters
    .map((c: number, i: number) => (c >= lo && c <= hi ? i : -1))
    .filter((i: number) => i >= 0)
  return kept.length > 0 ? kept : binCenters.map((_: number, i: number) => i)
}
```

- [ ] **Step 4：跑到绿**

```bash
npx vitest run test/unit/histogramBins.spec.ts
```
Expected：`Test Files 1 passed`、用例全绿。

- [ ] **Step 5：让 2D 直方图改调它**

`frontend/src/pages/analysis/components/HistogramChart.vue`：

新增 import（第 16 行 `OutlierHintBar` 那行之前）：

```ts
import { activeBinIndices } from '../composables/histogramBins'
```

把 `HistogramChart.vue:89-112` 整段（从 `const shouldClip = ...` 到 `activeIndices` 回退守卫的收尾 `}`）替换为：

```ts
  // 统计口径启用：clip 与 exclude 都切到后端 filtered 统计（与统计卡 useHistogram
  // 的 useFiltered 同判断）——此前只认 clip，exclude 下卡片用 filtered 而 σ 线/
  // 正态曲线用全量，同界面口径矛盾
  const useFilteredStats = handlingMode !== 'off' && outlierInfo?.has_outliers
  // 柱体显隐口径与 3D 图同源（composables/histogramBins.ts）。useFilteredStats 留在
  // 这里：它管的是 σ 线/正态曲线取全量还是 filtered，不是柱体显隐，别一起搬走。
  const activeIndices = activeBinIndices({
    binCenters,
    handlingMode,
    outlierInfo,
    rangeType: props.rangeType,
    lowerLimit: r.lower_limit,
    upperLimit: r.upper_limit,
  })
```

同时**保留** `:90-92` 那条中文注释（「clip 与 exclude 都切到后端 filtered 统计…此前只认 clip」），它讲的是 `useFilteredStats` 的来历，与新函数无关；`HistogramChart.vue:69-71` 那三行英文「Outlier clipping: keep the X-axis range locked…」在删之前先要在**原位**留一条轴范围注释（收尾实测：`:84` 上方，指向 `outlier-handling.spec.ts:245`）——那句话里其实有两件事：「哪些 bin 被藏」搬进了新模块头注释，但「轴两端恒用**全量** binCenters」是 2D 自己的性质、新模块管不着，直接删掉就是把这个已上线的回归从注释里弄丢了。

- [ ] **Step 6：类型 + 现有 2D 判据都没坏**

```bash
npx vue-tsc -p tsconfig.app.json --noEmit
npx vitest run test/unit
```
Expected：`vue-tsc` 无输出；vitest 全绿（`histogramBins.spec.ts` 新计入）。若报 `'shouldClip' is declared but never read`（`noUnusedLocals`），说明 Step 5 没删干净，回去删。

- [ ] **Step 6.5：收尾实测校正（控制器 2026-11-04，规格复审后落的 4 处偏离；往后的任务以树为准，别照本任务正文回退）**

1. 头注释里「有意偏离的一处」说法不准：偏离是 `finiteOr` **这一道机制**，覆盖 null / undefined / NaN / ±Inf / 非数字五种；其中只有 `null` 在线上可达（`_helpers.py:126-129 clean_data` 把 NaN 与 ±Inf 都换成 `None`，DRF `allow_nan=False`）。正文那句「bound 为 null 时按那一侧不裁」是同一件事的窄口径。
2. `BinClipSource.rangeType` 的取值是 `RDL / DR / CL / S3 / S4 / S6`（`ChartConfigPanel.vue:28-33` 的 `value`），正文那个类型的注释写成 `'3σ' | '4σ' | '6σ' | 'Data Range'` —— 那是 el-option 的 label，不是 value。
3. RDL 放宽在真实载荷上是**恒等**：`histogram.py:126-128` 无条件把 rdl 传给 `detect_outliers_iqr`，`outliers.py:78-83` 对**每个档位**都并上规格限，而响应里的 `lower_limit/upper_limit` 就是同一对（`histogram.py:310-311`）。这一支保留是为了让本口径不依赖那条后端不变量、并维持抽出前的逐字语义；`histogramBins.spec.ts` 那三条放宽用例测的是**纯函数契约**（夹具造的是「只含 IQR 的窄边界」，生产不给那个形状），用例上方已写明。
4. 判据补两条：空 `binCenters` → `[]`（③ 的回退分支不由它生效）、bound 字段缺失（undefined）与 null 同义；非放宽档从只有 `CL` 扩成 `it.each(['CL','DR','S3','S4','S6'])`。

- [ ] **Step 7：提交**

```bash
git add src/pages/analysis/composables/histogramBins.ts test/unit/histogramBins.spec.ts src/pages/analysis/components/HistogramChart.vue
git commit -m "refactor(analysis): 直方图 bin 裁剪口径抽成 histogramBins 纯函数，为 2D/3D 同源铺路"
```

---

## Task 4：`echarts-tokens.ts`——色 token 提成纯数据 + `grid3DStyle()`

> spec §5（逐项映射回项目 token）与 R7②。把两套色从 `useEChartsTheme()` 的 computed 里搬到纯数据模块，是为了让「light/night 键集对称」这条判据在 **node 环境量得到**（computed 里要过 pinia，而 `stores/theme` 的 watch 一初始化就摸 `document`）。

- [ ] **Step 1：先写失败的 T2 测试**

创建 `frontend/test/unit/echartsTokens.spec.ts`：

```ts
/**
 * T2：ECharts 色 token 与 grid3D 样式件（specs/2026-11-04 §5、lessons R7①②）。
 *
 * 承重三条：
 * ① 两套 token 的键集**逐字相等**——不对称时 TS 会把 colors 推成联合类型、取键即红，
 *    但「两边都有该键、值一个是 var(--x) 一个是色值」这种半吊子只有断言抓得住；
 * ② grid3D 的每一处颜色都来自传入的 colors（不是写死），换主题必须换值——
 *    写死一份就等于「night 抄了 light 的长相」，正是本项目修过多轮的形状；
 * ③ 3D 用到的那把键（GRID3D_TOKEN_KEYS）在两分支都存在，缺一个就是运行时 undefined。
 * 外加一条库坑：`axisLine.show` 必须是 true——gl 2.1.0 在 false 时每次相机更新抛一次
 * TypeError（原型实测 194 条），「想抹掉轴线」只能给全透明色，不能关 show。
 */
import { describe, expect, it } from 'vitest'

import {
  ECHARTS_COLORS_LIGHT,
  ECHARTS_COLORS_NIGHT,
  GRID3D_TOKEN_KEYS,
  grid3DStyle,
} from '../../src/utils/echarts-tokens'

const keys = (o: object) => Object.keys(o).sort()

describe('双主题 token 对称（R7①）', () => {
  it('light/night 键集逐字相等', () => {
    expect(keys(ECHARTS_COLORS_NIGHT)).toEqual(keys(ECHARTS_COLORS_LIGHT))
  })

  it('3D 消费的每一把我都取得到', () => {
    for (const k of GRID3D_TOKEN_KEYS) {
      expect(ECHARTS_COLORS_LIGHT, `light 缺 token: ${k}`).toHaveProperty(k)
      expect(ECHARTS_COLORS_NIGHT, `night 缺 token: ${k}`).toHaveProperty(k)
    }
  })

  it('seriesColors 两边都是 8 格（站点色板按 % 8 循环，长度变了取色会错位）', () => {
    expect(ECHARTS_COLORS_LIGHT.seriesColors).toHaveLength(8)
    expect(ECHARTS_COLORS_NIGHT.seriesColors).toHaveLength(8)
  })
})

describe('grid3DStyle — 逐项取 token，不写死', () => {
  const light = grid3DStyle(ECHARTS_COLORS_LIGHT)
  const night = grid3DStyle(ECHARTS_COLORS_NIGHT)

  it('键集与轴型结构两边一致', () => {
    expect(keys(night)).toEqual(keys(light))
    expect(keys(night.axisLine)).toEqual(keys(light.axisLine))
    expect(keys(night.axisLabel.textStyle)).toEqual(keys(light.axisLabel.textStyle))
  })

  it('颜色确实随主题变化，且等于该主题的 token 值', () => {
    expect(light.axisLine.lineStyle.color).toBe(ECHARTS_COLORS_LIGHT.splitLineColor)
    expect(night.axisLine.lineStyle.color).toBe(ECHARTS_COLORS_NIGHT.splitLineColor)
    expect(night.axisLine.lineStyle.color).not.toBe(light.axisLine.lineStyle.color)
    expect(light.axisLabel.textStyle.color).toBe(ECHARTS_COLORS_LIGHT.axisLabelColor)
    expect(night.axisLabel.textStyle.color).toBe(ECHARTS_COLORS_NIGHT.axisLabelColor)
    expect(light.nameTextStyle.color).toBe(ECHARTS_COLORS_LIGHT.textColor)
  })

  it('没有任何 CSS 变量混进 setOption（R7②：ECharts 不解析 var(--x)）', () => {
    const text = JSON.stringify({ light, night })
    expect(text).not.toMatch(/var\(--/)
    expect(text).not.toMatch(/color-mix/)
  })

  it('gl 库坑：axisLine.show 恒为 true（false 会让每次相机更新抛一次 TypeError）', () => {
    expect(light.axisLine.show).toBe(true)
    expect(night.axisLine.show).toBe(true)
  })

  it('平涂不吃光：main 强度 0、不写 shadow（阴影是 demo 感主要来源）', () => {
    expect(light.light.main.intensity).toBe(0)
    expect(light.light.ambient.intensity).toBe(1)
    expect(JSON.stringify(light.light)).not.toContain('shadow')
  })

  it('轴线宽收到 1（gl 默认是 2 的 #333 硬线）', () => {
    expect(light.axisLine.lineStyle.width).toBe(1)
  })
})
```

- [ ] **Step 2：跑到它红**

```bash
npx vitest run test/unit/echartsTokens.spec.ts
```
Expected：FAIL，`Failed to load ...utils/echarts-tokens`。

- [ ] **Step 3：建纯数据模块**

创建 `frontend/src/utils/echarts-tokens.ts`，把 `echarts-theme.ts:61-152` 里 `colors` computed 内部的两套字面量**原值搬过来**，并加上接口与纯函数：

```ts
/**
 * ECharts 颜色 token（纯数据）与 grid3D 样式件（纯函数）
 * ────────────────────────────────────────────────
 * 为什么从 echarts-theme.ts 拆出来：那份是 `useEChartsTheme()` 里的 computed，取一次
 * 就要过 pinia，而 stores/theme 的 watch 一初始化就摸 `document` ⇒ node 环境的 T2 量不到。
 * 双主题对称（lessons R7①）与「3D 样式件逐项归 token」（specs/2026-11-04 §5）都需要
 * 对**真值**下断言，所以把数据放这儿。echarts-theme.ts 只保留 store 接线。
 *
 * ⚠ 这里只放颜色/字号/字族。业务色（站点色板）在 utils/chart-bar.ts，字号在
 * theme/typography.ts——两处都不要在这里再抄一份。
 */
import { chartFontSize, fontFamily } from '../theme/typography'

/** 两套主题必须提供**同一组键**：不对称会让 colors 退化成联合类型、消费点报 TS2339 */
export interface EChartsColors {
  backgroundColor: string
  textColor: string
  titleColor: string
  subtextColor: string
  axisLineColor: string
  axisLabelColor: string
  splitLineColor: string
  borderColor: string
  legendTextColor: string
  tooltipBg: string
  tooltipBorder: string
  tooltipText: string
  successColor: string
  warnColor: string
  errorColor: string
  infoColor: string
  brandColor: string
  brandColorSoft: string
  seriesColors: string[]
}

/** night 分支（原 echarts-theme.ts 的 isDark 分支，值逐字搬，注释留在原处） */
export const ECHARTS_COLORS_NIGHT: EChartsColors = {
  backgroundColor: 'transparent',
  textColor: 'rgba(255, 255, 255, 0.76)',
  titleColor: '#ffffff',
  subtextColor: 'rgba(255, 255, 255, 0.55)',
  axisLineColor: 'rgba(255, 255, 255, 0.10)',
  axisLabelColor: 'rgba(255, 255, 255, 0.76)',
  splitLineColor: 'rgba(255, 255, 255, 0.04)',
  borderColor: 'rgba(255, 255, 255, 0.10)',
  legendTextColor: 'rgba(255, 255, 255, 0.76)',
  tooltipBg: 'rgba(19, 19, 39, 0.88)',
  tooltipBorder: 'rgba(255, 255, 255, 0.18)',
  tooltipText: '#ffffff',
  successColor: '#11998e',
  warnColor: '#f9a825',
  errorColor: '#f5576c',
  infoColor: '#4facfe',
  brandColor: '#f9a825',
  brandColorSoft: 'rgba(249, 168, 37, 0.45)',
  seriesColors: [
    '#fdd835', '#14b8a6', '#4facfe', '#fb7185',
    '#38ef7d', '#b45309', '#00f2fe', '#ff9f43',
  ],
}

/** light 分支 */
export const ECHARTS_COLORS_LIGHT: EChartsColors = {
  backgroundColor: 'transparent',
  textColor: '#6b7280',
  titleColor: '#1f2937',
  subtextColor: '#9ca3af',
  axisLineColor: '#e5e7eb',
  axisLabelColor: '#6b7280',
  splitLineColor: '#eef0f3',
  borderColor: '#e5e7eb',
  legendTextColor: '#6b7280',
  tooltipBg: 'rgba(255, 255, 255, 0.92)',
  tooltipBorder: '#e5e7eb',
  tooltipText: '#1f2937',
  successColor: '#047857',
  warnColor: '#92400e',
  errorColor: '#b91c1c',
  infoColor: '#0369a1',
  brandColor: '#2563eb',
  brandColorSoft: 'rgba(37, 99, 235, 0.45)',
  seriesColors: [
    '#2563eb', '#047857', '#d97706', '#b91c1c',
    '#0284c7', '#86198f', '#475569', '#0d9488',
  ],
}

/** 3D 图消费的 token（T2 逐个断言两分支都有，缺一个就是运行时 undefined） */
export const GRID3D_TOKEN_KEYS = [
  'textColor', 'axisLabelColor', 'splitLineColor',
  'tooltipBg', 'tooltipBorder', 'tooltipText',
] as const

/** grid3D（echarts-gl）的样式件形状 */
export interface Grid3DStyle {
  axisLine: { show: true; lineStyle: { color: string; width: number } }
  splitLine: { show: true; lineStyle: { color: string; width: number } }
  axisTick: { show: false }
  axisLabel: {
    show: true
    margin: number
    textStyle: { color: string; fontSize: number; fontFamily: string }
  }
  nameTextStyle: { color: string; fontSize: number }
  light: { main: { intensity: number }; ambient: { intensity: number } }
}

/**
 * grid3D 的样式件：gl 的默认长相（#333 宽 2 硬轴线、12px 无字色标签、黑胶囊 axisPointer、
 * lambert 打光）逐项改回项目 token。只含样式——箱体几何与数据在
 * pages/analysis/composables/site3dOption.ts。
 */
export function grid3DStyle(colors: EChartsColors): Grid3DStyle {
  return {
    // show 必须为 true：echarts-gl 2.1.0 的 _updateAxisLabelAlign 在 show:false 时
    // 读到 null.axisLineCoords，每次相机更新抛一次 TypeError（原型实测一轮 194 条）。
    // 想彻底抹掉轴线的正确写法是保持 show:true + 全透明色，不是关 show。
    axisLine: { show: true, lineStyle: { color: colors.splitLineColor, width: 1 } },
    // 深底上 gl 默认的 #ccc 会糊成一片，与轴面同取极淡底色
    splitLine: { show: true, lineStyle: { color: colors.splitLineColor, width: 1 } },
    axisTick: { show: false },
    axisLabel: {
      show: true,
      margin: 6,
      // 字号/字族/字色三件都归 token（§5），gl 默认只有 12px 且没有字色
      textStyle: {
        color: colors.axisLabelColor,
        fontSize: chartFontSize.micro,
        fontFamily: fontFamily.sans,
      },
    },
    nameTextStyle: { color: colors.textColor, fontSize: chartFontSize.micro },
    // 平涂（shading:'color'）不吃光，也不写 shadow：阴影是「demo 感」的主要来源
    light: { main: { intensity: 0 }, ambient: { intensity: 1 } },
  }
}
```

- [ ] **Step 4：把 `echarts-theme.ts` 改成只做 store 接线**

在 `frontend/src/utils/echarts-theme.ts` 顶部 import 区加：

```ts
import {
  ECHARTS_COLORS_LIGHT,
  ECHARTS_COLORS_NIGHT,
  grid3DStyle,
  type EChartsColors,
} from './echarts-tokens'

export type { EChartsColors, Grid3DStyle } from './echarts-tokens'
```

把 `useEChartsTheme()` 里 `const colors = computed(() => { if (isDark.value) {…} else {…} })` **整块**（现 `:60-152`，含两套字面量与其间所有注释）替换为：

```ts
  // 两套值与「键集必须对称」的约束都在 utils/echarts-tokens.ts（那份是纯数据，
  // 双主题对称由 test/unit/echartsTokens.spec.ts 对真值断言）。这里只做 store 接线。
  const colors = computed<EChartsColors>(() =>
    isDark.value ? ECHARTS_COLORS_NIGHT : ECHARTS_COLORS_LIGHT
  )

  /** grid3D（3D 站点柱阵）样式件：与 getBaseOption 同一个 colors 源，不散写 */
  const grid3DTheme = computed(() => grid3DStyle(colors.value))
```

并把返回语句改为：

```ts
  return {
    isDark,
    colors,
    getBaseOption,
    grid3DTheme
  }
```

> 搬走时**保留原字面量里的解释性注释**：把 `colors` 那两段注释（语义状态色与 CSS token 同源、CVD 复验未过维持现状、`brandColorSoft` 替代 color-mix）跟着数据迁到 `echarts-tokens.ts` 对应位置——迁掉等于把这些事实从仓库里删了。

- [ ] **Step 5：类型 + 单测 + 全量 vitest 都过**

```bash
npx vue-tsc -p tsconfig.app.json --noEmit
npx vitest run test/unit/echartsTokens.spec.ts
npx vitest run test/unit
```
Expected：`vue-tsc` 无输出；新 spec 全绿；全量 vitest 全绿（所有消费 `useEChartsTheme()` 的组件不受影响，它们只取 `colors`/`getBaseOption`——消费点数量按 `grep -rn "useEChartsTheme()" frontend/src` 现量，别照抄任何写死的数字，本计划原先写的「14 个」实测是 19 个文件 / 23 处命中，其中还含定义文件与 README）。

- [ ] **Step 6：确认 token 单一来源没被抄成第二份**

```bash
grep -rn "#eef0f3" src | grep -v echarts-tokens
```
Expected：只剩 `src/styles/` 下的 CSS 定义（design tokens 本体）。若某个 `.vue` 里冒出 `#eef0f3` 硬编码，说明那处本该取 token，本任务顺手改掉或记录到 lessons。

- [ ] **Step 6.5：收尾实测校正（控制器 2026-11-04，规格复审后落，往后的任务以树为准）**

1. **Step 4 那句 `isDark.value ? ECHARTS_COLORS_NIGHT : ECHARTS_COLORS_LIGHT` 留在 theme 里是计划自带的缺口**：实施方按原样落完之后，「委托时取反」这条变异（M10b）实测 SURVIVED（新 spec 全绿 + 全量 test/unit 全绿 + `vue-tsc` exit 0）。根因是 pinia 在 node 不可测，不是漏写断言。修法：映射本身搬进 tokens 成为 `echartsColorsFor(isDark: boolean)`（唯一一份），theme 只委托；T2 加两条——按**引用相等**断言两分支，以及对 `echarts-theme.ts` 源码形状的委托断言（实参容忍改名/内联，但不许字面量、不许取反、色板名不许重新出现）。第二轮变异表 5 红 1 绿（等价内联写法 `echartsColorsFor(themeStore.currentTheme === 'night')` 必须保持不红，否则这判据会在下次重排时被当噪声删掉）。
2. **gl 版本措辞**：清单里是 `^2.1.0`（`package.json:40` 与 `package-lock.json` 都是 caret 区间，**没钉**），只有 `node_modules/echarts-gl/package.json` 是 2.1.0。所以「`axisLine.show` 必须为 true」那条库坑的可重跑依据是那条 grep，不是版本号；脱离 lockfile 重装后要先重跑。
3. **「夹具与真源逐字同值」从注释升级成判据**：`weightChartOption.spec.ts` 顶部的 `COLORS`/`NIGHT`/`base`/`NIGHT_BASE` 是从色板抄来的，Task 4 把真源搬走之后只剩注释在说「同值」。收尾补一条 describe 做等值断言（实测四对值当时全等，所以是绿的），并把那句「由 xxx 盯」改成指向本文件自己的判据。M11 变异（夹具首色改一位）红在该条。
4. **Step 7 的 `git add` 少列三个被本任务连带改到的文件**（`src/stores/userSettings.ts`、`test/unit/userSettings.spec.ts`、`test/unit/weightChartOption.spec.ts`：都只是为了把 `echarts-theme.ts:44-51` 这种行号指针换成符号名），照旧命令提交会把它们留在工作树里。已改成下面这条。
5. 数字更正：改动前的 `echarts-theme.ts` 是 **257** 行不是 258，本任务删了 **78** 行（257→179）；`useEChartsTheme()` 的消费点是 19 个文件 / 23 处调用（`grep -rn "useEChartsTheme()" src`），不是 Step 5 说的 14——树里没有注释复读 14，所以不构成假注释，只是别再拿它当依据。

- [ ] **Step 7：提交**

```bash
git add src/utils/echarts-tokens.ts src/utils/echarts-theme.ts test/unit/echartsTokens.spec.ts \
  src/stores/userSettings.ts test/unit/userSettings.spec.ts test/unit/weightChartOption.spec.ts
git commit -m "refactor(theme): ECharts 色 token 提成纯数据模块并补 grid3DStyle（双主题对称可由 T2 量真值）"
```

---

## Task 5：`site3dOption.ts`——option 纯构造（spec §10 判据 ①–⑧ 全在这里钉）

- [ ] **Step 1：先写失败的 T2 测试**

创建 `frontend/test/unit/site3dOption.spec.ts`：

```ts
/**
 * T2：3D 站点柱阵 option 构造（specs/2026-11-04 §10 判据 ①–⑧）。
 *
 * 这批断言里每一条都挡着一个**已经真踩过**的形状，不是装饰：
 * ① 轴型与 bin 对齐——x 必须是 category（bar3D 的柱宽由 category 轴等分，value 轴会退化成一根）；
 * ② shading/projection——lambert 会把 #0077BB 渲成别的色，色盲校验白做；perspective 的近大远小让柱高跨 Site 不可比；
 * ③ 色键走 pieces 且第 7 格换深灰——`categories` + `inRange.color` 实测一根柱都不画；#BBBBBB 在白底几乎不可辨；
 * ④ 主题对称由 echartsTokens.spec.ts 量，这里只验 option 里的颜色确实来自传入 colors；
 * ⑤ barSize 两个分量各管一个方向且**不相等**——写成单一 fill 同乘两方向就退回「3.85 宽 × 10.5 厚」的板状，
 *    用户在斜方位角看到的「歪」会复现（§6.3）；
 * ⑥ 无 Site 列返回 null 而不是空 option（组件据此走提示分支）；
 * ⑦ 3D 用的 bin 集合 === histogramBins 给 2D 的 activeIndices（§8 两图同口径）；
 * ⑧ 初始机位与「回到默认视角」读同一份导出值（§4，防两处各写一份漂移）。
 */
import { describe, expect, it } from 'vitest'

import {
  SITE3D_BAR_FILL,
  SITE3D_BOX,
  SITE3D_LIGHT_SLOT7,
  SITE3D_VIEW,
  applyDefaultView,
  buildSite3DOption,
  defaultViewControl,
  site3dBarSize,
  site3dPalette,
  type Site3DTheme,
} from '../../src/pages/analysis/composables/site3dOption'
import { activeBinIndices } from '../../src/pages/analysis/composables/histogramBins'
import {
  ECHARTS_COLORS_LIGHT,
  ECHARTS_COLORS_NIGHT,
  echartsColorsFor,
  grid3DStyle,
} from '../../src/utils/echarts-tokens'
import { SITE_COLORS_8_LIGHT, SITE_COLORS_8_NIGHT } from '../../src/utils/chart-bar'

const NB = 26          // 后端 binning.build_bin_grid：1 underflow + 24 正常 + 1 overflow
const NS = 8

function theme(isDark = false): Site3DTheme {
  // 用 echartsColorsFor 而不是自己写 `isDark ? NIGHT : LIGHT`：后者是 Task 4 刚清掉的
  // 第二份事实来源（照抄旧正文会把它回种进测试助手）
  const colors = echartsColorsFor(isDark)
  return { isDark, colors, grid3D: grid3DStyle(colors) }
}

/** 8 Site × 26 bin：Site 数越大峰越往右移（造一个「不旋转也能一眼辨出偏移」的形状） */
function mkResult(over: Record<string, unknown> = {}): any {
  const binCenters = Array.from({ length: NB }, (_, i) => -1 + i * 0.1)
  const site = (shift: number) => binCenters.map((c) => Math.max(0, 8 - Math.abs(c - shift) * 10))
  const site_histograms: Record<string, number[]> = {}
  for (let s = 1; s <= NS; s++) site_histograms[String(s)] = site(0.2 + s * 0.05)
  return {
    bin_centers: binCenters,
    bin_percentages: binCenters.map((_, i) => 4 - Math.abs(i - 12) * 0.1),
    bin_counts: binCenters.map((_, i) => 100 + i),
    total_count: 10000,
    unit: 'nA',
    lower_limit: -0.5,
    upper_limit: 1.0,
    outlier_info: { has_outliers: false, lower_bound: null, upper_bound: null, outlier_count: 0, normal_count: 10000 },
    site_histograms,
    ...over,
  }
}

const build = (r: any, over: Partial<{ mode: 'clip' | 'exclude' | 'off'; rangeType: string; param: string }> = {}, isDark = false) =>
  buildSite3DOption(r, theme(isDark), { mode: 'off', rangeType: 'RDL', param: 'Kelvin_VIN', ...over })

describe('① 轴型与 bin 网格', () => {
  it('x/y 是 category、z 是 value，且 x 逐格等于 bin_centers', () => {
    const o = build(mkResult())
    expect(o!.xAxis3D.type).toBe('category')
    expect(o!.yAxis3D.type).toBe('category')
    expect(o!.zAxis3D.type).toBe('value')
    expect(o!.xAxis3D.data).toHaveLength(NB)
    expect(o!.xAxis3D.data[0]).toBe('-1')
    expect(o!.xAxis3D.data[1]).toBe('-0.9')
    expect(o!.yAxis3D.data).toEqual(Array.from({ length: NS }, (_, i) => `Site${i + 1}`))
  })

  it('轴名带参数与单位，与 2D 直方图标题同族信息', () => {
    const o = build(mkResult(), { param: 'Vth' })
    expect(o!.xAxis3D.name).toBe('Vth (nA)')
    expect(o!.yAxis3D.name).toBe('Site')
    expect(o!.zAxis3D.name).toBe('占比 %')
  })

  it('柱体三元组 = [bin 位次, site 位次, 占比]，零占比不生成（192 根量级）', () => {
    const r = mkResult()
    r.site_histograms['1'] = r.site_histograms['1'].map((v: number, i: number) => (i % 2 ? 0 : v))
    const o = build(r)
    const data = o!.series[0].data
    expect(data.length).toBeLessThan(NS * NB)
    for (const d of data.slice(0, 5)) {
      expect(d.value).toHaveLength(3)
      expect(d.value[2]).toBeGreaterThan(0)
    }
  })
})

describe('② 平涂与正交投影（§5）', () => {
  it('shading=color、projection=orthographic', () => {
    const o = build(mkResult())
    expect(o!.series[0].shading).toBe('color')
    expect(o!.grid3D.viewControl.projection).toBe('orthographic')
  })

  it('opacity 不动（默认 1）：纵深渐隐会吃掉 Site 之间唯一的身份通道', () => {
    expect(build(mkResult())!.series[0].itemStyle.opacity).toBe(1)
  })
})

describe('③ 色键：pieces + 第 7 格覆盖', () => {
  it('用 pieces:[{value,label,color}]，不是 categories + inRange.color', () => {
    const o = build(mkResult())
    expect(o!.visualMap.type).toBe('piecewise')
    expect(o!.visualMap.dimension).toBe(1)
    expect(o!.visualMap.pieces).toHaveLength(NS)
    expect(o!.visualMap.pieces[0]).toMatchObject({ value: 0, label: 'Site1' })
    expect(o!.visualMap.inRange).toBeUndefined()
  })

  it('light 第 7 格换成深灰，其余 7 格与 SITE_COLORS_8_LIGHT 逐字相等', () => {
    const pal = site3dPalette(false)
    expect(pal[6]).toBe(SITE3D_LIGHT_SLOT7)
    expect(pal[6]).not.toBe(SITE_COLORS_8_LIGHT[6])
    expect(pal.map((c, i) => (i === 6 ? null : c))).toEqual(
      SITE_COLORS_8_LIGHT.map((c, i) => (i === 6 ? null : c)),
    )
  })

  it('night 整套与 SITE_COLORS_8_NIGHT 逐字相等（只治浅底那格，别顺手改深底）', () => {
    expect(site3dPalette(true)).toEqual([...SITE_COLORS_8_NIGHT])
  })

  it('pieces 的色 = 3D 专用色板（不是 2D 色板，也不是 seriesColors 主题色）', () => {
    const o = build(mkResult(), {}, false)
    expect(o!.visualMap.pieces.map((p: any) => p.color)).toEqual([...site3dPalette(false)])
    expect(o!.visualMap.pieces.map((p: any) => p.color)).not.toEqual([...ECHARTS_COLORS_LIGHT.seriesColors])
  })

  it('Site 数 > 8 时按 % 8 循环取色（与 2D 直方图同规则）', () => {
    const r = mkResult()
    r.site_histograms = { ...r.site_histograms }
    for (let s = 9; s <= 10; s++) r.site_histograms[String(s)] = r.site_histograms['1']
    const o = build(r)
    expect(o!.visualMap.pieces).toHaveLength(10)
    expect(o!.visualMap.pieces[8].color).toBe(o!.visualMap.pieces[0].color)
    expect(o!.visualMap.pieces[9].color).toBe(o!.visualMap.pieces[1].color)
  })
})

describe('④ 颜色来自传入 theme，不写死', () => {
  it('night 分支下 tooltip 与轴标签取 night token', () => {
    const o = build(mkResult(), {}, true)
    expect(o!.tooltip.backgroundColor).toBe(ECHARTS_COLORS_NIGHT.tooltipBg)
    expect(o!.tooltip.textStyle.color).toBe(ECHARTS_COLORS_NIGHT.tooltipText)
    expect(o!.visualMap.textStyle.color).toBe(ECHARTS_COLORS_NIGHT.axisLabelColor)
    expect(o!.grid3D.axisLine.lineStyle.color).toBe(ECHARTS_COLORS_NIGHT.splitLineColor)
  })

  it('option 里没有 CSS 变量混进 setOption（R7②）', () => {
    expect(JSON.stringify(build(mkResult()))).not.toMatch(/var\(--/)
  })

  it('背景 transparent：面板 CSS 底色透出，GL 图层不铺自己的底', () => {
    expect(build(mkResult())!.backgroundColor).toBe('transparent')
  })

  it('不放 ECharts toolbox：gl 画在第二张 canvas 上，saveAsImage 只会存出没有柱体的图', () => {
    expect(build(mkResult())!.toolbox).toBeUndefined()
  })
})

describe('⑤ barSize 是两个方向各自的绝对世界单位', () => {
  it('宽 = boxWidth/NB × 0.62、厚 = boxDepth/NS × 0.30，且两者不相等', () => {
    const o = build(mkResult())
    const [w, d] = o!.series[0].barSize
    expect(w).toBeCloseTo(SITE3D_BOX.width / NB * SITE3D_BAR_FILL.width, 10)
    expect(d).toBeCloseTo(SITE3D_BOX.depth / NS * SITE3D_BAR_FILL.depth, 10)
    // 这一条挡的是「写成单一 fill 同乘两个方向」：那样会退回板状截面（§6.3）
    expect(w).not.toBeCloseTo(d, 6)
  })

  it('bin 数变少（clip 之后）时宽跟着 band 重算，不是沿用满格值', () => {
    const full = site3dBarSize(NB, NS)[0]
    const clipped = site3dBarSize(NB - 6, NS)[0]
    expect(clipped).toBeGreaterThan(full)
  })

  it('箱体与机位是实测那一组数（改了要连原型一起回归）', () => {
    const g = build(mkResult())!.grid3D
    expect([g.boxWidth, g.boxHeight, g.boxDepth]).toEqual([SITE3D_BOX.width, SITE3D_BOX.height, SITE3D_BOX.depth])
    expect(SITE3D_BOX).toEqual({ width: 132, height: 74, depth: 120 })
    expect(SITE3D_BAR_FILL).toEqual({ width: 0.62, depth: 0.3 })
  })
})

describe('⑥ 无 Site 列 / 空数据 → null', () => {
  it('site_histograms 为 null 时返回 null（组件走 el-alert 分支）', () => {
    expect(build(mkResult({ site_histograms: null }))).toBeNull()
  })

  it('site_histograms 为空对象时返回 null', () => {
    expect(build(mkResult({ site_histograms: {} }))).toBeNull()
  })

  it('result 为 null/undefined 时返回 null，不抛', () => {
    expect(build(null)).toBeNull()
    expect(build(undefined)).toBeNull()
  })

  it('bin_centers 缺失时返回 null（没网格就没轴）', () => {
    expect(build(mkResult({ bin_centers: [] }))).toBeNull()
  })

  it('单 Site 文件照常出图（后端单站点也会填 site_histograms）', () => {
    const o = build(mkResult({ site_histograms: { '4': mkResult().site_histograms['4'] } }))
    expect(o!.yAxis3D.data).toEqual(['Site4'])
    expect(o!.visualMap.pieces).toHaveLength(1)
  })
})

describe('⑦ 与 2D 同一套 bin 口径（§8）', () => {
  const clipped = mkResult({
    outlier_info: { has_outliers: true, lower_bound: 0.1, upper_bound: 0.6, outlier_count: 90, normal_count: 9910 },
  })

  it('clip 下 x 轴标签集合 === histogramBins 给 2D 的 activeIndices 对应标签', () => {
    const o = build(clipped, { mode: 'clip' })
    const active = activeBinIndices({
      binCenters: clipped.bin_centers,
      handlingMode: 'clip',
      outlierInfo: clipped.outlier_info,
      rangeType: 'RDL',
      lowerLimit: clipped.lower_limit,
      upperLimit: clipped.upper_limit,
    })
    expect(o!.xAxis3D.data).toHaveLength(active.length)
    expect(active.length).toBeLessThan(NB)
    // 柱体的 x 位次必须落在 0..active.length-1（越界即两图各数各的）
    const xs = new Set(o!.series[0].data.map((d: any) => d.value[0]))
    expect(Math.max(...xs)).toBeLessThan(active.length)
  })

  it('RDL 放宽在 3D 里同样生效（边界并上规格限）', () => {
    const tight = build(clipped, { mode: 'clip', rangeType: 'CL' })
    const wide = build(clipped, { mode: 'clip', rangeType: 'RDL' })
    expect(wide!.xAxis3D.data.length).toBeGreaterThan(tight!.xAxis3D.data.length)
  })

  it('exclude 与 off 一样不藏柱（只 clip 过滤）', () => {
    expect(build(clipped, { mode: 'exclude' })!.xAxis3D.data).toHaveLength(NB)
  })

  it('tooltip 取的是原 bin 下标对应的 bin_counts，并把「全站点」写进文案', () => {
    const o = build(clipped, { mode: 'clip' })
    const active = activeBinIndices({
      binCenters: clipped.bin_centers, handlingMode: 'clip', outlierInfo: clipped.outlier_info,
      rangeType: 'RDL', lowerLimit: clipped.lower_limit, upperLimit: clipped.upper_limit,
    })
    const x = o!.series[0].data[0].value[0]
    const html = o!.tooltip.formatter({ value: [x, 0, 1.23] })
    expect(html).toContain('全站点该 bin n=' + clipped.bin_counts[active[x]])
    expect(html).toContain('1.23%')
    expect(html).toContain('Site1')
  })
})

describe('⑧ 机位常量单一来源', () => {
  it('初始 viewControl 与复位目标读同一份 SITE3D_VIEW', () => {
    expect(SITE3D_VIEW).toEqual({ alpha: 28, beta: 30, distance: 245, zoom: 1 })
    const vc = build(mkResult())!.grid3D.viewControl
    expect(vc.alpha).toBe(SITE3D_VIEW.alpha)
    expect(vc.beta).toBe(SITE3D_VIEW.beta)
    expect(vc.distance).toBe(SITE3D_VIEW.distance)
    expect(vc).toEqual(defaultViewControl())
  })

  it('applyDefaultView 用同一份值做合并写（不是 notMerge 全量重建）', () => {
    const calls: any[] = []
    applyDefaultView({ setOption: (o: any) => calls.push(o) })
    expect(calls).toHaveLength(1)
    expect(calls[0].grid3D.viewControl).toEqual(defaultViewControl())
    expect(calls[0].series).toBeUndefined()
  })

  it('实例为 null 时复位静默不抛（图还没建时点按钮）', () => {
    expect(() => applyDefaultView(null)).not.toThrow()
    expect(() => applyDefaultView(undefined)).not.toThrow()
  })
})
```

> 判据 ⑧ 还剩一半是**接线**（组件不许自己再抄一份机位数），它要读 `.vue` 文件，得等 Task 7 组件存在才有对象可测——那条写在 Task 7 Step 1 的 `site3dWiring.spec.ts` 里，别在这里提前塞一个必然红的 fs 断言。

- [ ] **Step 2：跑到它红**

```bash
npx vitest run test/unit/site3dOption.spec.ts
```
Expected：FAIL，`Failed to load ...site3dOption`。

- [ ] **Step 3：写实现**

创建 `frontend/src/pages/analysis/composables/site3dOption.ts`：

```ts
/**
 * 3D 站点柱阵（echarts-gl bar3D）的 option 纯构造
 * ────────────────────────────────────────────────
 * 与 dockGeometry.ts 同先例：纯模型放 composables/，判据能由 T2 直测
 * （test/unit/site3dOption.spec.ts 钉 spec §10 的 ①–⑧）。
 * 这里的每一个数都来自 2026-11-04 原型实测（specs/2026-11-04 §5/§6），改动任何一项
 * 都要连 `2026-11-04-3d-site-barchart-proto.html` 一起回归，别按「看着更顺眼」调。
 */
import { chartFontSize } from '../../../theme/typography'
import { formatAxisValue, formatPercent, getSiteColors8 } from '../../../utils/chart-bar'
import type { EChartsColors, Grid3DStyle } from '../../../utils/echarts-tokens'
import { activeBinIndices, type OutlierBounds, type OutlierMode } from './histogramBins'

/** 箱体（世界单位）。barSize 的两个 fill 只有和这组尺寸绑在一起才等价，换尺寸要同步重算（§6.3）。 */
export const SITE3D_BOX = { width: 132, height: 74, depth: 120 }
/**
 * 默认机位：alpha 低于 25 时后排被前排整根挡住；beta 取负会把值轴甩到左后方。
 * 初始 option 与面板头「回到默认视角」共用这一份（§10 判据 ⑧）。
 */
export const SITE3D_VIEW = { alpha: 28, beta: 30, distance: 245, zoom: 1 }
/**
 * 柱截面占格比例。宽度一度取过 0.85：正机位没问题，转到 alpha 35 / beta −25 时
 * 相邻 bin 沿 x 粘成一条斜脊（§6.6），0.62 才在任意角度保持单根可辨；
 * 纵深 0.30 是为了不把每根柱摊成斜板（§6.3）。
 */
export const SITE3D_BAR_FILL = { width: 0.62, depth: 0.3 }
/**
 * 平涂下 light 色板第 7 格 `#BBBBBB` 在白底几乎不可辨（§6.4，用户 2026-11-04 拍板）：
 * **只在这里**换成深灰，`SITE_COLORS_8_LIGHT` 本体不动——它还服务 2D 直方图、箱线图、
 * 多文件图与站点表色点，动它等于同时改这五处的视觉。取 #6b7280 是复用 textColor 那把灰。
 */
export const SITE3D_LIGHT_SLOT7 = '#6b7280'

export interface Site3DTheme {
  isDark: boolean
  colors: EChartsColors
  /** utils/echarts-tokens.ts 的 grid3DStyle(colors)：颜色/字号/字族单一来源 */
  grid3D: Grid3DStyle
}

export interface Site3DBuildOptions {
  /** 与 2D 同一把异常值档位（§8） */
  mode: OutlierMode
  /** 只有 'RDL' 会放宽裁剪边界，与 2D 同规则 */
  rangeType: string
  /** 当前参数名，进 x 轴名 */
  param: string
}

/** 后端 histogram 响应里本图消费的那几项 */
interface Site3DResult {
  bin_centers?: number[]
  bin_counts?: number[]
  site_histograms?: Record<string, number[]> | null
  outlier_info?: OutlierBounds | null
  lower_limit?: number | null
  upper_limit?: number | null
  unit?: string | null
}

export function site3dPalette(isDark: boolean): readonly string[] {
  const pal = getSiteColors8(isDark)
  if (isDark) return pal
  return pal.map((c, i) => (i === 6 ? SITE3D_LIGHT_SLOT7 : c))
}

/** 柱截面绝对世界尺寸：[x 方向宽, y 方向厚]，两个分量各管一个方向（§6.3） */
export function site3dBarSize(binCount: number, siteCount: number): [number, number] {
  const bandX = binCount > 0 ? SITE3D_BOX.width / binCount : 0
  const bandY = siteCount > 0 ? SITE3D_BOX.depth / siteCount : 0
  return [bandX * SITE3D_BAR_FILL.width, bandY * SITE3D_BAR_FILL.depth]
}

/** 正交 + 实测机位：初始 option 与复位按钮的共同来源 */
export function defaultViewControl(): Record<string, unknown> {
  return {
    projection: 'orthographic',
    alpha: SITE3D_VIEW.alpha,
    beta: SITE3D_VIEW.beta,
    distance: SITE3D_VIEW.distance,
    zoom: SITE3D_VIEW.zoom,
    rotateSensitivity: 0.8,
    zoomSensitivity: 0.7,
  }
}

/** 复位：合并写 viewControl（原型 :256 的同形写法；notMerge 会把柱数据一起换掉） */
export function applyDefaultView(
  chart: { setOption: (...args: any[]) => unknown } | null | undefined,
): void {
  if (!chart) return
  chart.setOption({ grid3D: { viewControl: defaultViewControl() } })
}

/**
 * 构建 option；无 Site 列 / 无网格时返回 **null**（不返回空 option——空 option
 * 会让 useChart 建出一张没有轴的空 canvas，用户看到的是「图坏了的空白框」而不是提示）。
 */
export function buildSite3DOption(
  result: Site3DResult | null | undefined,
  theme: Site3DTheme,
  opts: Site3DBuildOptions,
): Record<string, any> | null {
  const siteHists = result?.site_histograms
  const binCenters: number[] = result?.bin_centers ?? []
  if (!siteHists || binCenters.length === 0) return null

  // 站点序号升序：Site 名的数字序就是 y 轴的排布序，字符串序会把 Site10 排到 Site2 前面
  const sites = Object.keys(siteHists).sort((a, b) => Number(a) - Number(b))
  if (sites.length === 0) return null

  // 与 2D 同一把尺子（§8）：clip 边界外的 bin 既不进 x 轴标签，也不生成柱
  const active = activeBinIndices({
    binCenters,
    handlingMode: opts.mode,
    outlierInfo: result.outlier_info,
    rangeType: opts.rangeType,
    lowerLimit: result.lower_limit,
    upperLimit: result.upper_limit,
  })
  const binLabels = active.map((i) => formatAxisValue(binCenters[i]))
  const siteLabels = sites.map((s) => `Site${s}`)
  const counts: number[] = result.bin_counts ?? []
  const pal = site3dPalette(theme.isDark)
  const c = theme.colors

  const rows: { value: [number, number, number] }[] = []
  sites.forEach((site, s) => {
    const hists: number[] = siteHists[site] ?? []
    active.forEach((bi, x) => {
      const v = hists[bi] ?? 0
      // 零占比不生成柱体：8 Site × 26 bin 的满矩阵有三分之二是空的，
      // 全画会让 GL 侧的拾取射线命中零高柱、tooltip 弹出一堆 0%
      if (!(v > 0)) return
      rows.push({ value: [x, s, v] })
    })
  })

  const [barW, barD] = site3dBarSize(binLabels.length, sites.length)
  const unit = result.unit ?? ''
  const nameStyle = theme.grid3D.nameTextStyle

  return {
    // GL 图层本身以 transparent 创建（Grid3DView.js:35）⇒ 场景不铺底，ChartPanel 的
    // CSS 背景直接透出，双主题不必为 3D 单开背景处理
    backgroundColor: 'transparent',
    tooltip: {
      backgroundColor: c.tooltipBg,
      borderColor: c.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: c.tooltipText, fontSize: chartFontSize.dense },
      // value = [bin 位次, site 位次, 占比]；n= 来自 bin_counts，那是**该 bin 的全站点
      // 计数**（后端只下发占比，逐 Site 原始计数没有），文案不许缩成像 Site 级计数
      formatter: (p: any) => {
        const [x, s, v] = p.value
        const n = counts[active[x]] ?? 0
        return `<b>${siteLabels[s]}</b> · ${binLabels[x]}<br/>占比 ${formatPercent(v)}%（全站点该 bin n=${n}）`
      },
    },
    visualMap: {
      show: true,
      type: 'piecewise',
      dimension: 1,
      orient: 'vertical',
      right: 6,
      top: 'middle',
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 6,
      // 实测：`categories` + `inRange.color` 时 192 根柱一根都不画，必须 pieces。
      // 副作用正好：gl 系列不进 ECharts legend，所以这份 piecewise 就是本图唯一色键，
      // label 直接把色块标成 Site 名（§6.1）
      pieces: siteLabels.map((label, i) => ({ value: i, label, color: pal[i % 8] })),
      textStyle: { color: c.axisLabelColor, fontSize: chartFontSize.dense },
    },
    grid3D: {
      ...theme.grid3D,
      boxWidth: SITE3D_BOX.width,
      boxHeight: SITE3D_BOX.height,
      boxDepth: SITE3D_BOX.depth,
      viewControl: defaultViewControl(),
    },
    // x 用 category（官方两个结构型 bar3D 示例都是 category，柱宽由 category 轴等分）
    // ⇒ 规格限只能吸附到最近的 bin，画出来是误导性的精确，本图不画 LSL/USL（§7）
    xAxis3D: {
      type: 'category',
      data: binLabels,
      name: `${opts.param}${unit ? ` (${unit})` : ''}`,
      nameLocation: 'middle',
      nameGap: 30,   // 原型实测值（specs/…-proto.html:206）；正文此前写 26 是无出处的漂移
      nameTextStyle: nameStyle,
    },
    yAxis3D: { type: 'category', data: siteLabels, name: 'Site', nameTextStyle: nameStyle },
    zAxis3D: { type: 'value', name: '占比 %', min: 0, nameTextStyle: nameStyle },
    // 刻意不放 toolbox：gl 画在第二张 canvas 上，saveAsImage 只会存出没有柱体的图
    series: [
      {
        type: 'bar3D',
        data: rows,
        shading: 'color',
        bevelSize: 0.22,
        bevelSmoothness: 2,
        barSize: [barW, barD],
        // 纵深渐隐默认关（§6.5）：平涂 + 降 opacity 会把 Site 色饱和吃掉，
        // 而 Site 身份在这张图里就靠颜色
        itemStyle: { opacity: 1 },
        label: { show: false },
        emphasis: {
          label: {
            show: true,
            formatter: (p: any) => `${formatPercent(p.value[2])}%`,
            textStyle: { color: c.textColor, fontSize: chartFontSize.micro, backgroundColor: 'transparent' },
          },
        },
      },
    ],
  }
}
```

- [ ] **Step 3.5：正文示例代码的实测更正（Task 5 实施时发现，往后的任务照此办）**

上面这块**从没被机器验过**：`:1242` 原写 `if (!(v > 0)) continue`，而它在 `forEach` 的回调里 ⇒ esbuild 直接 `SyntaxError: Illegal continue statement`，spec 加载即崩，照抄正文不可能「Step 4 跑到绿」。已改成等价的 `return`（树里搜 `if (!(v > 0)) return` 就是——行号会随注释漂，别记数字）。
⇒ 往后任务（6/7/8）的示例代码**照抄前先单独跑一遍**；跑不通就是正文缺陷，按本条格式记在这里，别默默改掉。

- [ ] **Step 4：跑到它绿**

```bash
npx vitest run test/unit/site3dOption.spec.ts
```
Expected：全部通过。若「⑤」的 `not.toBeCloseTo(d, 6)` 红，说明 `barSize` 被写成了单一 `fill`（正是 §6.3 要挡的那个形状），按两个分量分开给。

- [ ] **Step 5：全量 vitest + 类型（两条类型检都要跑，它们覆盖面不同）**

```bash
npx vue-tsc -p tsconfig.app.json --noEmit && npx vue-tsc -b && npx vitest run test/unit
```
Expected：三条都无 TS 输出、全量 vitest 绿。
⚠ **`-p tsconfig.app.json` 不检 `test/`，`vue-tsc -b` 才检**（本任务实测：`site3dOption.spec.ts` 里
`new Set(any[])` 推成 `Set<unknown>`，`Math.max(...xs)` 在构建档报 TS2345，而 app-config 那条一路
exit 0；是 Task 5 的门禁跑到「前端构建失败」才露出来）。⇒ 只要这一批新增/改动了 `test/**`，
收尾必须额外跑 `npx vue-tsc -b`（或直接 `npm run build`），别拿 app-config 那条当全绿。

- [ ] **Step 5.5：规格复审后的收尾（控制器 2026-11-04，往后的任务以树为准）**

1. **spec 的根因错误**：`bin_counts` 行与 §4 那条曾写「`bin_counts` 之和 = 非空值数，而 `total_count` 含 NaN，两者口径不等」——**实测为假**：`histogram.py:119` 在任何计数之前就 `filter_finite`，`total_count` 与 `Σ bin_counts` 是同一个数。界面仍不写「各 bin 相加 = N」，但真正的理由是**裁剪档位下可见柱是子集**，不是因为 NaN。已同时勘误 spec §3 表格与 §4 正文（Task 1 那轮勘误把这条留在了规格里，Task 5 的注释只是把它传下来）。
2. **⑦ 有洞**：原来只钉「标签长度」与「柱的 x 值域」，`active.map((_, x) => binCenters[x])` 这种**整体错位**（长度对、值域对、每根柱顶刻度全是隔壁 bin 的）一条都不红 ⇒ 补 `xAxis3D.data` 与 `active.map(i => formatAxisValue(binCenters[i]))` 的**逐元素等值**。变异 N1 实测 CAUGHT。
3. **三件「刻意不画」原本无人钉**：补 `tooltip` 不含 `axisPointer`、option 不含 `legend`、系列不含 `markLine` 三条负向判据；变异 N2/N3/N4 各红对应那条。
4. **零占比不生成的判据从「少于 208」升级成独立 oracle 比值**（逐 Site 数 `>0` 的格求和），只断言上界会放过「多生成/少生成」两类写错的实现。
5. **`nameGap` 正文写 26 无出处**（原型 `specs/…-proto.html:206` 是 30，spec 无此数），与文件头「每一个数都来自原型实测」矛盾 ⇒ 改成 30。
6. **注释里两处数没根据**：「满矩阵有三分之二是空的」（全仓无出处）改成不写比例、只由判据钉行为；「它还服务箱线图与站点表色点」按 `grep -rln "getSiteColors8\|SITE_COLORS_8_LIGHT" src` 改成直方图/序列图/晶圆图/相关性散点/多文件图这五处（`BoxPlotChart.vue`、`SiteStatsTable.vue` 实测 0 引用）。
7. **反向探针的两条别当牙齿**：P2（`%8` → `%pal.length`）与 P3（`SITE3D_BOX` 键序）挡不住任何真错误——`pal.length ≡ 8`、`toEqual` 天生无序，属排版等价写法，留着只证明判据不误报；P1（formatter 改字符串拼接）是真探针。
8. **采集面第四坑（进 lessons）**：vitest 的 × 被 ANSI 转义包裹，而**测试标题里也会自带 ×**（本任务那条 `宽 = boxWidth/NB × 0.62…`）。用「行内含 ×」滤红名单会把绿行切成幻影红名单 ⇒ 必须剥 ANSI 后按 `trimStart` 的**行首**匹配。

- [ ] **Step 6：提交**

```bash
git add src/pages/analysis/composables/site3dOption.ts test/unit/site3dOption.spec.ts
git commit -m "feat(analysis): 3D 站点柱阵 option 纯构造（机位/箱体/截面/色键单一来源，T2 钉住 §10 ①–⑧）"
```

---

## Task 6：dock 第五格——`ChartKey` + 记忆 toggles + 存量存档不丢

> 这个任务**同时**动 `ChartKey`、`DockRow`、`ChartToggles`、`TITLES` 与 SingleParamTab 的最小接线：`Record<ChartKey, string>` 与 `ChartToggles` 是穷尽类型，少动一处 `vue-tsc -b` 就红（lessons R8①：判据必须走 `npm run build`，根目录 `--noEmit` 是空检查）。勾选框与图体留到 Task 7。

- [ ] **Step 1：先写失败的 T2 测试（存量存档不丢）**

创建 `frontend/test/unit/chartLayout.spec.ts`：

```ts
/**
 * T2：dock 布局存档与账号勾选的**向后兼容**判据（specs/2026-11-04 §4/§10）。
 *
 * 这次加的是第 5 个 key，所以真正的风险不是「新 key 读不到」，而是「旧存档被判非法」：
 * `isValidLayout` 只认 `v === VERSION` 且「key ∈ ALL_KEYS」⇒ 往 ALL_KEYS 加一项会让旧存档
 * **继续合法**（旧键集是新键集的子集），而升 `VERSION` 会让所有用户存过的布局整表丢弃。
 * 所以这条文件钉的是「不丢」，不是「迁移」：
 * ① 旧 v:1 四图存档在新代码下仍判合法，且 rows 逐字保留；
 * ② 含 site3d 的新存档合法；
 * ③ 未知 key（回滚场景/手改 localStorage）仍判非法，别让一处坏数据顶掉整表；
 * ④ 默认布局是 hist 独立首行 + 其余每行 2 张（5 图时 3 行）；
 * ⑤ 旧账号 toggles 缺 site3d ⇒ 默认关（勾过的用户才看得到 3D，别默认挤成 5 格）。
 */
import { describe, expect, it } from 'vitest'

import { DOCK_LAYOUT_STORAGE_KEY, defaultLayout, isValidLayout, type ChartKey } from '../../src/pages/analysis/composables/useChartDock'
import { parseToggles } from '../../src/composables/useChartMemory'

const LEGACY_V1 = {
  v: 1,
  rows: [['hist'], ['serial', 'qq'], ['box']],
  rowPcts: [58.6, 20.7, 20.7],
  colPcts: [[100], [50, 50], [100]],
  bodyH: null,
}

describe('存量布局存档：加第 5 个 key 不许把旧的判成非法', () => {
  it('旧 v:1 四图存档仍判合法', () => {
    expect(isValidLayout(LEGACY_V1)).toBe(true)
  })

  it('含 site3d 的存档判合法', () => {
    expect(isValidLayout({ ...LEGACY_V1, rows: [['hist'], ['serial', 'qq'], ['box', 'site3d']] })).toBe(true)
  })

  it('未知 key 仍判非法（旧版代码读到新存档时整表作废、回落默认，不画半张图）', () => {
    expect(isValidLayout({ ...LEGACY_V1, rows: [['hist'], ['nope']] })).toBe(false)
  })

  it('重复 key 判非法（同一张图占两格会让 findPos/moveTo 找错）', () => {
    expect(isValidLayout({ v: 1, rows: [['hist', 'hist']], rowPcts: [100], colPcts: [[50, 50]], bodyH: null })).toBe(false)
  })

  it('存档键名不变（改名等于把所有用户的本机布局清零）', () => {
    expect(DOCK_LAYOUT_STORAGE_KEY).toBe('lqdp-analysis-chart-layout')
  })
})

describe('defaultLayout — 5 图时的形状', () => {
  const all: ChartKey[] = ['hist', 'serial', 'qq', 'box', 'site3d']
  const rows = defaultLayout(all).rows
  it('hist 独立首行，其余每行 2 张 ⇒ 3 行', () => {
    expect(rows).toEqual([['hist'], ['serial', 'qq'], ['box', 'site3d']])
  })
  it('四图存档不受影响（勾集合没变就不该变形状）', () => {
    expect(defaultLayout(['hist', 'serial', 'qq', 'box']).rows).toEqual([['hist'], ['serial', 'qq'], ['box']])
  })
})

describe('toggles 向后兼容', () => {
  it('旧账号 state 缺 site3d → 默认关', () => {
    expect(parseToggles({ hist: true, serial: true, qq: false, box: false })?.site3d).toBe(false)
  })
  it('site3d: true 读得回来', () => {
    expect(parseToggles({ hist: true, serial: false, qq: false, box: false, site3d: true })?.site3d).toBe(true)
  })
  it('缺 serial 仍判整个 toggles 无效（旧口径不动：残缺对象不如按默认重来）', () => {
    expect(parseToggles({ hist: true, qq: false, box: false, site3d: true })).toBeNull()
  })
})
```

- [ ] **Step 2：跑到它红**

```bash
npx vitest run test/unit/chartLayout.spec.ts
```
Expected：FAIL——`parseToggles` 未导出，且 `defaultLayout(all)` 不会产出含 `site3d` 的三行。

- [ ] **Step 3：加 key（两处类型 + `ALL_KEYS` + 标题），并写下为什么不升 `VERSION`**

`frontend/src/pages/analysis/composables/useChartDock.ts:21-24`：

```ts
export type ChartKey = 'hist' | 'serial' | 'qq' | 'box' | 'site3d'
const ALL_KEYS: ChartKey[] = ['hist', 'serial', 'qq', 'box', 'site3d']
export const DOCK_LAYOUT_STORAGE_KEY = 'lqdp-analysis-chart-layout'
// 存档版本：加一个 ChartKey 是**向后兼容**的变换（isValidLayout 只要求 key ∈ ALL_KEYS），
// 所以不升档。升档会让 `p.v !== VERSION` 命中，把每个用户存过的布局（本机 localStorage
// 与账号记忆两条路）整表丢弃——2026-11-04 的 spec 初稿把这条因果写反了，已勘误。
const VERSION = 1
```

`frontend/src/pages/analysis/composables/dockGeometry.ts:17`（`ChartKey` 加宽后这里不加会 TS2345，`useChartDock` 把 `ChartKey[]` 交给了 `DockRow[]`）：

```ts
export type DockRow = 'hist' | 'serial' | 'qq' | 'box' | 'site3d'
```

`frontend/src/pages/analysis/components/ChartDock.vue:121-123`：

```ts
const TITLES: Record<ChartKey, string> = {
  hist: '直方图', serial: '序列分布', qq: 'QQ 图', box: '箱线图', site3d: '3D柱状图',
}
```

同文件第 7 行的说明注释补一句契约来源（`controls-<key>` 槽已存在，不需改 dock）：把
`内容通过按 key 命名的 slot 注入：hist/serial/qq/box（图体）与 controls-box（箱线控件）。` 改为
`内容通过按 key 命名的 slot 注入：图体 hist/serial/qq/box/site3d，专属控件 controls-serial/hist/box/site3d（dock 已有 controls-<key> 透传，加图不用改本组件）。`

- [ ] **Step 4：`ChartToggles` 加 site3d 并导出 parseToggles**

`frontend/src/composables/useChartMemory.ts:30`：

```ts
export interface ChartToggles { hist: boolean; serial: boolean; qq: boolean; box: boolean; site3d: boolean }
```

`parseToggles`（同文件 `:49-60`）加字段并导出（导出给 T2 直接量，不为了测试另开一层壳）：

```ts
/** 账号记忆里的勾选集（导出供 test/unit/chartLayout.spec.ts 量向后兼容） */
export function parseToggles(raw: unknown): ChartToggles | null {
  if (!raw || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  if (typeof o.serial !== 'boolean' || typeof o.qq !== 'boolean' || typeof o.box !== 'boolean') return null
  // hist 为 2026-09-13 新增字段：旧账号数据缺它 → 默认 true（直方图原为常驻不可关）
  // site3d 为 2026-11-04 新增字段：缺它 → 默认 false（新图默认不勾，别把 dock 从 4 格挤成 5 格）
  return {
    hist: typeof o.hist === 'boolean' ? o.hist : true,
    serial: o.serial,
    qq: o.qq,
    box: o.box,
    site3d: typeof o.site3d === 'boolean' ? o.site3d : false,
  }
}
```

同文件 `:85-93`「由布局反推勾选」那段加一项（F5 丢了 toggles 上报时，布局就是「当时勾着」的事实记录）：

```ts
        state.toggles = {
          hist: keys.has('hist'),
          serial: keys.has('serial'),
          qq: keys.has('qq'),
          box: keys.has('box'),
          site3d: keys.has('site3d'),
        }
```

- [ ] **Step 5：SingleParamTab 最小接线（先让类型与运行时都成立）**

`frontend/src/pages/analysis/components/SingleParamTab.vue`：

`:22` 之后加一行勾选：

```html
          <el-checkbox v-model="showSite3D" size="small">显示3D柱状图</el-checkbox>
```

`:424` 的 `const showQQPlot = ref(false)` 之后加：

```ts
// 3D 站点柱阵：默认不勾（勾上即把 dock 从 4 格挤到 5 格，且要下载 gl 分包）
const showSite3D = ref(false)
```

`:440-447` 的 `activeChartKeys` 里加一项、`:454-459` 的 `onDockClose` 里加分支：

```ts
  if (showBoxPlot.value) keys.push('box')
  if (showSite3D.value) keys.push('site3d')
```

```ts
  else if (key === 'box') showBoxPlot.value = false
  else if (key === 'site3d') showSite3D.value = false
```

`:465-478` 那段勾选记忆 watch 与恢复各加一项（Task 7 会把整块抽走，这里先保持类型成立）：

```ts
watch([showHistogram, showSerial, showQQPlot, showBoxPlot, showSite3D], ([h, s, q, b, d]) => {
  if (togglesApplying) return
  togglesTouched = true
  saveChartState({ toggles: { hist: h, serial: s, qq: q, box: b, site3d: d } })
})
```

```ts
  showBoxPlot.value = state.toggles.box
  showSite3D.value = state.toggles.site3d
```

- [ ] **Step 6：跑到 T2 绿 + 类型绿**

```bash
npx vitest run test/unit/chartLayout.spec.ts
npx vue-tsc -p tsconfig.app.json --noEmit
```
Expected：新 spec 全绿；无 TS 输出。

- [ ] **Step 6.5：规格 + 质量复审后的收尾（控制器 2026-11-04，往后的任务以树为准）**

1. **「勾选框留到 Task 7」是假的**：本任务 Step 5 就要加勾选与记忆接线，否则 `ChartToggles` 加宽后 `saveChartState({toggles})` 直接 TS 红。实施方按计划做了，这一点以树为准。
2. **`loadLayout` 已导出**（原先私有）：`isValidLayout` 只回答合法与否，答不了「读出来还是不是原来那份」。T2 现在用 mock 过的 `safeStorage` 喂一份 `v:1` 四图存档做**真回读**，断言 `rows/rowPcts/colPcts/bodyH` 值相等；mock 里校验键名，读错键会拿到 null 而红。变异「读档时补一行 site3d」「丢 bodyH」「rowPcts 重建」三条实测各红该条。
3. **`bodyH` 夹具从 null 改成 900**：null 进 null 出的回读断言是空断言（质量复审指出）。
4. **判据缺口（留给 Task 7）**：删掉 `SingleParamTab.vue` 里 `onDockClose` 的 `site3d` 分支，全量 vitest 664 例仍绿——面板「×」关闭 3D 却不取消勾选这条行为在 T2 层无人钉。Task 7 要把勾选块抽成 `useChartToggles.ts`，**抽出时必须给「关闭即取消对应勾选」补一条 T2**（五键逐一，别只测 histogram）。同理 `HIST_ROW_PX 780→781` 全绿，该常量目前无判据（风险低，记录在案）。
5. **中间态与 reconcile 的已知差异**：老用户存的是 4 图布局、勾上 site3d 时，`reconcileRows` 会**追加一整行**（4 行），而不是走 `defaultLayout` 的 3 行——这是「保留用户手调形状」的预期结果，不是缺陷；本任务 Step 7 的浏览器核对并入 Task 7 一起做（那时图体才存在）。
6. **e2e helper 的键清单漂了**：`frontend/e2e/helpers/params.ts:254,262` 仍写「四个图表开关」且 `CHART_TOGGLE_LABELS` 缺 `site3d` ⇒ Task 8 必须补（否则新勾选框的定位器契约是缺的）。
7. 前向注释（`ChartDock.vue` 的 `#site3d` slot、`SingleParamTab.vue` 的 gl 分包）当前都还没发生，Task 7 落地后这些话才成立——若 Task 7 改道，记得回来改这两处。

- [ ] **Step 7：确认第 5 格不会吃掉存量布局（真实浏览器一眼，别只看单测）**

```bash
npm run dev
```
用 Playwright/browser 打开 `http://localhost:3000/#/analysis`（登录态照 `frontend/e2e/.auth/admin.json` 那个账号），在**已存 4 图布局**的机器上：勾上「显示3D柱状图」再取消，控制台执行

```js
JSON.parse(localStorage.getItem('lqdp-analysis-chart-layout')).rows
```
Expected：`rows` 仍包含用户原有的行划分（例如 `[[hist],[serial,box],[qq]]` 这种手调形状不被抹回默认），且**没有** site3d 残留。看完 `Ctrl+C` 停掉 dev。

- [ ] **Step 8：提交**

```bash
git add src/pages/analysis/composables/useChartDock.ts src/pages/analysis/composables/dockGeometry.ts src/pages/analysis/components/ChartDock.vue src/composables/useChartMemory.ts src/pages/analysis/components/SingleParamTab.vue test/unit/chartLayout.spec.ts
git commit -m "feat(analysis): dock 契约加第 5 格 site3d（不升存档版本、旧账号缺省关，含 T2 存档回归）"
```

---

## Task 7：`Site3DChart.vue` + 接线（含把勾选块抽成 `useChartToggles.ts`）

> 抽取不是洁癖：`SingleParamTab.vue` 现在 577 行，直接加「异步组件 + `#site3d` 图体槽 + `#controls-site3d` 图标 + 复位态」会到 ~610 行，破 600 硬约束（真闸是 `lineLimit.spec.ts`，按 `git ls-files` 扫）。勾选块 + dock 键集 + 记忆接线正好是可独立成立的一层，抽出去净减 ~37 行。

- [ ] **Step 1：先写接线绊线（spec §10 判据 ⑧ 的另一半 + 槽位契约）**

创建 `frontend/test/unit/site3dWiring.spec.ts`。这是本仓既有的静态接线判据族（`portWiring.spec.ts`、`exportTimeoutWiring.spec.ts` 同形）：视角数只该有一份、图体槽与控件槽都得真的挂上。

```ts
/**
 * T2：3D 图的接线绊线（specs/2026-11-04 §4 + §10 判据 ⑧ 的组件半边）。
 *
 * 静态读源文件而不是起组件：这三条判据的对象是「接线形状」，用浏览器量要付 3s 单价，
 * 而它们一旦断了就是编译期/挂载期立刻可见的错，不需要真渲染。
 * 与 test/unit/site3dOption.spec.ts 的「⑧ 常量单一来源」配对：那边量纯函数，这边量消费者。
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SRC = new URL('../../src/', import.meta.url)
const read = (rel: string) => readFileSync(new URL(rel, SRC), 'utf8')

describe('Site3DChart.vue 不自己抄机位与箱体', () => {
  const vue = read('pages/analysis/components/Site3DChart.vue')

  it('复位走 composables 的导出值', () => {
    expect(vue).toMatch(/applyDefaultView/)
    expect(vue).toMatch(/from '..\/composables\/site3dOption'/)
  })

  it('源码里不出现任何机位/箱体字面量（写了就是第二份真相，复位会漂）', () => {
    for (const literal of ['alpha:', 'beta:', 'distance:', 'boxWidth:', 'boxDepth:', 'boxHeight:']) {
      expect(vue, `Site3DChart.vue 不该出现 ${literal}`).not.toContain(literal)
    }
  })

  it('渲染器恒为 canvas（gl 只吃 canvas，不写会被 useChart 判成渲染器不符反复重建）', () => {
    expect(vue).toMatch(/\(\s*\)\s*=>\s*'canvas'/)
  })

  it('有 echarts-gl 的**静态**副作用导入（缺这行 bar3D/grid3D 从未注册，图会静默空白）', () => {
    expect(vue).toContain("import 'echarts-gl'")
    // 动态形态实测撞 TS7016（该包无 .d.ts，动态 import 要推返回值类型），不许换写法
    expect(vue).not.toMatch(/import\(\s*['"]echarts-gl['"]\s*\)/)
  })

  it('降级分支存在且不建图（WebGL 缺失与无 Site 列各一条 el-alert）', () => {
    expect(vue).toMatch(/webglAvailable/)
    expect(vue).toMatch(/hasSites/)
    expect((vue.match(/<el-alert/g) ?? []).length).toBe(2)
  })

  it('宿主带 e2e 契约属性 data-site3d-canvas（T3 按它定位，别靠 class 猜）', () => {
    expect(vue).toContain('data-site3d-canvas')
  })
})

describe('SingleParamTab.vue 的五图接线', () => {
  const vue = read('pages/analysis/components/SingleParamTab.vue')

  it('图体槽与控件槽都挂上（dock 已按 controls-<key> 透传，缺槽就是面板没标题栏控件）', () => {
    expect(vue).toMatch(/<template #site3d>/)
    expect(vue).toMatch(/<template #controls-site3d>/)
  })

  it('勾选文案沿用「显示」前缀（e2e 的 CHART_TOGGLE_LABELS 按文本定位）', () => {
    expect(vue).toContain('显示3D柱状图')
  })

  it('组件走异步分包（同步 import 会把 gl 的 0.64MB 拉进冷启动）', () => {
    expect(vue).toMatch(/defineAsyncComponent\(\(\)\s*=>\s*import\('\.\/Site3DChart\.vue'\)\)/)
  })

  it('勾选态不再原地持有（改由 useChartToggles 单一来源）', () => {
    expect(vue).toMatch(/useChartToggles\(\)/)
    expect(vue).not.toMatch(/const showHistogram = ref/)
  })
})
```

```bash
npx vitest run test/unit/site3dWiring.spec.ts
```
Expected：FAIL（`Site3DChart.vue` 还不存在；`SingleParamTab` 的三条都还没做）。**先红再写实现**，红过才开始 Step 2。

- [ ] **Step 2：写 `Site3DChart.vue`**

创建 `frontend/src/pages/analysis/components/Site3DChart.vue`：

```vue
<!-- frontend/src/pages/analysis/components/Site3DChart.vue
     3D 站点柱阵的薄壳：容器 + useChart(canvas) + 三种降级 + 图下提示条。
     业务计算全在 composables/site3dOption.ts（纯函数，由 T2 钉），这里不写算法。 -->
<template>
  <div class="site3d-chart">
    <el-alert
      v-if="!webglAvailable"
      class="site3d-alert"
      type="warning"
      show-icon
      :closable="false"
      title="当前环境不支持 WebGL，无法显示 3D 站点柱阵；同屏直方图不受影响"
    />
    <el-alert
      v-else-if="!hasSites"
      class="site3d-alert"
      type="info"
      show-icon
      :closable="false"
      title="该文件没有 Site 列，无法进行站点统计"
    />
    <template v-else>
      <div
        ref="chartRef"
        class="site3d-canvas"
        data-site3d-canvas
        role="img"
        :aria-label="`3D 站点柱阵：${siteCount} 个 Site × ${binCount} 个 bin，占比对全站测试次数`"
      />
      <p class="site3d-hint">规格限（LSL/USL）不在 3D 图中绘制，请看同屏直方图</p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
// 副作用式注册：echarts-gl 只有被 import 进来才会把 bar3D/grid3D 注册到同一个 echarts
// 实例上。**少了这一行，option 里写 `type: 'bar3D'` 会静默画不出任何东西**（容器在、
// canvas 在、系列不存在）。必须是**静态**副作用导入：实测 `import('echarts-gl')`/
// `await import('echarts-gl')` 这种动态形态会被 vue-tsc 判 TS7016（该包无 .d.ts，
// 动态导入要推返回值类型），而静态 `import 'x'` 不消费绑定所以干净。
// 本组件自身已经是 defineAsyncComponent 的异步块 ⇒ 这行天然落在同一异步 chunk 里，
// spec §2「冷启动字节不变」仍然成立（分包实测 639,846 B）。
import 'echarts-gl'
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import { applyDefaultView, buildSite3DOption, type Site3DTheme } from '../composables/site3dOption'
import type { OutlierMode } from '../composables/histogramBins'

const props = defineProps<{
  /** histogram 响应的单参数结果（与 HistogramChart 同一份 histResult） */
  result: any
  param: string
  outlierHandling: OutlierMode
  rangeType: string
  /** 面板头图标每点一次 +1：复位走 props-down，不靠 defineExpose（异步组件下 ref 层数不确定） */
  resetEpoch: number
}>()

/**
 * 模块级一次性探测（不进 setup：每个实例都探一次等于每次勾选都建一张 canvas）。
 * 探不到就**不建图**、只出提示——用户 2026-11-04 拍板不做「退化成 2D 分组柱」的第二条
 * 渲染路径，两条路径的口径/主题/tooltip 都要各维护一份，维护成本高于它的价值。
 */
function detectWebGL(): boolean {
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    return false
  }
}
const webglAvailable = detectWebGL()

const { colors, isDark, grid3DTheme } = useEChartsTheme()

const hasSites = computed(() => Object.keys(props.result?.site_histograms ?? {}).length > 0)
const binCount = computed(() => props.result?.bin_centers?.length ?? 0)
const siteCount = computed(() => Object.keys(props.result?.site_histograms ?? {}).length)

function buildOption() {
  const theme: Site3DTheme = { isDark: isDark.value, colors: colors.value, grid3D: grid3DTheme.value }
  // null（无 Site 列）不该走到这里：模板那两条 v-if 已经把容器挡住了
  return buildSite3DOption(props.result, theme, {
    mode: props.outlierHandling,
    rangeType: props.rangeType,
    param: props.param,
  }) ?? {}
}

// 渲染器恒为 canvas：gl 只吃 canvas（不传第 4 参时全局默认是 svg，会被 useChart
// 的 ensureRenderer 判成「渲染器不符」反复 dispose 重建）。主题切换不必自己挂——
// useChart 已 watch themeStore.currentTheme 重渲染。
const { chartRef, chartInstance } = useChart(
  buildOption,
  [() => props.result, () => props.outlierHandling, () => props.rangeType, () => props.param],
  'chartRef',
  () => 'canvas',
)
void chartRef // 绑模板 <div ref="chartRef">（noUnusedLocals 需要显式消费一次）

watch(() => props.resetEpoch, () => applyDefaultView(chartInstance.value))
</script>

<style scoped>
.site3d-chart {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.site3d-canvas {
  flex: 1;
  min-height: 0;
  width: 100%;
}

/* 图下信息条：与 OutlierHintBar 同一族的位置与字号，DOM 侧用 var(--token)（R7①） */
.site3d-hint {
  flex-shrink: 0;
  margin: 4px 0 0;
  padding: 4px 8px;
  font-size: var(--p-fs-dense);
  color: var(--text-3, #9ca3af);
}

.site3d-alert {
  align-self: start;
  margin: 16px;
  height: auto;
}
</style>
```

- [ ] **Step 3：写 `useChartToggles.ts`**

创建 `frontend/src/pages/analysis/composables/useChartToggles.ts`：

```ts
/**
 * 单文件分析的图表勾选（5 张）+ 账号级记忆接线
 * ────────────────────────────────────────────────
 * 从 SingleParamTab.vue 抽出：加第 5 张图时那个文件会越过 600 行硬约束，而这块状态
 * 本身是内聚的一层（5 个 ref + 「勾选集 → dock key 列表」+ 记忆读写互斥）。
 * 套用与上报互斥照原实现：套用期间 watcher 不回写，否则把「恢复」当「用户改动」再存一遍。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { loadChartMemory, saveChartState } from '../../../composables/useChartMemory'
import type { ChartKey } from './useChartDock'

export function useChartToggles() {
  // 直方图默认勾选（2026-09-13 由常驻改为可关闭）；其余默认不勾
  const showHistogram = ref(true)
  const showSerial = ref(false)
  const showQQPlot = ref(false)
  const showBoxPlot = ref(false)
  // 3D 站点柱阵默认不勾：勾上会把 dock 从 4 格挤成 5 格，且首次要下载 gl 分包
  const showSite3D = ref(false)

  // 顺序即 ChartDock 的 reconcile 依据（新增图追加、取消勾选移除，保留其余相对顺序）
  const activeChartKeys = computed<ChartKey[]>(() => {
    const keys: ChartKey[] = []
    if (showHistogram.value) keys.push('hist')
    if (showSerial.value) keys.push('serial')
    if (showQQPlot.value) keys.push('qq')
    if (showBoxPlot.value) keys.push('box')
    if (showSite3D.value) keys.push('site3d')
    return keys
  })
  const anyChartVisible = computed(() => activeChartKeys.value.length > 0)

  /** 面板「×」关闭 → 复位对应勾选（与顶部五个勾选同源） */
  function closeChart(key: ChartKey) {
    if (key === 'hist') showHistogram.value = false
    else if (key === 'serial') showSerial.value = false
    else if (key === 'qq') showQQPlot.value = false
    else if (key === 'box') showBoxPlot.value = false
    else if (key === 'site3d') showSite3D.value = false
  }

  let applying = false
  let touched = false
  watch([showHistogram, showSerial, showQQPlot, showBoxPlot, showSite3D], ([h, s, q, b, d]) => {
    if (applying) return
    touched = true
    saveChartState({ toggles: { hist: h, serial: s, qq: q, box: b, site3d: d } })
  })
  void loadChartMemory().then(({ memoryEnabled, state }) => {
    // 开关关/未加载（null）一律不套用：记忆功能只在明确开启时生效
    if (memoryEnabled !== true || !state.toggles || touched) return
    applying = true
    showHistogram.value = state.toggles.hist
    showSerial.value = state.toggles.serial
    showQQPlot.value = state.toggles.qq
    showBoxPlot.value = state.toggles.box
    showSite3D.value = state.toggles.site3d
    nextTick(() => { applying = false })
  })

  return {
    showHistogram,
    showSerial,
    showQQPlot,
    showBoxPlot,
    showSite3D,
    activeChartKeys,
    anyChartVisible,
    closeChart,
  }
}
```

- [ ] **Step 4：SingleParamTab 接上（删被搬走的、加图体槽与控件槽）**

`frontend/src/pages/analysis/components/SingleParamTab.vue`：

`:227` 的 vue import 改为（`nextTick` 随记忆块一起搬走了，留着会被 `noUnusedLocals` 判红）：

```ts
import { ref, computed, watch } from 'vue'
```

`:258-259` 两行 import 替换为：

```ts
import { useChartToggles } from '../composables/useChartToggles'
const Site3DChart = defineAsyncComponent(() => import('./Site3DChart.vue'))
```
并在 `:227` 的 vue import 里带上 `defineAsyncComponent`（最终这行是 `import { computed, defineAsyncComponent, ref, watch } from 'vue'`）。同时删掉不再使用的 `import { loadChartMemory, saveChartState } ...` 与 `import type { ChartKey } ...`。

删除这些原地段（全部搬进 `useChartToggles.ts`）：
- `:305-306`（`showHistogram`）、`:310-312`（`showSerial`，保留 `:307-309` 的 `serialCol`）、`:396`（`showBoxPlot`）、`:424`（`showQQPlot`）
- `:437-459` 整个 dock 块（`activeChartKeys`/`anyChartVisible`/`onDockClose`）
- `:461-479` 整个「图表勾选账号记忆」块

在 `serialCol` 声明之后加一段等价接线：

```ts
// 五个图表勾选 + 账号记忆都在 useChartToggles（勾选集 → dock 的 active keys）
const {
  showHistogram, showSerial, showQQPlot, showBoxPlot, showSite3D,
  activeChartKeys, anyChartVisible, closeChart,
} = useChartToggles()
// 面板头「回到默认视角」图标每点一次 +1，Site3DChart watch 它做合并式 viewControl 复位
const site3dResetEpoch = ref(0)
```

`:77` 的 `<ChartDock ... @close="onDockClose">` 改为 `@close="closeChart"`。

`#box` 槽之后（`:143` 附近）插入图体槽：

```html
        <template #site3d>
          <Site3DChart
            v-if="histResult"
            :result="histResult"
            :param="localSelectedParam"
            :outlier-handling="outlierHandling"
            :range-type="rangeType"
            :reset-epoch="site3dResetEpoch"
          />
          <el-empty v-else description="3D 柱阵数据加载中" />
        </template>
```

`#controls-box` 槽之后插入控件槽（图标不是文字按钮——用户 2026-11-04 定的控件形态）：

```html
        <!-- 3D 专属控件：只有「回到默认视角」。视角常量单一来源在 site3dOption.ts -->
        <template #controls-site3d>
          <button
            type="button"
            class="site3d-view-reset"
            title="回到默认视角"
            aria-label="回到默认视角"
            @click="site3dResetEpoch++"
          >↺</button>
        </template>
```

`<style scoped>` 里加（slot 内容带父组件 scope，样式必须写在这里而不是子组件，见既有 `.serial-col-selector` 同例）：

```css
/* 面板头的「回到默认视角」：与 ChartPanel 自带 ⤢/× 同尺寸族 */
.site3d-view-reset {
  border: 0;
  background: transparent;
  cursor: pointer;
  color: var(--text-3, #9ca3af);
  font-size: var(--p-fs-base);
  line-height: 1;
  padding: 2px 6px;
  border-radius: 3px;
}
.site3d-view-reset:hover { color: var(--brand); background: color-mix(in srgb, var(--brand) 10%, transparent); }
```

- [ ] **Step 5：确认只用了清单内的 Element Plus 组件**

```bash
npx vitest run test/unit/elementPlusUsage.spec.ts
```
Expected：绿。新组件只用了 `<el-alert>`（清单里已有）。**别在 Site3DChart 里新引 `el-tooltip`/`el-button` 之外的新件**——`elementPlusUsage.spec.ts` 钉的是「src 真实用量逐字等于 `src/constants/element-plus-usage.ts` 清单，双向」，出现新件就要同步登记清单，那是另一件事。

- [ ] **Step 6：600 行闸 + 类型 + 全量 vitest（含 Step 1 的接线绊线转绿）**

```bash
git add src/pages/analysis/components/Site3DChart.vue src/pages/analysis/composables/useChartToggles.ts src/pages/analysis/components/SingleParamTab.vue test/unit/site3dWiring.spec.ts
wc -l src/pages/analysis/components/SingleParamTab.vue src/pages/analysis/components/Site3DChart.vue
npx vue-tsc -p tsconfig.app.json --noEmit && npx vitest run test/unit
```
Expected：`SingleParamTab.vue` ≤ 600、`Site3DChart.vue` ≤ 200；TS 无输出；vitest 全绿——`site3dWiring.spec.ts` 从 Step 1 的红转绿，`lineLimit.spec.ts` 也过（它按 `git ls-files` 扫，所以这条 `git add` 必须在跑它之前）。

- [ ] **Step 7：真机走一遍（本批的核心判据，不看单测就宣称渲染 OK 是假的）**

```bash
npm run dev
```
浏览器打开分析页 → 选 `BN281R3CYCAA_..._STS8200_...CP1_....csv` → 参数选 `Vth` → 勾「显示3D柱状图」。逐项看并记录实际结果：

1. 8 排彩色柱阵出现，**不旋转**就能看出某排峰位偏右（spec §1 的验收判据）；
2. 拖拽转一圈、滚轮缩放：控制台**零报错**（尤其没有 `_updateAxisLabelAlign` 那类 TypeError）；
3. 悬停柱体出 tooltip，文案是 `占比 x.xx%（全站点该 bin n=…）`；
4. 右侧 piecewise 色键的 label 是 `Site1…Site8`，且与柱色一一对上；
5. 面板头点 `↺` → 视角回到默认机位；
6. 点标题栏 `⤢` 最大化再还原，画布尺寸跟随（`useChart` 的 ResizeObserver 在承担）；
7. 切到 night 主题：柱色按 night 色板、轴线/标签不刺眼，`#6b7280` 那格换成 night 的 `#b45309`；
8. 异常值处理选「裁剪范围」：3D 与同屏直方图**消失的 bin 一致**（同一把 `activeBinIndices`）。注意两边轴的行为**有意不同**，别当成口径矛盾去「修」：2D 的数值轴恒按全量 `binCenters` 定 min/max（Limit 线必须留在框内，`outlier-handling.spec.ts:245` 钉着），3D 是 category 轴、被裁的档不进标签，轴宽随可见柱收窄。
9. 取消勾选再勾上：图重建且正常（容器被 v-if 销毁后重挂，R7③）。

任何一条与预期不符 → 先按 `systematic-debugging` 定位再改代码，改完重跑 T2 + 本步。

- [ ] **Step 8：提交**

```bash
git add src/pages/analysis/components/Site3DChart.vue src/pages/analysis/composables/useChartToggles.ts src/pages/analysis/components/SingleParamTab.vue test/unit/site3dWiring.spec.ts
git commit -m "feat(frontend): 3D 站点柱阵上图（异步分包 + canvas 强制 + WebGL/无 Site 降级 + 视角复位），勾选态抽成 useChartToggles"
```

---

## Task 8：e2e 两条不可替代判据（真出图 + night token）

- [ ] **Step 1：`ChartToggleKey` 认得新勾选**

`frontend/e2e/helpers/params.ts:262-267`：

```ts
const CHART_TOGGLE_LABELS = {
  hist: '显示直方图',
  serial: '显示序列分布',
  qq: '显示QQ图',
  box: '显示箱线图',
  site3d: '显示3D柱状图',
} as const
```
> 这条改动的必要性就是那段既有注释说的：勾选是账号级持久的，用例**必须自己声明**要什么状态。`ensureChartToggles` 的类型是 `Partial<Record<ChartToggleKey, boolean>>`，不加这一格就没法收敛 3D 勾选。

- [ ] **Step 2：写 `site3d.spec.ts`**

创建 `frontend/e2e/analysis/site3d.spec.ts`：

```ts
import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParam, ensureChartToggles } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { SEEDED_FILES } from '../fixtures/test-data'

/**
 * 3D 站点柱阵（specs/2026-11-04）。只有两条，且都是 node 层量不到的：
 * ① 真 WebGL 出图（`echarts-gl` 注册失败/渲染器没被强制成 canvas 时，DOM 有容器但没画布；
 *    `expectChartRendered` 那种「svg 优先」的判据在这里会误判，所以按 canvas 实测盒量）；
 * ② night 主题下 grid3D 的轴线/标签确实取 night token（双主题对比度只能看图）。
 * 其余判据（轴型、色键形状、barSize 两分量不相等、机位单一来源、两图同 bin 口径）全在
 * T2：test/unit/site3dOption.spec.ts —— 那里 0.6s，没必要占浏览器单价。
 *
 * 用 STS8200_CP / Vth：8 Site × 26 bin（同 histogram-multiseries-clip.spec.ts 的选型理由）。
 */

const SINGLE = '.single-param-tab'
const HOST = '.chart-panel[data-chart-key="site3d"] [data-site3d-canvas]'

async function enter3D(page: import('@playwright/test').Page) {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, SEEDED_FILES.STS8200_CP)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
  await waitLoadingGone(page.locator(SINGLE))
  // 自己收敛五个勾选：其余图开着会让 `${SINGLE} .chart-container` 这类选择器撞 strict mode，
  // 而勾选是账号级持久的（见 helpers/params.ts 里那段 flake 谱系）
  await ensureChartToggles(page, { hist: true, serial: false, qq: false, box: false, site3d: true })
  const paramSelect = page.locator('.param-selector .el-select')
  const current = await paramSelect.locator('.el-select__placeholder').textContent()
  if (!current?.includes('Vth')) {
    await selectParam(page, 'Vth')
    await waitLoadingGone(page.locator(SINGLE))
  }
  await expect(page.locator(HOST)).toBeVisible({ timeout: 25_000 })
}

/**
 * 读宿主上的 __echartsInstance__。注意 getOption() 会把组件归一成**数组**
 * （grid3D/xAxis3D 都是），所以先 pick 首项再取路径；直接按对象读会静默拿到 undefined。
 */
function grid3DStyleState(page: import('@playwright/test').Page) {
  return page.evaluate((sel) => {
    const dom = document.querySelector(sel) as any
    const opt = dom?.__echartsInstance__?.getOption?.()
    if (!opt) return null
    const pick = (v: any) => (Array.isArray(v) ? v[0] : v)
    const g = pick(opt.grid3D)
    const x = pick(opt.xAxis3D)
    if (!g) return null
    return {
      axisLineShow: g.axisLine?.show ?? null,
      axisColor: g.axisLine?.lineStyle?.color ?? null,
      labelColor: g.axisLabel?.textStyle?.color ?? null,
      nameColor: x?.nameTextStyle?.color ?? null,
    }
  }, HOST)
}

test.describe('@p1 3D 站点柱阵', { tag: ['@p1', '@analysis'] }, () => {
  test('勾选后 dock 出真 WebGL 画布且实测有尺寸', async ({ page }) => {
    await enter3D(page)
    try {
      const host = page.locator(HOST)
      // R2⑤：boundingBox 对空 locator 不是返回 null 而是等满超时后抛错，必须先 count()
      await expect.poll(async () => (await host.locator('canvas').count()), { timeout: 20_000 })
        .toBeGreaterThanOrEqual(1)
      const box = await host.boundingBox()
      expect(box, '3D 宿主应有有效布局尺寸').not.toBeNull()
      expect(box!.width).toBeGreaterThan(100)
      expect(box!.height).toBeGreaterThan(100)

      const stat = await page.evaluate((sel) => {
        const dom = document.querySelector(sel) as any
        const inst = dom?.__echartsInstance__
        const s = inst?.getOption?.()?.series?.find?.((x: any) => x.type === 'bar3D')
        return s ? { count: s.data.length, barSize: s.barSize, shading: s.shading } : null
      }, HOST)
      expect(stat, 'bar3D 系列应完成一次 setOption').not.toBeNull()
      // 8 Site × 26 bin 去掉零占比后仍有大量柱；为 0 就是「容器在但没出图」
      expect(stat!.count).toBeGreaterThan(40)
      expect(stat!.shading).toBe('color')
      // 两个分量各管一个方向且不相等（写成一个 fill 会退回板状截面，§6.3）
      expect(stat!.barSize[0]).not.toBeCloseTo(stat!.barSize[1], 6)
    } finally {
      await ensureChartToggles(page, { site3d: false })
    }
  })

  test('night 主题：grid3D 轴线与标签取 night token', async ({ page }) => {
    await enter3D(page)
    try {
      await page.locator('button.theme-toggle').click()
      await expect(page.locator('html')).toHaveAttribute('data-theme', 'night')
      // 主题切换 → useChart 的 theme watcher 重渲染，轮询到 night 那把值落地
      await expect
        .poll(grid3DStyleState, { timeout: 20_000, message: 'night 主题应重渲染 grid3D 样式' })
        .toEqual({
          axisLineShow: true,
          axisColor: 'rgba(255, 255, 255, 0.04)',
          labelColor: 'rgba(255, 255, 255, 0.76)',
          nameColor: 'rgba(255, 255, 255, 0.76)',
        })
    } finally {
      await ensureChartToggles(page, { site3d: false })
      await page.evaluate(() => {
        document.documentElement.setAttribute('data-theme', 'light')
        localStorage.setItem('theme', 'light')
      })
    }
  })
})
```

> `nameColor` 走 `pick(opt.xAxis3D).nameTextStyle.color`：gl 会把三个轴归一成数组，取径写错就会静默拿到 `undefined`，所以判据是**逐字等于 night 那把 rgba**，不是「有值就行」。形状与预期不符时按 Step 3 的口径改取值路径。

- [ ] **Step 3：e2e 类型 + 单跑两条**

```bash
npm run lint:e2e
npx playwright test analysis/site3d.spec.ts --project=P1 --workers=1
```
Expected：`lint:e2e` 无输出；两条 passed。

两处可能需要按实测形状修正，**都只许改取值路径，不许降断言强度**：
1. `nameColor`/`axisColor` 若拿到 `undefined`，是 `getOption()` 的归一形状与这里预期不同（组件数组、或 gl 把 `lineStyle.color` 存成数组）——把实际对象打出来对着改路径；
2. `selectParam(page, 'Vth')` 走的是 `filter({hasText:'Vth'})` 的 `.first()`，可能落在 `Vth_Post` 上。两条用例都不断言具体参数值，所以无所谓；真要给 3D 定一个确定参数，就改成 `Vth_Post`（与 `histogram-multiseries-clip.spec.ts:90` 同款写法）。

如果 ①红在「面板与宿主都在、但 `canvas` 数恒为 0」，先在同一页执行 `document.createElement('canvas').getContext('webgl2') || document.createElement('canvas').getContext('webgl')` 看是否为 `null`：非 `null` 才是实现问题（多半是渲染器没被强制成 canvas，或 `echarts-gl` 没被真正加载进这一页）；`null` 说明这台机器的测试浏览器走到了 §9 的「不建图 + 提示」分支——**那是产品行为被量出来了，如实报上去，不许为了让用例绿就删断言**。

- [ ] **Step 4：提交**

```bash
git add e2e/helpers/params.ts e2e/analysis/site3d.spec.ts
git commit -m "test(e2e): 3D 柱阵两条不可替代判据（真 WebGL 出图实测盒 + night token 落地）"
```

---

## Task 9：全量门禁收口（本批必然升档，不是可选项）

> `package.json`/`package-lock.json`/`frontend/src/utils/`/`frontend/e2e/helpers/` 四条都命中 GLOBAL（`scripts/affected-rules.mjs:177,194-195`），所以 `test:e2e:affected` 会直接升成全量池档。节奏与判绿口径照 `docs/reference/testing-gates.md` §1。

- [ ] **Step 1：确认工作树只有本批改动（池子没有脏树闸，别把别人的活记到自己账上）**

```bash
git status --porcelain
```
Expected：除 `?? docs/superpowers/specs/2026-11-03-site-ridgeline-design.md`（他人待做稿，**不动不提交**）与 gitignored 的 `tasks/` 外干净。

- [ ] **Step 2：build（R8①：600 行以外的全部类型判据只有这条真跑）**

```bash
mkdir -p tasks/3d-site-barchart
cd frontend && npm run build > ../tasks/3d-site-barchart/build.log 2>&1
grep -aE "error TS|built in|✓ built" ../tasks/3d-site-barchart/build.log | tail -5
```
Expected：无 `error TS`，vite 打出 `✓ built in …`。顺带确认 `dist/assets/` 里出现新的异步分块（gl 在异步 chunk 内，首屏字节不该变）。日志一律先落 `tasks/`（已 gitignore）再 `grep -a`：**不要用 `tail` 直接截门禁输出**——本机栽过三次，失败用例名会连同 `FAIL:` 头一起被截掉，留下一个无法归因的红。

- [ ] **Step 3：build 之后再跑一次 vitest（让首屏 chunk 绊线真承重）**

```bash
cd frontend && npx vitest run test/unit > ../tasks/3d-site-barchart/unit.log 2>&1
grep -aE "Test Files|Tests |FAIL" ../tasks/3d-site-barchart/unit.log
```
Expected：`Test Files  N passed`、无 FAIL。`firstScreenChunks.spec.ts` 只在 `dist/` 存在时承重（缺 dist 它按既有判例显式 skip，不是绿）。日志里那坨 `ReferenceError: localStorage is not defined` 堆栈来自 `localStorageHygiene.spec.ts` 的故意构造，随后仍 `✓`，别当门禁红去归因。

- [ ] **Step 4：affected 门禁（后台跑，输出落文件不用管道）**

```bash
cd frontend && npm --prefix . run test:e2e:affected > ../tasks/3d-site-barchart/gate.log 2>&1
grep -a "FAIL:\|^Ran \|^OK\|^FAILED\|档: \|RESULT: " ../tasks/3d-site-barchart/gate.log
```
Expected：末行 `RESULT: PASS · 计划 N 档全部执行`，各 `档: … ok`。backend 档要求 PATH 上那个 `python` 能 `import pytest`（本机系统 Python 3.13 可以，项目 `.venv` **不行**）⇒ 不要把 `.venv/Scripts` 前置，也不要为它装依赖；`ABORTED` 是门禁坏、不是产品红。

- [ ] **Step 5：收口跑全量并行池（独占机器，跑前查提交内存预算线 8.0GB）**

```bash
cd frontend && node ../scripts/e2e_pool.mjs --slots=4 > ../tasks/3d-site-barchart/pool.log 2>&1
grep -a "文件 \|用例 \|unexpected\|skipped\|结论 \|RESULT: \|slot[0-9] EXIT" ../tasks/3d-site-barchart/pool.log
```
Expected：`unexpected 0`、结论非 `VOID`。基线形状（2026-11-02 实测）文件 80 / 用例 427 / skipped 21 / 墙钟 ~8.1min，本批 +1 文件 +2 用例 ⇒ 81 / 429 附近；每次现算，别拿旧数当判据。已知 flaky：`analysis/wafermap-model-not-found.spec.ts`、`data/file-list-sort-filter.spec.ts`——重试后过属正常，但必须能从 slot 的 `*.results.json` 里报出名字。
若整轮以 `0xC0000409` / `结论 VOID (infra)` 收场：**那一轮不算结论**，先按 PID 认领并清掉崩池留下的孤儿（`manage.py runserver <slot端口> --noreload` 的子进程、`e2e_preview_supervised.mjs`、`vite preview`），只杀门禁时段自己的，用户长期跑着的 dev 后端绝不动，然后重跑。

- [ ] **Step 6：证据落在最终字节上**

```bash
git log --oneline -8
git status --porcelain
```
Expected：9 次提交（Task 1–8 + 收口），工作树只剩他人未跟踪稿。若 Step 4/5 之后又编辑过 `frontend/src/**`，那两轮的证据描述的是旧树 ⇒ 必须重跑。

---

## Task 10：台账收尾（只在真踩了新坑时写）

- [ ] **Step 1：判断有没有值得追加的 lessons**

命中以下任一条就追加 `## 2026-11-04 …` 条目到 `docs/tasks/lessons.md`（**按 CRLF 写**，否则那文件的 diff 变成整文件重写，复审就只能看噪音）；没有就如实说「本批无新坑」，不要为凑数写：

- 发现 spec 里某个「实测值」在新树上不成立（例如 `grid3D` 在 `getOption()` 里的归一形状与本计划预期不同）；
- `bar3D` 与 ECharts 6.1 出现任何注册/渲染层面的意外（例如 `saveAsImage`、tooltip 命中）；
- 类型面有「裸导入未声明模块」的实际行为与 Task 2 Step 3 的预期不符；
- 全量池里出现新形态的 flake。

- [ ] **Step 2：更新 `docs/tasks/todo.md` 的本批条目**（若在跟一批里），进度写「已提交到 `<sha>`，门禁 `<RESULT: PASS>`」。

- [ ] **Step 3：提交（本地，不 push）**

只有 Step 1 或 Step 2 真产生了内容才提交；一条都没有就**跳过本任务**并如实说明「本批无新坑、台账无变化」，不要为凑数造条目。有内容时：

```bash
git add docs/tasks/lessons.md docs/tasks/todo.md
git commit -m "docs(lessons): 3D 站点柱阵批次实测记录（例：gl 组件在 getOption 里归一成数组，T3 取径写法要跟着归一）"
```

---

## 不做的事（防止实现过程中加戏）

- 不改后端任何端点、序列化或分箱逻辑；不加 `site_counts` 之类新字段。
- 不做归一化开关（同一份 `total_count` 分母已经同时承载「量」与「形状」）。
- 不做 WebGL 不可用时「退化成 2D 分组柱」的第二条渲染路径。
- 不做 3D 专属设置面板（截面比例、机位、渐隐固定为实测值）；面板头只有那个不带参数的复位图标。
- 不做多文件分析/相关性 tab 的 3D，不进导出报告。
- 不给 3D 图加 ECharts `toolbox`（gl 画在第二张 canvas，`saveAsImage` 存出来会没有柱体）。
- 不动 `SITE_COLORS_8_LIGHT` 本体、不动 `docs/superpowers/specs/2026-11-03-site-ridgeline-design.md` 与 `tasks/` 下他人目录。
- 不 `git push`。

## 遗留风险（收口时要在结论里如实复述）

「任意角度可读」不承诺：`wFill 0.62 / dFill 0.30` 是在**默认机位 + 一个已知坏角度**（alpha 35 / beta −25）两档实测出来的，用户继续转仍可能落到第三种难看形状。兜底是复位图标 + 同屏 2D 直方图与站点统计表。低配机器 WebGL 落到 SwiftShader 软件渲染那一路只有「不建图 + 提示」这一条分支被量过，上线后需按实际反馈再看。
