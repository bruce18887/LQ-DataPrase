# 批1 实施计划：四个下拉迁 `el-select-v2` + 介绍书图标与 favicon

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让四个大列表下拉（参数 / 对比序列 / 测试列 / 导出参数）能浏览**全部**选项而不冻结主线程，并把介绍书入口图标提亮一档、给介绍书页面补上标签页图标。

**Architecture:** 渲染层从「`el-select` + 截断到 300」换成「`el-select-v2` + 全量数据 + 虚拟窗口」。过滤/排序/映射抽成一份纯函数（T2 承重），高亮改为**只在虚拟窗口内按需计算**（否则回退性能批 `d1146dd`）。e2e 侧把「数 DOM 选项条数」这一类判据换成「从 API 响应取全集」，并把参数列表的捕获点收到 `gotoApp` 一处。图标与 favicon 是两处独立小改，各自带一条判据。

**Tech Stack:** Vue 3.5 + Element Plus **2.14.0**（版本相关判据见下）+ Vite + Playwright + vitest；Django 后端（仅 favicon 路由）；VitePress（介绍书）。

**Spec:** `docs/superpowers/specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md` §2、§3。本计划只覆盖**批1**；批2（磁盘占用）与批3（重复项选保留 + 两页 toolbar）各另起一份计划。

---

## Global Constraints

以下约束绑定每个任务，审查时逐字对照：

1. **测试分层以 `docs/reference/testing-gates.md` 为唯一事实来源。** T1 后端契约（`test/backend/`、`apps/*/tests_*.py`）写全组合；T2 vitest 纯函数（`frontend/test/unit/`，node 环境，**不装 jsdom**）；T3 Playwright（`frontend/e2e/`）只留「只有渲染能证明」的接线。同一判据 T1 与 T3 都能表达时，T1 写全组合、T3 只留一条接线，**不要在浏览器里逐组合点按钮**。
2. **每批 commit 前**：`cd frontend && npm run test:e2e:affected`。每次 commit 前还要 `npx vitest run` + `npm run lint:e2e` + `npm run build`（三条都在 `frontend/` 下）。批1 收口（Task 12）跑仓库根 `node scripts/e2e_pool.mjs --slots=4` + 后端全套。
3. **判绿/红取日志末尾 `RESULT:` 行**（后端取 `OK`/`FAILED` 行），**不取 `$?`**；`NO AFFECTED TESTS` 不等于绿灯。非要用管道就 `| tee` 或 `set -o pipefail`，**不许 `| tail -N`**（那条会把退出码换成 `tail` 的，本仓撞过两次）。
4. **600 行硬约束**：被跟踪的 `.py`/`.ts`/`.vue` 整文件 ≤600 行，`.vue` 按整个 SFC 计（template+script+style）。判据内核 `scripts/line-limit.mjs`，断言 `frontend/test/unit/lineLimit.spec.ts`。本批四个组件现状 281 / 185 / 163 / 179 行，余量充足；新文件 `src/utils/selectOptions.ts` 与 `e2e/helpers/paramList.ts` 也必须 ≤600。
5. **`noUnusedLocals: true`** 在 `tsconfig.app.json:8`、`tsconfig.unit.json:22`、`tsconfig.node.json:18` 都开着（`tsconfig.e2e.json:15` 同）。删了引用就必须删定义，否则 `npm run build` 报 TS6133。
6. **双主题**：一切前端视觉改动 light/night 都必须可读，颜色一律走 CSS 变量（`var(--text)`、`var(--brand)`、`var(--text-2)`…），night 下不得纯黑文字。字号新增受 `e2e/global/fonts.spec.ts` 守门（禁新增硬编码 px 字号，装饰性字号要带 `@type-scale-one-off` 标注）。
7. **EP 版本相关判据**：本计划所有「v2 支持 X / DOM 类名是 Y」的结论都在**已安装的 element-plus 2.14.0** 上实测（源码出处写在各步骤括号里）。升 EP 主版本后这些全部要重量，别当定律。
8. **提交纪律**：逐文件 `git add`（**禁 `git add -A` / `git add .`**）；提交信息从 diff 现读；**不 push**（origin 是公开仓库，push 即全球发布）；不跑 `build.bat`；禁裸 stash。工作目录 = 当前检出 master。
9. **台账**：每个 Task 的实测数字（耗时、条数、计数）当场写进 `docs/tasks/todo.md` 的「批1」条目。lessons 2026-10-24 规则③：「台账里的计数一律现跑再引用」。
10. **e2e 是 ESM**：禁用 `__dirname`；上传型用例 `afterAll` 必须删 DB 行（`deleteFilesByNameQuiet`），只删磁盘临时文件会把残留行按 `-created_at` 顶到 `files[0]` 污染别家用例。
11. **探针产物不留档**：Task 1 的临时探针 spec 跑完即删，**结论写回 spec §2.6 与本计划**，否则等于没跑（lessons R1「磁盘才是事实」）。
12. **不新增文字按钮、不用文字替代图标**（用户定过的规矩：原位、图标、克制；字形语义要唯一、不得与常见功能近形）。

---

## Task 1: ~~探针~~ **已取消 —— 四问并入 Task 5 的 T3 运行**

**为什么取消（2026-11-13 开工前核实的，不是执行中才发现）**：原方案要在 `frontend/e2e/probe/` 下起一个裸 html 最小页驱动 v2。但本仓 e2e 默认起的是 `npm run build && npm run preview`（`frontend/playwright.config.ts:192-198`），**vite preview 只伺服 `dist/`**，`e2e/probe/*.html` 不在其中；而 preview 带 history fallback ⇒ 请求它不会 404，会静默返回 SPA 的 `index.html`。结果就是探针「跑通、打出数字」，量的却是整个应用外壳 —— 这是最坏的一种失败形状（同 lessons 2026-11-11「e2e 跑 Vite 自带 history fallback，覆盖不到 Django URL 层」同族）。

**替代方案（已落到 Task 5）**：四问的答案由「先迁 ParamSelector，再跑它自己的 T3」给出。三条断言恰好就是 Q1/Q2/Q4，窗口行数与耗时在同一次运行里打印。这不牺牲严谨性 —— 量的是**真实产品入口**，比最小页更接近结论。

| 原四问 | 现在由谁回答 |
|---|---|
| Q1 `#footer` 是否渲染、是否在虚拟窗口外 | Task 5 Step 1 第一条断言（footer 可见且文案等于全量数） |
| Q2 `filter-method` 是否真的不过滤 | Task 5 Step 1 第二条（输入关键词后能搜到列表末尾项）+ Task 2 的反向探针 |
| Q3 虚拟窗口 DOM 行数 | Task 5 Step 1.5 打印 `items.count()` |
| Q4 4,570 项首屏与滚到底耗时 | Task 5 Step 1.5 打印两个 `ms` |

**放行条件不变**：Q1 不成立（footer 不渲染）或 Q4 不成立（滚不动/明显卡顿）⇒ 停止本批，回设计。这两条写在 Task 5 Step 1.5 的 Expected 里。

> 源码依据仍然有效且已被直接读过：`select-v2/src/select-dropdown.mjs:160,177`（`#empty`/`#footer` 渲染点）、`useSelect.mjs:114-132`（filter-method 不过滤）、`defaults.mjs:100,107`（`height:274` / `itemHeight:34`）。取消的是「用浏览器复现一遍」的载体，不是核实本身。

---

## Task 2: 抽公共纯函数 `src/utils/selectOptions.ts` + T2 判据

**为什么抽**：四个组件的「过滤 → 排序 → 映射成 `{value,label}`」是同一段逻辑，本次要重写全部四处。不抽就是写四份新副本（比现状更糟）。**只抽纯函数，不抽 composable** —— 三个多选器的 Enter 全选/`clamp`/聚焦时机各有差异，那些 glue 留在各组件里，别为了 DRY 把它们焊成一套。

**Files:**
- Create: `frontend/src/utils/selectOptions.ts`
- Test: `frontend/test/unit/selectOptions.spec.ts`

- [ ] **Step 1: 写失败的测试**

Create `frontend/test/unit/selectOptions.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import {
  buildParamOptions,
  filterByKeyword,
  highlightSegments,
  sortPrefixFirst,
  toOptions,
} from '../../src/utils/selectOptions'

describe('toOptions', () => {
  it('字符串与数字都映射成 {value,label}，label 一律是字符串', () => {
    expect(toOptions(['A', 'B'])).toEqual([
      { value: 'A', label: 'A' },
      { value: 'B', label: 'B' },
    ])
    expect(toOptions([1, 2])).toEqual([
      { value: 1, label: '1' },
      { value: 2, label: '2' },
    ])
  })

  // el-select-v2 的 useProps.mjs:25-28 走 lodash.get(option,'label'|'value')，
  // 喂 string[] 是「静默空白行」。这条钉住映射不会退化。
  it('反向探针：产出项必须同时带 value 与 label 两个键', () => {
    for (const o of toOptions(['X'])) {
      expect(Object.keys(o).sort()).toEqual(['label', 'value'])
    }
  })
})

describe('filterByKeyword', () => {
  it('大小写不敏感子串匹配', () => {
    expect(filterByKeyword(['Kelvin_VIN', 'IBLK'], 'kel')).toEqual(['Kelvin_VIN'])
  })
  it('空关键词返回原集合（不复制、不改序）', () => {
    const items = ['B', 'A']
    expect(filterByKeyword(items, '')).toEqual(['B', 'A'])
  })
})

describe('sortPrefixFirst', () => {
  it('前缀匹配排在前面，其余按 localeCompare', () => {
    expect(sortPrefixFirst(['XPAR1', 'PAR1', 'APAR1'], 'par1')).toEqual(['PAR1', 'APAR1', 'XPAR1'])
  })
  it('不改动入参数组（排序必须在新数组上做）', () => {
    const items = ['b', 'a']
    sortPrefixFirst(items, '')
    expect(items).toEqual(['b', 'a'])
  })
})

describe('highlightSegments', () => {
  it('命中片段标 mark=true，且大小写不敏感', () => {
    expect(highlightSegments('Kelvin_VIN', 'kelvin')).toEqual([
      { text: 'Kelvin', mark: true },
      { text: '_VIN', mark: false },
    ])
  })
  it('多处命中全部标出，顺序与原文一致', () => {
    expect(highlightSegments('AxAxA', 'ax').map((s) => s.text).join('')).toBe('AxAxA')
  })
  it('空关键词返回单个不标亮的整段', () => {
    expect(highlightSegments('ABC', '')).toEqual([{ text: 'ABC', mark: false }])
  })
  // ParamSelector.vue:145-149 记的 XSS 修复：不走 v-html，列名里的尖括号必须是字面文本。
  it('反向探针：列名含 HTML 片段时仍是字面文本，绝不产出标签', () => {
    const evil = '<img src=x onerror=alert(1)>'
    const segs = highlightSegments(evil, 'img')
    expect(segs.map((s) => s.text).join('')).toBe(evil)
    expect(JSON.stringify(segs)).not.toMatch(/<img/)
    expect(segs.some((s) => s.mark && s.text === 'img')).toBe(true)
  })
  it('正则元字符不需要转义（子串匹配，非正则）', () => {
    expect(highlightSegments('V+(1)', '+(').map((s) => s.mark)).toEqual([false, true, false])
  })
})

describe('buildParamOptions', () => {
  it('无关键词：保持原顺序，total = 全量长度', () => {
    const r = buildParamOptions(['B', 'A', 'C'], '')
    expect(r.options.map((o) => o.value)).toEqual(['B', 'A', 'C'])
    expect(r.total).toBe(3)
  })
  it('有关键词：过滤 + 前缀优先，total = 匹配数而不是渲染数', () => {
    const r = buildParamOptions(['XPAR1', 'PAR1', 'OTHER'], 'par1')
    expect(r.options.map((o) => o.value)).toEqual(['PAR1', 'XPAR1'])
    expect(r.total).toBe(2)
  })
  // 这条是「高亮按需」的承重判据：options 里一旦出现 segments 字段，
  // 就等于把 ParamSelector.vue:97-99 注释里 d1146dd 治掉的「每次击键建 N 份」放回来。
  it('反向探针：options 只带 value/label，**不得**预建高亮片段', () => {
    const r = buildParamOptions(['PAR1', 'PAR2'], 'par')
    for (const o of r.options) {
      expect(Object.keys(o).sort()).toEqual(['label', 'value'])
    }
  })
  it('4570 项量级：total 是全量，且没有渲染截断', () => {
    const many = Array.from({ length: 4570 }, (_, i) => `P${i}`)
    const r = buildParamOptions(many, '')
    expect(r.total).toBe(4570)
    expect(r.options.length).toBe(4570)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run test/unit/selectOptions.spec.ts`
Expected: FAIL —— `Cannot find module '../../src/utils/selectOptions'`（或等价的解析失败）。

- [ ] **Step 3: 写实现**

Create `frontend/src/utils/selectOptions.ts`：

```ts
/**
 * 大列表下拉（`el-select-v2`）的选项准备：过滤 → 排序 → 映射。
 *
 * 为什么必须有这份文件：`el-select-v2` 的 `filter-method` 在 2.14.0 里**退化成纯回调**
 * （`useSelect.mjs:114-132` 判到 filterMethod 合法后让 `isValidOption` 恒 true ⇒
 * `filteredOptions` = 全量 `props.options`），组件自己不过滤。所以过滤必须由调用方算好
 * 塞进 `:options`。而 `:options` 的元素必须是对象（`useProps.mjs:25-28` 走
 * `lodash.get(option,'label'|'value')`），喂 `string[]` 是静默空白行。
 *
 * 高亮片段**不在这里算**：它由组件在 v2 的 `#default` 逐条渲染器里按需调用
 * `highlightSegments`（虚拟窗口每帧只渲染约 8 行）。若在准备 options 时就给每一项建
 * segments，等于把性能批 d1146dd 治掉的「1,702 项每次击键建 1,702 份」原样放回来
 * —— `test/unit/selectOptions.spec.ts` 里那条反向探针就是拦这个的。
 */

export interface SelectOption {
  value: string | number
  label: string
}

export interface ParamSegment {
  text: string
  mark: boolean
}

/** 映射成 `el-select-v2` 要求的 `{value,label}` 形状 */
export function toOptions(items: Array<string | number>): SelectOption[] {
  return items.map((value) => ({ value, label: String(value) }))
}

