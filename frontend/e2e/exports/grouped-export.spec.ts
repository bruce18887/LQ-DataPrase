import { expect, test } from '@playwright/test'

import { EXPORT_PARAM_POPPER, popperOf } from '../helpers/elplus'
import { gotoApp } from '../helpers/nav'

test.describe('@p2 导出 - 测试项归类', { tag: ['@p2', '@exports'] }, () => {
  test('添加分类后批量导出 Excel：提交 202 且触发下载', async ({ page }) => {
    test.slow()
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '导出工具' }).click()

    const fileSelect = page.locator('.active-file-banner:visible .el-select').first()
    await fileSelect.click()
    const dropdown = page.locator('.el-select-dropdown:visible')
    const options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
    await expect(options.first()).toBeVisible({ timeout: 15_000 })
    const histogram = page.waitForResponse(
      (r) => /\/analysis\/histogram\/?/.test(new URL(r.url()).pathname) && r.status() === 200,
      { timeout: 15_000 }).catch(() => null)
    await options.first().click()
    await page.keyboard.press('Escape')
    await histogram

    const panel = page.locator('.export-tools')
    const paramSelect = panel.locator('.el-select').filter({ hasText: '点击选择要导出的参数' }).first()
    await paramSelect.click()
    // 参数面板按**实例级** popper-class 取：横幅 FileSelect 刚收起，那 ~150ms 的 leave
    // 过渡帧里全局 `:visible` 会挑中正在退出的那一份（helpers/elplus.ts 的 EXPORT_PARAM_POPPER 注释）。
    const popper = popperOf(page, EXPORT_PARAM_POPPER)
    const paramOptions = popper.locator('.el-select-dropdown__item:not(.is-disabled)')
    await expect(paramOptions.first()).toBeVisible({ timeout: 5_000 })
    const firstName = (await paramOptions.first().textContent())?.trim() ?? ''
    await paramOptions.first().click()
    await page.keyboard.press('Escape')
    await expect(popper).toBeHidden({ timeout: 5_000 })

    await page.getByTestId('export-group-add').click()
    await page.getByTestId('export-group-name').locator('input').fill('A')
    await page.getByTestId('export-group-pattern-text').first().locator('input')
      .fill(firstName.slice(0, Math.min(3, firstName.length)))
    await expect(page.getByTestId('export-grouping-preview')).toContainText(/A：\d+ 项/)

    const submitPromise = page.waitForResponse(
      (r) => r.url().includes('/jobs/export_batch_charts/'), { timeout: 180_000 })
    const downloadPromise = page.waitForEvent('download', { timeout: 180_000 }).catch(() => null)
    await page.getByRole('button', { name: /批量导出 Excel/ }).click()
    const submit = await submitPromise
    expect(submit.status(), '提交批量导出作业应 202').toBe(202)
    // 202 只证明「结构校验通过」；分组是否真的被前端接进请求体，得看请求体自己
    // （不带 groups 也照样 202 —— 那正是本任务要防的「接线看起来跑了」）。
    const body = submit.request().postDataJSON() as {
      groups?: { name: string; params: string[] }[]
      max_items_per_sheet?: number
    }
    expect(body.groups?.length ?? 0, '请求体应携带已解析分组').toBeGreaterThan(0)
    expect(body.max_items_per_sheet, '请求体应携带每页上限').toBeGreaterThan(0)
    const download = await downloadPromise
    if (download) expect(download.suggestedFilename().toLowerCase()).toMatch(/\.xlsx$/)
  })
})
