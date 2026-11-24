import { test, expect, type Locator, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { deleteBatchQuiet, deleteFilesByNameQuiet } from '../helpers/cleanup'

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

async function captureArea(
  page: Page,
  testInfo: import('@playwright/test').TestInfo,
  theme: string,
  step: string,
  target: Locator,
) {
  await expect(target).toBeVisible()
  const shot = testInfo.outputPath(`combination-${theme}-${step}.png`)
  await page.screenshot({ path: shot })
  await testInfo.attach(`combination-${theme}-${step}`, { path: shot, contentType: 'image/png' })
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

async function uploadCombinationFile(
  page: Page,
  combinationId: number | null,
  filename: string,
  batchNo?: string,
  tags?: string[],
): Promise<number> {
  const token = await page.evaluate(() => localStorage.getItem('access_token'))
  const response = await page.request.post('/api/v1/upload/', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    multipart: {
      file: { name: filename, mimeType: 'text/csv', buffer: Buffer.from(CSV) },
      last_modified: String(Date.now()),
      ...(combinationId !== null ? { combination_id: String(combinationId) } : {}),
      ...(batchNo !== undefined ? { batch_no: batchNo } : {}),
      ...(tags !== undefined ? { tags: JSON.stringify(tags) } : {}),
    },
    failOnStatusCode: false,
  })
  expect(response.status(), await response.text()).toBe(201)
  const created = await response.json() as Array<{ id: number }>
  expect(created).toHaveLength(1)
  return created[0].id
}

async function selectCombination(page: Page, name: string) {
  await page.getByTestId('combination-select').click()
  await page.locator('.dp-combination-select-popper .el-select-dropdown__item')
    .filter({ hasText: name }).click()
  await expect(page.getByTestId('combination-current-name')).toHaveText(name)
}

async function clearCombination(page: Page) {
  const select = page.getByTestId('combination-select')
  await select.hover()
  await select.locator('.el-select__clear').click()
}

async function getUngroupedCount(page: Page) {
  return page.evaluate(async () => {
    const token = localStorage.getItem('access_token')
    const response = await fetch('/api/v1/files/?page_size=10000&include_hidden=1', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!response.ok) throw new Error(`读取未分组文件失败：${response.status}`)
    const body = await response.json()
    const rows = Array.isArray(body) ? body : body.results
    return rows.filter((row: { combination_id: number | null }) => row.combination_id == null).length
  })
}

test.describe('组合数据', { tag: ['@p2', '@data'] }, () => {
  for (const theme of ['light', 'night'] as const) {
    test(`${theme}：创建、重命名与删除组合`, async ({ page }, testInfo) => {
      await page.addInitScript((value) => localStorage.setItem('theme', value), theme)
      await gotoApp(page, '/data')
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      await openCombinationTab(page)
      await expect(page.getByTestId('combination-select').getByRole('combobox'))
        .toHaveAttribute('aria-label', '当前组合')

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

  test('清空当前组合后恢复未分组文件与计数', async ({ page }) => {
    await gotoApp(page, '/data')
    const prefix = `e2e_combo_clear_${Date.now()}`
    const comboName = `${prefix}_combo`
    const grouped = `${prefix}_grouped.csv`
    const ungrouped = `${prefix}_ungrouped.csv`
    let combinationId: number | null = null
    try {
      combinationId = await createCombination(page, comboName)
      await uploadCombinationFile(page, combinationId, grouped)
      await uploadCombinationFile(page, null, ungrouped)

      await gotoApp(page, '/data')
      await openCombinationTab(page)
      const ungroupedCount = await getUngroupedCount(page)
      const scopeCount = page.locator('.combination-scope-count')
      const files = page.getByTestId('combination-files')
      await expect(scopeCount).toHaveText(`${ungroupedCount} 个文件`)
      await expect(files.getByText(ungrouped, { exact: true })).toBeVisible()

      await selectCombination(page, comboName)
      await expect(files.getByText(grouped, { exact: true })).toBeVisible()
      await expect(files.getByText(ungrouped, { exact: true })).toHaveCount(0)

      await clearCombination(page)
      await expect(page.getByTestId('combination-current-name')).toHaveCount(0)
      await expect(scopeCount).toHaveText(`${ungroupedCount} 个文件`)
      await expect(files.getByText(ungrouped, { exact: true })).toBeVisible()
      await expect(files.getByText(grouped, { exact: true })).toHaveCount(0)
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

  for (const theme of ['light', 'night'] as const) {
    test(`${theme}：单文件保留手动标签并显示只读组合标签`, async ({ page }, testInfo) => {
      await page.addInitScript((value) => localStorage.setItem('theme', value), theme)
      await gotoApp(page, '/data')
      const name = `e2e_combo_tags_${theme}_${Date.now()}`
      const filename = `combo_single_${theme}_${Date.now()}.csv`
      const comboId = await createCombination(page, name)
      try {
        await gotoApp(page, '/data')
        await openCombinationTab(page)
        await selectCombination(page, name)
        const upload = page.getByTestId('combination-upload')
        await expect(upload.getByTestId('import-combination').getByRole('combobox')).toBeDisabled()
        await captureArea(page, testInfo, theme, 'upload-options', upload.locator('.upload-section'))
        const manualTagInput = upload.getByTestId('import-manual-tags').locator('input[role="combobox"]')
        const manualTagSelect = upload.getByTestId('import-manual-tags')
        await manualTagInput.fill('manual')
        await expect(page.getByRole('option', { name: 'manual', exact: true })).toBeVisible()
        await manualTagInput.press('ArrowDown')
        await manualTagInput.press('Enter')
        await expect(manualTagSelect.locator('.el-select__selected-item:not(.el-select__input-wrapper)')).toHaveText('manual')
        await manualTagInput.fill(name.toUpperCase())
        await page.getByRole('option', { name: name.toUpperCase(), exact: true }).click()
        await expect(manualTagSelect.locator('.el-select__selected-item:not(.el-select__input-wrapper)')).toHaveText('manual')
        await expect(page.getByText('系统标签由组合自动维护，不能作为手动标签重复添加')).toBeVisible()
        const uploadResponse = page.waitForResponse((response) =>
          response.request().method() === 'POST' && response.url().endsWith('/api/v1/upload/'),
        )
        await upload.locator('input[type=file]').setInputFiles({
          name: filename,
          mimeType: 'text/csv',
          buffer: Buffer.from(CSV),
        })
        const created = await (await uploadResponse).json() as Array<{ tags: string[] }>
        expect(created[0].tags).toEqual(['manual'])

        const files = page.getByTestId('combination-files')
        await expect(files).toContainText(filename)
        const row = files.locator('.el-table__row').filter({ hasText: filename })
        await expect(row.getByTestId('manual-tag')).toHaveCount(1)
        await expect(row.getByTestId('manual-tag')).toHaveText('manual')
        await expect(row.getByTestId('managed-tag')).toHaveText(name)
        await expect(row.getByTestId('managed-tag')).toHaveCount(1)
        await expect(row.getByTestId('managed-tag').locator('.el-tag__close')).toHaveCount(0)
        await captureArea(page, testInfo, theme, 'managed-tags', row)

        await page.getByTestId('combination-rename').click()
        await page.getByTestId('combination-name-input').fill(`${name}_lab`)
        await page.getByTestId('combination-save').click()
        await expect(row.getByTestId('managed-tag').filter({ hasText: `${name}_lab` })).toBeVisible()
        await expect(row.getByTestId('manual-tag')).toHaveText('manual')

        await page.getByRole('tab', { name: /文件列表/ }).click()
        const listRow = page.locator('.file-list-tab .el-table__row').filter({ hasText: filename })
        await expect(listRow).toBeVisible()
        await expect(listRow.getByTestId('manual-tag')).toHaveText('manual')
        await expect(listRow.getByTestId('manual-tag').locator('.el-tag__close')).toHaveCount(1)
        await expect(listRow.getByTestId('managed-tag').locator('.el-tag__close')).toHaveCount(0)
      } finally {
        await deleteFilesByNameQuiet(page, filename)
        await page.evaluate(async (id) => {
          const token = localStorage.getItem('access_token')
          await fetch(`/api/v1/combinations/${id}/`, {
            method: 'DELETE',
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          })
        }, comboId)
      }
    })
  }

  for (const theme of ['light', 'night'] as const) {
    test(`${theme}：文件列表组合筛选与批量归组保留或清空批次号`, async ({ page }, testInfo) => {
      await page.addInitScript((value) => localStorage.setItem('theme', value), theme)
      await gotoApp(page, '/data')
      const prefix = `e2e_as_${theme}_${Date.now()}`
      const comboName = `${prefix}_combo`
      const first = `${prefix}_a.csv`
      const second = `${prefix}_b.csv`
      const comboId = await createCombination(page, comboName)
      try {
        const firstId = await uploadCombinationFile(page, null, first, 'Keep-Lot', ['manual'])
        await uploadCombinationFile(page, null, second)
        await gotoApp(page, '/data')
        const row = (name: string) => page.locator('.file-list-tab .el-table__row').filter({ hasText: name })
        await expect(row(first)).toBeVisible()
        await row(first).locator('.el-checkbox').first().click()
        await row(second).locator('.el-checkbox').first().click()
        await page.getByRole('button', { name: '加入组合', exact: true }).click()
        const dialog = page.locator('.el-dialog')
        await expect(dialog).toBeVisible()
        await captureArea(page, testInfo, theme, 'assign-options', dialog)
        await dialog.getByTestId('import-combination').click()
        await page.getByRole('option', { name: comboName, exact: true }).click()
        await expect(dialog.getByTestId('import-combination')).toContainText(comboName)
        const assignRequest = page.waitForRequest((request) =>
          request.method() === 'POST' && request.url().endsWith('/files/assign_combination/'),
        )
        await page.getByTestId('import-submit').click()
        expect((await assignRequest).postDataJSON()).toEqual({
          file_ids: [firstId, expect.any(Number)],
          combination_id: comboId,
        })
        await expect(dialog).toBeHidden()
        await expect(row(first).getByTestId('managed-tag')).toHaveText([
          comboName,
          `${comboName} / Keep-Lot`,
        ])
        await expect(row(first).getByTestId('managed-tag').locator('.el-tag__close')).toHaveCount(0)

        await page.getByTestId('file-combination-filter').click()
        await page.locator('.el-select-dropdown__item:visible').filter({ hasText: comboName }).first().click()
        await expect(row(first)).toBeVisible()
        await expect(row(second)).toBeVisible()

        await row(first).locator('.add-tag-btn').click()
        await row(first).locator('.tag-native-input').fill(comboName.toUpperCase())
        await row(first).locator('.tag-native-input').press('Enter')
        await expect(page.getByText('该标签由组合自动维护，不能作为手动标签重复添加')).toBeVisible()
        await expect(row(first).getByTestId('manual-tag')).toHaveCount(1)

        await row(first).locator('.el-checkbox').first().click()
        await page.getByRole('button', { name: '加入组合', exact: true }).click()
        await dialog.getByTestId('import-combination').click()
        await page.getByRole('option', { name: comboName, exact: true }).click()
        await expect(dialog.getByTestId('import-combination')).toContainText(comboName)
        await page.getByTestId('import-clear-batch-no').click()
        await expect(page.getByTestId('import-clear-batch-no').locator('input[type="checkbox"]')).toBeChecked()
        const clearRequest = page.waitForRequest((request) =>
          request.method() === 'POST' && request.url().endsWith('/files/assign_combination/'),
        )
        await page.getByTestId('import-submit').click()
        expect((await clearRequest).postDataJSON()).toEqual({
          file_ids: [firstId],
          combination_id: comboId,
          batch_no: '',
        })
        await expect(row(first).getByTestId('managed-tag')).toHaveText([comboName])
        const saved = await page.evaluate(async (id) => {
          const token = localStorage.getItem('access_token')
          const response = await fetch(`/api/v1/files/${id}/`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          })
          return response.json()
        }, firstId)
        expect(saved.batch_no).toBe('')
        expect(saved.tags).toEqual(['manual'])
      } finally {
        await deleteFilesByNameQuiet(page, prefix)
        await page.evaluate(async (id) => {
          const token = localStorage.getItem('access_token')
          await fetch(`/api/v1/combinations/${id}/`, {
            method: 'DELETE',
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          })
        }, comboId)
      }
    })
  }

  test('组合为批次提交可选组合与批次号', async ({ page }) => {
    await gotoApp(page, '/data')
    const prefix = `e2e_cb_${Date.now()}`
    const comboName = `${prefix}_combo`
    const batchName = `${prefix}_batch`
    const first = `${prefix}_a.csv`
    const second = `${prefix}_b.csv`
    const comboId = await createCombination(page, comboName)
    try {
      await uploadCombinationFile(page, null, first)
      await uploadCombinationFile(page, null, second)
      await gotoApp(page, '/data')
      const row = (name: string) => page.locator('.file-list-tab .el-table__row').filter({ hasText: name })
      await row(first).locator('.el-checkbox').first().click()
      await row(second).locator('.el-checkbox').first().click()
      await page.getByRole('button', { name: '组合为批次', exact: true }).click()
      await page.getByTestId('combine-new-name').fill(batchName)
      await page.getByTestId('combine-combination').click()
      await page.locator('.el-select-dropdown__item:visible').filter({ hasText: comboName }).first().click()
      await page.getByTestId('combine-batch-no').fill('Combine-Lot')
      await expect(page.getByTestId('combine-submit')).toBeEnabled()
      const combineRequest = page.waitForRequest((request) =>
        request.method() === 'POST' && request.url().endsWith('/files/combine/'),
      )
      await page.getByTestId('combine-submit').click()
      expect((await combineRequest).postDataJSON()).toMatchObject({
        batch_name: batchName,
        combination_id: comboId,
        batch_no: 'Combine-Lot',
      })
      await expect(page.getByText(/已组合 2 个文件为批次/).first()).toBeVisible()
      await gotoApp(page, '/data')
      await openCombinationTab(page)
      await selectCombination(page, comboName)
      await expect(page.getByTestId('combination-files')).toContainText(`${comboName} / Combine-Lot`)
    } finally {
      await deleteBatchQuiet(page, batchName)
      await deleteFilesByNameQuiet(page, prefix)
      await page.evaluate(async (id) => {
        const token = localStorage.getItem('access_token')
        await fetch(`/api/v1/combinations/${id}/`, {
          method: 'DELETE',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
      }, comboId)
    }
  })

  test('解除组合只清组合并保留批次号和手动标签', async ({ page }) => {
    await gotoApp(page, '/data')
    const prefix = `e2e_combo_unassign_${Date.now()}`
    const comboName = `${prefix}_combo`
    const filename = `${prefix}.csv`
    const batchNo = 'Lot-Keep'
    const tags = ['manual-keep', 'qa-check']
    let combinationId: number | null = null
    try {
      combinationId = await createCombination(page, comboName)
      const fileId = await uploadCombinationFile(page, combinationId, filename, batchNo, tags)

      await gotoApp(page, '/data')
      await openCombinationTab(page)
      await selectCombination(page, comboName)
      const files = page.getByTestId('combination-files')
      const row = files.locator('.el-table__row').filter({ hasText: filename })
      await expect(row).toBeVisible()
      await expect(row.getByRole('button', { name: '移出', exact: true })).toHaveCount(0)
      const assignRequest = page.waitForRequest((request) =>
        request.method() === 'POST' && request.url().endsWith('/files/assign_combination/'),
      )
      await row.getByRole('button', { name: '解除组合', exact: true }).click()
      expect((await assignRequest).postDataJSON()).toEqual({
        file_ids: [fileId],
        combination_id: null,
      })

      await expect(row).toHaveCount(0)
      await expect(page.locator('.combination-scope-count')).toHaveText('0 个文件')
      await clearCombination(page)
      await expect(files.getByText(filename, { exact: true })).toBeVisible()

      const saved = await page.evaluate(async (id) => {
        const token = localStorage.getItem('access_token')
        const response = await fetch(`/api/v1/files/${id}/`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })
        if (!response.ok) throw new Error(`读取文件失败：${response.status}`)
        return response.json()
      }, fileId)
      expect(saved.combination_id ?? null).toBeNull()
      expect(saved.combination_name ?? null).toBeNull()
      expect(saved.batch_no).toBe(batchNo)
      expect([...saved.tags].sort()).toEqual([...tags].sort())
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
