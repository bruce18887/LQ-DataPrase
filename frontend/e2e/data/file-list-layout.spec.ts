import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'

/**
 * 文件列表页布局回归：125% 缩放（1920 屏 → 1536 CSS px）下的两处用户可见缺陷。
 *
 * 2026-11-23 实测根因：
 * ① 表头随页面滚走。`.content-area` 是页面滚动容器，el-table 未限高时表头只是普通行；
 *    吸顶的 `.tabs-wrapper` sticky 落点在 content-area 的 16px padding 之后 —— 页面一滚，
 *    表头被页签条盖住，还会在页签条上方露出一截（截图的「表头被挡住」）。
 *    修法：给 el-table 设 max-height（`calc(100vh - 320px)`），表头常驻、表体内部滚动。
 * ② 固定操作列透底。13 列 min-width 合计 1608px > 1536 视口下约 1270px 的表格可视宽，
 *    横向滚动时「上传时间 / 测试日期 / 大小」会滑到 `fixed="right"` 的操作列下面；
 *    操作列的 sticky 单元格是 `background: inherit`，而本表行底色是透明（light 偶数行）
 *    或半透明叠加（night 条纹/悬停）⇒ 下层文字从按钮缝隙里透出（10/14、2、26、28 重影）。
 *    修法：行底色改为不透明（light `--bg`、night `--bg-2`），night 条纹/悬停/当前行
 *    改为同值的不透明合成色。
 *
 * 判据都按可观察事实取，不写像素常量：
 * - 表头完整落在吸顶页签条下方：表体滚到底、页面再滚到底后仍成立；
 * - 操作列单元格计算背景色 alpha = 1（两种主题、奇偶行都查）。
 * 「横向溢出 > 操作列宽」是承重前置：不成立时第二条判据看不见缺陷，必须先红在前提上。
 */
const TABS = '.tabs-wrapper'
const HEADER = '.el-table__header-wrapper'
const BODY_WRAP = '.el-table__body-wrapper .el-scrollbar__wrap'

/** 1920×1080 屏在 125% 缩放下的 CSS 视口（与 lessons 2026-10-17 的基线同源） */
const VIEWPORT_125 = { width: 1536, height: 864 }

async function gotoFileList(page: Page) {
  await gotoApp(page, '/data')
  await expect(page.locator('.content-section:visible .el-table .el-table__row').first())
    .toBeVisible({ timeout: 15_000 })
}

/**
 * 计算样式里背景色的 alpha（不透明度）。
 *
 * Chromium 对同一个「不透明色」会按来源序列化成 rgb() / color(srgb …) / oklab(…)
 * 等多种形式（color-mix 的结果尤其如此），这里统一取：
 * - 带 `/ a` 或 rgba 第 4 通道的取 a（支持百分比）；
 * - 其余三通道形式一律视为 1；
 * - 读不出的格式返回 null，让判据红，而不是静默当成不透明。
 */
function alphaOf(expr: string): number | null {
  const m = expr.trim().match(/^[a-z-]+\((.+)\)$/i)
  if (!m) return null
  const slash = m[1].split('/')
  let alpha: string | undefined
  if (slash.length === 2) {
    alpha = slash[1].trim()
  } else {
    const comma = m[1].split(',')
    if (comma.length === 4) alpha = comma[3].trim()
  }
  if (alpha === undefined) return 1
  const n = Number.parseFloat(alpha)
  if (Number.isNaN(n)) return null
  return alpha.endsWith('%') ? n / 100 : n
}

