import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'

/**
 * 字体统一（方案③）：平台感知字体栈 + 单一事实来源。
 * 说明：getComputedStyle().fontFamily 返回的是声明值（非实际渲染字体），
 * 断言与运行机器无关——正对应方案③"声明栈统一"的目标。
 * 单一事实来源：frontend/src/styles/design-tokens.css 的 --font-sans / --font-mono；
 * TS 侧（typography.ts / echarts-theme.ts）与 Element Plus 覆盖必须与之保持一致。
 */

// 必须与 frontend/src/styles/design-tokens.css 的 --font-sans / --font-mono 完全一致
const FONT_SANS =
  "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans CJK SC', 'Source Han Sans SC', 'Helvetica Neue', Arial, sans-serif"
const FONT_MONO =
  "'SF Mono', 'Cascadia Mono', 'Consolas', 'Liberation Mono', 'Menlo', 'Courier New', monospace"

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
    expect(tokens.sans).toBe(FONT_SANS)
    expect(tokens.mono).toBe(FONT_MONO)
    // Element Plus 组件字体跟随 --font-sans（element-plus-theme.css 覆盖）
    expect(tokens.elFont).toBe(FONT_SANS)
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
})
