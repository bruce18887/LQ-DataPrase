/**
 * EP 样式落地回归网（@p2 增强）—— 按需注册那一刀的前置条件。
 *
 * 为什么不是像素截图：本仓**明确否决过**截图基线（`e2e/smoke/type-snapshot.spec.ts:11-13`、
 * `e2e/dashboard/dashboard-loading.spec.ts:105-108`，且 git 里 0 个 PNG 基线）。这里用可判定
 * 的等价物：样式没落地时，DOM 里的 `el-*` class 在**已加载样式表里没有任何规则指向它** ——
 * 这是「漏了某件 style/css」唯一的机器可读形状，比肉眼比对像素更早、也更便宜。
 *
 * 三层判据：
 *   1) 遍历五个路由，收集 DOM 出现过的全部 `el-*` class token → 没有任何规则指向它的那些，
 *      必须逐个落在下面的冻结名单里；名单外的新面孔 = 某件的样式没进来
 *      （EP 自己就会发一批「只在复合选择器里出现」或「按列号动态生成」的类，见
 *      KNOWN_UNCOVERED 与 FAMILY_PATTERNS 上的说明）
 *   2) 交互件（loading 遮罩、message、message-box、dialog 遮罩、popper）在自动化里不一定要
 *      点得到，但它们的规则必须在表里 —— 按名字逐个查
 *   3) 计算样式抽查（按钮圆角/内距/边框与高度、表头底色、select wrapper 的 padding/圆角/min-height）：
 *      规则在表里但**没落到元素上**（例如被更高优先级的覆盖层打掉）也能抓到
 *   4) 反空自证：把语料换成一条**哨兵规则**再跑同一谓词，覆盖必须整体转红 —— 证明这条绊线
 *      不是恒绿。（不能用 `sheet.disabled` 做这件事：它只让规则不生效，`cssRules` 里的
 *      selector 一条不少，文本匹配照样全绿。）
 *
 * 跑（本轮实测口径）：
 *   cd frontend && E2E_PW_ARGS="--project=P2" node ../scripts/e2e_pool.mjs --slots=1 -- \
 *     e2e/theme/element-plus-styles.spec.ts
 */
import { expect, test, type Page } from '@playwright/test'

import { gotoApp } from '../helpers/nav'

/** 交互件的规则名（点不点得到都要在表里）。 */
const RULE_CHECKS = [
  '.el-button',
  '.el-select',
  '.el-table',
  '.el-form-item',
  '.el-tag',
  '.el-loading-mask',
  '.el-message',
  '.el-message-box',
  '.el-overlay',
  '.el-dialog',
  '.el-popper',
  '.el-select-dropdown__item',
  '.el-tabs__item',
  '.el-collapse-transition-enter-active',
]

/** 遍历后必须见过的 token（防「一个 el-* 都没渲染所以全绿」）。 */
const MUST_SEE = ['el-button', 'el-table', 'el-select', 'el-tag', 'el-icon', 'el-input']

/** 五个路由：都是普通测试账号可达的页面，覆盖表格/下拉/表单/卡片/空态。 */
const TOUR = ['/data', '/analysis', '/dashboard', '/settings', '/sftp']

/**
 * 两类「EP 自己发出来的 class，但结构上不可能有独立规则」，按**家族**排除而不是逐个点名：
 * 它们随渲染列数与动画相位变，进冻结名单就是 flake 生成器（实测同一页两次跑就差两条
 * el-loading-fade-*）。
 */
const FAMILY_PATTERNS = [
  /^el-table_\d+_column_\d+$/, // EP 为每列生成的 id 类
  /^el-[a-z0-9-]+-(enter|leave)-(from|to|active)$/, // Vue 过渡相位
]

/**
 * 2026-10-28 实测：整包样式下这些类在 EP 的 CSS 里没有任何独立规则
 * （逐个对 node_modules/element-plus/dist/index.css 正则核过，命中数 0 —— 它们是
 * `.el-tag` 之类的默认态或只出现在复合选择器里的挂载点，不是漏样式）。
 * 名单之外的新面孔 = 某件的样式真的没进来。
 */
const KNOWN_UNCOVERED = [
  'el-col',
  'el-form--default',
  'el-form--label-right',
  'el-input--prefix',
  'el-input--suffix',
  'el-scrollbar__view',
  'el-select--default',
  'el-select__icon',
  'el-tab-pane',
  'el-table--layout-fixed',
  'el-table--scrollable-x',
  'el-tag--light',
  'el-tooltip__trigger',
  'el-upload--text',
]

