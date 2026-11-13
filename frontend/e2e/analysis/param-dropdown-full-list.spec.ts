import { expect, test } from '@playwright/test'

import { gotoApp } from '../helpers/nav'
import {
  listParams,
  PARAM_POPPER_SINGLE,
  selectAnalysisFile,
  selectParam,
} from '../helpers/params'

/**
 * 用户报的原话是「参数选择框为啥只能看前 300 个测试项」。旧实现是 `el-select` +
 * `DROPDOWN_RENDER_CAP=300` 的显式截断（EP 2.14 的 el-select 不虚拟化，每个 el-option
 * 是完整组件实例，原样挂载即冻结主线程），本批换成 `el-select-v2` 的虚拟窗口。
 *
 * 三条判据各挡一种回退：
 *  - footer 逐字等于「共 N 项」且 N = 响应条数：挡「把截断偷偷放回来」。截断时 N 仍会写
 *    成全量，所以光这条不够，必须配合第 3 条
 *  - 搜到列表末尾那一项并选中：挡「过滤这一步本身退化成只在已渲染子集里找」
 *    （把 v2 的 `filter-method` 当成真过滤器用、或 `:options` 改回喂窗口那几行，都是这种）。
 *    旧的那个「截断到 300」的 bug **不由它兜**：旧实现是先在完整集合上过滤、再截断到 300，
 *    拿整个参数名去搜照样命中（2026-11-13 复审实测：迁移前这条也过）。截断那一半由
 *    第 1 条的 footer 文案 + 第 3 条的滚到底兜
 *  - 不输入关键词时滚到底、末尾项进入 DOM 且可见：挡「虚拟窗口没生效 / 只渲染前 N」
 *
 * 夹具刻意选 `BPD93204_FT1_ETS163550_12252024.csv`（2026-11-13 现测 **1723** 个参数，
 * 全仓最大，正好是用户报的那个数）：默认那发文件只有 41 项，三条判据里只有第一条会红，
 * 「只能看前 300」这个具体形状就没人兜。参数条数由第 3 条用例的前提断言钉住，
 * 夹具哪天变小就是红而不是静默跳过（换夹具，别删用例）。
 *
 * 参数全集一律走 `listParams()`（响应侧，见 helpers/paramList.ts），**不是**数 DOM ——
 * 虚拟窗口里 DOM 只有十来行，数条数从本批起不再是「列表有多少项」的判据。
 * 「下拉真的把响应里那些项渲染出来了」这一维由本文件兜（paramList.ts 的捕获与产品同源）。
 */
const POPPER = PARAM_POPPER_SINGLE
const BIG_FILE = 'BPD93204_FT1_ETS163550_12252024'

/**
 * 旧实现的渲染封顶。写死数字而**不 import** `DROPDOWN_RENDER_CAP`：那个常量本批 Task 9 就删，
 * 判据要活过它 —— 删完还留着引用，等于把这条用例和一段死代码焊在一起。
 */
const LEGACY_RENDER_CAP = 300

/**
 * 虚拟窗口允许出现的最大行数。上界由 EP 默认值推出：`select-v2/src/defaults.mjs` 的
 * `height:274 / itemHeight:34` ≈ 9 行，加 overscan 实测 11 行（2026-11-13）。留到 20 是
 * 给「以后有人调高面板」的余量；真正的判据是「远小于全集」，不是「等于 11」。
 *
 * 它同时是「不虚拟化、但也不截断」这种回退的唯一哨兵：那种实现下 DOM 会等于全集
 * （1723 行），这条必红，而上面两条都照样绿。
 */
const MAX_WINDOW_ROWS = 20

/** 本实例 popper 里的选项行（v2 的虚拟窗口只渲染这几行） */
function paramItems(page: import('@playwright/test').Page) {
  return page.locator(`.el-popper.${POPPER}[aria-hidden="false"] .el-select-dropdown__item`)
}

/**
 * 末项在窗口里的状态：`{ inDom, inViewport }`。
 *
 * 为什么走 DOM 而不是 Playwright 定位器：`:text-is()` 只匹配**最小**的那个元素，而选项行
 * 里面还有 `.param-option > .param-name > span` 三层，`li:text-is("X")` 永不命中
 * （2026-11-13 实测假红一次）；`hasText` 反过来是子串匹配，'VTH' 会冒充 'VTH_2'。
 * 逐字比较只能在 DOM 侧做，`toBeVisible()` 也答不出「被滚动视口裁掉了」这一半。
 */
