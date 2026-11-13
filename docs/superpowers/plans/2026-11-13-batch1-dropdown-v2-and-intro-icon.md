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

## Task 1: 探针——迁移动产品代码前先把 v2 的四件事量出来

**为什么先跑探针**：本仓 `el-select-v2` **零先例**（`grep -rn "el-select-v2" frontend/src` 只有 `constants/dropdown.ts:4-5` 那句「虚拟化的是自带的 el-select-v2」的说明）。lessons 的规矩是「仓内没用过的 API 先跑探针」，2026-11-12 那条 Event/Condition 过不了池的教训就是第一版方案被探针否掉的。探针不过 → 回设计，不许硬迁。

**Files:**
- Create: `frontend/e2e/probe/select-v2-probe.spec.ts`（**临时**，Task 12 前删除）
- Read: `frontend/e2e/fixtures/*.ts`（找现成的多参数夹具与 `gotoApp` 用法）

- [ ] **Step 1: 先读一份现成 analysis 用例，照它的登录与选文件写法起探针**

Run: `cd frontend && sed -n '1,40p' e2e/analysis/histogram-fail-bins.spec.ts`
Expected: 看到 `test.describe.configure` / `storageState` / `gotoApp('/analysis')` / `selectAnalysisFile` 的既有用法。探针照抄这套前置，**不要自造登录**。

- [ ] **Step 2: 写探针（四问各一条，打印数值，不断言产品行为）**

Create `frontend/e2e/probe/select-v2-probe.spec.ts`：

```ts
import { expect, test } from '@playwright/test'

import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile } from '../helpers/params'

/**
 * 临时探针（2026-11-13 批1 Task 1）：迁 el-select-v2 前量四件事。
 * 跑完即删，结论写回 spec §2.6。不断言产品行为，只打印实测值。
 */
test.describe('probe: el-select-v2 四问', () => {
  test.use({ storageState: 'e2e/.auth/admin.json' })

  test('Q1 footer slot / Q2 filter-method / Q3 Enter / Q4 首屏耗时', async ({ page }) => {
    const errors: string[] = []
    page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))

    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page)

    // 用 v2 起一个一次性实例：把 ParamSelector 的 popper 当观察对象不现实（还没迁）
    // 所以这里直接在页面里挂一个 v2 —— 通过真实产品入口不行，改成量 EP 本身：
    // 打开任意一个已存在的 el-select，确认 v2 的类名差异只影响定位器不影响渲染。
    const t0 = Date.now()
    await page.evaluate(() => {
      const el = document.createElement('div')
      el.id = 'probe-v2-root'
      document.body.appendChild(el)
    })
    console.log('PROBE-Q4-mount-dom-ms', Date.now() - t0)

    // Q1/Q2/Q3 需要真实 v2 组件，改由 Step 4 的手工最小页承担（见下）。
    // 这里只留控制台噪声采集，证明 gotoApp 通路本身干净。
    console.log('PROBE-consoleErrors', JSON.stringify(errors))
    expect(errors.filter((e) => !/favicon|ResizeObserver/.test(e))).toEqual([])
  })
})
```

- [ ] **Step 3: 建手工最小页（v2 四问的真判据在这里）**

Create `frontend/e2e/probe/select-v2-min.html`：

```html
<!DOCTYPE html>
<html lang="zh">
  <head><meta charset="utf-8" /><title>v2 probe</title></head>
  <body>
    <div id="app"></div>
    <script type="module" src="./select-v2-min.mjs"></script>
  </body>
</html>
```

Create `frontend/e2e/probe/select-v2-min.mjs`：

```js
import { createApp, h, ref } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

// 4570 项，与用户报的真实量级对齐
const PARAMS = Array.from({ length: 4570 }, (_, i) => `MTP_page1_${(i + 1).toString(36).toUpperCase()}`)

const Probe = {
  setup() {
    const value = ref('')
    const query = ref('')
    const footerHits = ref(0)
    const options = (q) =>
      q ? PARAMS.filter((p) => p.toLowerCase().includes(q.toLowerCase())) : PARAMS
    return () =>
      h(ElementPlus.ElConfigProvider ?? 'div', {}, [
        h('div', { id: 'probe-state' }, [
          h('span', { id: 'probe-total' }, String(options(query.value).length)),
          h('span', { id: 'probe-dom' }, String(document.querySelectorAll('.el-select-dropdown__item').length)),
        ]),
        h(
          resolveSelectV2(),
          {
            modelValue: value.value,
            'onUpdate:modelValue': (v) => { value.value = v },
            options: options(query.value).map((p) => ({ value: p, label: p })),
            filterable: true,
            clearable: true,
            'filter-method': (q) => { query.value = q },
            popperClass: 'probe-popper',
          },
          {
            footer: () => { footerHits.value++; return h('div', { id: 'probe-footer' }, `共 ${options(query.value).length} 项`) },
            default: ({ item }) => h('div', { class: 'probe-opt' }, String(item.label)),
          },
        ),
      ])
  },
}

function resolveSelectV2() {
  // el-select-v2 的全局注册名是 ElSelectV2
  return ElementPlus.ElSelectV2
}

createApp(Probe).use(ElementPlus).mount('#app')
```

