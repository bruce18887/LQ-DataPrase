import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParam, listParams, filePicker, pickOutlierMode } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { tintContrastProbe, tokenTintProbe } from '../helpers/colors'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 主题视觉回归（@p2 增强：主题切换是纯视觉行为，不阻塞核心流程）
 *
 * 背景（2026-08-26）：`main.ts` 导入 ag-grid CSS 文件主题后与 ag-grid v33+ 默认
 * Theming API 冲突（error #239），夜晚模式整表黑字深底不可读——e2e 功能用例全绿，
 * 没有任何测试抓到。本文件固化：
 *   1) ag-grid Theming API 冲突是否重现（console error #239）
 *   2) 查看数据网格在 night/light 下的格子文字计算色
 *   3) 关键页面夜晚文本对比度扫描（WCAG < 3.0 即为问题，实测全页 0 个 <3.5）
 */

// ---- 对比度扫描（与 tasks/audit-night.mjs 同一实现） ----
function contrastScan() {
  const parse = (s) => {
    s = (s || '').trim()
    let m = s.match(/^rgba?\(([^)]+)\)$/)
    if (m) {
      const p = m[1].split(',').map((x) => parseFloat(x))
      if (p[3] === 0) return null
      return [p[0], p[1], p[2]]
    }
    m = s.match(/^#([0-9a-fA-F]{6})$/)
    if (m) return [parseInt(m[1].slice(0, 2), 16), parseInt(m[1].slice(2, 4), 16), parseInt(m[1].slice(4, 6), 16)]
    m = s.match(/^#([0-9a-fA-F]{3})$/)
    if (m) return [parseInt(m[1][0] + m[1][0], 16), parseInt(m[1][1] + m[1][1], 16), parseInt(m[1][2] + m[1][2], 16)]
    return null
  }
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])
  }
  const contrast = (a, b) => { const L1 = lum(a), L2 = lum(b); const hi = Math.max(L1, L2), lo = Math.min(L1, L2); return (hi + 0.05) / (lo + 0.05) }
  const effBg = (el) => {
    let cur = el, acc = null
    while (cur && cur !== document.documentElement) {
      const s = getComputedStyle(cur)
      const m = (s.backgroundColor || '').match(/^rgba?\(([^)]+)\)$/)
      if (m) {
        const p = m[1].split(',').map((x) => parseFloat(x))
        if (p.length >= 3 && p[3] !== 0) {
          const top = [p[0], p[1], p[2]]
          if (!acc) { acc = top } else {
            const a = p[3] === undefined ? 1 : p[3]
            acc = [top[0] * a + acc[0] * (1 - a), top[1] * a + acc[1] * (1 - a), top[2] * a + acc[2] * (1 - a)]
          }
          if (p[3] === undefined || p[3] === 1) break
        }
      }
      cur = cur.parentElement
    }
    return acc
  }
  const issues = []
  const seen = new Set()
  const els = document.querySelectorAll('body *')
  for (const el of els) {
    if (el.children.length) continue
    const text = (el.textContent || '').trim()
    if (!text || text.length > 60) continue
    const style = getComputedStyle(el)
    if (style.visibility === 'hidden' || style.display === 'none') continue
    const rect = el.getBoundingClientRect()
    if (rect.width < 2 || rect.height < 2 || rect.top > innerHeight || rect.bottom < 0) continue
    const fg = parse(style.color)
    const bg = effBg(el)
    if (!fg || !bg) continue
    const c = contrast(fg, bg)
    if (c < 3.0) {
      const key = text.slice(0, 24) + '|' + c.toFixed(2)
      if (seen.has(key)) continue
      seen.add(key)
      let sel = el.tagName.toLowerCase()
      if (el.id) sel = '#' + el.id
      else if (el.className && typeof el.className === 'string') sel += '.' + el.className.split(' ').slice(0, 2).join('.')
      issues.push({ c: +c.toFixed(2), sel, text: text.slice(0, 30), fg: style.color, bg: bg.map(Math.round).join(',') })
    }
  }
  issues.sort((a, b) => a.c - b.c)
  return issues
}

/** 进入查看数据 tab（与 view-data.spec 相同流程） */
async function openViewTab(page: Page, filename: string) {
  await gotoApp(page, '/data')
  const searchInput = page.locator('input[placeholder="按文件名/程序名/标签搜索"]')
  await searchInput.fill(filename.slice(0, 15))
  const row = page.locator('.el-table .el-table__row').filter({ hasText: filename.slice(0, 12) }).first()
  await expect(row).toBeVisible({ timeout: 30_000 })
  await row.locator('button').filter({ hasText: '查看' }).click()
  await expect(page.locator('.tab-btn.active')).toContainText('查看数据')
  await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })
}

