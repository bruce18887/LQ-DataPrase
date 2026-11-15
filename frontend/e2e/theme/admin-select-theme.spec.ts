import { test, expect } from '@playwright/test'

import { loginAs } from '../helpers/auth'

/**
 * 批3b §6.5：EP 2.14 的 select 触发区是 `.el-select__wrapper`，
 * 旧规则 `.el-select .el-input__wrapper` 在 theme-chalk 里恒不命中。
 * 这条用例盯两件事：night 覆写真的落到 wrapper 上（不是只写在 CSS 里），
 * 且焦点态没有被一个静态 !important 阴影抹掉。
 */
test.describe('@theme 管理页 select 触发区主题覆写', { tag: ['@p2', '@theme'] }, () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('@p2 night 下 audit-event 的 .el-select__wrapper 底色与 light 不同', async ({ page }) => {
    await loginAs(page, 'admin')
    await page.goto('/admin/audit')
    await expect(page.locator('.main-layout')).toBeVisible({ timeout: 15_000 })
    const wrapper = page.locator('[data-testid="audit-event"] .el-select__wrapper')
    await expect(wrapper).toBeVisible()

    const read = () =>
      wrapper.evaluate((el) => {
        const s = getComputedStyle(el)
        return { bg: s.backgroundColor, shadow: s.boxShadow }
      })

    const light = await read()
    await page.addInitScript(() => localStorage.setItem('theme', 'night'))
    await page.reload()
    await expect(page.locator('.main-layout')).toBeVisible({ timeout: 15_000 })
    await expect(wrapper).toBeVisible()
    const night = await read()

    expect(night.bg, 'night 下事件下拉仍是 light 的底色 ⇒ 覆写没落到 wrapper 上').not.toBe(light.bg)
    expect(night.bg, 'night 覆写值不是全局主题层那一条').toBe('rgba(255, 255, 255, 0.05)')
    expect(night.shadow, 'night 下边框没有由 .el-select__wrapper 承载').toContain(
      'rgba(255, 255, 255, 0.1)',
    )

    // 焦点态：点开 select，wrapper 必须仍有可辨识的焦点环（不能被静态阴影吃掉）。
    // EP 的 .el-select__wrapper 带 transition:var(--el-transition-duration)（含 box-shadow），
    // 点开后立刻取计算值拿到的是白→琥珀的插值中间色（实测 rgba(254,244,227,.114) 一类），
    // 所以轮询等过渡结束；断言仍是「最终阴影含琥珀色」，强度不变。
    await page.locator('[data-testid="audit-event"] .el-select').click()
    await expect(wrapper).toHaveClass(/is-focused/)
    await expect
      .poll(async () => (await read()).shadow, {
        message: '焦点环被静态 !important 阴影抹掉了',
      })
      .toContain('rgb(249, 168, 37)')
    await page.keyboard.press('Escape')
  })

  test('@p2 新增账号对话框的输入框：light 吃页面基线，night 由全局覆写', async ({ page }) => {
    await loginAs(page, 'admin')
    // 审计页 light 下的输入框底色同为 var(--bg)，作为页面基线
    await page.goto('/admin/audit')
    await expect(page.locator('.main-layout')).toBeVisible({ timeout: 15_000 })
    const baseline = await page
      .locator('[data-testid="audit-username"] .el-input__wrapper')
      .evaluate((el) => getComputedStyle(el).backgroundColor)

    await page.goto('/admin/users')
    await expect(page.locator('.main-layout')).toBeVisible({ timeout: 15_000 })
    await page.getByRole('button', { name: '新增账号', exact: true }).click()
    const input = page.locator(
      '.user-form-dialog [data-testid="create-username"] .el-input__wrapper',
    )
    await expect(input).toBeVisible()
    const read = () => input.evaluate((el) => getComputedStyle(el).backgroundColor)

    const light = await read()
    expect(light, '对话框输入框没吃到页面基线 ⇒ 样式没搬进子组件').toBe(baseline)

    await page.addInitScript(() => localStorage.setItem('theme', 'night'))
    await page.reload()
    await expect(page.locator('.main-layout')).toBeVisible({ timeout: 15_000 })
    await page.getByRole('button', { name: '新增账号', exact: true }).click()
    await expect(input).toBeVisible()
    const night = await read()
    expect(night, 'night 下对话框输入框没被全局主题层接管').toBe('rgba(255, 255, 255, 0.05)')
    expect(night).not.toBe(light)
  })
})
