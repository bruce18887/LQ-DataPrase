import { test, expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { gotoApp } from '../helpers/nav'
import { chartFontSize } from '../../src/theme/typography'

const SRC_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'src')

/**
 * 字体统一（方案③）：平台感知字体栈 + 单一事实来源。
 * 说明：getComputedStyle().fontFamily 返回的是声明值（非实际渲染字体），
 * 断言与运行机器无关——正对应方案③"声明栈统一"的目标。
 * 单一事实来源：frontend/src/styles/design-tokens.css 的 --font-sans / --font-mono；
 * TS 侧（typography.ts / echarts-theme.ts）与 Element Plus 覆盖必须与之保持一致。
 *
 * 字号侧的「接线」同样在这里钉住：EP 的 --el-font-size-* 与 AG Grid 的
 * --ag-font-size/--ag-font-family 必须解析回 --p-fs-* / --font-sans 的值，
 * 这样以后谁把 token 改回去会红，而不是静默漂移成第二套字号真相。
 */

// 必须与 frontend/src/styles/design-tokens.css 的 --font-sans / --font-mono 完全一致
const FONT_SANS =
  "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans CJK SC', 'Source Han Sans SC', 'Helvetica Neue', Arial, sans-serif"
const FONT_MONO =
  "'SF Mono', 'Cascadia Mono', 'Consolas', 'Liberation Mono', 'Menlo', 'Courier New', monospace"

/**
 * 页内字号/字族探针：把 var() 写在一个挂到 host 下的隐形节点上，读它的**计算值**。
 * 直接 getPropertyValue('--x') 拿到的是书写形式，解析不到实际 px。
 */
function probeFont(page: Page, hostSel: string, css: string) {
  return page.evaluate(({ hostSel, css }) => {
    const host = document.querySelector(hostSel) || document.documentElement
    const el = document.createElement('span')
    el.style.cssText = 'position:absolute;left:-9999px;top:0;' + css
    host.appendChild(el)
    const cs = getComputedStyle(el)
    const out = { fontFamily: cs.fontFamily, fontSize: cs.fontSize }
    el.remove()
    return out
  }, { hostSel, css })
}

