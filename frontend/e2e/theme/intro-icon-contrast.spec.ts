import { expect, test, type Page } from '@playwright/test'

import { gotoApp } from '../helpers/nav'

/**
 * 顶栏「产品介绍书」入口的明显度判据（用户诉求：「介绍书的图标再稍微明显一点」）。
 * 定稿是设计稿 §3.1 选型 B —— **同尺寸只提亮一档**：不改大小、不改字形、不顺手提亮邻居。
 *
 * 四条判据，light / night 两主题各跑一遍（CLAUDE.md「任何前端改动都要维护两套主题」）：
 *  1) intro 那颗 = 主题主文本色 `--text` —— 这是「明显」的实现本体，本批唯一的承重
 *  2) 铃铛那颗仍是次要文本色 `--text-2` —— 挡「顺手把共用的 `.icon-btn` 一起提亮」：
 *     两颗一样响就没有层级了，也就等于没提亮；用户要的是「找得到」不是「最亮」
 *     （头像那颗是 `--brand` 底上的反白，属另一族，本文件不判它）
 *  3) intro hover = `--brand` —— 改动只允许动静态色
 *  4) 铃铛 hover = **同一个** `--brand`，且两颗字号相同 —— 见下面「同值」那条注释
 *
 * 判据只证明颜色与尺寸，证不了观感；「找得到但不出格」是主观项，靠 tasks/ 下那四张截图人工判。
 */

/**
 * 颜色真值现量自 `frontend/src/styles/design-tokens.css`（全仓唯一 token 事实来源）：
 *   light  —— `--text` :63 → `--p-slate-800`（:31 `#1f2937`）；`--text-2` :63 → `--p-slate-500`（:30 `#6b7280`）；
 *             `--brand` :68 → `--p-blue-600`（:14 `#2563eb`）
 *   night  —— `--text` :107 字面量 `#ffffff`；`--text-2` :107 `rgba(255, 255, 255, 0.76)`；
 *             `--brand` :112 → `--p-amber-500`（:18 `#f9a825`）
 * 改动这些 token 会红在这里，**这是有意的**：本文件断的是「intro = 该主题的主文本色」这层语义，
 * token 挪了就得起码看一眼观感再改这几个字面量，别顺手把断言改成读变量（那样判据就自我循环了）。
 */
const TOKEN = {
  light: { text: 'rgb(31, 41, 55)', text2: 'rgb(107, 114, 128)', brand: 'rgb(37, 99, 235)' },
  night: { text: 'rgb(255, 255, 255)', text2: 'rgba(255, 255, 255, 0.76)', brand: 'rgb(249, 168, 37)' },
} as const

const introBtn = (page: Page) => page.locator('[data-testid=open-intro]')
const bellBtn = (page: Page) => page.locator('.notification-badge .el-button')
const introIcon = (page: Page) => introBtn(page).locator('.el-icon')
const bellIcon = (page: Page) => bellBtn(page).locator('.el-icon')

/**
 * 主题一律在 goto **之前**经 localStorage 落（`src/stores/theme.ts` 的启动 watch 同时写
 * `data-theme` 属性、`.theme-night`/`.theme-light` 类与 theme-color meta）；导航后裸改属性
 * 只会得到真机不存在的半切换态。回读一次 `data-theme` 才算「主题确实生效」——
 * 否则四条颜色判据会在错误的主题上假绿。
 */
async function openDashboard(page: Page, theme: 'light' | 'night') {
  await page.addInitScript((t) => localStorage.setItem('theme', t), theme)
  await gotoApp(page, '/dashboard')
  await expect
    .poll(() => page.evaluate(() => document.documentElement.getAttribute('data-theme')))
    .toBe(theme)
}

test.describe('@theme 顶栏介绍书入口明显度', { tag: ['@p2', '@theme'] }, () => {
  for (const theme of ['light', 'night'] as const) {
    test(`@p2 ${theme} 模式：intro 图标提到主文本色，铃铛保持次要色且同尺寸`, async ({ page }) => {
      await openDashboard(page, theme)
      const c = TOKEN[theme]

      await expect(introIcon(page), `${theme}：intro 必须是主文本色`).toHaveCSS('color', c.text)
      await expect(bellIcon(page), `${theme}：铃铛必须仍是次要色（层级差）`).toHaveCSS('color', c.text2)

      // toHaveCSS 自带重试 —— `.icon-btn` 上有 `transition: color .2s`，
      // 直接 evaluate 读 computed color 会偶发拿到过渡中间值（一个谁都复现不稳的假红）。
      await introBtn(page).hover()
      await expect(introIcon(page), `${theme}：intro hover 落到品牌色`).toHaveCSS('color', c.brand)

      await bellBtn(page).hover()
      // 「同值」不是笔误：现量下铃铛与 intro 共用同一个 class `icon-btn`（Topbar.vue 两颗都是），
      // 因而共用 `.icon-btn:hover { color: var(--brand) }` ⇒ 两颗 hover 后必然同色。
      // 这条断言挡的是「共享 hover 规则被顺手改掉」（改 `.icon-btn:hover` 则两条一起红）
      // 与「给 intro 配一条更响的私有 hover」，而不是「铃铛不许变品牌色」。
      await expect(bellIcon(page), `${theme}：铃铛 hover 与 intro 共用同一条 hover 规则`).toHaveCSS(
        'color',
        c.brand,
      )

      // §3.1「尺寸不动」钉的是相对量：intro 不得比邻居大。写成绝对 px 的话，
      // 将来全站字号一档挪位就会在两个不相关的文件里各红一次。
      const sizes = await Promise.all([
        introIcon(page).evaluate((el) => getComputedStyle(el).fontSize),
        bellIcon(page).evaluate((el) => getComputedStyle(el).fontSize),
      ])
      expect(sizes[0], `${theme}：intro 不得比铃铛大（选型 B 只改颜色）`).toBe(sizes[1])
    })
  }
})