/** 大小写不敏感子串匹配；空关键词返回原集合 */
export function filterByKeyword(items: string[], keyword: string): string[] {
  if (!keyword) return items
  return items.filter((it) => it.toLowerCase().includes(keyword))
}

/** 前缀匹配优先，其余按 localeCompare。返回新数组，不改入参。 */
export function sortPrefixFirst(items: string[], keyword: string): string[] {
  return [...items].sort((a, b) => {
    const aStarts = a.toLowerCase().startsWith(keyword)
    const bStarts = b.toLowerCase().startsWith(keyword)
    if (aStarts && !bStarts) return -1
    if (!aStarts && bStarts) return 1
    return a.localeCompare(b)
  })
}

/**
 * 高亮分段：返回 {text, mark} 片段列表。
 *
 * 不走 v-html：参数名来自上传文件的列头（用户可控输入），旧实现对 text 未转义，
 * 列名含 `<img src=x onerror=...>` 即成存储型 XSS，普通 `<`/`&` 也会被当标签/实体
 * 吞掉导致下拉显示错乱。大小写不敏感子串匹配与旧 `gi` 正则高亮等价，
 * 且无正则元字符转义问题。（本段说明从 ParamSelector.vue:145-149 原样搬来，
 * 搬动原因是 Serial/TestColumn/Export 三处也需要同一条判据的注释锚点。）
 */
export function highlightSegments(text: string, query: string): ParamSegment[] {
  if (!query) return [{ text, mark: false }]
  const lower = text.toLowerCase()
  const q = query.toLowerCase()
  const segments: ParamSegment[] = []
  let i = 0
  while (i < text.length) {
    const idx = lower.indexOf(q, i)
    if (idx === -1) {
      segments.push({ text: text.slice(i), mark: false })
      break
    }
    if (idx > i) segments.push({ text: text.slice(i, idx), mark: false })
    segments.push({ text: text.slice(idx, idx + q.length), mark: true })
    i = idx + q.length
  }
  return segments
}

/**
 * 参数下拉的完整视图：`options` 交给 `:options`，`total` 交给 footer 计数。
 *
 * 顺序是「过滤 → 排序 → 映射」，**没有截断步骤**（截断是旧 DROPDOWN_RENDER_CAP 的做法，
 * 本批删除）。排序必须留在映射之前：`el-select-v2` 按数组顺序渲染，映射后再排要重建对象。
 */