for (const theme of ['light', 'night'] as const) {
  test.describe(`文件列表布局 @p2 ${theme}`, () => {
    test.use({ viewport: VIEWPORT_125 })

    test.beforeEach(async ({ page }) => {
      await page.addInitScript((t) => localStorage.setItem('theme', t), theme)
    })

    test('表头常驻：滚到表底、页面到底后仍完整位于吸顶页签条下方', async ({ page }) => {
      await gotoFileList(page)
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)

      // 表体滚到底（修复前没有竖向内部滚动，这一步是空操作）
      await page.locator(BODY_WRAP).first().evaluate((el) => {
        el.scrollTop = el.scrollHeight
      })
      // 页面自身也滚到底：修复前表头会整块钻进吸顶页签条
      await page.locator('.content-area').evaluate((el) => {
        el.scrollTop = el.scrollHeight
      })

      const header = page.locator(HEADER).first()
      await expect(header).toBeVisible()
      const tabsBox = await page.locator(TABS).boundingBox()
      const headerBox = await header.boundingBox()
      expect(tabsBox).not.toBeNull()
      expect(headerBox).not.toBeNull()
      const tabsBottom = tabsBox!.y + tabsBox!.height
      // 表头不得被页签条盖住：上缘在页签条下缘之下；且整行仍在视口内
      expect(headerBox!.y).toBeGreaterThanOrEqual(tabsBottom - 1)
      expect(headerBox!.y + headerBox!.height).toBeLessThanOrEqual(VIEWPORT_125.height)
      // 表头内容确实渲染（不是被压成 0 高的空壳）
      expect(headerBox!.height).toBeGreaterThan(20)
    })

    test('固定操作列不透底：横向滚到底后单元格背景不透明', async ({ page }) => {
      await gotoFileList(page)
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)

      const wrap = page.locator(BODY_WRAP).first()
      const overflow = await wrap.evaluate((el) => el.scrollWidth - el.clientWidth)
      const opWidth = await page.locator('th.el-table-fixed-column--right').first()
        .evaluate((el) => el.getBoundingClientRect().width)
      // 承重前置：非固定列至少能整列滑进操作列底下，否则本判据对缺陷是瞎的
      expect(overflow).toBeGreaterThan(opWidth)

      await wrap.evaluate((el) => {
        el.scrollLeft = el.scrollWidth
      })
      // 等 EP 把表头 scrollLeft 同步到位
      await page.waitForTimeout(100)

      // 取前 4 行（必含奇偶与条纹行）的操作列单元格计算底色
      const cells = await page.evaluate(() => {
        return [...document.querySelectorAll('.el-table__body tr')]
          .slice(0, 4)
          .map((tr) => {
            const td = tr.querySelector('td.el-table-fixed-column--right')
            if (!td) return null
            return { cls: tr.className, bg: getComputedStyle(td).backgroundColor }
          })
          .filter((x): x is { cls: string; bg: string } => x !== null)
      })
      expect(cells.length).toBeGreaterThanOrEqual(2)
      for (const c of cells) {
        expect(alphaOf(c.bg), `行 ${c.cls} 的操作列背景 ${c.bg}`).toBe(1)
      }

      // 悬停行：真实指针悬停（EP 的 hover 规则挂在 tr:hover 上，加 class 模拟不了）
      await page.locator('.el-table__body tr').first().hover()
      const hoverBg = await page.locator('.el-table__body tr').first()
        .locator('td.el-table-fixed-column--right').evaluate((td) => getComputedStyle(td).backgroundColor)
      expect(alphaOf(hoverBg), `悬停行操作列背景 ${hoverBg}`).toBe(1)

      // 当前行（highlight-current-row）：EP 默认取半透明的 --el-color-primary-light-9
      const currentBg = await page.evaluate(() => {
        const tr = document.querySelector('.el-table__body tr')
        if (!tr) return null
        const td = tr.querySelector('td.el-table-fixed-column--right')
        if (!td) return null
        tr.classList.add('current-row')
        const bg = getComputedStyle(td).backgroundColor
        tr.classList.remove('current-row')
        return bg
      })
      expect(currentBg).not.toBeNull()
      expect(alphaOf(currentBg!), `当前行操作列背景 ${currentBg}`).toBe(1)
    })
  })
}
