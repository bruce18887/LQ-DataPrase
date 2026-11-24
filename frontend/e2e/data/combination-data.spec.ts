import { test, expect, type Locator, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { deleteFilesByNameQuiet } from '../helpers/cleanup'

const CSV = [
  '[GENERAL],',
  'Tester_Type,GenericTester,',
  '[Data]',
  'col1,col2',
  'u1,u2',
  'min1,min2',
  'max1,max2',
  '1,2',
  '',
].join('\n')

async function openCombinationTab(page: Page) {
  await page.locator('.tabs-nav .tab-btn').filter({ hasText: '组合数据' }).click()
  await expect(page.getByTestId('combination-upload')).toBeVisible()
}

async function expectTokenColor(locator: Locator, property: 'color' | 'backgroundColor', token: string) {
  const { actual, expected } = await locator.evaluate((el, input) => {
    const probe = document.createElement('span')
    probe.style[input.property] = `var(${input.token})`
    document.body.appendChild(probe)
    const expected = getComputedStyle(probe)[input.property]
    probe.remove()
    return { actual: getComputedStyle(el)[input.property], expected }
  }, { property, token })
  expect(actual, `${token} 应驱动 ${property}`).toBe(expected)
}

async function captureDialog(page: Page, testInfo: import('@playwright/test').TestInfo, theme: string, step: string) {
  const target = step === 'delete' ? page.locator('.el-message-box') : page.locator('.el-dialog')
  await expect(target).toBeVisible()
  await expect(target).toHaveCSS('opacity', '1')
  await expect(page.locator('.el-overlay').filter({ has: target })).toHaveCSS('opacity', '1')
  const shot = testInfo.outputPath(`combination-${theme}-${step}.png`)
  await page.screenshot({ path: shot })
  await testInfo.attach(`combination-${theme}-${step}`, { path: shot, contentType: 'image/png' })
}

async function deleteCombinationByName(page: Page, name: string) {
  await page.evaluate(async (comboName) => {
    const token = localStorage.getItem('access_token')
    const headers = token ? { Authorization: `Bearer ${token}` } : {}
    const resp = await fetch('/api/v1/combinations/', { headers })
    const rows = await resp.json()
    const row = rows.find((item: { name: string }) => item.name === comboName)
    if (row) {
      await fetch(`/api/v1/combinations/${row.id}/`, { method: 'DELETE', headers })
    }
  }, name)
}

async function createCombination(page: Page, name: string): Promise<number> {
  return page.evaluate(async (comboName) => {
    const token = localStorage.getItem('access_token')
    const resp = await fetch('/api/v1/combinations/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ name: comboName }),
    })
    if (!resp.ok) throw new Error(`创建组合失败：${resp.status} ${await resp.text()}`)
    return (await resp.json()).id as number
  }, name)
}

async function uploadCombinationFile(page: Page, combinationId: number | null, filename: string, batchNo?: string) {
  const token = await page.evaluate(() => localStorage.getItem('access_token'))
  const response = await page.request.post('/api/v1/upload/', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    multipart: {
      file: { name: filename, mimeType: 'text/csv', buffer: Buffer.from(CSV) },
      last_modified: String(Date.now()),
      ...(combinationId !== null ? { combination_id: String(combinationId) } : {}),
      ...(batchNo !== undefined ? { batch_no: batchNo } : {}),
    },
    failOnStatusCode: false,
  })
  expect(response.status(), await response.text()).toBe(201)
}