export function buildParamOptions(
  params: string[],
  query: string,
): { options: SelectOption[]; total: number } {
  const kw = query.trim().toLowerCase()
  const matched = filterByKeyword(params, kw)
  const ordered = kw ? sortPrefixFirst(matched, kw) : matched
  return { options: toOptions(ordered), total: matched.length }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run test/unit/selectOptions.spec.ts`
Expected: PASS，13 条（`toOptions` 3 / `filterByKeyword` 2 / `sortPrefixFirst` 2 / `highlightSegments` 5 / `buildParamOptions` 4 —— 数一下实际 `it` 数，台账写实测值）。

- [ ] **Step 5: 变异探针（证明反向断言真的承重）**

临时把 `buildParamOptions` 的返回改成 `{ options: ordered.map(v => ({ value: v, label: String(v), segments: highlightSegments(v, kw) })), total: matched.length }`，再跑：

Run: `cd frontend && npx vitest run test/unit/selectOptions.spec.ts`
Expected: FAIL —— 「options 只带 value/label」那条红。
然后**改回去**，再跑一次确认 PASS。**不许用 `git checkout --` 回滚**（工作树里可能有别人的改动），手工改回或 `Edit` 还原。

- [ ] **Step 6: 全量 vitest + 提交**

Run: `cd frontend && npx vitest run`
Expected: 全绿，文件数与例数各比基线 +1（基线见 `docs/reference/testing-gates.md` §2 的 T2 那行，**现跑取实际值**写进台账）。

```bash
git add frontend/src/utils/selectOptions.ts frontend/test/unit/selectOptions.spec.ts
git commit -m "feat(dropdown): 抽 selectOptions 纯函数（过滤/前缀排序/按需高亮片段），为迁 el-select-v2 铺路"
```

---

## Task 3: 注册 `ElSelectV2` —— **已取消，整体并入 Task 5 的那一次提交**

**为什么取消（2026-11-13 实现者判 BLOCKED 后核实，不是执行者能力问题，是计划错了）**：原计划把「先注册」排在「改组件」之前，动机是怕 Task 5 一写 `<el-select-v2>` 就因未注册而渲染不出。但 `frontend/test/unit/elementPlusUsage.spec.ts` 钉的是**三方双向逐字相等**：

```
真实 src 的 <el-*> 用量  ↔  EP_TEMPLATE_COMPONENTS 常量  ↔  installables 表
```

实测 `grep -rl "<el-select-v2" frontend/src --include=*.vue` = 0 命中（首个 `<el-select-v2>` 要到 Task 5 才出现）⇒ Task 3 单独落地时：加常量则 `:139` 红（清单里多一件没人用的），不加常量只加注册则 `:174` 红。**两种组合都不可达绿。** 而该绊线的注释原话就是「这里多列一件没人用的 → 也红」——它是设计意图，不是 bug。所以「先注册后迁移」在这个仓的顺序前提本来就不成立。

**并进去之后还要带的两处计划漏项**：

1. **第四处注册点**：`frontend/src/plugins/element-plus.ts` 除 import 块（:60）与 `installables`（:170）外，还有第三张**样式入口表**（:76-129，`import 'element-plus/es/components/select/style/css'` 在 :117）。`elementPlusUsage.spec.ts:182/:186` 把 `styled` 与「模板+服务式+指令」全集逐字比对（49+2+1=52 ⇒ 加 v2 是 53），不补 `import 'element-plus/es/components/select-v2/style/css'` 就直接红。**Step 5 原本担心的「样式没挂上要到生产构建才炸」其实就是这一行。**
2. **判据自身的盲区**：`elementPlusUsage.spec.ts:211-223` 的 `pluginLists()` 两条解析正则 `/^\s+(El[A-Z][A-Za-z]*),$/gm` 与 `/\b(El[A-Z][A-Za-z]*)\b/g` **不接受数字** ⇒ 模板里写了 `ElSelectV2,` 它也抓不到，`:174` 会红在「清单有、解析没有」。而同文件 `:29` 的 TAG 正则已经是 `[A-Za-z0-9]*` —— 即这两条解析正则与该文件自己的命名文法不一致。**两条必须一起放宽**，否则 `:178` 的 `notImported` 换成红在 `ElSelectV2` 上。这是通用修正，不只对本批有用。

**顺带要订正的陈旧计数（注释与 `it` 标题，不是断言，不影响判绿，但不订正就是「标题承诺了但没断言」那一类）**：`elementPlusUsage.spec.ts:171`「模板 49 件」、`:182`「52 件」、`element-plus.ts:131`「模板里的 49 个标签」、`e2e/theme/element-plus-styles.spec.ts:111`「模板 49 + 服务式 2 + 指令 1」。

**已静态核算过、不需要动的地方**（实现者实测，Task 5 收口时复核）：`e2e/theme/element-plus-styles.spec.ts:328` 的 `expect(fingerprints.length).toBe(46)` 与 `:325` 的 `NO_OWN_STYLE` 都从常量推导；`theme-chalk/el-select-v2.css` 存在且与 `el-select.css` **md5 相同**（`3b0587227aa8053c4b78d7def58a2d0f`）、首个类都是 `el-select-dropdown` ⇒ 去重后仍 46。**这条 md5 相同也是「v2 不需要新增主题变量」的依据**，若将来 EP 升级后两者不再相同，本批的「只提亮颜色不改主题」前提要重审。

**留给 Task 8/12 的一条**：Task 5-8 迁完后 `'option'` / `'option-group'` 是否仍在清单里，取决于剩下那些仍用 `<el-select>`/`<el-option>` 的页面（实测 10 个 `.vue` 用 `<el-select`，本批只迁 4 个下拉）⇒ `:147` 的最终计数在 Task 8 之后可能要再动一次。**Task 12 收口时必须现跑一次 `npx vitest run test/unit/elementPlusUsage.spec.ts` 并按实际值订正，不要沿用 Task 5 写的 50。**

---

## Task 4: e2e helper——参数全集改从响应取，popper 判据改 `aria-hidden`

**这是本批最容易做错的一个 Task。** 虚拟化后 `listParams()` 再数 DOM 只会拿到约 8 项，而它有两个消费者靠「完整列表」承重：`selectParamWithSpecLimits()`（逐个试参数直到找到有真实规格限的）与 `chart-filter-switches` 的 `listParams().length` 族。

**为什么改从响应取而不是滚动收集**：`useTabFileParams.ts:79-87` 本来就用一次**不带 `params`** 的 `POST /analysis/histogram/` 拿全部参数名（`Object.keys(data.results)`）。响应就是产品自己的数据源，比在浏览器里滚虚拟列表凑全集确定得多；仓内也已有先例（`e2e/exports/exports.spec.ts:540-544` 的注释明写「改从响应 `results` 键取全集、不数 DOM option」）。

**Files:**
- Create: `frontend/e2e/helpers/paramList.ts`
- Modify: `frontend/e2e/helpers/nav.ts:7-11`
- Modify: `frontend/e2e/helpers/params.ts:24-27`（`visibleOptions`）、`:107-114`（`listParams`）
- Test: `frontend/test/unit/e2eAffectedDecide.spec.ts` 之外**无新增单测**（helper 属 T3 通路）

- [ ] **Step 1: 写捕获 helper**

Create `frontend/e2e/helpers/paramList.ts`：

```ts
import type { Page } from '@playwright/test'

/**
 * 参数全集的捕获器。
 *
 * 为什么需要：迁 `el-select-v2` 后 DOM 里只有虚拟窗口那约 8 行，
 * 「数 `.el-select-dropdown__item` 条数」不再等于「列表有多少项」。
 * 而产品自己拿全集的路径就在那儿 —— `useTabFileParams.ts:79-87` 发一次
 * **不带 `params`** 的 POST /analysis/histogram/，用 `Object.keys(results)` 当参数全集。
 * 本 helper 挂同一个响应，取同一个键，判据与实现异源（DOM 是渲染，响应是数据源）。
 *
 * 过滤条件与前端逐字一致（`p && p.trim() !== ''`）：后端 `analysis_views.py:139`
 * 回的是 `{p: {} for p in params}`，脏列名在前端就被丢掉，捕获侧不能把它放回来。
 */
const captured = new WeakMap<Page, string[]>()
const installed = new WeakSet<Page>()

/** 在 page 上装一次响应监听。必须在导航**之前**装，否则错过首次列表请求。 */
export function attachParamListCapture(page: Page): void {
  if (installed.has(page)) return
  installed.add(page)
  page.on('response', (response) => {
    void (async () => {
      const req = response.request()
      if (!response.url().includes('/analysis/histogram/')) return
      if (req.method() !== 'POST') return
      // 带 params 的是「算某参数」的请求，其 results 只有被算的那几项，不是全集
      const body = req.postData() ?? ''
      if (body.includes('"params"')) return
      if (response.status() !== 200) return
      try {
        const json = (await response.json()) as { results?: Record<string, unknown> }
        const keys = Object.keys(json?.results ?? {}).filter((p) => p && p.trim() !== '')
        if (keys.length > 0) captured.set(page, keys)
      } catch {
        /* 非 JSON / 响应已销毁：保持上一次捕获值，不抛 */
      }
    })()
  })
}

/**
 * 取捕获到的参数全集（保持后端返回顺序）。
 * 空数组意味着监听装晚了或还没选文件 —— 调用方必须显式失败，不能当「列表真的为空」。
 */
export function capturedParamList(page: Page): string[] {
  return captured.get(page) ?? []
}
```

- [ ] **Step 2: 在 `gotoApp` 里装监听（一处覆盖 82 个调用文件）**

Modify `frontend/e2e/helpers/nav.ts`：

```ts
import { expect, type Page } from '@playwright/test'

import { attachParamListCapture } from './paramList'

/**
 * 导航到指定业务路由并等待主布局就绪。
 * 适用于已注入 storageState（已登录）的用例。
 */
export async function gotoApp(page: Page, route: string) {
  // 必须在 goto 之前装：参数全集那次请求发生在首屏选文件时，装晚了就永远捕不到，
  // 而 listParams() 会静默返回空数组（见 paramList.ts 的注释）。
  attachParamListCapture(page)
  await page.goto(route)
  // 主布局容器出现即认为进入应用（未登录会被守卫重定向到 /login）
  await expect(page.locator('.main-layout')).toBeVisible({ timeout: 15_000 })
}
```

- [ ] **Step 3: 改 `visibleOptions` 的 popper 判据**

Modify `frontend/e2e/helpers/params.ts` 的 `visibleOptions`（现 :24-27）：

```ts
/**
 * 当前**开着的那个**下拉里的选项。
 *
 * 不能用 `:visible`：EP 收起下拉走 Vue 的 leave 过渡，`display:none` 要等动画结束才落下，
 * 而 `aria-hidden` 绑在 visible 上、同一拍就翻成 true ⇒ 过渡帧里 `:visible` 数到的是
 * 正在退出的上一个（连 `toHaveCount(1)` 再取也照样挑中它）。2026-11-10 账号审计批实测，
 * 红字是「每页条数候选收到 10 项而不是 3 项」这种毫不相干的形状。
 * popper-class 同时挂在外层 .el-popper 与内层 .el-select-dropdown 上，
 * 所以限定必须落在外层 .el-popper（裸类名会 strict violation）。
 */
function visibleOptions(page: Page, popperClass?: string) {
  const cls = popperClass ? `.el-popper.${popperClass}` : '.el-popper'
  return page.locator(`${cls}[aria-hidden="false"] .el-select-dropdown__item`)
}
```

同批把 `pickTabFile`（:81）、`pickOutlierMode`（:95）、`pickSensitivity`（:102）里手写的 `.dp-xxx-popper-…:visible .el-select-dropdown__item` 三处换成同一形状：

```ts
const options = page.locator(
  `.el-popper.dp-file-picker-${scope}[aria-hidden="false"] .el-select-dropdown__item`,
)
```

- [ ] **Step 4: `listParams` 改成从捕获器取**

Modify `frontend/e2e/helpers/params.ts` 的 `listParams`（现 :107-114）：

```ts
/**
 * 分析页当前文件的**全部**参数名（后端返回顺序）。
 *
 * 旧实现是「打开下拉 → 数 DOM 选项 → Escape」，在 `el-select` 时代等于全集（因为渲染被
 * 截断到 300，而测试文件都少于 300 项）；迁 `el-select-v2` 后 DOM 只有虚拟窗口那约 8 行，
 * 数 DOM 就不再是「列表有多少项」的判据。改成读产品取全集用的同一次响应（见 paramList.ts）。
 */
export async function listParams(page: Page): Promise<string[]> {
  const list = capturedParamList(page)
  expect(
    list.length,
    '参数全集未捕获：监听在 gotoApp 里装，用例必须在选完文件后再调用本函数',
  ).toBeGreaterThan(0)
  return list
}
```

并在文件顶部 import 区加：

```ts
import { capturedParamList } from './paramList'
```

- [ ] **Step 5: 跑受影响 helper 的两条用例，证明没把绿的改红**

Run: `cd frontend && npx playwright test e2e/analysis/histogram-fail-bins.spec.ts e2e/analysis/multi-file.spec.ts --project=P1 --reporter=list`
Expected: 全绿。**注意 SFTP 类用例必须带 `--project=P1`**，否则被 Edge project 的 `grepInvert` 静默跳过（假绿，`testing-gates.md` §5）。

- [ ] **Step 6: `lint:e2e`（e2e 不在 build 的 include 覆盖内，死 import 只有这条能发现）**

Run: `cd frontend && npm run lint:e2e`
Expected: 无错误。

- [ ] **Step 7: 提交**

```bash
git add frontend/e2e/helpers/paramList.ts frontend/e2e/helpers/nav.ts frontend/e2e/helpers/params.ts
git commit -m "test(e2e): 参数全集改从 histogram 无 params 响应取；下拉可见性认 aria-hidden"
```

---

### Task 4 落地后对计划的三处订正（2026-11-13，实现者判 DONE_WITH_CONCERNS 后控制器核实采纳）

上面 Step 1/4 写的形状**在本仓真实数据上会造出两种真 flake**，实现者加了守卫才收敛。控制器独立核实其证据后**采纳偏离** —— 本节是新的权威形状，Step 1/4 的旧代码块按此读。

**订正 1：捕获回写要带请求序号（采纳）**。计划版 handler 是 `await response.json()` 之后直接 `captured.set` —— 两个快路径响应的 json resolve 顺序**不保证**，旧文件（41 列）的晚 resolve 会把新文件（180 列）的列表回写覆盖掉。实现者实测：`outlier-handling:346` 首跑红、retry 绿。
补守卫时先试了 `Request.timestamp()` —— **Node 版 Playwright 没有这个 API**（Python 版才有），因此 16 条全红；最终改成在 `request` 事件上自打序号（发出顺序严格单调），镜像产品侧 `useTabFileParams.ts:60,85` 的 `mySeq/loadSeq` 守卫。**这条要记住**：不能假定仓内既有等待形状对应的 Playwright API 存在，先探针（lessons「没用过的 API 先跑探针」在 e2e 侧同样成立）。

**订正 2：`listParams` 必须自己等「新文件的列表已落地」（采纳）**。旧 DOM 版里 `options.first()` 那 15s 可见等待**顺带**承担了「新文件的列表响应已处理完」这一步；改成纯读捕获后这一步消失了 —— `pickTabFileAndWaitCompute` 等的是计算**请求发出**（首发带旧参数会 400，且早于列表响应处理完成），于是 `allParams` 读到上一个文件的 41 项当全量基线，Fail 收缩后的 80 项反而「不少于全量」。实现者实测：`chart-filter-switches:71` 红。
修法两条：`capturedParamList` 只在「捕获所属 `file_id` == 最后一次快路径请求的 `file_id`」时给值；`listParams` 用 `expect.poll(15s)` 补回那一步等待。**这不是「为兼容而做一次无谓的下拉开合」**（Task 4 任务书里警告过的那种），是数据源侧的真判据。

**订正 3：`maxTries` 语义变化目前不可观测**。`selectParamWithSpecLimits` 的 `slice(0, maxTries)` 从「渲染出的前 N 个」变成「全集里前 N 个」，但本仓**没有 >300 参数的测试夹具**（实测 DA35 是 180 参数：`found=Kelvin_VIN tried=9 of total=180 ms=18538`），新旧列表一致、试的个数与耗时同量级。⇒ 计划里「这条变化要靠收口全量池兜住」暂时无的放矢；**若将来引入 >300 参数的夹具，必须回来看这条**。

**转给后续 Task 的两项**：
- `frontend/e2e/helpers/elplus.ts:16` 的 `visibleSelectOptions` 仍是 `:visible`，同一「过渡帧挑中上一个 popper」的风险在这条通路上原样存在（`file-correlation` 等 8+ 文件在用）。**并入 Task 6**（相关性页正是 SerialSelector 的落点），不要留到 Task 12。
- `pickTabFile` 上方注释里「隐藏 pane 的那一份仍会被全局 `:visible` 命中」的措辞在新判据下已过时（作用域限定本身仍然必要）。**并入 Task 9**（组件改完、注释集中收敛时一起改）。

**一条被核实为假的前提，记录以免重复提出**：有人提议「迁 v2 后 `SerialSelector` 在 loading 期间会渲染 `#empty` 显示『无匹配序列』，而 v1 显示『加载中』，所以要补 `#loading` slot」。
**不成立**：v1 的 `select/src/select2.mjs:343-346` 是 `renderSlot($slots,"empty", {}, () => [span emptyText])` —— `#empty` slot **本来就优先于** `emptyText`，后者只是兜底。v2 的 `select-v2/src/select-dropdown.mjs:160` 是 `slots.loading?.() || slots.empty?.()`，两侧同样被我们提供的 `#empty` 抢先。⇒ **v1 与 v2 行为逐字相同，不存在迁移回归。**
真实情况是另一件事：**「加载期间显示『无匹配序列』」是本批之前就存在的文案错位**（把「还没拿到」说成「查过了没有」，与 `AuditLogPage.vue:52-55` 那条「失败不能写成空态」同类）。改它要新增用户可见文案，属独立工单，不在批1。提案留档在 `tasks/2026-11-13-loading-slot-proposal.patch`。

---

### Task 4 复审后的第二轮订正（2026-11-13，commit `0590002` + `c986c2c`）

复审判 ❌，最关键的一条是：**`RESULT: PASS` 掩盖了两条恒真断言**。守卫从「比 `file_id`」升级成「比 `seq` + 显式结算态」后才闭合，判定逻辑同时下沉成可注入纯核 `frontend/e2e/helpers/paramListCore.ts`（零 Playwright），配 39 例 T2（`frontend/test/unit/paramListGuard.spec.ts`）—— 原来这两条竞态守卫只由 e2e 全量池兜，是 `testing-gates.md` 里最贵的一档，且回归症状毫无可读性。

**① 「比 file_id」不够，实测复现**：同 `file_id=1`、body 加 `only_fail_test_item:true` 后 `lastFast` 已推进到新 seq，但 `fileId` 相等 ⇒ 旧守卫放行 ⇒ 返回**上一个口径**的列表，且 `poll(length>0)` 一次都不等。后端确认这是真实形状：`analysis_views.py:91-140` 的快路径 `params` 由 `ignore_no_limit` / `filter_test_items(...)` / `filter_bin1_rows` 逐层决定，`column_profile.py:83-107` 在行收窄后**再筛一次空列**；`useTabFileParams.ts:131-133` → `scheduleRefresh`（250ms 防抖）→ `:79` 重发快路径时 **file_id 不变、seq 变**。⇒ 后续任何「按 file_id 判定列表是否新鲜」的想法都要走这条证据。

**② 空结果集必须能表达**。旧 `keys.length > 0` 那道拒写空集的闸与 `status() !== 200` 功能冗余（400 体没有 `results`，keys 必空），而它让「当前口径真的返回 0 项」被静默报告成上一口径的全量 —— 与 `chart-filter-switches.spec.ts:114` 注释「可能为空集——允许为空但请求必须正确」直接契约冲突。现在任何快路径响应（200/4xx/5xx、含 0 项、json 解析失败）都落一条捕获，「已结算」与「非空」彻底分开。

**③ `aria-hidden` 那条判据的机理，先前记错了 —— 这条影响整批的 e2e 约定**（真 `/analysis` 页，Escape 关参数下拉后逐帧采样）：

```
Escape+0ms    aria-hidden=false  display=block  ariaFalsePoppers=2  items=87
Escape+30ms   aria-hidden=false  display=block  ariaFalsePoppers=2  items=267
Escape+80ms   aria-hidden=false  display=block  ariaFalsePoppers=2  items=267
Escape+160ms  aria-hidden=true   display=none   ariaFalsePoppers=0  items=0
```

⇒ **`aria-hidden` 与 `display` 是同一拍翻转的**（EP 源码 `ariaHidden` 只在 `onAfterLeave` 翻回 true：`tooltip/src/content.vue_…_lang.mjs:46-50,108`），两者都在约 150ms 的 `el-zoom-in-top-leave-*` 窗口内保持「还开着」。**不带 popperClass 时 `[aria-hidden="false"]` 与 `:visible` 给的是同一个 267，完全等价、并不更安全。** 真正起作用的是 `.el-popper.<popperClass>` 的**每实例限定**。
后果与处置：`visibleOptions` 的 `popperClass` 已改成**必填**（可选分支就是那个等价于旧 bug 的形状）；机理注释按实测重写，并点名 `file-correlation.spec.ts:31` 的 `waitForTimeout(600)` 作窗口量级的仓内旁证。
⚠ **这条与项目记忆里的一条既有结论冲突**：记忆条目「Element Plus e2e 定位器陷阱」第 ③ 条把 `.el-popper[aria-hidden="false"] .el-select-dropdown` 记成 `:visible` 的正解。按本次实测，那个 flake 真正被修掉靠的是 popper 实例限定，不是 `aria-hidden`。**批3 的两页 admin 改造会直接引用这条约定**（`audit.spec.ts` 里「每页条数候选」那族），所以批3 开工前要先把记忆条目按实测订正，否则会把同一个坑再抄一遍。

**④ I-4 的核实结论：三个 tab 里两个无法从请求体分辨**。`SingleParamTab.vue:321-333` 与 `CorrelationToolsTab.vue:200-216` 的 `filters()` 键集**逐字相同**，产品不在请求里留 tab 身份 ⇒ 单文件↔相关性没有可靠判据，改用显式声明 `setActiveAnalysisTab(page, scope)`（必须在点 tab **之前**调）；晶圆图可以自动分辨（`WaferMapPanel.vue:105-109` 拉列表不传 filters），由 `resolveScope()` 承担，**前提若变（晶圆图开始传 filters）这条必须删**。
**残留缺口（已知、未修）**：漏声明或声明晚了不会静默给脏值（读不到就 15s 超时并在消息里点名该调哪个声明），但防不住「勾选单文件开关后 250ms 防抖还没发、用例已切到相关性并声明」这种跨切 tab 的错位。根因在产品侧没有 tab 身份 —— 要真修得给快路径请求加一个来源标识，属独立工单。

**⑤ 光补守卫不足以让那两条断言有牙**（实现者的发现，复审没说到）：勾选开关后列表那一发是 250ms 防抖后才离开浏览器，`lastFast` 还停在旧口径时 `listParams` 返回旧口径**是正确行为**，比较仍是自己比自己。修法是在勾选**之前**注册一次**不带 params 的快路径** `waitForResponse`（同文件 `:88-103` 的既有范式），让「新口径那一发已发出且已响应」成为读列表的前提。⇒ **凡是「改筛选 → 读列表 → 比前后」的用例，都必须先等那一发快路径**，这条要写进批3 的 e2e 约定。

**⑥ 内联 `:visible` 的完整清点（批末专项，不在本批）**：helper 层已统一，但 spec 内联仍有 **15 个文件 38 处**活的内联 `.el-select-dropdown__item:visible`（2026-11-14 批1 收口现跑：`git grep -hE "\.el-select-dropdown__item:visible" HEAD -- frontend/e2e | grep -vE '^[[:space:]]*(//|\*|/\*)' | wc -l`；分布 `outlier-handling` 14、`analysis.spec` 4、`data.spec` 3、`multi-file` 3、`custom-limit-cpk` 3、`view-data` 2，余 9 个文件各 1 处，含 helper 侧 `elplus.ts` 1 + `colfilter.ts` 1）。**订正：原稿那句「19 个文件 48 处」和「view-data 12」都不成立** —— 同一条命令在 master 上是 **39 处**（48 是初稿估的），`view-data.spec.ts` 在 master 就只剔注释 2 处、本批后仍 2 处 ⇒ 本批对这一族的净变化是**减 1 处**，没有"顺手清掉十个"。另有 `colfilter.ts:13,18,22` 三处（其中 `:22` 是**无 popperClass** 的那个等价于旧 bug 的形状），被 `data.spec.ts` / `file-list-sort-filter.spec.ts` 共 13 处调用。最刺眼的是同一份 spec 内两套判据并存：`outlier-handling.spec.ts:175,178,199` 用裸 `:visible` 点异常值处理下拉，而 `pickOutlierMode` 已经是 aria-hidden+popperClass。
**为什么本批不动它们**：这些下拉选出来的都是小的固定候选集（RowDataLimit / 裁剪范围 / 3 Sigma / 按 Bin 分组），不在本批四个被虚拟化的组件里 ⇒ 虚拟化不会打红它们，属判据一致性问题而非本批回归。**留一个专项**：统一成 `visibleOptions(page, popperClass)` 的形态，并把 `popperClass` 必填这条推广到所有 helper。

**⑦ Task 4 的验证覆盖面（如实记）**：`npm run test:e2e:affected` 在干净工作树下只比 `HEAD~1..HEAD`，而 Task 4 分两个 commit ⇒ 实跑那一轮**没把 `frontend/e2e/helpers/` 算进改动集**。用 `--base HEAD~2 --dry-run` 核过：两个 commit 一起看时判定是 `decide: 全量 e2e（兜底命中）`。**Task 12 收口的全量池必须覆盖这条**，不能沿用 Task 4 那轮的 PASS。

---

## Task 5: `ParamSelector.vue` 迁 `el-select-v2`（含高亮按需 + footer 计数）

**Files:**
- Modify: `frontend/src/pages/analysis/components/ParamSelector.vue`（281 行）
- Modify: `frontend/src/plugins/element-plus.ts`（import 块 :60 / 样式入口表 :117 区 / `installables` :170）
- Modify: `frontend/src/constants/element-plus-usage.ts`（`EP_TEMPLATE_COMPONENTS`，`'select'` 在 :56）
- Modify: `frontend/test/unit/elementPlusUsage.spec.ts`（计数 :147、`pluginLists()` 两条正则 :211-223、注释 :171 与标题 :182）
- Modify: `frontend/e2e/theme/element-plus-styles.spec.ts`（注释 :111 的计数；断言不动，见 Step 0.4）
- Modify: `frontend/test/unit/selectOptions.spec.ts`（承接 Task 2 复审遗留的 1 条 Important + 1 条 Minor）
- Modify: `frontend/test/unit/e2eAffectedDecide.spec.ts`（承接 Task 2 复审的 1 条 Minor）
- Test: `frontend/e2e/analysis/param-dropdown-full-list.spec.ts`（新建，T3 接线）

> **本 Task 承接原 Task 3 的全部注册工作**（原因见 Task 3 一节：三方逐字相等的绊线让「先注册、后迁移」在任何只改注册文件的组合下都不可达绿）。注册与**首个** `<el-select-v2>` 必须同一个 commit 落地。

**从 Task 2 回环复审转来的三项（Task 5 必须一并落，否则就是「说了但没人出资」）**：

- **[I-1 真判据] 跨函数不变量「过滤命中 ⇒ 必高亮」目前没有断言钉住。** Task 2 只在两侧各钉了归一化单测，缺的是组合本身。在 `describe('buildParamOptions')` 里补一条：

```ts
  // I-1 的真判据：过滤侧与高亮侧共用同一归一化契约 ⇒ 凡被 buildParamOptions 放行的项，
  // 用同一个原始 query 去算高亮必须至少命中一段。两侧各自 trim 不等于二者一致。
  it('不变量：被过滤命中的每一项，高亮必命中至少一段', () => {
    const params = ['PAR1', 'OTHER', 'A B', 'a  b', 'Kelvin_VIN', 'IBLK', 'V+(1)', 'XPAR1', 'P AR', 'par1x', '']
    for (const query of ['  ', 'par', 'PAR ', ' a b ', 'kelvin', '+(', 'P AR', 'XPAR1 ', 'PAR1', 'A', '']) {
      const { options } = buildParamOptions(params, query)
      for (const o of options) {
        const segs = highlightSegments(String(o.label), query)
        expect(segs.map((s) => s.text).join(''), `拼接无损: ${query}/${o.label}`).toBe(o.label)
        if (query.trim()) {
          expect(
            segs.some((s) => s.mark),
            `过滤命中但高亮没命中: query=${JSON.stringify(query)} label=${o.label}`,
          ).toBe(true)
        }
      }
    }
  })
```

  落地前先证明它**不是空转**：临时把 `highlightSegments` 的 `query.trim().toLowerCase()` 改回 `query.toLowerCase()` ⇒ 这条必须红（Task 2 的那条单侧断言也会红，两者都算证据）；手工改回 ⇒ 绿。

- **[锚点] `selectOptions.spec.ts:91` 与 `:116` 用 `ParamSelector.vue:145-149` / `:97-99` 这种**行号**锚点，而本 Task Step 3 会删掉那些行 ⇒ 锚点届时指向错的位置。** 在本 Task 里把这两处改写成符号+提交锚点（`ParamSelector 的 highlightSegments 历史实现 / 提交 d1146dd`），与 `selectOptions.ts:69` 已采用的范式一致。

- **[门禁形状判据] `e2eAffectedDecide.spec.ts:193-195` 的形状扫描过滤条件是「处置恰为 `['unit']`」**，会放过 `['frontend/src/utils/', ['unit', 'none:理由']]` 这种带 note 的目录级放行（本表其它处的合法写法）。改成按首元素判：`Array.isArray(mods) && mods[0] === 'unit'`。行为探针仍兜得住，这条只是把纵深补全。改完跑到红（用一次刻意造的坏形状变异）再改回。

- [ ] **Step 0.1: 先放宽解析正则，并钉住它**

`frontend/test/unit/elementPlusUsage.spec.ts` 的 `pluginLists()`（:211-223）两条解析正则**不接受数字**：

```
installed: /^\s+(El[A-Z][A-Za-z]*),$/gm
imported:  /\b(El[A-Z][A-Za-z]*)\b/g
```

`ElSelectV2` 是 EP 里少数带数字的导出名 ⇒ 模板里写了它也解析不出来，`:174` 会红成「清单写了、解析没解析出来」这种看起来像产品坏了的形状。而同文件 `:29` 的 TAG 正则已经是 `[A-Za-z0-9]*` —— 这两条解析正则与该文件自己的命名文法不一致。**两条必须一起放宽**，只放宽一条的话 `:178` 的 `notImported` 换成红在 `ElSelectV2` 上。

改成：

```ts
  installed: /^\s+(El[A-Z][A-Za-z0-9]*),$/gm,
  imported: /\b(El[A-Z][A-Za-z0-9]*)\b/g,
```

补一条 T2 断言，钉住「数字后缀能被解析」：

```ts
  // ElSelectV2 是 EP 里少数带数字的导出名。旧正则 [A-Z][A-Za-z]* 抓不到它 ⇒
  // 注册写了、判据看不见。两条一起放宽才有意义（见 pluginLists 的注释）。
  it('解析正则认数字后缀：ElSelectV2 同时被 imported 与 installed 抓到', () => {
    const source = [
      'import { ElSelect, ElSelectV2 } from "element-plus"',
      'const installables = [',
      '  ElSelect,',
      '  ElSelectV2,',
      ']',
    ].join('\n')
    const lists = parsePluginListsFrom(source)
    expect(lists.imported).toContain('ElSelectV2')
    expect(lists.installed).toContain('ElSelectV2')
  })
```

`pluginLists()` 现在直接读文件、无参数。为让上面这条能喂字符串，把解析体拆成**纯函数 `parsePluginListsFrom(source: string)` + 一层读文件的壳**（壳仍叫 `pluginLists()`，行为逐字不变）。这是本 Task 唯一允许的判据文件重构，且必须保持既有 10 条断言语义不变。**若拆分过程中任何既有断言的行为发生变化，停下来报告，不要为了写这条测试而改了判据本身。**

**判别力证明**：临时把任一条正则改回 `[A-Za-z]*` ⇒ 新断言必须红；手工改回（禁 `git checkout --` / `git restore` / `git stash`）⇒ 绿。贴两次汇总行原文。

- [ ] **Step 0.2: 常量 + 注册三张表**

- `frontend/src/constants/element-plus-usage.ts`：`EP_TEMPLATE_COMPONENTS` 加 `'select-v2'`。该表**是字典序**（`'select' < 'select-v2' < 'skeleton'` 成立），插在 `'select'` 之后即符合既有排序。
- `frontend/src/plugins/element-plus.ts` 三处，位置都紧跟 `select` 的对应条目：
  - import 块（:60 区）加 `ElSelectV2,`
  - **样式入口表**（:117 区，第三张表，Task 3 原计划漏掉的那处）加 `import 'element-plus/es/components/select-v2/style/css'`
  - `installables`（:170 区）加 `ElSelectV2,`

Run: `cd frontend && ls node_modules/element-plus/es/components/select-v2/style/css.mjs`
Expected: 存在。

- [ ] **Step 0.3: 计数与陈旧注释一起订正**

- `elementPlusUsage.spec.ts:147` `toBe(49)` → `toBe(50)`
- `elementPlusUsage.spec.ts:171` 注释「模板 49 件」→ 50；`:182` 标题「52 件」→ 53（49+2+1=52 ⇒ 加 v2 是 53）
- `element-plus.ts:131` 注释「模板里的 49 个标签」→ 50
- `e2e/theme/element-plus-styles.spec.ts:111` 注释「模板 49 + 服务式 2 + 指令 1」→ 50 + 2 + 1

Run: `cd frontend && npx vitest run test/unit/elementPlusUsage.spec.ts`
Expected: **11 条全绿**（三方逐字相等此刻才同时成立，因为 Step 3 会真的往模板写 `<el-select-v2>`）。
⚠ 若在 Step 3 之前跑，`:139`「真实 src 的模板用量逐字等于清单」必红 —— 那是**预期的中间态**，不要为了让它绿而把 `<el-select-v2>` 提前塞进别的文件，也不要在这一步回退常量。正确做法是把 Step 0.1-0.3 与 Step 2-3 当作一次原子改动，只在 Step 5/6 之后统一验证与提交。

- [ ] **Step 0.4: 复核主题侧不需要动**

`e2e/theme/element-plus-styles.spec.ts:328` 的 `toBe(46)` 与 `:325` 的 `NO_OWN_STYLE` 都从常量推导。已静态核算：`theme-chalk/el-select-v2.css` 与 `el-select.css` **md5 相同**（`3b0587227aa8053c4b78d7def58a2d0f`）、首个类都是 `el-select-dropdown` ⇒ 去重后仍 46，这也是「v2 不需要新增主题变量」的依据。

Run: `cd frontend && md5sum node_modules/element-plus/theme-chalk/el-select-v2.css node_modules/element-plus/theme-chalk/el-select.css`
Expected: 两个 md5 相同。**不同就停下来报告** —— 那意味着 v2 有独立样式，spec §3.1「只提亮颜色不改主题」的前提要重审。

- [ ] **Step 1: 写失败的 T3 用例**

Create `frontend/e2e/analysis/param-dropdown-full-list.spec.ts`：

```ts
import { expect, test } from '@playwright/test'

import { gotoApp } from '../../helpers/nav'
import { capturedParamList } from '../../helpers/paramList'
import { selectAnalysisFile, selectParam } from '../../helpers/params'

/**
 * 用户报的原话是「参数选择框为啥只能看前 300 个测试项」。旧实现是 `el-select` +
 * `DROPDOWN_RENDER_CAP=300` 的显式截断（EP 2.14 的 el-select 不虚拟化，每个 el-option
 * 是完整组件实例，原样挂载即冻结主线程）。本批换成 `el-select-v2` 的虚拟窗口。
 *
 * 三条判据各挡一种回退：
 *  - footer 的「共 N 项」：挡「把截断偷偷放回来」（截断后 N 仍等于全量，所以这条要配合下一条）
 *  - 搜到列表末尾那一项并选中：挡「只渲染前 N，后面的搜不到」
 *  - 滚到底后末尾项出现在 DOM：挡「虚拟窗口没生效 / 滚不动」
 */
test.describe('参数下拉可浏览全部测试项', () => {
  test.use({ storageState: 'e2e/.auth/admin.json' })

  test.beforeEach(async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page)
  })

  test('footer 说出全集规模，且没有「仅显示前 N」这句话', async ({ page }) => {
    const sel = page.locator('.param-selector .el-select')
    await sel.click()
    const footer = page.locator('.el-popper.dp-param-popper-single[aria-hidden="false"] .param-count-hint')
    await expect(footer).toBeVisible()
    await expect(footer).not.toContainText('仅显示前')

    const total = Number((await footer.innerText()).replace(/\D/g, ''))
    const captured = capturedParamList(page).length
    expect(total, 'footer 的「共 N 项」必须等于响应里的参数数').toBe(captured)
  })

  test('搜到列表最后一项并选中它', async ({ page }) => {
    const all = capturedParamList(page)
    const last = all[all.length - 1]
    await selectParam(page, last)
    await expect(page.locator('.param-selector .el-select')).toContainText(last)
  })

  test('不输入关键词时滚到底能看见最后一项', async ({ page }) => {
    const all = capturedParamList(page)
    const last = all[all.length - 1]
    const items = page.locator(
      '.el-popper.dp-param-popper-single[aria-hidden="false"] .el-select-dropdown__item',
    )
    await page.locator('.param-selector .el-select').click()
    await expect(items.first()).toBeVisible({ timeout: 15_000 })

    // 只断言「窗口装不下全集」才有意义：全集 ≤ 窗口行数时这条用例不承重
    test.skip(all.length <= 20, '当前夹具参数太少，测不出虚拟窗口')

    await items.first().hover()
    await page.mouse.wheel(0, 200_000)
    await expect(items.filter({ hasText: last }).first()).toBeVisible({ timeout: 10_000 })
  })
})
```

Run: `cd frontend && npx playwright test e2e/analysis/param-dropdown-full-list.spec.ts --project=P1 --reporter=list`
Expected: FAIL —— 第一条断 `footer` 可见会超时（现在 class 叫 `.param-cap-hint` 且文案含「仅显示前 300」）。**先把失败形状记进台账**（它证明判据抓得住）。

- [ ] **Step 1.5: 把原探针的 Q3/Q4 打印临时加进第三条用例（迁完即摘）**

在 Step 1 第三条用例的 `await page.mouse.wheel(0, 200_000)` 前后各插一段计时与计数，**只打印不断言**：

```ts
    console.log('PROBE-Q3-dom-window-rows', await items.count())
    const t0 = Date.now()
    await items.first().hover()
    await page.mouse.wheel(0, 200_000)
    console.log('PROBE-Q4-scroll-to-end-ms', Date.now() - t0)
```

Run: `cd frontend && npx playwright test e2e/analysis/param-dropdown-full-list.spec.ts --project=P1 --reporter=list`
Expected: 组件未迁，此时应当**红**（`.param-count-hint` 不存在）。红没关系 —— 这一步的目的是确认打印通路接上了；真正读数在 Step 5。

**放行判据（Step 5 跑出来后逐条对照，任一不成立就停下回设计，不要继续 Task 6-9）**：
- `PROBE-Q3-dom-window-rows` 是个**小常数**（约 8–12，对应 `defaults.mjs:100,107` 的 `height:274 / itemHeight:34`）而不是全量数 ⇒ 证明虚拟化生效。若它等于全集条数，说明 `el-select-v2` 没虚拟窗口，本批前提不成立。
- `PROBE-Q4-scroll-to-end-ms` 远小于 1000ms，且第三条用例最终可见末尾项 ⇒ 证明上万项滚得动。
- 第一条用例的 footer 断言通过 ⇒ 证明 `#footer` 在窗口外仍渲染（原 Q1）。

- [ ] **Step 2: 改 template**

Modify `frontend/src/pages/analysis/components/ParamSelector.vue` 的 `<template>`（现 :1-53）：

```vue
<template>
  <div class="param-selector" :class="{ 'param-selector--inline': inline }">
    <div class="selector-label">选择参数 (↑↓ 切换)</div>
    <el-select-v2
      :model-value="selectedParam"
      :options="options"
      placeholder="输入搜索或选择参数..."
      filterable
      clearable
      size="small"
      :style="inline ? 'width: 260px' : 'width: 100%'"
      :filter-method="filterMethod"
      :popper-class="popperClass"
      @change="onParamChange"
      @visible-change="onVisibleChange"
    >
      <!-- 高亮片段**在这里**算，不是在 computed 里：`el-select-v2` 的 #default 是逐条
           渲染器，虚拟窗口每帧只调用约 8 次。旧写法在 listView 里给每个匹配项预建
           segments 数组，那是性能批 d1146dd 治掉的东西（原注释：1,702 项的文件上每次
           击键建 1,702 份），全量渲染后放回来就是原样回退。 -->
      <template #default="{ item }">
        <div class="param-option">
          <span class="param-name">
            <span
              v-for="(seg, i) in segmentsFor(String(item.value))"
              :key="i"
              :class="{ 'param-name__hit': seg.mark }"
            >{{ seg.text }}</span>
          </span>
        </div>
      </template>
      <template #footer>
        <!-- 封顶取消了，但「一共多少项」仍然要说：用户需要知道自己在看的不是残缺列表 -->
        <div class="param-count-hint">共 {{ total }} 项</div>
      </template>
    </el-select-v2>
    <div class="nav-buttons">
      <el-button :disabled="params.length === 0" size="small" @click="onPrev">
        ◀ 上一个
      </el-button>
      <el-button :disabled="params.length === 0" size="small" @click="onNext">
        下一个 ▶
      </el-button>
    </div>
  </div>
</template>
```

- [ ] **Step 3: 改 script**

Modify `<script setup>`：删 `DROPDOWN_RENDER_CAP` import、删 `ParamItem`/`ParamSegment` 本地 interface、删 `allItems`/`filteredItems`/`capped`、删 `getParamHint`（**它唯一的消费者是 template 里那段被注释掉的 `param-hint` span，本批一并删；留着会被 `noUnusedLocals` 判 TS6133**）、删 `highlightSegments`（搬进 utils）。改成：

```ts
<script setup lang="ts">
import { computed, ref } from 'vue'

import { buildParamOptions, highlightSegments } from '../../../utils/selectOptions'

const props = withDefaults(defineProps<{
  params: string[]
  selectedParam: string
  /** teleport 到 body 的下拉面板**实例级** class：ParamSelector 在单文件 tab
   * （非 lazy 常驻）与多文件 tab 各挂一个，同名 popper 会让隐藏 pane 的面板
   * 参与全局可见性查询——reference 零尺寸导致 popper 逐帧重定位、
   * `.first()` 误点另一个 tab 的选项（lessons 2026-09-05） */
  popperClass?: string
  /** inline：横向单行（label + select + 上下一个），用于单文件 tab 顶部冻结行；
      默认纵向堆叠（多文件 tab 的 top-bar 布局不变） */
  inline?: boolean
}>(), { popperClass: 'dp-param-popper-single', inline: false })

const emit = defineEmits<{
  'update:selectedParam': [value: string]
}>()

const filterText = ref('')

/** 视图 = 过滤 → 前缀优先排序 → {value,label} 映射；无截断（见 utils 的注释） */
const view = computed(() => buildParamOptions(props.params, filterText.value))
const options = computed(() => view.value.options)
const total = computed(() => view.value.total)

/** 由 #default 逐条渲染器调用 ⇒ 只对虚拟窗口内的项计算 */
function segmentsFor(name: string) {
  return highlightSegments(name, filterText.value)
}

/**
 * `el-select-v2` 的 filter-method 在 2.14.0 里**不过滤**，只是回调
 * （`useSelect.mjs:114-132`）。这里只记关键词，过滤由上面的 `view` 承担。
 */
function filterMethod(query: string) {
  filterText.value = query
}

/** 下拉框关闭时清空过滤 */
function onVisibleChange(visible: boolean) {
  if (!visible) filterText.value = ''
}

function onParamChange(val: string) {
  emit('update:selectedParam', val)
}

/** ◀上一个/下一个▶：推进逻辑只有这一份（父组件曾经还有一份同逻辑副本，
 *  与这里的 emit 叠成「点一次跳两项」，2026-10-17 删掉）。 */
function onPrev() {
  const idx = props.params.indexOf(props.selectedParam)
  if (idx > 0) {
    emit('update:selectedParam', props.params[idx - 1])
  } else if (props.params.length > 0) {
    emit('update:selectedParam', props.params[props.params.length - 1])
  }
}

function onNext() {
  const idx = props.params.indexOf(props.selectedParam)
  if (idx < props.params.length - 1) {
    emit('update:selectedParam', props.params[idx + 1])
  } else if (props.params.length > 0) {
    emit('update:selectedParam', props.params[0])
  }
}
</script>
```

- [ ] **Step 4: 改 style**

`<style scoped>` 里把 `.param-cap-hint` 选择器改名 `.param-count-hint`（内容不变：`font-size: var(--p-fs-micro); color: var(--text-2); text-align: center;`），删掉不再存在的 `.param-hint` 那一段（:268-273）。其余不动。

- [ ] **Step 5: 跑 T3 与 build**

Run: `cd frontend && npx playwright test e2e/analysis/param-dropdown-full-list.spec.ts --project=P1 --reporter=list`
Expected: 3 passed（第三条若被 `test.skip` 跳过，说明夹具参数 ≤20，**必须换夹具而不是删用例** —— 记进台账）。同时读出 Step 1.5 的两个 `PROBE-` 值，逐条对照那里的放行判据；**放行后才继续 Task 6**。

Run: `cd frontend && grep -n "PROBE-" e2e/analysis/param-dropdown-full-list.spec.ts`
Expected: 放行判据核对完就把这几行打印删掉（`console.log` 留在套件里会让全量池的日志变脏，且它们不是判据）。删完重跑一次确认仍 3 passed。

Run: `cd frontend && npm run build`
Expected: 无新增 TS 错误（`getParamHint` 若忘删，这里报 TS6133）。

- [ ] **Step 6: 跑 ParamSelector 的既有消费者，证明没改坏**

Run: `cd frontend && npx playwright test e2e/analysis/histogram-fail-bins.spec.ts e2e/analysis/histogram-multiseries-clip.spec.ts e2e/analysis/multi-file.spec.ts e2e/analysis/toolbar-sticky.spec.ts --project=P1 --reporter=list`
Expected: 全绿。若红在 `.el-select` 定位上，先确认 v2 的根类名仍是 `.el-select`（Task 1 探针已量）；红在「数选项」上则回到 Task 4 的 helper。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/pages/analysis/components/ParamSelector.vue frontend/e2e/analysis/param-dropdown-full-list.spec.ts
git commit -m "feat(analysis): 参数下拉迁 el-select-v2，高亮改虚拟窗口内按需计算"
```

---

## Task 5 落地后的订正（**Task 6-9 开工前必读**，2026-11-13）

实际落地是 4 个提交，不是一个：`243dff4`（迁移 + 注册）→ `8650885`（规格复审修复）→
`35450af`（质量复审修复）→ `a0728d4`（补 `35450af` 漏删的半条判据）。上面 Step 7 那段
`git add` 只列了 2 个文件，真实范围是 10 个（注册三张表 + 两份绊线判据 + 两份 helper 注释
+ 新 T3 + 组件）。**Step 7 的提交清单作废，以 `git log` 为准。**

放行判据核对结果（Step 1.5 要求的三条，全部成立）：虚拟窗口 DOM **11 行**、滚到底 **310ms**、
`#footer` 在窗口外仍渲染。footer 逐字 = 「共 1723 项」（夹具现测 1723 个参数）。

后面四个 Task 会照抄 Task 5 的模板，以下 6 条与本文正文不同，**以这里为准**：

1. **`#default` 里算分段用 `item.label`，不是 `item.value`**（正文 Step 2 的示例写的是
   `String(item.value)`）。EP 自己的兜底渲染的就是 `getLabel(item)`
   （`select-v2/src/select-dropdown.mjs:110`）；Task 6 的序列号一旦有展示名（label≠value），
   照抄 `value` 会高亮一段屏幕上不存在的文本。
2. **`filterByKeyword` / `sortPrefixFirst` 已加宽到 `Array<string | number>`**（Task 2 原文
   是 `string[]`）。`SerialSelector` 的候选本来就是 `number[]`，直接传，别再 `map(String)`
   一遍；`sortPrefixFirst` 走的是字符串序（`'1' < '12' < '2'`），与 v2 实际显示的 label 一致。
3. **popper 身份串从 `e2e/helpers/params.ts` 导入了**：`PARAM_POPPER_SINGLE`。新用例不要再
   内联 `'dp-param-popper-*'` 字面量；多文件实例的 `dp-param-popper-multi` 暂无导出，用到再补。
4. **可见性谓词统一 `.el-popper.<cls>[aria-hidden="false"]`**，不要写 `:not([aria-hidden="true"])`。
   同一个判据两套写法，将来 EP 改绑定方式时只会红一半，根因看不出来。
5. **footer 文案的分歧记在案，Task 9 收口时一并拍板**：ParamSelector 用「共 N 项」，
   Task 6/7/8 正文一律写「匹配 N 项」，现存三个未迁组件也都是「匹配 N 项」。
   ParamSelector 搜索态显示的也是命中数，却写着「共」—— 既是歧义也是同族不一致。
   本批不在此处改（改一次要动一条 T3 精确匹配判据），Task 9 删 `DROPDOWN_RENDER_CAP` 时统一。
6. **`buildParamOptions` 这个名字为唯一消费者写窄了**（签名对四个下拉通用）。复审建议改叫
   `buildSelectView`，但 Task 6/7/8 正文都按现名引用，**本批不改名**，同样并进 Task 9。

另记两条已核清、不必再查的事实：`theme-chalk/el-select-v2.css` 与 `el-select.css` **md5 逐字
相同**（`3b0587227aa8053c4b78d7def58a2d0f`，所以主题侧 46 个指纹不变）；EP 里 `select/src/` 与
`select-v2/src/` **各有** `useSelect.mjs`，写锚点必须带目录前缀。

---

## Task 6: `SerialSelector.vue` 迁 v2（multiple + Enter 全选 + `clamp`）

**Files:**
- Modify: `frontend/src/pages/data/components/correlation/SerialSelector.vue`（185 行）
- Test: `frontend/e2e/data/file-correlation.spec.ts`（:190-199、:208/213 两条）

- [ ] **Step 1: 改 template**

`el-select` → `el-select-v2`，`el-option` 循环换成 `:options`，footer 文案去掉「显示前 N」：

```vue
    <el-select-v2
      ref="selectRef"
      :model-value="modelValue"
      :options="selectOptions"
      multiple
      filterable
      automatic-dropdown
      placeholder="搜索序列号"
      collapse-tags
      collapse-tags-tooltip
      class="seri-select"
      aria-label="对比序列"
      :loading="loading"
      :disabled="options.length === 0"
      :multiple-limit="MAX_SELECTED"
      :filter-method="filterMethod"
      @update:model-value="$emit('update:modelValue', clamp($event))"
      @keydown.capture="onSelectKeydown"
      @visible-change="onVisibleChange"
    >
      <template #empty>
        <div class="empty-hint">无匹配序列</div>
      </template>
      <template #footer>
        <div v-if="kw" class="match-hint">匹配 {{ matches.length }} 项，按 Enter 全选</div>
      </template>
    </el-select-v2>
```

> **命名冲突必须处理**：这个组件的 props 里已经有一个 `options: number[]`（:59）。若把新的 computed 也叫 `options`，模板里 `:options="options"` 会指向 computed，而 `:disabled="options.length === 0"` 就从「有没有序列」变成「过滤后有没有匹配项」——**空关键词时恰好等价，所以这个 bug 在正常路径上看不出来**，只在「搜一个不存在的序列号」时把整个控件禁掉。统一把 computed 命名为 `selectOptions`，props 侧一律不加 `props.` 前缀。Task 6/7/8 三个组件同此约定。

- [ ] **Step 2: 改 script**

删 `DROPDOWN_RENDER_CAP` import，`filteredItems` 换成映射后的全量：

```ts
import { computed, nextTick, ref } from 'vue'
import { toOptions } from '../../../../utils/selectOptions'

/* … MAX_SELECTED / filterText / selectRef / kw / matches 保持原样 … */

/**
 * 下拉选项 = 匹配集（有关键词）或全量（无关键词），**不截断**。
 * `el-select-v2` 的 filter-method 不过滤（useSelect.mjs:114-132），所以这里必须给
 * 已经过滤好的数组；虚拟化让上万条序列可浏览，靠 300 封顶那段注释（:71）作废。
 */
const selectOptions = computed(() => toOptions(kw.value ? matches.value : props.options))
```

`clamp` / `filterMethod` / `onSelectKeydown` / `clearFilterInput` / `onVisibleChange` / `selectAll` / `clearAll` / `selectMatches` **全部保持不动** —— 它们操作的是 `props`/emit 而不是 DOM，虚拟化不影响（spec §2.3 已核）。`:71` 那句「渲染封顶值取 constants/dropdown」的注释删掉。

- [ ] **Step 3: 跑相关性用例**

Run: `cd frontend && npx playwright test e2e/data/file-correlation.spec.ts --project=P1 --reporter=list`
Expected: 全绿。红在 `.match-hint` 计数或 Enter 上时，先确认 footer 在窗口外仍渲染（Task 1 的 Q1 结论）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/pages/data/components/correlation/SerialSelector.vue
git commit -m "feat(correlation): 对比序列下拉迁 el-select-v2，取消 300 项渲染封顶"
```

---

## Task 6 落地后的订正（**Task 7/8 开工前必读**，2026-11-13）

落地 = `19a1232`（迁移）+ `883753a`（删掉控制器给错的零消费者可选参数）+ `c9e0d67`（合并复审的修复）。

1. **`--project` 按被测文件里**每条用例自己的 tag** 选，别照抄本计划的 `--project=P1`。**
   `e2e/data/file-correlation.spec.ts` 的 describe 是 `tag: ['@p2','@data']` ⇒ P1 项目下
   `No tests found`，正解 `--project=P2`（10 条 = 8 业务 + 2 setup）。
   ⚠ **本条原稿说 `view-data.spec.ts` 归 Edge —— 是控制器写错的，Task 7 实现方实测反驳**：
   Edge 项目是 `grepInvert: /@p[012]/`（`playwright.config.ts:124`），而该文件**用例标题自带
   `@pN`** ⇒ `--project=Edge` 只选中 1 条。条数一律现跑（`npx playwright test e2e/data/view-data.spec.ts
   --project=P1 --list`，数 `[P1]` 行；setup 那 2 条每个项目都会带进来，别算进业务数）：
   2026-11-14 收口实跑 = 业务 **36 条**（Edge 1 / P0 1 / P1 14 / P2 20），原稿记的「35 条、p1×13、
   合跑 36（34 业务 + 2 setup）」是 Task 9C 新增那条千列用例**之前**的账。
   **Task 8 的 `exports.spec.ts`：tag 在 describe 上（4 处 `['@p2','@exports']`）⇒ 归 P2。**
   跑之前一律先 `--list` 数一遍，别按 describe 的 tag 猜项目。
2. **`filterByKeyword` 现在是泛型** `<T extends string | number>(items: T[], keyword: string): T[]`。
   泛型不是装饰：`SerialSelector` 把返回值原样喂给 `clamp()` 与 `emit('update:modelValue', …: number[])`，
   非泛型签名在那两处都要重新断言一次。`sortPrefixFirst` 仍是 `Array<string|number>`（没人用它保类型）。
3. **「Enter 全选匹配」这一族的 `matches` 空关键词一支必须自己给 `[]`**，形如
   `kw.value ? filterByKeyword(props.options, filterText.value) : []`。
   `filterByKeyword` 空串返回**入参本身**（全量，那是它自己的引用契约），透传会把「没输入」
   变成「全匹配」⇒ footer 冒出「按 Enter 全选」，且 Enter 从「选中键盘高亮那一项」变成
   「全选上千颗」。本计划正文没写这一点，Task 7/8 的组件形状相同，照这条做。
4. **命名陷阱（computed 与 `options` prop 撞名）现在有判据了**，在
   `e2e/data/file-correlation.spec.ts:274-300`：搜一个匹配不到的串 ⇒ 断 `.el-select__wrapper`
   **没有** `is-disabled`。**但这条钉的是 `:disabled="options.length === 0"` 这个具体形状，
   是相关性页专属** —— Task 7/8 别复制粘贴，先读自己组件的 disabled 语义再决定要不要同类判据。
   `is-disabled` 的落点是 EP 2.14 的 `.el-select__wrapper`（`select-v2/src/select.mjs:55-61`），
   写在 `.el-select` 根节点上会**恒绿**。
5. **序列 / 测试项 / 导出这三族没有「虚拟窗口真生效、第 301 项够得着」的正向判据**，这是**已知
   且被接受**的债（设计稿 §7 验收第 1 条只点名参数下拉）。收口方式定在 **Task 9**，且要最省：
   把 `param-dropdown-full-list.spec.ts` 的 `tailRowState` 与 `MAX_WINDOW_ROWS` 提到
   `e2e/helpers/selectV2.ts`，在既有多族用例里各加 1 条 `items.count() < 20` + 1 条 footer 逐字；
   **不新建 spec、不新建夹具**（现在给三族各写一份会被 Task 7/8 各改一遍）。
6. **`clearFilterInput()` 到底有没有把 EP 内部 query 洗掉，全仓零判据**（症状：搜索后关面板
   再打开，框里残留旧关键词）。Task 5 也没钉。记为已知缺口，批末若要补就在 `file-correlation`
   那条已在跑的序列用例里加两句，别为它开新用例。
7. 实测过的两条 EP 事实，不必再查：**v2 的 Enter 绑在过滤 input 自己身上**
   （`select-v2/src/select.mjs:227`，`withKeys(withModifiers(onKeyboardSelect,['stop','prevent']),['enter'])`），
   组件的 `@keydown.capture` 在祖先捕获阶段先跑 ⇒ 抢得到；**v2 的 `#empty` 与 v1 门条件逐字同构**
   （`select.mjs:318` vs v1 `select2.mjs:344`），「加载中显示『无匹配序列』」是 v1 既有行为，
   不是迁移回归（Task 4 那条否证继续成立）。

---

## Task 7: `TestColumnSelector.vue` 迁 v2（全选/清空在 `#footer`）

**Files:**
- Modify: `frontend/src/pages/data/components/browser/TestColumnSelector.vue`（163 行）
- Test: `frontend/e2e/data/view-data.spec.ts`（:663-667、:687-691、:732-741、:745-752、:807-810）

- [ ] **Step 1: 改 template**

```vue
    <el-select-v2
      ref="selectRef"
      :model-value="modelValue"
      :options="selectOptions"
      multiple
      filterable
      placeholder="搜索测试列"
      collapse-tags
      collapse-tags-tooltip
      class="col-select"
      aria-label="显示测试列"
      :filter-method="filterMethod"
      @update:model-value="$emit('update:modelValue', $event)"
      @keydown.capture="onSelectKeydown"
      @visible-change="onVisibleChange"
    >
      <template #empty>
        <div class="empty-hint">无匹配测试列</div>
      </template>
      <template #footer>
        <!-- 全选/清空收进下拉底部：挂在控件下面会多撑出一行（实测筛选行 75px → 54px），
             而这两个动作只在看列表时才用得到 -->
        <div class="col-footer">
          <div class="col-actions">
            <el-button size="small" link type="primary" :disabled="cols.length === 0" @click="selectAll">
              全选
            </el-button>
            <el-button size="small" link type="primary" :disabled="modelValue.length === 0" @click="clearAll">
              清空
            </el-button>
          </div>
          <div v-if="kw" class="match-hint">匹配 {{ matches.length }} 项，按 Enter 全选</div>
        </div>
      </template>
    </el-select-v2>
```

- [ ] **Step 2: 改 script**

同 Task 6：删 `DROPDOWN_RENDER_CAP` import 与 `filteredItems`，加 `selectOptions` computed（`toOptions(kw ? matches : props.cols)`）。`selectAll` 保持 `[...props.cols]`（全集，与渲染无关）。

- [ ] **Step 3: 跑查看数据用例，重点看 footer 里的按钮**

Run: `cd frontend && npx playwright test e2e/data/view-data.spec.ts --project=P1 --reporter=list`
Expected: 全绿。`:687-691` 点 footer 里「清空」那条最容易红（footer 在虚拟列表容器之外，但 popper 限定改了之后可能取不到）—— 若红，把定位器限定到 `.el-popper[aria-hidden="false"] .col-actions button`。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/pages/data/components/browser/TestColumnSelector.vue frontend/e2e/data/view-data.spec.ts
git commit -m "feat(data): 测试列下拉迁 el-select-v2，取消渲染封顶"
```

---

## Task 7 落地后的订正（**Task 8/9 开工前必读**，2026-11-13）

落地 = `1a0a4c3`（迁移 + `popper-class` + `popperOf`）+ `4dc1659`（合并复审的两条要紧项）。

1. **谓词入口**：`e2e/helpers/elplus.ts` 新增 `popperOf(page, popperClass)`（返回 `.el-popper.<cls>[aria-hidden="false"]`
   容器，7 处消费者），本控件身份串 `COL_POPPER = 'dp-col-popper'`。**同一个谓词现在有三处写法**
   （`params.ts:51` 私有的 `visibleOptions`、`elplus.ts` 的 `popperOf`、`file-correlation.spec.ts:244`
   与 `params.ts:117/133/141` 的内联模板串）⇒ 统一动作并入 Task 9（导出 `popperOf`，其余从它组合
   `.locator('.el-select-dropdown__item')`），别在 Task 8 里顺手改。
2. **实例级 popper-class 判为「预防性正确」不是投机**：查看数据页共用 `.el-select-dropdown` 类名的
   实例有 **6 个**（本控件 + `DataBrowserToolbar.vue` 的 Pass/Fail / Site / 列宽 三颗 v1 与「固定列」
   那颗 v2 + 横幅 `ActiveFileBanner.vue` 里那颗 `banner-file-select`），且 `view-data.spec.ts` 的
   「@p2 显示测试列：切换文件后选中集重置为全部显示」那条（按标题认它，锚点 `1574012`）在同一次交互里
   开两个下拉。**Task 9 给本族补正向判据时必须有实例锚点**，这六个类名就是那批锚点的清单。
   诚实的一半：同一条用例里横幅那两步（点 `.banner-file-select` 后用全局 `.el-select-dropdown:visible`
   取选项）仍是全局 `:visible`，本批只修了一半。
3. **不需要 Task 6 那条 disabled 判据**：本组件 props 是 `cols`/`modelValue`，computed 叫
   `selectOptions`，**没有撞名**，`:disabled="cols.length === 0"` 引用的仍是 props 全集。
   可选的结构化灭法（`props.cols.length` 显式写死）记在这儿，未做。
4. **两条被裁定的等价/加强替换**（后面别改回去，位置一律按用例标题认，锚点 `1574012`）：
   「@p2 系统列按格式权威下发：前缀同名测试项（SITE_CHECK）不误判」那条里「在列表里等 SITE_CHECK 出现」
   改成「按名搜它再断可见」—— 旧写法在 v1 下其实多断了「它落在前 300 渲染项里」，真正承重的一直在同那条
   用例前半的 `sysHas`/`testHas` 两个 API 侧断言；「@p2 显示测试列：输入关键词 + Enter 全选匹配项」那条
   末尾的 poll 从「firstMatch 有 is-selected」改成「重搜同一词 ⇒ 窗口每一条都 is-selected 且行数 ≥2」
   （下界 2 挡「窗口只挂 1 行且它恰选中」时「全选」与「v2 加 1 颗」同形的假绿）。
   ⚠ 变异自证只证到**半条**：摘掉 Enter 分支后红打在上述那条 poll 之前的 `toHaveValue('')` 上，
   新 poll 自身的增量力**未实测**，靠推理成立。
5. **`view-data.spec.ts` 被 `scripts/line-limit.mjs` 的 `EXEMPT` 账按精确行数冻着**（登记值的唯一事实来源
   就是那张账，本计划刻意不抄数字——抄了就会像这里原来写的「1802」一样，下一批加完断言后已经是错的）：
   多一行 `grew` 红，少一行 `now < frozen.lines` 也要红（正解是**同批同步下调登记值**，不是把文件撑回去）。
   要往本文件加断言，先 `cd frontend && wc -l e2e/data/view-data.spec.ts` 现跑，再决定同批减行还是同步登记值。
6. **⚠ 并入 Task 9 的第 4 件事（本批设计漏项，Task 7 复审时发现的）**：
   迁 v2 之前的「固定列」那颗 `el-select`（`DataBrowserToolbar.vue`，位置以 `1574012^` 为准）
   是**未封顶的 v1 实现**（`v-for="c in allCols"`，无 `DROPDOWN_RENDER_CAP`）。`allCols` = 表格
   `headers`（`DataBrowserAgGrid.vue` 里 `allCols.value = d.headers ?? []` 那一处），ETS88_FT 实测
   **1,728 列**（数法见 `view-data.spec.ts` 的「千列文件：每页行数按列数预算压低且提示可见」那条里
   `page_size` 被钳到 205 那句断言）⇒
   打开即挂 1,728 个 `el-option`，正是 `constants/dropdown.ts:8` 记的那个冻结风险，且它是那轮唯一
   红过的业务用例（「@p1 固定列：多选，后选的列叠加而不是替换已钉住的列」那条的
   `toBeVisible({ timeout: 15_000 })`，15s 等不到选项）。设计稿 §2 只说「四个下拉」、§8 的「明确不做」里也没有它
   ⇒ **设计漏项，裁定并入本批 Task 9**（迁 v2 后模板全是现成的，机制与 Task 7 同形）。
7. **记在案的行为缺口（本批不补）**：「空关键词 + Enter 会不会全选上千列」零判据（新增那条 footer
   判据只有「matches 透传」+「`v-if` 丢掉 kw 一支」两个 mutation 同时成立才红）；
   `clearFilterInput()` 有没有真把 EP 内部 query 洗掉，col 族被「@p2 显示测试列：输入关键词 + Enter
   全选匹配项」那条的 `toHaveValue('')` 顺带兜住了一半，序列族仍零覆盖。
8. **汇报纪律**：跑 e2e 报数必须带 **flake 数**（「36 passed」与「33 passed + 3 flaky」不是一回事）。
   本轮实测既有负载 flake 两条：「@p1 固定列：多选，后选的列叠加而不是替换已钉住的列」与
   「@p2 ETS88 文件末尾不渲染 Data Collection 尾部元数据行」（均按标题认，锚点 `1574012`）。

---

## Task 8: `ExportParamSelector.vue` 迁 v2 + `exports.spec` 的数条数判据下沉 T1

**Files:**
- Modify: `frontend/src/pages/data/components/export/ExportParamSelector.vue`（179 行）
- Modify: `frontend/e2e/exports/exports.spec.ts:433-455`
- Test: `test/backend/`（若已有导出参数端点契约测试则补一条，否则留在 T3）

- [ ] **Step 1: 改 template 与 script（完整块，不指回 Task 7）**

与 Task 7 的三处差异：① 全选/清空按钮在控件**外面**（:34-35），footer 里只有提示；② 没有 `#empty` slot；③ `aria-label="选择导出参数"`、`placeholder="点击选择要导出的参数"`、外层是 `.step-body` 而非 `.test-col-selector`。props 名是 `params`（不是 `cols`），且**没有** `options` 命名冲突，但 computed 仍统一叫 `selectOptions`（Task 6 的约定）。

`<template>` 里 `<div class="step-body">` 的第一个子元素（现 :9-33）整块替换：

```vue
      <el-select-v2
        ref="selectRef"
        :model-value="modelValue"
        :options="selectOptions"
        multiple
        filterable
        placeholder="点击选择要导出的参数"
        collapse-tags
        collapse-tags-tooltip
        class="param-select"
        aria-label="选择导出参数"
        :filter-method="filterMethod"
        @update:model-value="$emit('update:modelValue', $event)"
        @keydown.capture="onSelectKeydown"
        @visible-change="onVisibleChange"
      >
        <template #footer>
          <div v-if="kw" class="match-hint">匹配 {{ matches.length }} 项，按 Enter 全选</div>
        </template>
      </el-select-v2>
```

`:34-35` 那两个按钮（全选 / 清空）**逐字不动**。

`<script setup>` 里删 `DROPDOWN_RENDER_CAP` import（:42）与 `filteredItems`（:64-67），换成：

```ts
import { computed, ref } from 'vue'
import { toOptions } from '../../../../utils/selectOptions'

/* … filterText / selectRef / kw / matches 保持原样 … */

/**
 * 下拉选项 = 匹配集或全量，不截断。全选走 props.params、Enter 走 matches，
 * 两者本来就是完整集合（旧注释 :64-65 的这半句仍然成立，作废的是「截断」那半句）。
 */
const selectOptions = computed(() => toOptions(kw.value ? matches.value : props.params))
```

`filterMethod` / `onSelectKeydown` / `clearFilterInput` / `onVisibleChange` / `selectAll` / `clearAll` / `selectMatches` 全部保持不动。

- [ ] **Step 2: 把「数 DOM 选项」那条改成从响应取全集**

Modify `frontend/e2e/exports/exports.spec.ts`（现 :433-455 是 `count()` + `paramOptions.nth(i)` 循环）：照该文件 :540-544 已有的注释写法，改成从 histogram 响应的 `results` 键取全集再断言条数，DOM 侧只断「目标项能被搜到并选中」。

```ts
// 判据从「DOM 里有几个 option」改成「响应里有几个参数」：
// el-select-v2 只渲染虚拟窗口那约 8 行，数 DOM 不再等于列表规模（2026-11-13 批1）。
const allParams = capturedParamList(page)
expect(allParams.length).toBeGreaterThan(0)
await expect(paramOptions.filter({ hasText: allParams[allParams.length - 1] }).first())
  .toBeVisible()
```

- [ ] **Step 3: 跑导出用例**

Run: `cd frontend && npx playwright test e2e/exports/exports.spec.ts --project=P1 --reporter=list`
Expected: 全绿。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/pages/data/components/export/ExportParamSelector.vue frontend/e2e/exports/exports.spec.ts
git commit -m "feat(export): 导出参数下拉迁 el-select-v2；条数判据改从响应取"
```

---

## Task 8 落地后的订正 + **Task 9 重新切分**（2026-11-13，四个下拉已全部迁完）

落地 = `5378292`（迁移 + 判据改造）+ `b36343a`（合并复审的四条小账）。
迁移面到此收口：`grep -rn DROPDOWN_RENDER_CAP frontend/src` 现测只剩 `constants/dropdown.ts:14`
（定义本身）与 `utils/selectOptions.ts` 的一处历史注释 ⇒ **Task 9 的原始范围（删常量）已无阻塞**。

### 三条实测事实（别再重新论证）

1. **`fill()` 与 `pressSequentially()` 一样触发过滤**，「必须逐键输入」作废（该错账原文活了
   2026-08-21 到 2026-11-13，已在 `b36343a` 删成一行正确事实；那行现在在
   `view-data.spec.ts` 的「@p2 显示测试列：输入关键词 + Enter 全选匹配项」那条开头，按标题认，锚点 `1574012`）。
   机理：Playwright 的 `fill` 派发 `input` 事件，v1（`select/src/useSelect.mjs:270→185`）与
   v2（`select-v2/src/useSelect.mjs:447→251`）走同一条
   `onInput→onInputChange→handleQueryChange→filterMethod` 链。边界只有三条：
   ① input 必须可编辑（v2 `select.mjs:215` 的 `readonly: !filterable`）⇒ 只有 `filterable` 下拉能 fill；
   ② 值与 `states.previousQuery` 相同时 `useSelect.mjs:251` 直接 return ⇒ 同一个词连填两次不重发
   （Enter 清空后再填可以）；③ 未开面板时 query 照样变，但 footer 读不到。
2. **导出页的 histogram 请求原理上进不了 `paramList.ts` 那台捕获器**：`ExportToolsTab.vue:77`
   发的是 `{file_id, params: []}`，而 `paramListCore.ts:67` 把带 `params` 的请求判为「算某参数」
   ⇒ 永不进桶；`ParamListScope` 也只有分析页三个 tab。全仓因此**恰有两套**取参数全集的机制
   （监听式 `listParams` / 自注册的 `paramKeysFromHistogram`），两者在 `params.ts` 里互相指认。
   **不要为了「统一」再引第三份。**
3. **`exports.spec.ts` 在默认 6 workers 下有 1-3 条条件跳过**（走文件头 `:13-18` 的「可选文件 < 2
   则 skip」，跳过点是 `waitForOptions` 5s 预算内 `/files/` 选项数为 0；`git blame` 是 2026-08/09
   的既有负载敏感点，**不是本批引入**）。⇒ **Task 12 读这个文件必须固定 `--workers=2`**
   （实测 `--workers=2` ⇒ 10 passed / 0 skipped），否则门禁会把被改的那两条读成 skip。

### Task 9 待办清单（复审一路攒下来的，比正文大得多）

**9A 收口删除与统一**（= 下面「Task 9: 删掉 `DROPDOWN_RENDER_CAP` 与那份说明文件」一节的原范围 + 三条同族统一）
- [ ] 删 `DROPDOWN_RENDER_CAP` 与 `constants/dropdown.ts`（正文原任务）+ `pickTabFile` 的陈旧注释
- [ ] **footer 措辞统一**：ParamSelector 搜索态显示的是命中数却写「共 N 项」，另三个写「匹配 N 项」
      —— 既是歧义也是同族不一致（Task 5 复审记的）。改文案会连带 `param-dropdown-full-list`
      第 1 条的 `toHaveText` 精确匹配，必须同批改。
- [ ] `buildParamOptions` → `buildSelectView`（名字为唯一消费者写窄了，签名对四个下拉通用）
- [ ] **谓词入口统一**：现在同一个谓词有三处写法（`params.ts:51` 私有 `visibleOptions`、
      `elplus.ts` 的 `popperOf`、`file-correlation.spec.ts:244` 与 `params.ts:117/133/141` 内联串）
      ⇒ 导出 `popperOf`，其余从它组合 `.locator('.el-select-dropdown__item')`。
      同批把 48 处内联 `:visible`（19 个 spec）与 `colfilter.ts` 的 3 处摊开清点：**能收的收，
      收不完的写进 todo 作为下一批专项**，别默默扩大。
      ⚠ **这三个数是初稿估的，实数见 :536 那条订正**：`.el-select-dropdown__item:visible` 现跑 38 处 /
      15 个文件（master 上 39），`colfilter.ts` 那 3 处其实是 2× `.col-filter-popper:visible` + 1× item；
      全部 `:visible` 是 190 处 / 35 个文件（剔注释行口径，命令在 `docs/tasks/todo.md`）。

**9B 反截断正向判据（三族补齐，形式已定死：不新建 spec、不新建夹具）**
- [ ] 把 `param-dropdown-full-list.spec.ts` 的 `tailRowState` 与 `MAX_WINDOW_ROWS` 提到
      `e2e/helpers/selectV2.ts`，在序列 / 测试列 / 导出三族的**既有**用例里各加 1 条
      `items.count() < 20` + 1 条 footer 逐字。
- [ ] 导出族要先换夹具才有牙齿：现在那条走 `options.first()`、默认文件只有 **41** 个参数
      （< 旧封顶 300），迁不迁 v2 都绿 ⇒ 换 `BPD93204_FT1_ETS163550_12252024`（现测 1,723 列）。
- [ ] `pickBoundedKeyword` 是带 throw 的纯启发式且零 T2 ⇒ 拆纯 + 补 4 例（阶梯跳带 / 首字符全唯一 /
      空数组 / cap=1）。判据：`EXPORT_PARAM_SELECT_CAP=20` 与「匹配数 ≥2」两处边界必须能各自红。
- [ ] ⚠ `exports.spec.ts` **不在** `scripts/line-limit.mjs` 的 EXEMPT 账上，所以它顶的是 600 硬闸本身；
   行数**一律现跑**（`cd frontend && wc -l e2e/exports/exports.spec.ts`）—— 本文件正文与台账里出现过的
   588 / 592 / 597 都是某一轮的快照，收口那轮是 599 ⇒ 距硬闸 1 行，加断言前**先腾行**，别把任何数字当长期事实。
- [ ] 记在案但不做（除非要动的那条用例顺手）：「空关键词 + Enter」行为零判据；
      `clearFilterInput()` 是否真洗掉 EP 内部 query（col 族被「@p2 显示测试列：输入关键词 + Enter 全选匹配项」
      那条 poll 之前的 `toHaveValue('')` 兜了一半，序列族零覆盖）。

**9C 第五个下拉 —— 设计漏项，等用户拍板是否并入本批**（2026-11-13 拍板并入，落地 `1574012`）
- 迁 v2 之前 `DataBrowserToolbar.vue` 的「固定列」那颗 `el-select`（位置以 `1574012^` 为准）
  是**未封顶的 v1 实现**
  （`v-for="c in allCols"`，无 `DROPDOWN_RENDER_CAP`），`allCols` = 表格 `headers`
  （`DataBrowserAgGrid.vue` 里 `allCols.value = d.headers ?? []` 那一处），ETS88_FT 实测 **1,728 列** ⇒ 打开即挂 1,728 个 `el-option`，
  正是 `constants/dropdown.ts:8` 记的那个冻结风险；它也是 Task 7/8 复审里唯一反复红的业务用例
  （`view-data.spec.ts` 的「@p1 固定列：多选，后选的列叠加而不是替换已钉住的列」那条，
  选项首行的 `toBeVisible({ timeout: 15_000 })` 等不到）。
  设计稿 §2 只承诺「四个下拉」、§8 的「明确不做」里也没有它 ⇒ 属**设计漏项**而非范围蔓延。
  机制与 Task 7 同形（约 1 小时工作量），但**批 1 已越过原设计范围，必须先问用户**。

---

## Task 9: 删掉 `DROPDOWN_RENDER_CAP` 与那份说明文件

**Files:**
- Delete: `frontend/src/constants/dropdown.ts`
- Test: `frontend/test/unit/`（若有引用该文件的用例一并删）

- [ ] **Step 1: 确认零引用**

Run: `cd frontend && grep -rn "DROPDOWN_RENDER_CAP\|constants/dropdown" src e2e test`
Expected: **只剩这一份文件自身**（四处组件引用已在 Task 5-8 清完）。若还有引用，回到对应 Task，不要在这里加兼容层。

- [ ] **Step 2: 删除文件**

```bash
git rm frontend/src/constants/dropdown.ts
```

> 那份文件里「为什么要有这个数」的注释（含「EP 2.14 里虚拟化的是 el-select-v2，el-select 甚至没有 virtual 这个 prop」）**不搬到别处留档**：它是本次推翻的旧决策的正文，历史在 `docs/superpowers/specs/2026-11-13-…-design.md` §2.5 与 git 里。留一份副本就是未来的第二事实来源。

- [ ] **Step 3: 全绿验证**

Run: `cd frontend && npx vitest run && npm run lint:e2e && npm run build`
Expected: 三条全绿。

- [ ] **Step 4: 提交**

```bash
git add -u frontend/src/constants
git commit -m "refactor(dropdown)!: 删除 DROPDOWN_RENDER_CAP（el-select-v2 虚拟化后不再需要渲染封顶）"
```

---

## Task 10: 介绍书入口图标提亮（只提亮这一颗）

**Files:**
- Modify: `frontend/src/components/layout/Topbar.vue:42-52`（template）与 `:330-344`（style）
- Test: `frontend/e2e/theme/intro-icon-contrast.spec.ts`（新建）

- [ ] **Step 1: 写失败的双主题对比度用例**

Create `frontend/e2e/theme/intro-icon-contrast.spec.ts`：

```ts
import { expect, test } from '@playwright/test'

import { gotoApp } from '../../helpers/nav'

/**
 * 用户诉求是「介绍书的图标再稍微明显一点」，定稿是**同尺寸只提亮一档**（spec §3.1）。
 * 三条判据：
 *  - intro 那颗 = 主题主文本色（这是「明显」的实现本体）
 *  - 铃铛那颗仍是次要文本色（挡「顺手把三颗都提亮」——那样等于没提亮，
 *    因为同排三颗一样响就没有层级了）
 *  - light/night 两主题都成立（CLAUDE.md：任何前端改动都要维护两套主题）
 */
const RGB = {
  light: { text: 'rgb(31, 41, 55)', text2: 'rgb(107, 114, 128)' },   // #1f2937 / #6b7280
  night: { text: 'rgb(255, 255, 255)', text2: 'rgba(255, 255, 255, 0.76)' },
} as const

for (const theme of ['light', 'night'] as const) {
  test(`${theme} 主题下介绍书图标比邻居更醒目`, async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await page.evaluate((t) => document.documentElement.setAttribute('data-theme', t), theme)

    const colorOf = (locator: ReturnType<Page['locator']>) =>
      locator.evaluate((el) => getComputedStyle(el).color)

    const intro = colorOf(page.locator('[data-testid=open-intro] .el-icon'))
    await expect(intro).toBe(RGB[theme].text)

    const bell = colorOf(page.locator('.notification-badge .el-icon').first())
    await expect(bell).toBe(RGB[theme].text2)
  })
}
```

Run: `cd frontend && npx playwright test e2e/theme/intro-icon-contrast.spec.ts --project=Edge --reporter=list`
Expected: FAIL —— intro 现在是 `--text-2`。（project 名以 `playwright.config.ts` 现量为准，若主题类用例归在别的 project 就跟着改。）

- [ ] **Step 2: 加专用类并提亮**

Modify `frontend/src/components/layout/Topbar.vue:42-52`：给那颗按钮加一个修饰类。

```vue
      <el-button
        text
        circle
        class="icon-btn icon-btn--intro"
        data-testid="open-intro"
        title="产品介绍书（新标签页打开）"
        aria-label="在新标签页打开产品介绍书"
        @click="openIntro"
      >
        <el-icon :size="18" aria-hidden="true"><Reading /></el-icon>
      </el-button>
