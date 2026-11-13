import { expect, test } from '@playwright/test'

import { gotoApp } from '../helpers/nav'
import { listParams, selectAnalysisFile, selectParam } from '../helpers/params'

/**
 * 用户报的原话是「参数选择框为啥只能看前 300 个测试项」。旧实现是 `el-select` +
 * `DROPDOWN_RENDER_CAP=300` 的显式截断（EP 2.14 的 el-select 不虚拟化，每个 el-option
 * 是完整组件实例，原样挂载即冻结主线程），本批换成 `el-select-v2` 的虚拟窗口。
 *
 * 三条判据各挡一种回退：
 *  - footer 的「共 N 项」：挡「把截断偷偷放回来」的**说出来**那一半（footer 文案里
 *    不许再有「仅显示前」）——截断时 total 仍等于全量，所以它必须配合第 3 条
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
 * 虚拟窗口里 DOM 只有约 8 行，数条数从本批起不再是「列表有多少项」的判据。
 * 「下拉真的把响应里那些项渲染出来了」这一维由本文件兜（paramList.ts 的捕获与产品同源）。
 */
const POPPER = 'dp-param-popper-single'
const BIG_FILE = 'BPD93204_FT1_ETS163550_12252024'

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
    const panel = document.querySelector(`.el-popper.${popper}:not([aria-hidden="true"])`)
    const rows = panel ? [...panel.querySelectorAll('.el-select-dropdown__item')] : []
    const hit = rows.find((r) => (r.textContent ?? '').trim() === target)
    if (!hit) return { inDom: false, inViewport: false }
    // 最近的可滚祖先 = 虚拟列表的视口（不写死 EP 内部类名，v1/v2 都拿得到）
    let vp: HTMLElement | null = hit.parentElement
    while (vp && vp.scrollHeight <= vp.clientHeight + 1) vp = vp.parentElement
    if (!vp) return { inDom: true, inViewport: false }
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
    await expect(footer).not.toContainText('仅显示前')
    // 逐字整句：footer 里的数字必须就是响应里的条数（toHaveText 会重试到组件收到那发响应）
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

    // 前提：夹具必须比旧封顶（300）大，否则「取消截断」这件事根本没进判据范围。
    // 红了就换更大的夹具，不要把它改成 skip —— skip 等于把这条判据删掉。
    expect(all.length, `夹具 ${BIG_FILE} 的参数数应当 > 旧封顶 300`).toBeGreaterThan(300)

    await items.first().hover()
    await page.mouse.wheel(0, 200_000)
    // Q3/Q4 两个临时打印是 Task 5 Step 1.5 的放行判据（实测 11 行 / 310ms），核对完摘掉：
    // 常驻的 console.log 会把全量池日志弄脏，而「滚到底」这件事由下面的 poll 承重

    await expect
      .poll(() => tailRowState(page, last), {
        timeout: 10_000,
        message: `滚到底以后末项 "${last}" 必须既在窗口里又在视口里（inDom / inViewport 分开报，` +
          '分不清就是用例自己坏了）',
      })
      .toEqual({ inDom: true, inViewport: true })
    // 窗口行数必须远小于全集，否则「虚拟窗口」这个词没被验到（放行判据 Q3 的常驻版本）
    expect(await items.count(), 'DOM 里只该有虚拟窗口那几行').toBeLessThan(40)
  })
})
