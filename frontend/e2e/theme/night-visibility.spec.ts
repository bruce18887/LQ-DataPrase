import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, selectParam, listParams, filePicker, pickOutlierMode, filterControl } from '../helpers/params'
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

  test('@p2 夜+昼模式：分析页 tab 内新控件（文件选择器 / 数据筛选 / 异常值处理）可读', async ({ page }) => {
    test.setTimeout(180_000)
    // 2026-09-05 页头控件下移到各 tab 后，新增的三处文字（选择器 label、筛选区
    // 小标题、敏感度提示）只用了 CSS token。本用例钉住它们在两套主题下都 ≥ 3，
    // 并确认边框与卡片底色不同色（轮廓存在；底色本身不拿当对比度门槛）。
    const NEW_CLASSES = ['picker-label', 'section-label', 'sensitivity-hint', 'el-checkbox__label']

    for (const theme of ['night', 'light'] as const) {
      // 后注册的 init script 后执行，同一页里循环切换主题不会互相残留
      await page.addInitScript((t) => localStorage.setItem('theme', t), theme)
      await gotoApp(page, '/analysis')
      await selectAnalysisFile(page, RECOMMENDED.analysis)
      await waitLoadingGone(page.locator('.single-param-tab'))

      // 勾「仅显示低CPK项」让敏感度行与其提示文字渲染出来（否则无样本可测）
      await page.locator('.el-tab-pane:visible .filter-section .el-checkbox')
        .filter({ hasText: '仅显示低CPK项' }).first().click()
      await expect(filterControl(page, 'iqr-multiplier')).toBeVisible({ timeout: 30_000 })

      // ① 控件真的在屏上（否则后面的扫描会空转假绿）
      for (const sel of ['.dp-analysis-filepicker .picker-label',
        '.el-tab-pane:visible .filter-section .section-label',
        '.el-tab-pane:visible .sensitivity-hint',
        '.el-tab-pane:visible .filter-section .el-checkbox__label']) {
        await expect(page.locator(sel).first(), `${theme}: ${sel} 应渲染`).toBeVisible({ timeout: 15_000 })
      }

      // ② 实渲文字对比度：复用全页扫描，只看新控件的类（其他元素自有用例）
      const issues = await page.evaluate(contrastScan)
      const mine = issues.filter((i) => NEW_CLASSES.some((c) => i.sel.includes(c)))
      expect(mine, `${theme}: 新控件存在低对比度文字\n${JSON.stringify(mine)}`).toHaveLength(0)

      // ③ token 实色 vs 筛选卡片有效底色（percent=0 即不混色）。
      // 只钉新控件真正用的 --text-2；--text-3（浅色 #9ca3af）在白底只有
      // 2.54:1，不能拿来做正文字色（本组件已改用 --text-2；全页扫描的步骤②会守住残留项）。
      // baseSel 必须是**纯 CSS**：它在 page.evaluate 里交给 document.querySelector，
      // Playwright 的 `:visible` 伪类在那里是非法选择器（直接抛 SyntaxError）。
      const probe = await page.evaluate(tokenTintProbe, {
        tokens: ['--text-2', '--text-3', '--border'],
        percent: 0,
        baseSel: '.single-param-tab .filter-section',
      })
      const byName: Record<string, { fg: string; contrast: number | null }> = {}
      for (const t of probe.tokens) byName[t.name] = t
      expect(byName['--text-2'].contrast ?? 0, `${theme}: --text-2（小标题/提示文字）对卡片底色`).toBeGreaterThanOrEqual(3)
      // 反向钉住一个事实：浅色下 --text-3 不够对比度，所以提示文字不得用它
      if (theme === 'light') {
        expect(byName['--text-3'].contrast ?? 99, '浅色下 --text-3 不够 3:1，只能当装饰色')
          .toBeLessThan(3)
      }
      expect(byName['--border'].fg, `${theme}: --border 应能解析出实色`).not.toBe('')
      // 底色是 "r,g,b"（无空格）、计算色是 "rgb(r, g, b)"（有空格），
      // 不归一化空格这条断言永远成立（假绿）。
      const borderRgb = byName['--border'].fg.replace(/\s+/g, '')
      expect(borderRgb, `${theme}: 边框不得与卡片底色同值（轮廓消失）`)
        .not.toContain(`rgb(${probe.baseBgCss})`)
    }
  })
})