function novelUncovered(uncovered: string[]): string[] {
  return uncovered.filter(
    (t) => !FAMILY_PATTERNS.some((re) => re.test(t)) && !KNOWN_UNCOVERED.includes(t)
  )
}

interface ProbeArg {
  ruleChecks: string[]
  mustSee: string[]
  /** 反空自证：不看真的样式表，只喂一条必然对不上的哨兵规则。 */
  synthesizeEmptyCorpus?: boolean
}

interface ProbeOut {
  tokens: number
  sheets: number
  rules: number
  uncovered: string[]
  missingRules: string[]
  seenMusts: string[]
}

/** 自包含：作为变量传给 page.evaluate，不能引用模块作用域。 */
function probeBody(arg: ProbeArg): ProbeOut {
  const tokens = new Set<string>()
  for (const el of Array.from(document.querySelectorAll('[class]'))) {
    for (const c of Array.from(el.classList)) if (/^el-[a-z0-9]/.test(c)) tokens.add(c)
  }
  const sheets = Array.from(document.styleSheets)
  const selectors: string[] = []
  let sheetCount = 0
  if (arg.synthesizeEmptyCorpus) {
    // 唯一一条哨兵规则：真 DOM 里不可能有这个名字 ⇒ 覆盖判据必须整体转红
    selectors.push('.el-sentinel-not-a-real-component')
    sheetCount = sheets.length
  } else {
    for (const sh of sheets) {
      let rules: CSSRuleList | null = null
      try {
        rules = sh.cssRules
      } catch {
        rules = null
      }
      if (!rules) continue
      sheetCount += 1
      for (const r of Array.from(rules)) {
        const st = (r as CSSStyleRule).selectorText
        if (st) selectors.push(st)
        const grp = r as CSSGroupingRule
        if (grp.cssRules) {
          for (const q of Array.from(grp.cssRules)) {
            const st2 = (q as CSSStyleRule).selectorText
            if (st2) selectors.push(st2)
          }
        }
      }
    }
  }
  const blob = selectors.join('\n')
  const hit = (name: string) => {
    const esc = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return new RegExp('\\.' + esc + '(?![\\w-])').test(blob)
  }
  return {
    tokens: tokens.size,
    sheets: sheetCount,
    rules: selectors.length,
    uncovered: Array.from(tokens)
      .filter((t) => !hit(t))
      .sort(),
    missingRules: arg.ruleChecks.map((c) => c.slice(1)).filter((c) => !hit(c)),
    seenMusts: arg.mustSee.filter((m) => tokens.has(m)),
  }
}

/** 遍历五个路由并累积 probe（每页各跑一次，最后取并集）。 */
async function tourProbe(page: Page): Promise<{ uncovered: string[]; seenMusts: string[]; rules: number; sheets: number }> {
  const uncovered = new Set<string>()
  const seenMusts = new Set<string>()
  let rules = 0
  let sheets = 0
  for (const route of TOUR) {
    await gotoApp(page, route)
    const one = await page.evaluate(probeBody, { ruleChecks: RULE_CHECKS, mustSee: MUST_SEE })
    rules += one.rules
    sheets = Math.max(sheets, one.sheets)
    for (const t of one.uncovered) uncovered.add(t)
    for (const m of one.seenMusts) seenMusts.add(m)
  }
  return { uncovered: [...uncovered].sort(), seenMusts: [...seenMusts].sort(), rules, sheets }
}