```

Modify `<style scoped>`（:330-344 那一段之后）：

```css
/* 介绍书入口比邻居（通知/用户菜单）醒目一档：同尺寸、主文本色。
   只提这一颗 —— 三颗一样响就没有层级了，用户要的是「找得到」不是「最亮」。 */
.icon-btn--intro {
  color: var(--text);
}

.icon-btn--intro:hover {
  color: var(--brand);
}
```

- [ ] **Step 3: 跑绿并双主题目测**

Run: `cd frontend && npx playwright test e2e/theme/intro-icon-contrast.spec.ts --project=Edge --reporter=list`
Expected: 2 passed。

手工：`cd frontend && npm run dev` → 浏览器里 light/night 各看一眼顶栏，确认 intro 那颗「找得到但不出格」。**这一步不能省**（用户偏好：涉及视觉取舍先确认再落地，且「明显」是主观词，判据只能证明颜色，不能证明观感）。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/layout/Topbar.vue frontend/e2e/theme/intro-icon-contrast.spec.ts
git commit -m "feat(topbar): 介绍书入口图标提亮到主文本色，邻居图标保持次要色"
```

---

## Task 11: 介绍书标签页图标（VitePress `head` + Django `/favicon.ico`）

**Files:**
- Modify: `docs/intro/.vitepress/config.mts`
- Modify: `config/urls.py:96-105`
- Test: `test/backend/test_intro_serving.py`（若已有同名文件则追加用例）

