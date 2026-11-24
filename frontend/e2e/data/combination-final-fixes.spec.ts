import { test, expect, type Locator, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { gotoApp } from '../helpers/nav'
import { deleteBatchQuiet, deleteFilesByNameQuiet } from '../helpers/cleanup'
import { popperOf } from '../helpers/elplus'
import { DATA_DIR } from '../fixtures/test-data'

const CSV = [
  '[GENERAL],', 'Tester_Type,GenericTester,', '[Data]',
  'col1,col2', 'u1,u2', 'min1,min2', 'max1,max2', '1,2', '',
].join('\n')

async function createCombination(page: Page, name: string): Promise<number> {
  const token = await page.evaluate(() => localStorage.getItem('access_token'))
  const response = await page.request.post('/api/v1/combinations/', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    data: { name },
  })
  expect(response.status(), await response.text()).toBe(201)
  return (await response.json()).id as number
}

async function uploadFile(page: Page, filename: string, combinationId: number | null, tags: string[] = []): Promise<number> {
  const token = await page.evaluate(() => localStorage.getItem('access_token'))
  const response = await page.request.post('/api/v1/upload/', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    multipart: {
      file: { name: filename, mimeType: 'text/csv', buffer: Buffer.from(CSV) },
      ...(combinationId !== null ? { combination_id: String(combinationId) } : {}),
      tags: JSON.stringify(tags),
    },
  })
  expect(response.status(), await response.text()).toBe(201)
  return (await response.json() as Array<{ id: number }>)[0].id
}