function tailRowState(page: import('@playwright/test').Page, last: string) {
  return page.evaluate(({ popper, target }) => {
    // 与 `helpers/params.ts` 的 visibleOptions 同一套谓词（`[aria-hidden="false"]`）：
    // 本文件里两种写法并存，将来 EP 改了绑定方式就会只红一半，根因看不出来。
    const panel = document.querySelector(`.el-popper.${popper}[aria-hidden="false"]`)
    const rows = panel ? [...panel.querySelectorAll('.el-select-dropdown__item')] : []
    const hit = rows.find((r) => (r.textContent ?? '').trim() === target)
    if (!hit) return { inDom: false, inViewport: false }
    // 最近的可滚祖先 = 虚拟列表的视口（不写死 EP 内部类名，v1/v2 都拿得到）。
    // body/documentElement 必须排除：整页可滚时它们同样满足 scrollHeight>clientHeight，
    // 一旦窗口自身没撑起来，末项就会被「页面滚动的位置」判成「在窗口里可见」—— 那是假绿，
    // 而本用例唯一承重的就是「窗口滚到了末尾」。找不到合格祖先 ⇒ inViewport:false ⇒ 红。
    let vp: HTMLElement | null = hit.parentElement
    while (vp && vp.scrollHeight <= vp.clientHeight + 1 && vp !== document.body) {
      vp = vp.parentElement
    }
    if (!vp || vp === document.body || vp === document.documentElement) {
      return { inDom: true, inViewport: false }
    }
    const a = vp.getBoundingClientRect()
    const b = hit.getBoundingClientRect()
    return { inDom: true, inViewport: b.top >= a.top - 1 && b.bottom <= a.bottom + 1 }
  }, { popper: POPPER, target: last })
}

test.describe('@p1 参数下拉可浏览全部测试项', { tag: ['@p1', '@analysis'] }, () => {
  test.use({ storageState: 'e2e/.auth/admin.json' })

  test.beforeEach(async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, BIG_FILE)
  })

  test('footer 说出全集规模，且没有「仅显示前 N」这句话', async ({ page }) => {
    // 先把参数全集结算到手再开下拉：`selectAnalysisFile` 只等到「新文件的请求发出去」
    // （pickTabFileAndWaitCompute 等的是 request 不是 response），先开下拉会读到
    // 「共 0 项」—— 那是用例自己的竞态，2026-11-13 实测红过一次。
    const all = await listParams(page)
    const sel = page.locator('.param-selector .el-select')
    await sel.click()
    const footer = page.locator(`.el-popper.${POPPER}[aria-hidden="false"] .param-count-hint`)
    await expect(footer).toBeVisible()
    // 只这一句就够：`toHaveText` 拿**整串**比，footer 里再出现「仅显示前 300」之类的
    // 任何多余文字它自己就红，失败信息里连被截断的原文一起打出来。以前另配的一条
    // `not.toContainText('仅显示前')` 被它严格蕴含，是装饰性判据，已删（复审 #6）。
    await expect(footer).toHaveText(`共 ${all.length} 项`)
  })

  test('搜到列表最后一项并选中它', async ({ page }) => {
    const all = await listParams(page)
    const last = all[all.length - 1]
    await selectParam(page, last)
    // 逐字相等而不是 toContainText：`selectParam` 的 hasText 是子串匹配，
    // 「VTH」会命中 'VTH_2'，弱判据在这里会变成恒真。
    await expect(page.locator('.param-selector .el-select__placeholder')).toHaveText(last)
  })

  test('不输入关键词时滚到底能看见最后一项', async ({ page }) => {
    const all = await listParams(page)
    const last = all[all.length - 1]
    const items = paramItems(page)
    await page.locator('.param-selector .el-select').click()
    await expect(items.first()).toBeVisible({ timeout: 15_000 })

    // 前提：夹具必须比旧封顶大，否则「取消截断」这件事根本没进判据范围。
    // 红了就换更大的夹具，不要把它改成 skip —— skip 等于把这条判据删掉。
    expect(all.length, `夹具 ${BIG_FILE} 的参数数应当 > 旧封顶 ${LEGACY_RENDER_CAP}`)
      .toBeGreaterThan(LEGACY_RENDER_CAP)

    await items.first().hover()
    await page.mouse.wheel(0, 200_000)
    await expect
      .poll(() => tailRowState(page, last), {
        timeout: 10_000,
        message: `滚到底以后末项 "${last}" 必须既在窗口里又在视口里（inDom / inViewport 分开报，` +
          '分不清就是用例自己坏了）',
      })
      .toEqual({ inDom: true, inViewport: true })
    // 「虚拟窗口」这四个字只有这条兜得住：行数回到全量即等于虚拟化没生效，而上面两条
    // 在「不虚拟化但也不截断」的实现下一样会绿。Task 5 放行实测 11 行 / 滚到底 310ms。
    expect(await items.count(), 'DOM 里只该有虚拟窗口那几行').toBeLessThan(MAX_WINDOW_ROWS)
  })
})