- [ ] **Step 1: 写失败的后端契约测试**

Create/Modify `test/backend/test_intro_serving.py`：

```python
"""介绍书 serving 的三条契约（T1：响应体就能表达，不进浏览器）。"""
from django.test import SimpleTestCase


class IntroFaviconTests(SimpleTestCase):
    def test_intro_index_has_icon_link(self):
        """VitePress 产出的 index.html 必须带 <link rel="icon">。

        根因：config.mts 过去没有 head 数组，构建产物里根本没有这条 ⇒ 浏览器退回
        请求 /favicon.ico，而 urls.py 只挂了 /favicon.svg ⇒ 标签页无图标。
        """
        resp = self.client.get('/intro/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8')
        self.assertIn('rel="icon"', html)
        self.assertIn('/favicon.svg', html)

    def test_favicon_ico_resolves(self):
        """浏览器无条件请求 /favicon.ico；不路由就是 404。

        注意本仓 e2e 的 console 采集把 favicon 当噪声过滤掉了（e2e/helpers/nav.ts:30），
        所以这条 404 **在自动化里是看不见的**，只有人工走读会撞见 —— 正是「判据抓不到
        ≠ 没问题」，故用 T1 钉住。
        """
        resp = self.client.get('/favicon.ico')
        self.assertEqual(resp.status_code, 200)

    def test_favicon_svg_still_served(self):
        resp = self.client.get('/favicon.svg')
        self.assertEqual(resp.status_code, 200)
```

