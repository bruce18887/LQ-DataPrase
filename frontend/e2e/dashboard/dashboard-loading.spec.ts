import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { waitLoadingGone } from '../helpers/charts'
import { SEEDED_FILES } from '../fixtures/test-data'

/**
 * 切文件时的加载态必须**盖在数据区之上**（2026-10-25 产品侧修复）。
 *
 * 修前的形状：加载态是数据面板的兄弟占位（`v-else-if="loading"` 的一条 min-height:200px 空 div），
 * 而面板走独立的 `v-if="data"` ⇒ 换文件时用户看到的是「一条转圈的空条 + 下面整屏上一个文件的
 * 数字」，而且旧行仍可点（`TestItemOverviewSection` 的 `@row-click` 会拿**新** fileId 配**旧**参数名
 * 跳分析页）。`settings/cpk-thresholds.spec.ts` 那条「分桶依赖真红」就是这个形状的副产物。
 *
 * 判据不赌时序：用 `page.route` 把 `/summary/` 挂 1.5s（先例 `settings/chart-memory.spec.ts:277`），
 * 「加载中」这段状态被人为拉长且必然出现。承重形状有三条，缺一不可：
 * ① 遮罩在 `.dash-data` **里面**（在兄弟占位上就抓不到）；
 * ② 命中测试：旧行中心点上真正收到指针事件的是遮罩本身（挡住误点，也证明旧行确实还在 DOM 里被盖着）；
 * ③ 遮罩不是透明的（alpha ≥ 0.5）——否则「变暗」这件事用户根本看不见。
 * 对照组：空闲态 `.dash-data` 内遮罩数为 0，防止「恒有遮罩」这种写法蒙过 ①。
 */

const SUMMARY_ROUTE = /\/api\/v1\/summary\//
const HOLD_MS = 3000
const MASK = '.dash-data .el-loading-mask'
const keyword = SEEDED_FILES.CTA8280F_FT.slice(0, 12)

/** `.overview-total` 里的「共 N 项」 */
async function shownItemCount(page: import('@playwright/test').Page): Promise<number> {
  const text = await page.locator('.overview-total').innerText()
  return Number((text.match(/共 (\d+) 项/) ?? [])[1] ?? -1)
}

