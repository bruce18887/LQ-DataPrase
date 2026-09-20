import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { gotoApp } from '../helpers/nav'

/**
 * 字号计算值快照（**工具**，不是回归用例）
 *
 * 为什么不用像素基线：这是 Electron 桌面应用，用户机器的字体 hinting / 滚动条 /
 * 子像素渲染都不同，`toHaveScreenshot` 会长期飘；而第二步要证明的只是「哪些元素的
 * 字号从多少变成多少」，计算值就够，且完全可比对（实测同源码两次跑 DIFF=0）。
 *
 * 用法（归档前后各跑一次）：
 *   TYPE_SNAPSHOT=before npx playwright test e2e/global/type-snapshot.spec.ts --workers=1
 *   TYPE_SNAPSHOT=after  npx playwright test e2e/global/type-snapshot.spec.ts --workers=1
 *   node scripts/type_scale_diff.mjs        # 出「元素 → 旧值 → 新值」并判定有无回归
 *   TYPE_SNAPSHOT=clip   npx playwright test e2e/global/type-snapshot.spec.ts --workers=1
 *       # 附带产物：字号变大后「文字溢出容器」清单（计算值快照看不到的那类后果）
 *
 * 产物：``test/type-snapshot/<TYPE_SNAPSHOT>.json``。before 那份进 git 当基线。
 * 未设 TYPE_SNAPSHOT 时整个文件 skip，不会混进常规回归。
 */

const OUT = process.env.TYPE_SNAPSHOT
const OUT_DIR = path.join(
  path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'test', 'type-snapshot')

/** 固定页面清单（数据浏览器要先选文件，否则 AG Grid 整个不挂载） */
const ROUTES = [
  { key: 'dashboard', route: '/dashboard', openViewTab: false },
  { key: 'analysis', route: '/analysis', openViewTab: false },
  { key: 'data-files', route: '/data', openViewTab: false },
  { key: 'data-grid', route: '/data', openViewTab: true },
  { key: 'sftp', route: '/sftp', openViewTab: false },
  { key: 'settings', route: '/settings', openViewTab: false },
]

type Sizes = Record<string, number>
type Captured = Record<string, { sizes: Sizes; sample: string }>

/**
 * 页内采集：每个「自带直接文本」且已渲染的元素，按 cssPath 归并成尺寸计数。
 *
 * cssPath 只取 tag + 首个稳定类名、向上 4 层：够定位到人，又不会被 Vue scoped 的
 * data-v-* 与动态类名搅成每次不同的 key。同一路径本来就可能多种字号（如 .ag-cell），
 * 所以存**尺寸集合**；拼成单值字符串会让 key 无限变长且读不出差异（第一版踩过）。
 */
function collectFontSizes(): Captured {
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TITLE', 'META'])
  const pathOf = (el: Element) => {
    const parts: string[] = []
    let cur: Element | null = el
    while (cur && cur.nodeType === 1 && parts.length < 4) {
      const tag = cur.tagName.toLowerCase()
      if (tag !== 'html' && tag !== 'body') {
        const cls = (cur.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean)
        const stable = cls.find((c) => !/^el-[-\w]+$/.test(c)) || cls[0]
        parts.unshift(tag + (stable ? '.' + stable : ''))
      }
      cur = cur.parentElement
    }
    return parts.join('>') || '(body)'
  }
  const out: Captured = {}
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT)
  let el = walker.nextNode() as Element | null
  while (el) {
    if (!SKIP.has(el.tagName)) {
      const ownText = Array.from(el.childNodes)
        .filter((n) => n.nodeType === 3)
        .map((n) => (n.textContent || '').trim())
        .filter(Boolean)
        .join(' ')
      if (ownText && el.getClientRects().length) {
        const size = getComputedStyle(el).fontSize
        const key = pathOf(el)
        const entry = out[key] || (out[key] = { sizes: {}, sample: ownText.slice(0, 28) })
        entry.sizes[size] = (entry.sizes[size] || 0) + 1
      }
    }
    el = walker.nextNode() as Element | null
  }
  return out
}

/**
 * 截断探针：字号整体调大后最坏的后果不是"大小不对"而是"文字被切了"，
 * 而计算值快照看不到这个。这里把 scrollWidth/clientHeight 溢出的元素列出来，
 * 供人工判断是不是某档字号在固定宽度容器里挤不下了。
 */
