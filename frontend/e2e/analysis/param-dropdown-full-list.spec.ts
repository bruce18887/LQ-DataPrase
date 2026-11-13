import { expect, test } from '@playwright/test'

import { popperOf } from '../helpers/elplus'
import { gotoApp } from '../helpers/nav'
import {
  listParams,
  PARAM_POPPER_SINGLE,
  selectAnalysisFile,
  selectParam,
} from '../helpers/params'
import { expectWindowRows, tailRowState, windowItems } from '../helpers/selectV2'

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
 *
 * `tailRowState` 与 `MAX_WINDOW_ROWS` 本体住在 `helpers/selectV2.ts`（Task 9B 提出去给五族共用，
 * 此前 Task 9C 在 `view-data.spec.ts` 复制了第二份界值）；本文件那四条判据一条没变弱、没变形。
 */
const POPPER = PARAM_POPPER_SINGLE
const BIG_FILE = 'BPD93204_FT1_ETS163550_12252024'

/**
 * 旧实现的渲染封顶。写死数字而**不 import** `DROPDOWN_RENDER_CAP`：那个常量已在批1 Task 9 删除，
 * 判据要活过它 —— 删完还留着引用，等于把这条用例和一段死代码焊在一起。
 */
const LEGACY_RENDER_CAP = 300

/** 本实例 popper 里的选项行（v2 的虚拟窗口只渲染这几行） */
function paramItems(page: import('@playwright/test').Page) {
  return windowItems(page, POPPER)
}

/** 本实例 popper 的 footer 文案（两支措辞的判据都从这一句逐字比） */
function paramFooter(page: import('@playwright/test').Page) {
  return popperOf(page, POPPER).locator('.param-count-hint')
}

test.describe('@p1 参数下拉可浏览全部测试项', { tag: ['@p1', '@analysis'] }, () => {
  // 登录态**不在这里给**：四个业务项目的 `use.storageState` 已经是 `ADMIN_STATE`
  // （playwright.config.ts:121/130/137/144），那个常量由 helpers/slot.ts 按 slot.json 算。
  // 这里曾写过字面量 `'e2e/.auth/admin.json'`：串行档两条路等价所以全绿，池档里 slot 的
  // admin.json 在 `C:\lqdp-e2e\slots\<run>\slotN\auth\`，字面量读到的却是上一次串行跑的**旧
  // SECRET_KEY 签的 token** ⇒ 401 弹回 /login ⇒ 五条用例全红在 `gotoApp` 的 `.main-layout`
  // 上（2026-11-14 批1 收口全量池实测，独占 slot 复跑仍红）。别把这类"路径写死"再放回来。
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
    const footer = paramFooter(page)
    await expect(footer).toBeVisible()
    // 只这一句就够：`toHaveText` 拿**整串**比，footer 里再出现「仅显示前 300」之类的
    // 任何多余文字它自己就红，失败信息里连被截断的原文一起打出来。以前另配的一条
    // `not.toContainText('仅显示前')` 被它严格蕴含，是装饰性判据，已删（复审 #6）。
    await expect(footer).toHaveText(`共 ${all.length} 项`)
  })

  test('搜索态 footer 改口「匹配 N 项」，N 是响应侧命中数', async ({ page }) => {
    const all = await listParams(page)
    // '1' 在这份 1,723 项的夹具上命中约 585 项（2026-11-13 实测）：既要真的命中一些，
    // 又必须**少于**全集，否则「匹配」与「共」两支在同一个数上分不开（红了就换关键词，别删用例）。
    const kw = '1'
    // 命中数在测试侧独立算一遍（子串 + 忽略大小写），不 import src 的 filterByKeyword：
    // 判据与实现异源，否则产品把过滤写坏时这条跟着一起绿。
    // kw 也在**测试侧**归一化一次（与产品同语义、不同实现）：'1' 恰好是小写才让
    // `includes(kw)` 成立，不归一化的话将来有人把关键词换成大写就是假红。
    const matched = all.filter((p) => p.toLowerCase().includes(kw.toLowerCase()))
    expect(matched.length, `夹具里没有含 "${kw}" 的参数`).toBeGreaterThan(0)
    expect(matched.length, `关键词 "${kw}" 命中了整个夹具，两支文案分不开`).toBeLessThan(all.length)

    const sel = page.locator('.param-selector .el-select')
    await sel.click()
    // `fill` 会派发 input 事件 ⇒ v2 的 filterMethod 照样被调用（2026-11-13 Task 8 实测，
    // 逐键 pressSequentially 不是必需）
    await sel.locator('input').first().fill(kw)
    const footer = paramFooter(page)
    await expect(footer).toBeVisible()
    await expect(footer).toHaveText(`匹配 ${matched.length} 项`)
  })

  test('纯空格等于没输入：footer 必须是「共 N 项」（N = 全集，不是某个命中数）', async ({ page }) => {
    const all = await listParams(page)
    const sel = page.locator('.param-selector .el-select')
    await sel.click()
    // `hasKeyword` 判的是 trim() 后非空，而 `buildSelectView` 对纯空格返回全量 `total`
    // ⇒ 去掉那个 trim() 会让 footer 改口「匹配 1723 项」（拿全集冒充命中数）。
    // 本条就是那一格的判据：2026-11-13 现测判别力 —— 摘掉 trim() 这条必红。
    await sel.locator('input').first().fill('   ')
    await expect(paramFooter(page)).toHaveText(`共 ${all.length} 项`)
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
      .poll(() => tailRowState(page, POPPER, last), {
        timeout: 10_000,
        message: `滚到底以后末项 "${last}" 必须既在窗口里又在视口里（inDom / inViewport 分开报，` +
          '分不清就是用例自己坏了）',
      })
      .toEqual({ inDom: true, inViewport: true })
    // 「虚拟窗口」这四个字只有这条兜得住：行数回到全量即等于虚拟化没生效，而上面两条
    // 在「不虚拟化但也不截断」的实现下一样会绿。Task 5 放行实测 11 行 / 滚到底 310ms。
    await expectWindowRows(items, all.length, '参数下拉')
  })
})
