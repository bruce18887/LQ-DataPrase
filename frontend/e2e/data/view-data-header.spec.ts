import { test, expect, type Page } from '@playwright/test'
import { SEEDED_FILES } from '../fixtures/test-data'
import { openViewTab } from '../helpers/viewTab'

/**
 * T3：查看数据表头的两行布局（真实渲染判据）。
 *
 * 只有浏览器能证明三件事：headerName 里的 \n 被 pre-line 保留、::first-line 真的让
 * 次行变成小字、列宽收窄到 150 后仍在首屏外可滚达。T2（browserColumns.spec.ts）
 * 只钉 colDef 的形状，证明不了这些渲染事实。
 */

/** 横向渐进滚动直到 probe 渲染（与 view-data.spec.ts 的 scrollGridUntil 同形） */
async function scrollGridUntil(page: Page, probe: string) {
  await page.locator('.ag-header-viewport').evaluate(async (el, sel) => {
    const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
    let max = 0
    for (let i = 0; i < 100; i++) {
      max = el.scrollWidth - el.clientWidth
      if (max > 0 || document.querySelector(sel)) break
      await wait(100)
    }
    for (let x = 0; max > 0; x += 400) {
      el.scrollLeft = Math.min(x, max)
      await wait(60)
      if (document.querySelector(sel) || x >= max) return
    }
  }, probe)
}

async function readTwoLineHeader(page: Page) {
  await openViewTab(page, SEEDED_FILES.CTA8280F_FT)
  await expect(page.locator('.ag-row').first()).toBeVisible({ timeout: 30_000 })
  // 系统列在前，有规格的测试列首屏在横向视口外（表头虚拟化），先滚到它渲染
  await scrollGridUntil(page, '.ag-header-cell.dp-header-2l')
  const header = page.locator('.ag-header-cell.dp-header-2l').first()
  await expect(header).toBeVisible({ timeout: 10_000 })
  const textSpan = header.locator('.ag-header-cell-text')

  const text = await textSpan.innerText()
  // 行盒几何：按字符 Range 的 top 分组（换行符自身没有矩形）
  const geom = await textSpan.evaluate((el) => {
    const node = el.firstChild as Text
    const s = node.textContent ?? ''
    const tops = new Set<number>()
    for (let i = 0; i < s.length; i++) {
      const r = document.createRange()
      r.setStart(node, i)
      r.setEnd(node, i + 1)
      const b = r.getBoundingClientRect()
      if (b.height > 0) tops.add(Math.round(b.top))
    }
    return [...tops].sort((a, b) => a - b)
  })
  const styles = await textSpan.evaluate((el) => {
    const base = getComputedStyle(el)
    const firstLine = getComputedStyle(el, '::first-line')
    return {
      baseSize: parseFloat(base.fontSize),
      firstLineSize: parseFloat(firstLine.fontSize),
      baseColor: base.color,
      firstLineColor: firstLine.color,
    }
  })
  const width = await header.evaluate((el) => (el as HTMLElement).offsetWidth)
  return { text, geom, styles, width }
}

for (const theme of ['light', 'night'] as const) {
  test.describe(`数据管理 → 查看数据两行表头（${theme}）`, { tag: ['@data'] }, () => {
    test(`@p2 有规格列：次行小字显示范围，默认列宽 150`, async ({ page }) => {
      if (theme === 'night') {
        await page.addInitScript(() => localStorage.setItem('theme', 'night'))
      }
      const { text, geom, styles, width } = await readTwoLineHeader(page)
      if (theme === 'night') {
        await expect
          .poll(() => page.evaluate(() => document.documentElement.getAttribute('data-theme')))
          .toBe('night')
      }

      const lines = text.split('\n')
      expect(lines.length, `表头应为两行，实际：${JSON.stringify(text)}`).toBe(2)
      expect(lines[1]).toMatch(/^\[.+, .+\]$/)
      expect(geom.length, '真实行盒应恰好两行').toBe(2)
      expect(styles.firstLineSize).toBeGreaterThan(styles.baseSize)
      expect(styles.firstLineColor, '首行与次行不能同色').not.toBe(styles.baseColor)
      expect(width, '默认列宽应为 150px（v35 无 defaultColWidth，不配会退回 200）').toBe(150)
    })
  })
}