test.describe('@p1 切文件时加载态覆盖数据区', { tag: ['@p1', '@dashboard'] }, () => {
  test('旧行被遮罩盖住且点不着；响应回来后遮罩消失、总项数换成新文件的', async ({ page }) => {
    test.slow()
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)
    await expect(async () => {
      expect(await shownItemCount(page), '仪表板首屏应已渲染总览行数').toBeGreaterThan(0)
    }).toPass({ timeout: 30_000 })

    const itemsBefore = await shownItemCount(page)
    // 前置：默认选中的文件必须不是目标文件，否则这次切换压根不发请求（遮罩也就无从出现）。
    // 槽库里的默认文件 = 最新 ready 的那份（实测是 BN281…CP1，179 项的目标文件不是它）。
    expect(await page.locator('.dash-file-select').innerText(),
      '默认文件已是目标 ⇒ 本用例的切换形状不成立').not.toContain(keyword)
    // 对照组：没有切换动作时不该有遮罩（否则本用例的 ① 等于没判据）
    await expect(page.locator(MASK)).toHaveCount(0)

    await page.route(SUMMARY_ROUTE, async (route) => {
      await new Promise((r) => setTimeout(r, HOLD_MS))
      await route.continue()
    })

    const select = page.locator('.dash-file-select')
    await select.click()
    await select.locator('input').fill(keyword)
    await page.locator('.dp-file-select-dropdown .el-select-dropdown__item')
      .filter({ hasText: keyword }).first().click()

    // ① 遮罩存在，且文案说明它在等什么（对用户可解释，而不是一个无字的灰块）
    const mask = page.locator(MASK)
    await expect(mask, '换文件后应在数据区之上出现加载遮罩').toBeVisible({ timeout: 5_000 })
    await expect(mask).toContainText(/正在加载所选文件/)

    // ③ 遮罩必须真的把内容压暗，且**两个主题都要压得住**（R7①）：
    //    night 是 element-plus-theme.css:454 的 rgba(26,26,46,.9)，light 走 EP 默认
    //    `--el-mask-color` = rgba(255,255,255,.9)。判据只钉「alpha ≥ 0.5」这个形状而不是颜色本身，
    //    所以同一条件在两个主题成立；哪天有人把遮罩调成半透明到看不见，这里会红。
    for (const theme of ['night', 'light']) {
      await page.evaluate((t) => document.documentElement.setAttribute('data-theme', t), theme)
      // 前提守卫：主题真的切过去了才谈"两个主题都判"，否则这条循环量两遍的是同一个主题。
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      const read = await page.locator(MASK).first().evaluate((el) => {
        const parts = getComputedStyle(el).backgroundColor.match(/[\d.]+/g) ?? []
        return { color: getComputedStyle(el).backgroundColor, alpha: parts.length >= 4 ? Number(parts[3]) : 0 }
      })
      expect(read.alpha, `${theme} 主题下遮罩背景=${read.color}，透明到等于没提示`).toBeGreaterThanOrEqual(0.5)
    }

    // ② 旧行仍在 DOM（这正是修前会被当成新数据的那批行），但真正收到点击的是遮罩
    const staleRow = page.locator('.overview-table .el-table__row').first()
    await staleRow.scrollIntoViewIfNeeded()
    const box = await staleRow.boundingBox()
    expect(box, '旧行应当还在 DOM 里（本用例测的是"盖住"而不是"清空"）').not.toBeNull()
    const hitClass = await page.evaluate(({ x, y }) => {
      const el = document.elementFromPoint(x, y)
      return el ? `${el.className}` : ''
    }, { x: box!.x + box!.width / 2, y: box!.y + box!.height / 2 })
    expect(hitClass, '旧行中心点收到的应该是遮罩，不是行本身').toContain('el-loading-mask')

    await expect(async () => {
      const n = await shownItemCount(page)
      expect(n, '总览应换成新文件的行数').toBeGreaterThan(0)
      expect(n).not.toBe(itemsBefore)
    }).toPass({ timeout: 30_000 })
    await expect(page.locator(MASK)).toHaveCount(0)

    await page.unroute(SUMMARY_ROUTE)
  })

  /**
   * 夜间模式下**遮罩与 spinner 的落点**回归。
   *
   * 口径说明：这条不是像素基线。本仓库明确不用 `toHaveScreenshot`
   * （理由原文在 `e2e/global/type-snapshot.spec.ts:8-12`：桌面端字体 hinting / 滚动条 /
   * 子像素渲染逐台不同，基线长期飘），走的是同一套「计算值 + 几何」判据。
   *
   * 钉的是这次产品改动里最容易无声退化的一件事：`.dash-data :deep(.el-loading-spinner)`
   * 的 `top: 120px`。EP 默认把 spinner 放在容器垂直 50% 处，而这块数据区两三千 px 高 ⇒
   * 修前用户只看到"整屏变暗"、看不到任何转圈。那条 CSS 一旦被删，页面**仍是绿的、遮罩仍在**，
   * 所以必须用几何判据把它按住：
   * ① spinner 落在首屏内（`window.scrollTo(0,0)` 后 bottom ≤ 视口高）；
   * ② 恒等式「距数据区顶 × 2 < 数据区高」——处在容器中点时左边 == 右边，必然不过；
   * ③ night 的遮罩底色必须是**深色**半透明（走 `element-plus-theme.css:454` 的
   *    rgba(26,26,46,.9)），亮度过半说明夜间规则没生效、等于用白纱糊黑底。
   * ④ 遮罩整块盖住总览表（覆盖关系，不是只盖住首屏）。
   */
  test('夜间模式：遮罩压住数据区、spinner 落在首屏内', async ({ page }) => {
    test.slow()
    await page.addInitScript(() => localStorage.setItem('theme', 'night'))
    await gotoApp(page, '/dashboard')
    await expect(async () => {
      expect(await shownItemCount(page), '夜模式首屏应已渲染总览').toBeGreaterThan(0)
    }).toPass({ timeout: 30_000 })
    // 前提守卫：主题没切成就无从谈"夜间"，这里先出声
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'night')
    expect(await page.locator('.dash-file-select').innerText(),
      '默认文件已是目标 ⇒ 这次切换不发请求').not.toContain(keyword)

    await page.route(SUMMARY_ROUTE, async (route) => {
      await new Promise((r) => setTimeout(r, HOLD_MS))
      await route.continue()
    })
    const select = page.locator('.dash-file-select')
    await select.click()
    await select.locator('input').fill(keyword)
    await page.locator('.dp-file-select-dropdown .el-select-dropdown__item')
      .filter({ hasText: keyword }).first().click()

    const mask = page.locator(MASK)
    await expect(mask, '夜模式换文件后应出现覆盖数据区的遮罩').toBeVisible({ timeout: 5_000 })
    await page.evaluate(() => window.scrollTo(0, 0))

    const maskBox = await mask.first().boundingBox()
    const spinner = mask.locator('.el-loading-spinner')
    const spinnerBox = await spinner.boundingBox()
    const vp = page.viewportSize()
    expect(maskBox, '遮罩量不到盒子').not.toBeNull()
    expect(spinnerBox, 'spinner 量不到盒子（被 CSS 移走了？）').not.toBeNull()
    expect(vp, '用例需要固定视口').not.toBeNull()

    // ① 首屏内看得见（容器 50% 的位置在这里必然出界）
    expect(spinnerBox!.y + spinnerBox!.height, 'spinner 掉到首屏之外，用户看不到"在加载"')
      .toBeLessThanOrEqual(vp!.height)
    // ② 恒等式：距数据区顶的两倍仍要小于整区高度 ⇒ 严格高于中点
    const fromTop = spinnerBox!.y - maskBox!.y
    expect(fromTop, 'spinner 贴到容器顶了（负偏移）').toBeGreaterThanOrEqual(40)
    expect(fromTop * 2, `spinner 在容器 ${Math.round((fromTop / maskBox!.height) * 100)}% 处，等于回了 EP 默认中点`)
      .toBeLessThan(maskBox!.height)
    // ③ 夜模式遮罩底色要够暗
    const bg = await mask.first().evaluate((el) => getComputedStyle(el).backgroundColor)
    const nums = (bg.match(/[\d.]+/g) ?? []).map(Number)
    expect(nums.length, `夜模式遮罩背景解析失败：${bg}`).toBeGreaterThanOrEqual(4)
    const luma = 0.299 * nums[0] + 0.587 * nums[1] + 0.114 * nums[2]
    expect(luma, `夜模式遮罩背景=${bg}，亮度 ${luma.toFixed(0)} 偏白（夜间规则没生效？）`).toBeLessThan(128)
    expect(nums[3], `夜模式遮罩背景=${bg} 太透明`).toBeGreaterThanOrEqual(0.5)
    // ④ 覆盖关系：总览表整块在遮罩之下
    const table = page.locator('.dash-data .overview-table')
    const tableBox = await table.boundingBox()
    expect(tableBox, '总览表应仍在 DOM 里').not.toBeNull()
    expect(maskBox!.y, '遮罩顶边没盖住总览表').toBeLessThanOrEqual(tableBox!.y)
    expect(maskBox!.y + maskBox!.height, '遮罩底边没盖住总览表')
      .toBeGreaterThanOrEqual(tableBox!.y + tableBox!.height)

    await expect(async () => {
      const n = await shownItemCount(page)
      expect(n).toBeGreaterThan(0)
    }).toPass({ timeout: 30_000 })
    await page.unroute(SUMMARY_ROUTE)
  })

  test('@p1 一次进页只发一份 UPH（卡片不再自取）', async ({ page }) => {
    // 回归：UphCard 曾在 uphData 还没落地时自己再 GET 同一个 file_id 的 UPH ——
    // DashboardPage 先写 data（:215）⇒ 卡片的 fileId 立刻变化，而那一刻 uphData 仍是
    // null ⇒ 它的 `if (fileId && !uphData) fetchUph()` 成立，于是一次进页打两份。
    // 现在数据与 loading/error 态都由页面单一持有，卡片只消费 props。
    // 计数器必须装在 goto 之前（lessons R2④：goto 之后再装会漏计前置阶段）。
    const uph: string[] = []
    page.on('request', (r) => {
      const url = r.url()
      if (/\/analysis\/uph\/(\?|$)/.test(url)) uph.push(url)
    })

    await gotoApp(page, '/dashboard')
    await expect(page.getByText('UPH 效率明细').first()).toBeVisible({ timeout: 30_000 })
    await page.waitForTimeout(2_000)

    expect(uph, `发出了 ${uph.length} 条 UPH 请求，应为 1 条：${JSON.stringify(uph)}`).toHaveLength(1)
  })
})