test.describe('组合数据', { tag: ['@p2', '@data'] }, () => {
  for (const theme of ['light', 'night'] as const) {
    test(`${theme}：创建、重命名与删除组合`, async ({ page }, testInfo) => {
      await page.addInitScript((value) => localStorage.setItem('theme', value), theme)
      await gotoApp(page, '/data')
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      await openCombinationTab(page)

      const name = `e2e_combo_${theme}_${Date.now()}`
      const renamed = `${name}_lab`
      try {
        await page.getByTestId('combination-create').click()
        await expect(page.getByTestId('combination-name-input')).toBeFocused()
        await expectTokenColor(page.locator('.combination-toolbar'), 'backgroundColor', '--bg-2')
        await expectTokenColor(page.locator('.el-dialog'), 'backgroundColor', '--card-glass')
        await captureDialog(page, testInfo, theme, 'create')
        await page.getByTestId('combination-name-input').fill(name)
        await page.getByTestId('combination-save').click()
        await expect(page.getByTestId('combination-current-name')).toHaveText(name)
        const combinationSelect = page.getByTestId('combination-select')
        await expect(combinationSelect).toContainText(name)
        expect((await combinationSelect.boundingBox())?.width ?? 0, '组合下拉应保持可用宽度').toBeGreaterThan(200)
        await expectTokenColor(page.getByTestId('combination-current-name'), 'color', '--text')

        await page.getByTestId('combination-rename').click()
        await expect(page.getByTestId('combination-name-input')).toHaveValue(name)
        await captureDialog(page, testInfo, theme, 'rename')
        await page.getByTestId('combination-name-input').fill(renamed)
        await page.getByTestId('combination-save').click()
        await expect(page.getByTestId('combination-current-name')).toHaveText(renamed)
        await expect(page.getByTestId('combination-select')).toContainText(renamed)

        await page.getByTestId('combination-delete').click()
        await expect(page.getByRole('button', { name: '确认删除组合', exact: true })).toBeVisible()
        await captureDialog(page, testInfo, theme, 'delete')
        await page.getByRole('button', { name: '确认删除组合', exact: true }).click()
        await expect(page.getByTestId('combination-current-name')).toHaveCount(0)
      } finally {
        await deleteCombinationByName(page, name)
        await deleteCombinationByName(page, renamed)
      }
    })
  }

  test('未分组文件可见，批次号按 trim/lower 合并并单列无批次文件', async ({ page }) => {
    await gotoApp(page, '/data')
    const prefix = `e2e_combo_group_${Date.now()}`
    const comboName = `${prefix}_combo`
    let combinationId: number | null = null
    try {
      combinationId = await createCombination(page, comboName)
      const first = `${prefix}_a.csv`
      const second = `${prefix}_b.csv`
      const unbatched = `${prefix}_c.csv`
      const ungrouped = `${prefix}_d.csv`
      await uploadCombinationFile(page, combinationId, first, ' Lot-A ')
      await uploadCombinationFile(page, combinationId, second, 'lot-a')
      await uploadCombinationFile(page, combinationId, unbatched)
      await uploadCombinationFile(page, null, ungrouped)

      await gotoApp(page, '/data')
      await openCombinationTab(page)
      const files = page.getByTestId('combination-files')
      await expect(files).toContainText('未分组文件')
      await expect(files).toContainText(ungrouped)

      await page.getByTestId('combination-select').click()
      await page.locator('.dp-combination-select-popper .el-select-dropdown__item')
        .filter({ hasText: comboName }).click()
      await expect(page.getByTestId('combination-current-name')).toHaveText(comboName)
      await expect(files.getByText('有批次文件', { exact: true })).toBeVisible()
      await expect(files.getByText('无批次文件', { exact: true })).toBeVisible()

      const batched = files.locator('.combination-batch-group')
      await expect(batched).toHaveCount(1)
      await expect(batched).toContainText(/lot-a/i)
      await expect(batched).toContainText(first)
      await expect(batched).toContainText(second)
      await expect(files.locator('.combination-unbatched-group')).toContainText(unbatched)
    } finally {
      await deleteFilesByNameQuiet(page, prefix)
      if (combinationId != null) {
        await page.evaluate(async (id) => {
          const token = localStorage.getItem('access_token')
          await fetch(`/api/v1/combinations/${id}/`, {
            method: 'DELETE',
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          })
        }, combinationId)
      }
    }
  })
})