async function deleteCombination(page: Page, id: number) {
  const token = await page.evaluate(() => localStorage.getItem('access_token'))
  await page.request.delete(`/api/v1/combinations/${id}/`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
}

async function openCombinationTab(page: Page) {
  await page.locator('.tabs-nav .tab-btn').filter({ hasText: '组合数据' }).click()
  await expect(page.getByTestId('combination-upload')).toBeVisible()
}

async function selectCombination(page: Page, name: string) {
  await page.getByTestId('combination-select').click()
  await page.locator('.dp-combination-select-popper .el-select-dropdown__item')
    .filter({ hasText: name }).click()
  await expect(page.getByTestId('combination-current-name')).toHaveText(name)
}

async function chooseFile(select: Locator, filename: string) {
  const wrapper = select.locator('xpath=ancestor::div[contains(@class, "el-select__wrapper")][1]')
  await wrapper.click()
  const popper = popperOf(select.page(), 'dp-file-select-dropdown')
  await popper.locator('.el-select-dropdown__item').filter({ hasText: filename }).click()
  await expect(popper).toHaveCount(0)
  await expect(wrapper).toContainText(filename)
}

test.describe('组合数据终审回归', { tag: ['@p2', '@data'] }, () => {
  test('同名手动/系统标签共存，关闭手动标签只改手动集合', async ({ page }) => {
    await gotoApp(page, '/data')
    const prefix = `e2e_final_tags_${Date.now()}`
    const comboName = `${prefix}_combo`
    const filename = `${prefix}.csv`
    const combinationId = await createCombination(page, comboName)
    try {
      const fileId = await uploadFile(page, filename, combinationId, [comboName, 'manual'])
      await gotoApp(page, '/data')
      const row = page.locator('.file-list-tab .el-table__row').filter({ hasText: filename })
      await expect(row).toBeVisible()
      await expect(row.getByTestId('manual-tag')).toHaveCount(2)
      await expect(row.getByTestId('managed-tag')).toHaveText([comboName])
      const request = page.waitForRequest((req) =>
        req.method() === 'POST' && req.url().endsWith(`/files/${fileId}/set_tags/`),
      )
      await row.getByTestId('manual-tag').filter({ hasText: comboName }).locator('.el-tag__close').click()
      expect((await request).postDataJSON()).toEqual({ tags: ['manual'] })
      await expect(row.getByTestId('manual-tag')).toHaveText(['manual'])
      await expect(row.getByTestId('managed-tag')).toHaveText([comboName])
      const saved = await page.evaluate(async (id) => {
        const token = localStorage.getItem('access_token')
        const response = await fetch(`/api/v1/files/${id}/`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
        return response.json()
      }, fileId)
      expect(saved.managed_tags).toEqual([comboName])
    } finally {
      await deleteFilesByNameQuiet(page, prefix)
      await deleteCombination(page, combinationId)
    }
  })

  for (const kind of ['gage', 'buyoff'] as const) {
    test(`${kind} 打开组合时清空越界旧分配且不自动分配`, async ({ page }) => {
      await gotoApp(page, '/data')
      const prefix = `cf_${kind}_${Date.now().toString().slice(-10)}`
      const comboName = `${prefix}_combo`
      const grouped = `${prefix}_grouped.csv`
      const outsideA = `${prefix}_outside_a.csv`
      const outsideB = `${prefix}_outside_b.csv`
      const combinationId = await createCombination(page, comboName)
      try {
        await uploadFile(page, grouped, combinationId)
        await uploadFile(page, outsideA, null)
        await uploadFile(page, outsideB, null)
        await gotoApp(page, '/data')
        await page.getByRole('tab', { name: kind === 'gage' ? /Gage Summary/ : /Buyoff Form/ }).click()
        const name = kind === 'gage' ? '选择Gage文件' : '选择角色用户'
        const selects = page.getByRole('combobox', { name })
        await chooseFile(selects.nth(0), outsideA)
        await chooseFile(selects.nth(1), outsideB)
        const action = page.getByRole('button', {
          name: kind === 'gage' ? /生成 Gage Summary/ : /生成 Buyoff Form/,
        })
        await expect(action).toBeEnabled()

        await openCombinationTab(page)
        await selectCombination(page, comboName)
        await page.getByTestId(`combination-open-${kind}`).click()
        await expect(page.getByText(
          `当前组合：${comboName}；候选文件已收敛，${kind === 'gage' ? 'Site 仍需手动分配' : '角色仍需手动分配'}`,
          { exact: true },
        )).toBeVisible()
        await expect(selects.nth(0).locator('xpath=ancestor::div[contains(@class, "el-select__wrapper")][1]'))
          .not.toContainText(outsideA)
        await expect(selects.nth(1).locator('xpath=ancestor::div[contains(@class, "el-select__wrapper")][1]'))
          .not.toContainText(outsideB)
        await expect(action).toBeDisabled()
        const requests: string[] = []
        page.on('request', (req) => {
          if (/\/(gage|buyoff)\//.test(new URL(req.url()).pathname)) requests.push(req.url())
        })
        await chooseFile(selects.nth(0), grouped)
        expect(requests).toEqual([])
      } finally {
        await deleteFilesByNameQuiet(page, prefix)
        await deleteCombination(page, combinationId)
      }
    })
  }

  test('存量归组只提交本用例选中文件并预览系统标签', async ({ page }) => {
    await gotoApp(page, '/data')
    const prefix = `cf_existing_${Date.now().toString().slice(-10)}`
    const comboName = `${prefix}_combo`
    const batch = `${prefix}_lot`
    const chosen = `${prefix}_chosen.csv`
    const control = `${prefix}_control.csv`
    const combinationId = await createCombination(page, comboName)
    const batchDir = path.join(DATA_DIR, 'media', 'data', 'admin', 'batch', batch)
    fs.mkdirSync(batchDir, { recursive: true })
    fs.writeFileSync(path.join(batchDir, chosen), CSV)
    fs.writeFileSync(path.join(batchDir, control), CSV)
    try {
      const imported = await page.evaluate(async (dirName) => {
        const token = localStorage.getItem('access_token')
        const response = await fetch('/api/v1/batch-dirs/import/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ dir_name: dirName }),
        })
        return { status: response.status, rows: await response.json() }
      }, batch)
      expect(imported.status).toBe(201)
      const chosenId = imported.rows.find((row: { filename: string }) => row.filename === chosen).id as number
      await gotoApp(page, '/data')
      await openCombinationTab(page)
      await page.getByTestId('combination-existing').click()
      const dialog = page.locator('.el-dialog')
      await expect(dialog.getByTestId('existing-search')).toBeVisible()
      await dialog.getByTestId('existing-search').fill(chosen)
      await dialog.getByTestId('existing-source-batch').click()
      await page.locator('.el-select-dropdown__item:visible').filter({ hasText: batch }).click()
      const row = dialog.locator('.el-table__row').filter({ hasText: chosen })
      await expect(row).toHaveCount(1)
      await expect(dialog.locator('.el-table__row').filter({ hasText: control })).toHaveCount(0)
      await row.locator('.el-checkbox').click()
      await dialog.getByTestId('import-combination').click()
      await page.locator('.el-select-dropdown__item:visible').filter({ hasText: comboName }).click()
      await dialog.getByTestId('import-batch-no').fill('BE01-PREVIEW')
      await expect(dialog.getByTestId('existing-preview')).toContainText(`${comboName} / BE01-PREVIEW`)
      const request = page.waitForRequest((req) =>
        req.method() === 'POST' && req.url().endsWith('/files/assign_combination/'),
      )
      await dialog.getByTestId('import-submit').click()
      expect((await request).postDataJSON()).toEqual({
        file_ids: [chosenId], combination_id: combinationId, batch_no: 'BE01-PREVIEW',
      })
      await expect(dialog).toBeHidden()
      await selectCombination(page, comboName)
      await expect(page.getByTestId('combination-files')).toContainText(chosen)
      await expect(page.getByTestId('combination-files')).not.toContainText(control)
    } finally {
      await deleteBatchQuiet(page, batch)
      await deleteCombination(page, combinationId)
    }
  })

  test('SFTP 未导入目录导入提交组合与批次号并刷新组合页', async ({ page }) => {
    await gotoApp(page, '/data')
    const prefix = `cf_sftp_${Date.now().toString().slice(-10)}`
    const comboName = `${prefix}_combo`
    const batch = `${prefix}_lot`
    const combinationId = await createCombination(page, comboName)
    const batchDir = path.join(DATA_DIR, 'media', 'data', 'admin', 'batch', batch)
    fs.mkdirSync(batchDir, { recursive: true })
    fs.writeFileSync(path.join(batchDir, `${prefix}.csv`), CSV)
    try {
      await gotoApp(page, '/data')
      await openCombinationTab(page)
      const section = page.getByTestId('batch-directory-section')
      const header = section.locator('.el-collapse-item__header')
      if ((await header.getAttribute('aria-expanded')) !== 'true') await header.click()
      const card = section.locator('.batch-group.unregistered').filter({ hasText: batch })
      await expect(card).toBeVisible()
      await card.getByRole('button', { name: '导入', exact: true }).click()
      const dialog = page.locator('.el-dialog')
      await dialog.getByTestId('import-combination').click()
      await page.locator('.el-select-dropdown__item:visible').filter({ hasText: comboName }).click()
      await dialog.getByTestId('import-batch-no').fill('BE01-SFTP')
      const request = page.waitForRequest((req) =>
        req.method() === 'POST' && req.url().endsWith('/batch-dirs/import/'),
      )
      await dialog.getByTestId('import-submit').click()
      expect((await request).postDataJSON()).toEqual({
        dir_name: batch, combination_id: combinationId, batch_no: 'BE01-SFTP',
      })
      await expect(dialog).toBeHidden()
      await selectCombination(page, comboName)
      await expect(page.getByTestId('combination-files')).toContainText(`${prefix}.csv`)
      await expect(page.getByTestId('combination-files')).toContainText(`${comboName} / BE01-SFTP`)
    } finally {
      await deleteBatchQuiet(page, batch)
      await deleteCombination(page, combinationId)
    }
  })

  test('来源批次头准确区分未分组、单一组合与混合组合', async ({ page }) => {
    const cases = [
      { name: 'status_ungrouped', names: ['', ''], expected: '未分组' },
      { name: 'status_single', names: ['Gage', 'Gage'], expected: 'Gage' },
      { name: 'status_mixed', names: ['Gage', ''], expected: '多个组合' },
      { name: 'status_multiple', names: ['Gage', 'Buyoff'], expected: '多个组合' },
    ]
    await page.route('**/api/v1/batch-dirs/', async (route) => {
      await route.fulfill({
        json: cases.map((item) => ({
          name: item.name,
          path: `/virtual/${item.name}`,
          file_count: item.names.length,
          total_size: item.names.length,
          registered: true,
          files: item.names.map((name, index) => ({
            id: index + 1,
            filename: `${item.name}_${index}.csv`,
            combination_name: name,
            file_size: 1,
            row_count: 1,
            sub_batch: '',
          })),
        })),
      })
    })
    await gotoApp(page, '/data')
    await openCombinationTab(page)
    const section = page.getByTestId('batch-directory-section')
    const header = section.locator('.el-collapse-item__header')
    if ((await header.getAttribute('aria-expanded')) !== 'true') await header.click()
    for (const item of cases) {
      await expect(section.getByTestId(`batch-group-${item.name}`)
        .getByTestId('batch-combination-status')).toHaveText(item.expected)
    }
  })

  test('组合筛选保留未分组对照并在清除后恢复', async ({ page }) => {
    await gotoApp(page, '/data')
    const prefix = `cf_filter_${Date.now().toString().slice(-10)}`
    const comboName = `${prefix}_combo`
    const grouped = `${prefix}_grouped.csv`
    const control = `${prefix}_control.csv`
    const combinationId = await createCombination(page, comboName)
    try {
      await uploadFile(page, grouped, combinationId)
      await uploadFile(page, control, null)
      await gotoApp(page, '/data')
      const row = (name: string) => page.locator('.file-list-tab .el-table__row').filter({ hasText: name })
      await expect(row(control)).toBeVisible()
      const request = page.waitForRequest((req) =>
        req.method() === 'GET' && new URL(req.url()).pathname.endsWith('/files/')
          && new URL(req.url()).searchParams.get('combination_id') === String(combinationId),
      )
      await page.getByTestId('file-combination-filter').click()
      await page.locator('.el-select-dropdown__item:visible').filter({ hasText: comboName }).click()
      await request
      await expect(row(grouped)).toBeVisible()
      await expect(row(control)).toHaveCount(0)
      await page.getByTestId('file-combination-filter').hover()
      await page.getByTestId('file-combination-filter').locator('.el-select__clear').click()
      await expect(row(control)).toBeVisible()
      await expect(row(grouped)).toBeVisible()
    } finally {
      await deleteFilesByNameQuiet(page, prefix)
      await deleteCombination(page, combinationId)
    }
  })
})
