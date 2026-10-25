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
})