Run: `python manage.py test test.backend.test_intro_serving --settings=config.settings.development`
Expected: FAIL —— `rel="icon"` 不在 html 里、`/favicon.ico` 返回 404。
（`--settings` 与 `manage.py test` 的 profile 以本仓后端测试惯例为准，先 `sed -n '1,40p' test/backend/test_server_settings_profile.py` 确认。）

- [ ] **Step 2: 加 VitePress `head`**

Modify `docs/intro/.vitepress/config.mts`（在 `title`（:15）附近）：

```ts
  // 标签页图标：base 是 '/intro/'，相对 href 会被解析成 /intro/favicon.svg，
  // 而 Django 只在根路径挂了 /favicon.svg（config/urls.py:103）⇒ 必须用绝对根路径。
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' }],
  ],
```

- [ ] **Step 3: 加 Django `/favicon.ico` 路由**

Modify `config/urls.py`，紧跟现有 `path('favicon.svg', ...)`（:103）：

```python
    path('favicon.svg', _serve_frontend_file('favicon.svg')),
    # 浏览器无条件请求 /favicon.ico。打包期另有 build/icon.ico（给 Windows 外壳用），
    # 但 web 根下没有那个文件 ⇒ 这里直接复用 SVG：现代浏览器与 Electron 都吃 SVG，
    # 且省一次位图转换。返回 200 而不是 404 才是这条路由的目的。
    path('favicon.ico', _serve_frontend_file('favicon.svg')),
    path('icons.svg', _serve_frontend_file('icons.svg')),
```

