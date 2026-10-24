import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'

/**
 * 系统设置页 `el-input-number` 的盒宽判据（2026-10-24 普查落成的常驻哨兵）。
 *
 * 来历：`export-timeout` 那条挂了 4 天的红，真因是**产品**把输入框挤没了 ——
 * 控件与长说明文案同在一个 `display:flex` 行里，控件默认 `flex: 0 1 auto` 允许收缩，
 * 收缩下限只有 `.el-input__wrapper` 的 42+42px 内边距 ⇒ 内部 `<input>` 宽 0px
 * （用户看不见也点不着）。回归点是「把文案从一行加到三行」这种纯内容提交。
 * 见 docs/tasks/lessons.md 2026-10-23 与 e2e/settings/export-timeout.spec.ts:43-56。
 *
 * 那次之后还剩一句没量：其它同样「控件 + 文案同行」的行有没有同型缺陷。本用例把
 * 设置页那批量齐并钉住。普查读数（1280×720，day 档）：
 *   图表 DPI        外层 150 / 内部 66   ← 恒等式 150 − 42 − 42 = 66，健康
 *   CPK A/B/C 三行  外层 150 / 内部 66   ← 同上，`.threshold-hint` 没有挤到控件
 * 阈值取 140 / 40：稳稳压住历史实测的 84 与 0，同时给浏览器取整留余量。
 */
async function expectControlNotSquished(
  page: import('@playwright/test').Page,
  formItemLabel: string,
) {
  const item = page.locator('.el-form-item').filter({ hasText: formItemLabel }).first()
  await expect(item).toBeVisible()
  const outer = await item.locator('.el-input-number').first().boundingBox()
  expect(outer?.width, `${formItemLabel}：控件被同级文案挤扁（普查实测 150px）`).toBeGreaterThanOrEqual(140)
  const inner = await item.locator('.el-input-number input').first().boundingBox()
  expect(inner?.width, `${formItemLabel}：内部 <input> 宽度归零，用户看不见也点不着`).toBeGreaterThanOrEqual(40)
}

test.describe('@p1 设置页数值控件盒宽', { tag: ['@p1', '@settings'] }, () => {
  test('显示设置：图表 DPI 的说明文案不挤控件', async ({ page }) => {
    await gotoApp(page, '/settings')
    await page.getByRole('tab', { name: '📊 显示设置' }).click()
    await expect(page.getByText(/图表 DPI/)).toBeVisible()
    await expectControlNotSquished(page, '图表 DPI')
  })

  test('CPK 阈值：三行各带 .threshold-hint，都不挤控件', async ({ page }) => {
    await gotoApp(page, '/settings')
    await page.getByRole('tab', { name: '📐 CPK 阈值' }).click()
    await expect(page.getByText(/CPK A 级阈值/)).toBeVisible()
    // 三行逐条量：只量第一行等于默认相信后两行同构（普查时它们是各自独立的 flex 行）
    for (const label of ['CPK A 级阈值', 'CPK B 级阈值', 'CPK C 级阈值']) {
      await expectControlNotSquished(page, label)
    }
  })
})