function collectClipping(): string[] {
  const rows: string[] = []
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT)
  let el = walker.nextNode() as Element | null
  while (el) {
    const cs = getComputedStyle(el)
    const own = Array.from(el.childNodes)
      .filter((n) => n.nodeType === 3)
      .map((n) => (n.textContent || '').trim())
      .filter(Boolean)
      .join(' ')
    if (own && el.getClientRects().length && cs.overflowX !== 'visible') {
      const clippedX = el.scrollWidth - el.clientWidth > 1 && cs.textOverflow !== 'ellipsis'
      const clippedY = el.scrollHeight - el.clientHeight > 1
      if (clippedX || clippedY) {
        rows.push(
          `${el.tagName.toLowerCase()}.${el.getAttribute('class') || ''}`
          + `  ${cs.fontSize}  ${clippedX ? '横向' : ''}${clippedY ? '纵向' : ''}`
          + `  溢出 ${el.scrollWidth - el.clientWidth}/${el.scrollHeight - el.clientHeight}px  「${own.slice(0, 24)}」`,
        )
      }
    }
    el = walker.nextNode() as Element | null
  }
  return rows
}

async function capturePage(page: Page, entry: typeof ROUTES[number]): Promise<{ sizes: Captured; clip: string[] }> {
  await gotoApp(page, entry.route)
  if (entry.openViewTab) {
    const search = page.locator('input[placeholder="按文件名/程序名/标签搜索"]')
    await search.fill('BPD60320_QA2')
    const row = page.locator('.el-table .el-table__row').filter({ hasText: 'BPD60320_QA2' }).first()
    await expect(row).toBeVisible({ timeout: 30_000 })
    await row.locator('button').filter({ hasText: '查看' }).click()
    await expect(page.locator('.tab-btn.active')).toContainText('查看数据')
    await expect(page.locator('.ag-cell').first()).toBeVisible({ timeout: 30_000 })
  }
  // 数据是异步填的：等一轮网络静默再采，否则同一路由两次跑的元素集会不同
  await page.waitForLoadState('networkidle')
  const sizes = await page.evaluate(collectFontSizes)
  const clip = await page.evaluate(collectClipping)
  return { sizes, clip }
}

test('字号快照 @tool', { tag: '@tool' }, async ({ page }) => {
  test.skip(!OUT, '仅在 TYPE_SNAPSHOT=before|after|clip 时作为工具运行')
  const result: Record<string, Captured> = {}
  const clipped: string[] = []

  for (const theme of ['light', 'night']) {
    // 必须先落到同源文档：about:blank 上读 localStorage 会抛 SecurityError
    await page.goto('/dashboard')
    await page.evaluate((t) => localStorage.setItem('theme', t), theme)
    await page.reload()
    await expect(page.locator('.main-layout')).toBeVisible({ timeout: 15_000 })
    expect(
      await page.evaluate(() => document.documentElement.getAttribute('data-theme')),
      `主题未切到 ${theme}`,
    ).toBe(theme)

    for (const entry of ROUTES) {
      const cap = await capturePage(page, entry)
      result[`${theme}/${entry.key}`] = cap.sizes
      cap.clip.forEach((row) => clipped.push(`${theme}/${entry.key}  ${row}`))
    }
  }

  const pathCount = Object.values(result).reduce((n, g) => n + Object.keys(g).length, 0)
  expect(pathCount, '采集到的元素路径太少，八成是页面没进去').toBeGreaterThan(200)

  fs.mkdirSync(OUT_DIR, { recursive: true })
  if (OUT === 'clip') {
    fs.writeFileSync(path.join(OUT_DIR, 'clipping.txt'), clipped.join('\n') + '\n')
    console.log(`[type-snapshot] clip: ${clipped.length} 处文字溢出容器`)
    return
  }
  fs.writeFileSync(
    path.join(OUT_DIR, `${OUT}.json`),
    JSON.stringify({ capturedAt: new Date().toISOString(), groups: result }, null, 2),
  )
  console.log(`[type-snapshot] ${OUT}: ${Object.keys(result).length} 页态 / ${pathCount} 元素路径`)
})