- [ ] **Step 4: 重新构建介绍书并跑后端测试**

Run: `cd frontend && npm run intro:build`
Expected: 构建成功（`intro:build` 的实际脚本名以 `frontend/package.json` 为准，先 `grep -n "intro" frontend/package.json` 确认）。

Run: `python manage.py test test.backend.test_intro_serving --settings=config.settings.development`
Expected: 3 passed。

> ⚠ 介绍书产物是 `docs/intro/.vitepress/dist/`，由 `vite.config.ts` 的 `introBooklet()` 在 build 时 `cpSync` 拷进前端 dist。**改 config.mts 后必须重跑 intro:build**，否则测试在本地会因为拿到旧 dist 而假绿/假红 —— 顺序就是上面这两步的顺序，别倒过来。

- [ ] **Step 5: 跑红线扫描**

Run: `node scripts/intro/check.mjs`
Expected: `RESULT: PASS`（红线：真实料号/外迁兄弟工程名/凭据字面量/私有样例名）。

- [ ] **Step 6: 人工走读确认标签页有图标**

Run: `cd frontend && npm run dev` → 打开 `http://localhost:3000/intro/` → 看标签页图标 + F12 Network 确认 `/favicon.ico` 是 200、控制台零报错。
Expected: 图标出现；无 404。