test.describe('@p2 字体统一', { tag: ['@p2', '@global'] }, () => {
  test('字体 Token 与单一事实来源一致', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    const tokens = await page.evaluate(() => {
      const cs = getComputedStyle(document.documentElement)
      return {
        sans: cs.getPropertyValue('--font-sans').trim(),
        mono: cs.getPropertyValue('--font-mono').trim(),
        elFont: cs.getPropertyValue('--el-font-family').trim(),
      }
    })
    // 生产构建的 CSS 压缩（lightningcss）会把 'Segoe UI' 规范化为 "Segoe UI"：
    // 比较前两侧统一剥离引号（下方 body 用例同款处理），否则 dev 绿 / preview 必挂
    const strip = (s: string) => s.replace(/["']/g, '')
    expect(strip(tokens.sans)).toBe(strip(FONT_SANS))
    expect(strip(tokens.mono)).toBe(strip(FONT_MONO))
    // Element Plus 组件字体跟随 --font-sans（element-plus-theme.css 覆盖）
    expect(strip(tokens.elFont)).toBe(strip(FONT_SANS))
  })

  test('body 继承统一字体栈（中文平台字体顺序固定）', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    // computed font-family 会规范化引号（'X' → "X"），比较前统一剥离引号
    const bodyFont = (await page.evaluate(() => getComputedStyle(document.body).fontFamily)).replace(/["']/g, '')
    for (const name of ['PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', 'Source Han Sans SC']) {
      expect(bodyFont).toContain(name)
    }
  })

  test('双主题下字体 Token 一致（字体不随主题变化）', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    const readSans = () =>
      page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--font-sans').trim())

    const before = await readSans()
    const themeBefore = await page.evaluate(() => document.documentElement.getAttribute('data-theme'))
    await page.locator('button.theme-toggle').click()
    await expect
      .poll(() => page.evaluate(() => document.documentElement.getAttribute('data-theme')))
      .not.toBe(themeBefore)
    expect(await readSans()).toBe(before)
  })

  test('Element Plus 字号变量解析回 --p-fs-* 九档', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    // 前五档与 EP 默认值逐位相同（像素不变）；extra-large 的 EP 默认 20px 按九档
    // 规则就近折到 18px —— 那是**本批唯一有意的 EP 视觉变化**，写死在这里当契约。
    const pairs = [
      ['--el-font-size-extra-small', '--p-fs-dense', '12px'],
      ['--el-font-size-small', '--p-fs-small', '13px'],
      ['--el-font-size-base', '--p-fs-base', '14px'],
      ['--el-font-size-medium', '--p-fs-lead', '16px'],
      ['--el-font-size-large', '--p-fs-title', '18px'],
      ['--el-font-size-extra-large', '--p-fs-title', '18px'],
    ] as const
    for (const [elVar, token, px] of pairs) {
      const viaEl = await probeFont(page, 'body', `font-size: var(${elVar})`)
      const viaToken = await probeFont(page, 'body', `font-size: var(${token})`)
      expect(viaEl.fontSize, `${elVar} 应解析成 ${px}`).toBe(px)
      expect(viaEl.fontSize, `${elVar} 与 ${token} 不同源`).toBe(viaToken.fontSize)
    }
  })

  test('字号九档 CSS ↔ TS 单一来源不漂移', async ({ page }) => {
    // 九档在 design-tokens.css；typography.ts 的 chartFontSize 只是给 ECharts 用的镜像。
    // 这里同时断言 CSS 值 = 期望 px、且 TS 镜像 = CSS，防止再出现「两套字号真相」。
    await gotoApp(page, '/dashboard')
    const SCALE = [
      ['micro', 11], ['dense', 12], ['small', 13], ['base', 14], ['lead', 16],
      ['title', 18], ['headline', 22], ['display', 26], ['hero', 32],
    ] as const
    const css = await page.evaluate((names: string[]) => {
      const cs = getComputedStyle(document.documentElement)
      return names.map((n) => cs.getPropertyValue(`--p-fs-${n}`).trim())
    }, SCALE.map(([name]) => name))
    SCALE.forEach(([name, px], i) => {
      expect(css[i], `--p-fs-${name} 应为 ${px}px`).toBe(`${px}px`)
    })
    const ts = chartFontSize
    SCALE.forEach(([name, px]) => {
      expect(ts[name as keyof typeof ts], `chartFontSize.${name}`).toBe(px)
    })
  })

  test('AG Grid 单元格使用全局字体栈与 --p-fs-dense（quartz 内置栈无 CJK 档）', async ({ page }) => {
    // 必须落到真实渲染的单元格上：grid 主题变量声明在 :deep(.ag-custom-theme.ag-theme-quartz)，
    // 未选文件时 AG Grid 整个不挂载，读外层 .ag-grid-wrapper 只会拿到 body 继承来的
    // --font-sans，字族断言会空过（实测如此）。流程与 theme/night-visibility.spec 同款。
    await gotoApp(page, '/data')
    const searchInput = page.locator('input[placeholder="按文件名/程序名/标签搜索"]')
    await searchInput.fill('BPD60320_QA2'.slice(0, 15))
    const row = page.locator('.el-table .el-table__row').filter({ hasText: 'BPD60320_QA2' }).first()
    await expect(row).toBeVisible({ timeout: 30_000 })
    await row.locator('button').filter({ hasText: '查看' }).click()
    await expect(page.locator('.tab-btn.active')).toContainText('查看数据')
    const cell = page.locator('.ag-custom-theme .ag-center-cols-container .ag-cell').first()
    await expect(cell).toBeVisible({ timeout: 30_000 })

    const style = await cell.evaluate((el) => {
      const cs = getComputedStyle(el)
      return { fontFamily: cs.fontFamily, fontSize: cs.fontSize }
    })
    const stripped = style.fontFamily.replace(/["']/g, '')
    for (const name of ['Microsoft YaHei', 'Noto Sans CJK SC']) {
      expect(stripped, 'AG Grid 字体栈应含中文字体档').toContain(name)
    }
    expect(style.fontSize, 'AG Grid 字号应解析成 --p-fs-dense').toBe('12px')
  })

  test('禁止新增硬编码字号（源码级守门）', () => {
    // 第二步归档之后，字号只能来自 --p-fs-* 九档（CSS）或 chartFontSize（TS 镜像）。
    // 装饰性大字（404 / 图标）允许留在原地，但必须显式写 @type-scale-one-off，
    // 让"这是一次性决定"变成看得见的痕迹，而不是又一处无人认领的字面量。
    // 三种写法都要拦住：标准属性 font-size、ECharts 的 fontSize 数字，
    // 以及 `--xx-font-size: 12px` 这类自定义属性（它绕过九档，且因为前面是连字符，
    // 只匹配 "不紧跟连字符的 font-size:" 的正则抓不到它 —— 第一版就漏了）。
    const LITERAL = /(?:^|[^\w-])font-size:\s*\d+(?:\.\d+)?px|--[\w-]*font-size:\s*\d+(?:\.\d+)?px|fontSize:\s*["']?\d+(?:\.\d+)?/
    const offenders: string[] = []
    const files: string[] = []
    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, entry.name)
        if (entry.isDirectory()) walk(p)
        else if (/\.(vue|css|ts)$/.test(entry.name)) files.push(p)
      }
    }
    walk(SRC_DIR)

    for (const file of files) {
      if (file.endsWith(`${path.sep}design-tokens.css`)) continue
      fs.readFileSync(file, 'utf8').split('\n').forEach((line, i) => {
        const t = line.trim()
        if (t.startsWith('//') || t.startsWith('*') || t.startsWith('/*')) return
        if (LITERAL.test(line) && !line.includes('@type-scale-one-off')) {
          offenders.push(`${path.relative(SRC_DIR, file)}:${i + 1}  ${t.slice(0, 60)}`)
        }
      })
    }
    expect(offenders, `仍有硬编码字号，请改走 --p-fs-* 九档：\n${offenders.join('\n')}`).toEqual([])
  })
})