> 上面这个最小页故意把 `#footer` 的调用次数记下来（`footerHits`），用来回答 Q1「footer 到底渲染不渲染、在不在虚拟滚动容器外面」。`resolveSelectV2()` 单独抽出来，是为了在 EP 导出名不对时**当场报错而不是静默**（`h(undefined)` 会抛，抛了就是探针的结论之一）。

- [ ] **Step 4: 跑探针，逐条记录四问的实测答案**

Run: `cd frontend && npx playwright test e2e/probe/select-v2-probe.spec.ts --project=P0 --reporter=list`
Expected: 1 passed；`PROBE-consoleErrors []`、`PROBE-Q4-mount-dom-ms` 是个位数毫秒。

手工量 v2 四问（用 `page.evaluate` 起最小页太绕，直接用 Playwright 驱动真实页面更准）—— 建 `frontend/e2e/probe/run-v2-questions.spec.ts`：

```ts
import { expect, test } from '@playwright/test'

/**
 * 四问的判据版（Task 1 用完即删）。
 * 结论必须逐条抄回 spec §2.6 与本计划 Task 5-8 的注释里。
 */
test('v2 四问', async ({ page }) => {
  await page.goto('/probe/select-v2-min.html')   // 见 Step 5 的挂载方式
  const opts = page.locator('.el-select-dropdown__item')

  // Q1: #footer 是否渲染、是否在虚拟窗口之外
  await page.locator('.el-select-v2__wrapper').click()
  await expect(page.locator('#probe-footer')).toBeVisible()
  console.log('Q1-footer-rendered', await page.locator('#probe-footer').innerText())

  // Q2: filter-method 是否真的不过滤（父算 :options 才生效）
  await page.locator('.el-select-v2__input').fill('MTP_page1_100')
  console.log('Q2-total', await page.locator('#probe-total').innerText())
  console.log('Q2-dom-count', await opts.count())

  // Q3: 虚拟窗口 DOM 行数（对照 defaults.mjs:100,107 的 274/34 ≈ 8）
  console.log('Q3-dom-window-rows', await opts.count())

  // Q4: 4570 项首屏 + 滚到底
  const t0 = Date.now()
  await page.locator('.el-select-v2__input').fill('')
  await page.locator('.el-select-dropdown__item').first().hover()
  await page.mouse.wheel(0, 200_000)
  console.log('Q4-scroll-to-end-ms', Date.now() - t0)
  console.log('Q4-last-visible', (await opts.last().innerText()).trim())
})
```

Expected（**这三条是放行判据，任一不成立就停下回设计**）：
- `Q1-footer-rendered` 打印出「共 4570 项」⇒ `#footer` 有渲染且不受窗口影响（源码依据 `select-v2/src/select-dropdown.mjs:177`）。
- `Q2-total` 是过滤后的条数、`Q2-dom-count` ≤ 约 10 ⇒ **证明 v2 自己不过滤**（`useSelect.mjs:114-132`），必须由父算 `:options`。
- `Q4-last-visible` 是列表**末尾**那一项的文本 ⇒ 证明滚到底能拿到最后一项，且 `Q4-scroll-to-end-ms` 远小于 1000ms。

- [ ] **Step 5: 若最小页挂载路径不通，改走「直接驱动已迁移的 ParamSelector」**

如果 `/probe/select-v2-min.html` 在现有 playwright `baseURL` 下取不到（Vite 不会伺服 `e2e/` 下的裸 html），**不要为了跑通而加新配置**。退路是：先做 Task 5（只改 ParamSelector 一个组件），把四问的打印临时加进 Task 5 的 T3 用例里，量完再删。这条退路写在这里是为了避免 Task 1 卡住整批。

- [ ] **Step 6: 把四问结论写回 spec 与台账**