- [ ] **Step 7: 提交**

```bash
git add docs/intro/.vitepress/config.mts config/urls.py test/backend/test_intro_serving.py
git commit -m "feat(intro): 介绍书补标签页图标（VitePress head + Django /favicon.ico 路由）"
```

> `docs/intro/.vitepress/dist/` 是否入库以 `.gitignore` 现状为准（构建产物通常不入库）：`git status --porcelain` 若列出 dist 下大量文件，**不要提交它们**，只提交 config.mts。

---

## Task 12: 批1 收口——门禁、探针清理、台账

**Files:**
- Modify: `docs/tasks/todo.md`（批1 结果段）
- Verify: `frontend/e2e/probe/` 不存在（Task 1 已取消，本不该建）；`grep -rn "PROBE-" frontend/e2e` 为空

- [ ] **Step 1: 确认没有探针残留**

Run: `cd frontend && ls e2e/probe 2>&1; grep -rn "PROBE-" e2e src test`
Expected: `No such file or directory` + grep 零命中。若有，删掉（Task 1 取消后不该产生任何探针文件；Task 5 Step 1.5 的打印按其自身要求已在 Step 5 摘除）。

- [ ] **Step 2: affected 门禁**

Run: `cd frontend && npm run test:e2e:affected`
Expected: 末行 `RESULT:`。本批改了 `src/constants/`、`src/plugins/`、`src/utils/`、`src/components/layout/`、`e2e/helpers/` ⇒ 命中 `testing-gates.md` §3 全局清单与 6+ 模块 ⇒ **升全量是预期**，不是异常。

- [ ] **Step 3: 全量池收口**

Run: `node scripts/e2e_pool.mjs --slots=4`
Expected: 末行 `RESULT:`；判据是**池自己打印的「文件 N」**（N 应等于选中集合大小）与 `verdict`。`verdict=VOID (infra)` 时**什么都不判、重跑才是结论**（§4）。

Run: `python manage.py test test.backend apps.<逐个枚举 apps/ 下目录>`
Expected: `OK` 行。**绝不写 `apps.*`**（那不是合法标签，实测只跑 1104 例并带一条 `ModuleNotFoundError`，看着像回归）。枚举写法照 `scripts/e2e_nightly.mjs:129-136`，且**必须排除 `__*` 目录**（`__pycache__` 会让收集期崩）。

- [ ] **Step 4: 三条快检**

Run: `cd frontend && npx vitest run && npm run lint:e2e && npm run build`
Expected: 全绿。

- [ ] **Step 5: 行数与体积回归**

Run: `cd frontend && npx vitest run test/unit/lineLimit.spec.ts`
Expected: PASS（无新增超阈件；`src/utils/selectOptions.ts`、`e2e/helpers/paramList.ts` 都远低于 600）。

- [ ] **Step 6: 台账写实测值**

Modify `docs/tasks/todo.md` 批1 结果段，逐条写：
- 探针 Q1–Q4 四个实测数；
- 4,570 项（或实际最大夹具项数）下的首屏与滚到底耗时，与迁移前对照；
- vitest 文件数/例数、e2e 计划文件数/例数、后端 `Ran N tests`；
- 被改写的 e2e 条数（spec §2.7 估 15–20，写实际值）；
- `test.skip` 是否触发过（触发 = 夹具参数太少，必须记录用了哪个夹具）。

- [ ] **Step 7: 提交**

```bash
git add docs/tasks/todo.md
git commit -m "docs(todo): 批1 收口台账（v2 迁移实测值与 e2e 改写条数）"
```

---

## Task 12 落地后的订正（2026-11-14，收口当天）

落地 = `fa2200d`（池档抓到的真红 + 绊线）+ `a36f9cb`（终审三笔判据）+ `6255122`（消费者账/谓词债订正）
+ `1abe68b`（intro 声明源侧 T2）+ 本节的台账。**Step 2/3/4/5 的判据本身没变，全部按正文跑完**。
四处与本文不同，以这里为准：

1. **Step 3 的全量池实际跑了两轮，且第一轮是必须花的。** 本文没有任何一步要求「新增的 spec 进一次
   slot 档」，于是 Task 5 新建的 `param-dropdown-full-list` 从没在池档跑过 —— 它把 `storageState`
   写成字面量路径，串行档与 slot 档等价所以每轮全绿，收口池里 5 条全红在 `gotoApp` 的 `.main-layout`
   上（判据一条都没跑到）。⇒ **补一条批内纪律**：新 spec 只要依赖登录态 / 落盘路径 / 端口 / media，
   就得至少跑一次 `node scripts/e2e_pool.mjs --slots=1 -- <file>`（4 文件 3.6min，比事后重跑整池便宜
   一个量级）。教训全文在 `docs/tasks/lessons.md` 2026-11-14。
2. **Step 6 要的「4,570 项首屏与滚到底耗时，与迁移前对照」这份仓内给不出。** 实测最大夹具是
   1,723 参数 / 1,728 列（同一个文件），4,570 是设计稿 §2 当初的假设值；旧实现封顶 300、从没打过 ms
   ⇒ **没有同形计时可对照**。台账改成记形状与后果两条（footer「仅显示前 300」+ 固定列那颗 1,728 个
   `el-option` 把 `view-data` 那条 15s 等待拖成复审里唯一反复红的业务用例），并明写「别读成快了多少倍」。
   固定列那颗的打开耗时**没落断言**（9C 那条永不触发的耗时断言已在 `798e277` 删）。
3. **Step 6 的「被改写的 e2e 条数」用脚本现跑，不引用 §2.7 的估算。** `node scripts/e2e-rewritten-census.mjs`
   按「describe 链 + 用例标题」当身份比 master/HEAD 的块体 ⇒ 新增 8 / 改写 16 / 删除 0（运行条 +9，
   `intro-icon-contrast` 是双主题循环）。与单文件 playwright 计数异源交叉：每文件 = 脚本条数 + 2 条 setup。
4. **Step 3 那条「后端全量」的标签枚举要现跑取，别抄本文的写法。** 现跑 = `test.backend` + 12 个 `apps.*`
   （`fs.readdirSync(apps)` 剔 `__*`），结果 `Ran 2576 tests in 539.961s / OK (skipped=16)`。
   另外 `npm run build` 必须在**最终树**上跑一次再开收口池：池档 preview 服务的是 `frontend/dist`，
   改了 src 不重跑 build，池子测的就是旧产物。

---

## Self-Review（写完计划后自查）

**1. Spec 覆盖**：spec §2（1–8 小节）→ Task 1–9；spec §3.1 → Task 10；spec §3.2–3.3 → Task 11；spec §7 判据 1–4 → Task 5/9/10/11；spec §7 判据 8–10 → Task 12。spec §4/§5/§6（磁盘占用、重复项、两页 toolbar）**不在本计划** —— 属批2/批3，各另起一份，因此 spec §7 判据 5–7 本批不验。无遗漏项。

**2. 占位符扫描**：初稿有两处违规，已改掉 —— ① Task 8 Step 1 原本写「同 Task 7 的形状」，现在给出完整 template + script 块并列出与 Task 7 的三处具体差异；② Task 6 原本在模板里混用 `:options="options"` 与 `:disabled="props.options.length === 0"`，现在统一 `selectOptions`，并把「空关键词时两种写法恰好等价、所以这个 bug 正常路径看不出来」写进说明。

**3. 类型一致性**：`SelectOption` / `ParamSegment` / `toOptions` / `filterByKeyword` / `sortPrefixFirst` / `highlightSegments` / `buildParamOptions` / `attachParamListCapture` / `capturedParamList` / `selectOptions`（computed 名，Task 6/7/8 统一）/ `segmentsFor` / `.param-count-hint` / `.icon-btn--intro` —— 各 Task 引用与 Task 2/4/5/10 的定义逐一对齐。

**4. 两处需要现场判定的外部事实**（不是占位符，是计划里无法确定的仓库现状，各步骤已给出取法）：
- Task 10 Step 1 的 `--project=Edge`：主题类用例归属哪个 project 要读 `frontend/playwright.config.ts` 定。
- Task 11 Step 4 的 `intro:build` 脚本名与 `docs/intro/.vitepress/dist/` 是否入库：分别读 `frontend/package.json` 与 `git status --porcelain` 定。

**5. 本批的已知残留（写清楚，不留到「以后再说」）**：
- Task 4 把 `listParams()` 从「数 DOM」改成「读响应」，**顺带修好了一个旧 bug**：旧实现在参数超过 300 的夹具上本来就只能拿到 300 项（`selectParamWithSpecLimits` 的 `params.slice(0, maxTries)` 因此一直在前 300 项里找）。新实现返回全集，行为更正确，但也意味着 `maxTries` 的语义变了（现在是「全集里前 N 个」而不是「渲染出的前 N 个」）。Task 4 Step 5 的两条用例不足以覆盖这个变化，收口（Task 12 Step 3）的全量池才是判据。
- `highlightSegments` 从组件搬进 utils 后，那段 XSS 说明注释在 utils 里有一份、git 历史里有一份，组件里那份随 template 改写消失。**没有留第二副本**，符合「唯一事实来源」。