test.describe('@theme Element Plus 样式落地回归网', { tag: ['@p2', '@theme'] }, () => {
  test('@p2 日模式：DOM 里每个 el-* class 都有样式规则兜着，交互件规则齐全', async ({ page }) => {
    const out = await tourProbe(page)
    expect(out.sheets, '样式表必须已加载').toBeGreaterThan(0)
    expect(out.rules, '规则总量为 0 说明探针取不到 cssRules').toBeGreaterThan(2000)
    expect(
      novelUncovered(out.uncovered),
      `这些 el-* class 没有任何样式规则，且不在冻结名单里：${novelUncovered(out.uncovered).join(', ')}`
    ).toEqual([])
    expect(out.seenMusts).toEqual([...MUST_SEE].sort())
    const single = await page.evaluate(probeBody, { ruleChecks: RULE_CHECKS, mustSee: MUST_SEE })
    expect(single.missingRules).toEqual([])
  })

  test('@p2 夜模式：同一套判据（主题覆盖层不得把 EP 本体样式换掉）', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('theme', 'night'))
    const out = await tourProbe(page)
    expect(novelUncovered(out.uncovered)).toEqual([])
    expect(out.seenMusts).toEqual([...MUST_SEE].sort())
    const single = await page.evaluate(probeBody, { ruleChecks: RULE_CHECKS, mustSee: MUST_SEE })
    expect(single.missingRules).toEqual([])
  })

  test('@p2 计算样式抽查：按钮/表头/下拉真的拿到了盒模型', async ({ page }) => {
    await gotoApp(page, '/data')
    // /data 第一个 `.el-button` 是 text 型（EP 给它的边框就是 0），盒模型判据要挑实心那颗
    const btn = page.locator('.el-button:visible:not(.is-text):not(.is-link)').first()
    await expect(btn).toBeVisible({ timeout: 15_000 })
    const box = await btn.evaluate((el) => {
      const s = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      return {
        radius: s.borderTopLeftRadius,
        padTop: s.paddingTop,
        border: s.borderTopWidth,
        h: Math.round(r.height),
      }
    })
    // 漏样式的形状是确定的：圆角 0px、内距 0px、边框 0px、高度≈行高（EP medium 按钮 32px）。
    // 刻意不查 backgroundColor：夜模式的主题覆盖层会改按钮底色，查它等于把两件事混一条判据。
    expect(box.radius).not.toBe('0px')
    expect(box.padTop).not.toBe('0px')
    expect(box.border).not.toBe('0px')
    expect(box.h).toBeGreaterThanOrEqual(30)

    const th = page.locator('.el-table th:visible').first()
    await expect(th).toBeVisible({ timeout: 15_000 })
    const headBg = await th.evaluate((el) => getComputedStyle(el).backgroundColor)
    expect(headBg, '表头背景透明 = el-table 的 CSS 没进来').not.toBe('rgba(0, 0, 0, 0)')

    // 下拉换到分析页：/data 上的 el-select 只有 banner 里收起态那几颗（DOM 在、没画出来）。
    // 判据打在 EP 自己给的 wrapper 三个声明上，避免被控件 size（分析页是 small=24px）带偏。
    await gotoApp(page, '/analysis')
    const wrap = page.locator('.el-select[data-file-picker="single"] .el-select__wrapper')
    await expect(wrap).toBeVisible({ timeout: 15_000 })
    const box2 = await wrap.evaluate((el) => {
      const s = getComputedStyle(el)
      return { pad: s.paddingLeft, radius: s.borderTopLeftRadius, minH: s.minHeight }
    })
    expect(box2.pad, 'wrapper 内距 0 = el-select 的 CSS 没进来').not.toBe('0px')
    expect(box2.radius, 'wrapper 圆角 0 = el-select 的 CSS 没进来').not.toBe('0px')
    // EP 三档 size 的 min-height 是定值（large 40 / default 32 / small 24）；没样式时是 0px/auto
    expect(['40px', '32px', '24px']).toContain(box2.minH)
  })

  test('@p2 反空自证：换成一条哨兵规则，同一谓词必须立刻报出全部没兜住的 class', async ({ page }) => {
    await gotoApp(page, '/data')
    const clean = await page.evaluate(probeBody, { ruleChecks: RULE_CHECKS, mustSee: MUST_SEE })
    expect(novelUncovered(clean.uncovered)).toEqual([])
    expect(clean.tokens, 'DOM 里一个 el-* 都没有 ⇒ 下面的判据会比一个空集合').toBeGreaterThan(20)
    const off = await page.evaluate(probeBody, {
      ruleChecks: RULE_CHECKS,
      mustSee: MUST_SEE,
      synthesizeEmptyCorpus: true,
    })
    // 哨兵 corpus 下 rules 只有 1 条：证明语料真的来自样式表，而不是写死的字符串
    expect(off.rules).toBe(1)
    expect(off.tokens).toBe(clean.tokens)
    expect(off.uncovered.length, '换成空语料仍然满覆盖 ⇒ 这条绊线是恒绿的').toBeGreaterThan(0)
    expect(off.uncovered).toContain('el-button')
    expect(off.missingRules.sort()).toEqual([...RULE_CHECKS.map((c) => c.slice(1))].sort())
  })
})