Modify: `docs/superpowers/specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md` §2.6 —— 在四条后面各追一句实测值。
Modify: `docs/tasks/todo.md` —— 新增/追加「批1」条目，记 `Q1..Q4` 四个实测数。

Run: `git diff --stat`
Expected: 两个 docs 文件有改动，无产品代码改动。

- [ ] **Step 7: 提交**

```bash
git add docs/superpowers/specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md docs/tasks/todo.md
git commit -m "docs(specs): 批1 探针结论写回（v2 footer/filter-method/窗口行数/4570 项耗时实测值）"
```

> 探针 spec 文件此刻**先不提交**（Task 12 删除它们，提交再删除会在历史里留两个空壳提交）。

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

## Task 3: 注册 `ElSelectV2`（三处，漏第三处是「产品能跑、单测红」）

**Files:**
- Modify: `frontend/src/plugins/element-plus.ts:60` 与 `:170`
- Modify: `frontend/src/constants/element-plus-usage.ts:56`
- Test: `frontend/test/unit/elementPlusUsage.spec.ts:147`

- [ ] **Step 1: 先读这三处的现形状，别凭行号猜**

Run: `cd frontend && sed -n '55,65p;165,175p' src/plugins/element-plus.ts && sed -n '50,60p' src/constants/element-plus-usage.ts && sed -n '140,152p' test/unit/elementPlusUsage.spec.ts`
Expected: 看到 `ElSelect` 在 import 列表与 install 列表各出现一次；usage 清单里 `'select'`；spec 里 `expect(list.length).toBe(49)`。

- [ ] **Step 2: 改断言到 50 并加 `'select-v2'`（先红后绿）**

Modify `frontend/test/unit/elementPlusUsage.spec.ts`：把 `expect(list.length).toBe(49)` 改成 `toBe(50)`，并按该文件既有的 `installed` 比对写法加上 `'select-v2'`（**照抄它现有的排序/大小写约定，不要自造**——它是逐字比对）。

Run: `cd frontend && npx vitest run test/unit/elementPlusUsage.spec.ts`
Expected: FAIL —— 计数仍是 49 / `installed` 缺 `select-v2`。

- [ ] **Step 3: 注册组件**

Modify `frontend/src/plugins/element-plus.ts`：在 `ElSelect` 所在的 import 块与 install 块各加一行 `ElSelectV2`（两处都要，位置紧跟 `ElSelect` 便于对照）。

```ts
// import 块（约 :60 附近，与 ElSelect 并列）
  ElSelect,
  ElSelectV2,
// install / 组件表（约 :170 附近，与 ElSelect 并列）
  ElSelect,
  ElSelectV2,
```

Modify `frontend/src/constants/element-plus-usage.ts:56` 附近：

```ts
  'select',
  'select-v2',
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run test/unit/elementPlusUsage.spec.ts`
Expected: PASS。

- [ ] **Step 5: 确认样式入口存在（v2 的 style 文件没挂上会在生产构建期才炸）**

Run: `cd frontend && ls node_modules/element-plus/es/components/select-v2/style/css.mjs && npx vue-tsc -b`
Expected: 文件存在；`vue-tsc -b` 无新增错误（对照 Step 3 之前先跑一次取基线，**别把存量噪音算成本批引入**——判断归属用 `git stash` 对照或 grep 自己改的文件名，见 lessons R8②）。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/plugins/element-plus.ts frontend/src/constants/element-plus-usage.ts frontend/test/unit/elementPlusUsage.spec.ts
git commit -m "build(element-plus): 注册 ElSelectV2 并同步 usage 清单与计数判据"
```

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

## Task 5: `ParamSelector.vue` 迁 `el-select-v2`（含高亮按需 + footer 计数）

**Files:**
- Modify: `frontend/src/pages/analysis/components/ParamSelector.vue`（281 行）
- Test: `frontend/e2e/analysis/param-dropdown-full-list.spec.ts`（新建，T3 接线）

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
Expected: 3 passed（第三条若被 `test.skip` 跳过，说明夹具参数 ≤20，**必须换夹具而不是删用例** —— 记进台账）。

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
- Delete: `frontend/e2e/probe/select-v2-probe.spec.ts`、`select-v2-min.html`、`select-v2-min.mjs`、`run-v2-questions.spec.ts`
- Modify: `docs/tasks/todo.md`（批1 结果段）

- [ ] **Step 1: 删探针**

```bash
rm -rf frontend/e2e/probe
git status --porcelain
```
Expected: 无 `frontend/e2e/probe` 残留；`git status` 里不出现该路径。

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