test.describe('@theme 主题视觉回归', { tag: ['@p2', '@theme'] }, () => {
  test('@p2 夜模式：查看数据格子文字为白色，且无 ag-grid Theming API 冲突(#239)', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('theme', 'night'))
    const consoleErrors: string[] = []
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })

    await openViewTab(page, 'BPD60320_QA2')

    // 1) Theming API 冲突（error #239）绝不允许重现
    await expect
      .poll(() => consoleErrors.filter((e) => e.includes('Theming API') || e.includes('#239')).length, { timeout: 10_000 })
      .toBe(0)

    // 2) 格子/表头文字 = --text-primary（夜 = #ffffff）；等首块行渲染完成再测
    await expect(page.locator('.ag-custom-theme .ag-center-cols-container .ag-cell').first()).toBeVisible({ timeout: 30_000 })
    const cellColor = await page.evaluate(() => {
      const cell = document.querySelector('.ag-custom-theme .ag-center-cols-container .ag-cell')
      return cell ? getComputedStyle(cell).color : null
    })
    expect(cellColor, '夜模式单元格文字应为白色').toBe('rgb(255, 255, 255)')
    const headerColor = await page.evaluate(() => {
      const h = document.querySelector('.ag-custom-theme .ag-header-cell')
      return h ? getComputedStyle(h).color : null
    })
    expect(headerColor, '夜模式表头文字应为白色').toBe('rgb(255, 255, 255)')
  })

  test('@p2 日模式：查看数据格子文字为深色（--text-primary 浅色值）', async ({ page }) => {
    await openViewTab(page, 'BPD60320_QA2')
    await expect(page.locator('.ag-custom-theme .ag-center-cols-container .ag-cell').first()).toBeVisible({ timeout: 30_000 })
    const cellColor = await page.evaluate(() => {
      const cell = document.querySelector('.ag-custom-theme .ag-center-cols-container .ag-cell')
      return cell ? getComputedStyle(cell).color : null
    })
    expect(cellColor, '日模式单元格文字应为深色 #1f2937').toBe('rgb(31, 41, 55)')
  })

  test('@p2 夜模式：单文件分析直方图轴标签色已提亮（#64B5F6/#90CAF9）', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('theme', 'night'))
    await gotoApp(page, '/analysis')

    // 选 CTA8280F（含多 Site → All Site 轴）
    await filePicker(page).click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: 'DA35_BPC50338_CL08D4' }).first().click()
    await expect(page.locator('svg text').filter({ hasText: '百分比' }).first()).toBeVisible({ timeout: 30_000 })
    await page.waitForTimeout(2000)

    const fills = await page.evaluate(() => {
      const texts = [...document.querySelectorAll('.single-param-tab svg text')]
      return texts.map((t) => ({ s: (t.textContent || '').trim(), f: getComputedStyle(t).fill }))
    })
    const pct = fills.find((x) => x.s === '百分比 (%)')
    const allSite = fills.find((x) => x.s === 'All Site (%)')
    // 2026-08-26 修复：axis 色改为 theme-aware（night 提亮），深蓝 #1E88E5/#42A5F5 在深底不可读
    expect(pct?.f, '左轴（百分比）night 应为 #64B5F6').toBe('rgb(100, 181, 246)')
    expect(allSite?.f, 'All Site 轴 night 应为 #90CAF9').toBe('rgb(144, 202, 249)')
    // All Site 柱顶百分比标签：night 必须白字（柱面 50% 半透明 #90CAF9 叠深底 ≈ 中蓝，
    // 旧深蓝 #1565C0 对比度≈1.3:1——2026-08-26 用户二次反馈）
    const whitePct = fills.filter((x) => x.f === 'rgb(255, 255, 255)' && x.s.endsWith('%'))
    expect(whitePct.length, 'All Site 柱顶百分比标签 night 应为白色').toBeGreaterThan(0)
  })

  test('@p2 夜模式：关键页面文本对比度扫描无 <3.0 问题', async ({ page }) => {
    test.setTimeout(180_000)
    await page.addInitScript(() => localStorage.setItem('theme', 'night'))

    const pages: { name: string; url: string; ready: string }[] = [
      { name: '仪表板', url: '/dashboard', ready: '[data-testid="overview-strip"]' },
      { name: '数据管理-文件列表', url: '/data', ready: '.el-table' },
      { name: '系统设置', url: '/settings', ready: '.el-tabs' },
      { name: 'SFTP 浏览器', url: '/sftp', ready: '.connect-card' },
    ]
    for (const p of pages) {
      await gotoApp(page, p.url)
      await expect(page.locator(p.ready).first()).toBeVisible({ timeout: 30_000 })
      await page.waitForTimeout(1500)
      const issues = await page.evaluate(contrastScan)
      const severe = issues.filter((i) => i.c < 3.0)
      expect(severe, `${p.name}: 夜晚模式发现 ${severe.length} 个低对比度文本\n` +
        severe.map((i) => `   ${i.c} ${i.sel} "${i.text}" fg=${i.fg} bg=rgb(${i.bg})`).join('\n')).toHaveLength(0)
    }
  })

  test('@p2 夜模式：分析页 token 化着色（异常值提示条 / 当前范围行）生效且可读', async ({ page }) => {
    test.setTimeout(120_000)
    await page.addInitScript(() => localStorage.setItem('theme', 'night'))
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator('.single-param-tab'))
    const params = await listParams(page)
    expect(params.length).toBeGreaterThan(0)
    await selectParam(page, params[0])
    await waitLoadingGone(page.locator('.single-param-tab'))

    await pickOutlierMode(page, '裁剪范围')
    await waitLoadingGone(page.locator('.single-param-tab'))

    // 提示条按「有没有异常值」在 --ok / --clip / --exclude 间切换，种子参数无异常值
    // 时是 --ok，所以不断言具体态，只断言命中的是三态之一并测其实际底色。
    const bar = page.locator('.outlier-hint-bar').first()
    await expect(bar).toBeVisible({ timeout: 10_000 })
    expect(await bar.getAttribute('class')).toMatch(/outlier-hint-bar--(clip|exclude|ok)/)

    const probe = await page.evaluate(tintContrastProbe, {
      barSel: '.outlier-hint-bar',
      rowClasses: ['site-fail-row', 'range-active-row'],
    })
    expect(probe.barAlpha, `提示条 color-mix 底色不应全透明（css=${probe.barBgCss}）`).toBeGreaterThan(0)
    expect(probe.barContrast ?? 0, `提示条文字对比度（底色 ${probe.barBgCss}）应 ≥ 3`).toBeGreaterThanOrEqual(3)

    // 三态各自的 token：--clip 用 --warn、--exclude 用 --error、--ok 用 --success，
    // 底色都是同色 12% 混，故按 percent=12 逐 token 算对比度（不依赖页面渲染哪一态）。
    const TINT = 12
    const tokens = ['--warn', '--error', '--success']
    const nightTokens = await page.evaluate(tokenTintProbe, {
      tokens, percent: TINT, baseSel: '.single-param-tab',
    })
    for (const t of nightTokens.tokens) {
      expect(t.contrast ?? 0, `夜模式 ${t.name} 12% 底色上文字对比度应 ≥ 3（fg=${t.fg} 底=rgb(${nightTokens.baseBgCss})）`)
        .toBeGreaterThanOrEqual(3)
    }

    // 行底色：scoped :deep(.el-table tr.X > td.el-table__cell) 改成主题 token 后，
    // 最大风险是选择器不再命中（EP 把行底色画在 td 上）→ 着色静默丢失。
    // range-active-row 一定存在（当前范围类型那行）；site-fail-row 取决于该参数
    // 有没有失败数，只在出现时附加断言。
    const active = probe.rows.find((r) => r.cls === 'range-active-row')!
    const fail = probe.rows.find((r) => r.cls === 'site-fail-row')!
    expect(active.found, '范围对比表应有当前范围行（range-active-row）').toBe(true)
    expect(active.differs, `range-active-row 底色应与普通行不同（${active.tintCss}）`).toBe(true)
    expect(active.contrast ?? 0, `range-active-row 文字对比度应 ≥ 3（${active.tintCss}）`).toBeGreaterThanOrEqual(3)
    if (fail.found) {
      expect(fail.differs, `site-fail-row 底色应与普通行不同（${fail.tintCss}）`).toBe(true)
      expect(fail.contrast ?? 0, 'site-fail-row 文字对比度应 ≥ 3').toBeGreaterThanOrEqual(3)
    }

    const issues = await page.evaluate(contrastScan)
    const severe = issues.filter((i) => i.c < 3.0)
    expect(severe, `夜模式分析页发现 ${severe.length} 个低对比度文本\n` +
      severe.map((i) => `   ${i.c} ${i.sel} "${i.text}" fg=${i.fg} bg=rgb(${i.bg})`).join('\n')).toHaveLength(0)

    // 同一套 token 在浅色主题下也必须可读（批次 3 删掉了「夜块」，两主题共用一份规则）
    await page.getByRole('button', { name: '切换到浅色模式' }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    const lightTokens = await page.evaluate(tokenTintProbe, {
      tokens, percent: TINT, baseSel: '.single-param-tab',
    })
    for (const t of lightTokens.tokens) {
      expect(t.contrast ?? 0, `浅色模式 ${t.name} 12% 底色上文字对比度应 ≥ 3（fg=${t.fg} 底=rgb(${lightTokens.baseBgCss})）`)
        .toBeGreaterThanOrEqual(3)
    }
  })
})
