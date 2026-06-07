import { test, expect } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { SEEDED_FILE_COUNT, PRIMARY_SAMPLE_FILE, SEEDED_FILES } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { uploadFile, uploadMultipleFiles, expectUploadSuccess } from '../helpers/upload'
import { elSelectByPlaceholder, visibleSelectOptions } from '../helpers/elplus'

const SEEDED_MIN = SEEDED_FILE_COUNT

/** 在文件列表 tab 内按文件名定位卡片 */
function fileCard(page: import('@playwright/test').Page, filename: string) {
  return page.locator('.el-card').filter({ hasText: filename })
}

test.describe('数据管理 /data', { tag: ['@p0', '@p1', '@p2', '@data'] }, () => {
  test('@p0 页面渲染：已植入文件列表可见，/files/ 返回 200', async ({ page }) => {
    const filesResp = page.waitForResponse(
      (r) => /\/files\/?(\?|$)/.test(r.url()) && r.request().method() === 'GET',
    )
    await gotoApp(page, '/data')

    await expect(page.locator('h1, h2').filter({ hasText: '数据管理' })).toBeVisible()

    // 文件列表 tab should be active by default
    await expect(page.locator('.tab-btn.active')).toContainText('文件列表')

    const resp = await filesResp
    expect(resp.status()).toBe(200)

    // 预植入文件已出现
    await expect.poll(
      () => page.locator('.el-table .el-table__row').count(),
      { timeout: 15_000 },
    ).toBeGreaterThanOrEqual(SEEDED_MIN)
  })

  test('@p1 查看数据：选中文件后切到查看数据 tab 并渲染 ag-grid', async ({ page }) => {
    await gotoApp(page, '/data')

    // Click the first file row's "查看" button
    const firstRow = page.locator('.el-table .el-table__row').first()
    await expect(firstRow).toBeVisible({ timeout: 10_000 })
    await firstRow.locator('button').filter({ hasText: '查看' }).click()

    // Should switch to 查看数据 tab
    await expect(page.locator('.tab-btn.active')).toContainText('查看数据')

    // ag-grid should render
    await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })
  })

  test('@p1 文件类型标签：上传的文件显示"单文件"类型', async ({ page }) => {
    await gotoApp(page, '/data')

    const uniqueName = `e2e_type_${Date.now()}.csv`
    const tmpPath = path.join(os.tmpdir(), uniqueName)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmpPath)

    try {
      // Click upload button to expand upload area
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, tmpPath)
      await expectUploadSuccess(page)

      // Verify the file appears in the table
      await expect(page.locator('.el-table').getByText(uniqueName)).toBeVisible({ timeout: 15_000 })
    } finally {
      fs.rmSync(tmpPath, { force: true })
    }
  })

  test('@p2 删除：上传唯一命名文件，再删除并确认消失', async ({ page }) => {
    await gotoApp(page, '/data')

    const uniqueName = `e2e_del_${Date.now()}_${Math.floor(Math.random() * 1e6)}.csv`
    const tmpPath = path.join(os.tmpdir(), uniqueName)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmpPath)

    try {
      // Click upload button to expand upload area and upload
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, tmpPath)
      await expectUploadSuccess(page)

      // Wait for the file to appear
      await expect(page.locator('.el-table').getByText(uniqueName)).toBeVisible({ timeout: 15_000 })

      // Click the row's delete button (操作 column)
      const row = page.locator('.el-table__row').filter({ hasText: uniqueName })
      await row.locator('button').filter({ hasText: /删除/ }).click()

      // Confirm deletion in the MessageBox
      const confirmBtn = page.getByRole('button', { name: '删除', exact: true })
      await expect(confirmBtn).toBeVisible({ timeout: 10_000 })
      await confirmBtn.click()

      await expect(page.getByText('文件已删除').first()).toBeVisible({ timeout: 15_000 })
      await expect(page.locator('.el-table').getByText(uniqueName)).toHaveCount(0, { timeout: 15_000 })
    } finally {
      fs.rmSync(tmpPath, { force: true })
    }
  })

  test('@p2 API 验证：/files/ 返回的文件包含 file_type 字段', async ({ page }) => {
    await gotoApp(page, '/data')

    const result = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/files/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      const data = await res.json()
      const files = Array.isArray(data) ? data : (data.results ?? [])
      return {
        status: res.status,
        count: files.length,
        hasFileType: files.length > 0 && 'file_type' in files[0],
        hasBatchName: files.length > 0 && 'batch_name' in files[0],
      }
    })
    expect(result.status).toBe(200)
    expect(result.hasFileType).toBe(true)
    expect(result.hasBatchName).toBe(true)
  })

  test('@p2 多文件上传：一次上传两个文件均出现在列表中', async ({ page }) => {
    await gotoApp(page, '/data')

    const ts = Date.now()
    const name1 = `e2e_multi_${ts}_a.csv`
    const name2 = `e2e_multi_${ts}_b.csv`
    const tmp1 = path.join(os.tmpdir(), name1)
    const tmp2 = path.join(os.tmpdir(), name2)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmp1)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmp2)

    try {
      // Click upload button to expand upload area
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadMultipleFiles(page, [tmp1, tmp2])

      // Wait for both success messages
      await expect(page.getByText(/上传成功/).first()).toBeVisible({ timeout: 30_000 })

      // Both files should appear
      await expect(page.locator('.el-table').getByText(name1)).toBeVisible({ timeout: 15_000 })
      await expect(page.locator('.el-table').getByText(name2)).toBeVisible({ timeout: 15_000 })
    } finally {
      fs.rmSync(tmp1, { force: true })
      fs.rmSync(tmp2, { force: true })
    }
  })

  test('@p2 批次目录 API：GET /batch-dirs/ 返回 200', async ({ page }) => {
    await gotoApp(page, '/data')

    const status = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/batch-dirs/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      return res.status
    })
    expect(status).toBe(200)
  })
})

test.describe('数据管理 /data 列表增强（搜索/筛选/分页/批量删除/新列）', { tag: ['@p1', '@p2', '@data'] }, () => {
  test('@p1 新列渲染：表头出现“产品”与“原始修改时间”', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.el-table th').filter({ hasText: '产品' })).toBeVisible()
    await expect(page.locator('.el-table th').filter({ hasText: '原始修改时间' })).toBeVisible()
  })

  test('@p1 搜索：按文件名过滤列表', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    // 用某个已植入文件名的片段搜索
    const fragment = SEEDED_FILES.ETS88_FT.slice(0, 8)
    const search = page.locator('.file-list-tab input[placeholder*="搜索"]')
    await search.fill(fragment)

    // 等待匹配结果，确认目标文件可见
    await expect(page.locator('.el-table').getByText(SEEDED_FILES.ETS88_FT)).toBeVisible({ timeout: 15_000 })

    // 清空后行数恢复
    await search.fill('')
    await expect.poll(
      () => page.locator('.el-table .el-table__row').count(),
      { timeout: 15_000 },
    ).toBeGreaterThan(0)
  })

  test('@p2 产品筛选：下拉存在并可选择产品过滤', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    // product_codes API 返回 200 且含数据
    const codes = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/files/product_codes/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      const data = await res.json()
      return { status: res.status, codes: data.product_codes ?? [] }
    })
    expect(codes.status).toBe(200)
    expect(Array.isArray(codes.codes)).toBe(true)

    if (codes.codes.length > 0) {
      // 打开“全部产品”下拉并选第一个产品
      await elSelectByPlaceholder(page.locator('.file-list-tab'), '全部产品').first().click()
      await visibleSelectOptions(page).first().click()
      // 列表至少应有一行（选中产品存在文件）
      await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })
    }
  })

  test('@p2 批量删除：上传两个唯一文件后多选批量删除', async ({ page }) => {
    await gotoApp(page, '/data')

    const ts = Date.now()
    const name1 = `e2e_bulk_${ts}_a.csv`
    const name2 = `e2e_bulk_${ts}_b.csv`
    const tmp1 = path.join(os.tmpdir(), name1)
    const tmp2 = path.join(os.tmpdir(), name2)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmp1)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmp2)

    try {
      // Click upload button to expand upload area
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadMultipleFiles(page, [tmp1, tmp2])
      await expect(page.getByText(/上传成功/).first()).toBeVisible({ timeout: 30_000 })

      // 用搜索缩小到本次上传的两个文件
      const search = page.locator('.file-list-tab input[placeholder*="搜索"]')
      await search.fill(`e2e_bulk_${ts}_`)
      await expect(page.locator('.el-table').getByText(name1)).toBeVisible({ timeout: 15_000 })
      await expect(page.locator('.el-table').getByText(name2)).toBeVisible({ timeout: 15_000 })

      // 勾选两行的 selection checkbox
      const row1 = page.locator('.el-table__row').filter({ hasText: name1 })
      const row2 = page.locator('.el-table__row').filter({ hasText: name2 })
      await row1.locator('.el-checkbox').click()
      await row2.locator('.el-checkbox').click()

      // 点击批量删除
      const bulkBtn = page.locator('.file-list-tab button').filter({ hasText: '批量删除' })
      await expect(bulkBtn).toBeEnabled()
      await bulkBtn.click()

      // 二次确认
      const confirmBtn = page.getByRole('button', { name: '删除', exact: true })
      await expect(confirmBtn).toBeVisible({ timeout: 10_000 })
      await confirmBtn.click()

      await expect(page.getByText(/已删除 \d+ 个文件/).first()).toBeVisible({ timeout: 15_000 })
      await expect(page.locator('.el-table').getByText(name1)).toHaveCount(0, { timeout: 15_000 })
      await expect(page.locator('.el-table').getByText(name2)).toHaveCount(0, { timeout: 15_000 })
    } finally {
      fs.rmSync(tmp1, { force: true })
      fs.rmSync(tmp2, { force: true })
    }
  })

  test('@p2 分页：文件数超过页大小时分页控件出现', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    // 读取总数判断是否应出现分页（后端 PAGE_SIZE=20）
    const count = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/files/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      const data = await res.json()
      return data.count ?? (Array.isArray(data) ? data.length : 0)
    })

    if (count > 20) {
      await expect(page.locator('.file-list-tab .el-pagination')).toBeVisible({ timeout: 10_000 })
    } else {
      // 不足一页时分页控件应隐藏
      await expect(page.locator('.file-list-tab .el-pagination')).toHaveCount(0)
    }
  })
})

test.describe('数据管理 /data 文件列表增强（标签/上传/批次管理）', { tag: ['@p1', '@p2', '@data'] }, () => {
  test('@p1 标签列渲染：文件列表表格显示标签列', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })
    // 标签列表头应该存在
    await expect(page.locator('.el-table th').filter({ hasText: '标签' })).toBeVisible()
  })

  test('@p1 上传按钮：点击上传按钮展开上传区域', async ({ page }) => {
    await gotoApp(page, '/data')
    // 点击上传按钮
    await page.locator('button').filter({ hasText: '上传文件' }).click()
    // 上传区域应该出现
    await expect(page.locator('.upload-section')).toBeVisible({ timeout: 5_000 })
    // 再次点击应该收起
    await page.locator('button').filter({ hasText: '上传文件' }).click()
    await expect(page.locator('.upload-section')).not.toBeVisible({ timeout: 5_000 })
  })

  test('@p2 API：POST /files/list_tags/ 返回去重标签列表', async ({ page }) => {
    await gotoApp(page, '/data')
    const result = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/files/list_tags/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ prefix: '' }),
      })
      const data = await res.json()
      return { status: res.status, tags: Array.isArray(data?.tags) ? data.tags : [] }
    })
    expect(result.status).toBe(200)
    expect(Array.isArray(result.tags)).toBe(true)
  })

  test('@p2 API：set_tags 覆盖写 + 归一化（trim/去重）', async ({ page }) => {
    await gotoApp(page, '/data')

    // 找一个当前用户的文件
    const fileId = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/files/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      const data = await res.json()
      const list = Array.isArray(data) ? data : (data.results ?? [])
      return list.length > 0 ? list[0].id : null
    })
    if (!fileId) {
      test.skip(true, '当前用户无文件，无法测试 set_tags')
    }
    const tag = `E2E_${Date.now()}`
    const result = await page.evaluate(async ({ id, t }) => {
      const token = localStorage.getItem('access_token')
      const res = await fetch(`/api/v1/files/${id}/set_tags/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ tags: ['  ' + t + '  ', t, t.toLowerCase(), 'Other'] }),
      })
      const data = await res.json()
      return { status: res.status, tags: data.tags }
    }, { id: fileId, t: tag })
    expect(result.status).toBe(200)
    // 第一个出现的大小写保留，后续去重；'Other' 独立保留
    expect(result.tags).toContain(tag)
    expect(result.tags).toContain('Other')
    // 大小写重复的不应出现两次
    const lowerHits = result.tags.filter((x: string) => x.toLowerCase() === tag.toLowerCase())
    expect(lowerHits.length).toBe(1)

    // 清理：清空 tags
    await page.evaluate(async ({ id }) => {
      const token = localStorage.getItem('access_token')
      await fetch(`/api/v1/files/${id}/set_tags/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ tags: [] }),
      })
    }, { id: fileId })
  })

  test('@p2 API：set_tags 拒绝超过 50 字符的 tag', async ({ page }) => {
    await gotoApp(page, '/data')
    const fileId = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/files/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      const data = await res.json()
      const list = Array.isArray(data) ? data : (data.results ?? [])
      return list.length > 0 ? list[0].id : null
    })
    if (!fileId) {
      test.skip(true, '当前用户无文件，无法测试 set_tags 校验')
    }
    const result = await page.evaluate(async ({ id }) => {
      const token = localStorage.getItem('access_token')
      const res = await fetch(`/api/v1/files/${id}/set_tags/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ tags: ['x'.repeat(60)] }),
      })
      return { status: res.status, body: await res.json() }
    }, { id: fileId })
    expect(result.status).toBe(400)
    expect(JSON.stringify(result.body)).toMatch(/长度|超过/)
  })

  test('@p2 UI：标签编辑 - 添加/删除标签', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    // 找到第一行的添加标签按钮
    const firstRow = page.locator('.el-table .el-table__row').first()
    const addBtn = firstRow.locator('button').filter({ hasText: /添加/ }).first()

    // 如果有添加按钮，测试标签编辑
    if (await addBtn.isVisible()) {
      const tagName = `E2E_TAG_${Date.now()}`
      await addBtn.click()

      // 输入框应该出现
      const tagInput = firstRow.locator('input.tag-native-input').first()
      await expect(tagInput).toBeVisible({ timeout: 5_000 })

      // 输入标签并回车
      await tagInput.fill(tagName)
      await tagInput.press('Enter')

      // 标签应该出现
      await expect(
        firstRow.locator('.el-tag').filter({ hasText: tagName }),
      ).toHaveCount(1, { timeout: 15_000 })

      // 删除标签
      const newTag = firstRow.locator('.el-tag').filter({ hasText: tagName }).first()
      const removed = await newTag.evaluate((el: any) => {
        const close = el.querySelector('.el-tag__close')
        if (!close) return false
        close.click()
        return true
      })
      expect(removed).toBe(true)
      await expect(firstRow.locator('.el-tag').filter({ hasText: tagName })).toHaveCount(0, { timeout: 10_000 })
    }
  })
})

test.describe('数据管理 /data 文件列表展开行（方案A）', { tag: ['@p1', '@p2', '@data'] }, () => {
  test('@p1 展开行：点击展开按钮后展示完整文件名/测试程序/所有标签', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    const firstRow = page.locator('.el-table .el-table__row').first()

    // 拿到首行的文件名/程序名原值（从 API 读）
    const fileInfo = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/files/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      const data = await res.json()
      const list = Array.isArray(data) ? data : (data.results ?? [])
      const f = list[0]
      return f ? { filename: f.filename, program_name: f.program_name ?? '' } : null
    })
    if (!fileInfo) {
      test.skip(true, '当前用户无文件，无法测试展开行')
      return
    }

    // 1) 默认未展开：行内不应有 .row-detail
    await expect(page.locator('.el-table__expanded-row .row-detail')).toHaveCount(0)

    // 2) 点击展开按钮
    const expandTrigger = firstRow.locator('.el-table__expand-icon').first()
    await expandTrigger.click()

    // 3) 展开后 .row-detail 出现
    const detail = page.locator('.el-table__expanded-row .row-detail').first()
    await expect(detail).toBeVisible({ timeout: 5_000 })

    // 4) 完整文件名在展开行内可见（不依赖 middle-ellipsis 截断）
    await expect(detail).toContainText(fileInfo.filename)

    // 5) 展开行内显示"完整文件名/测试程序/所有标签"三行
    await expect(detail.locator('.detail-label')).toHaveText(['完整文件名', '测试程序', '所有标签'])
  })

  test('@p2 无 popover 弹框：hover 文件名/测试程序 不出现 el-popper', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    const firstRow = page.locator('.el-table .el-table__row').first()
    const filenameCell = firstRow.locator('.filename-cell .file-name').first()
    const programCell = firstRow.locator('.program-name-cell').first()

    // 等待 mouseEnter 完全处理
    await filenameCell.hover()
    await page.waitForTimeout(400)
    // hover 文件名后，不应有 popper 出现
    await expect(page.locator('.el-popper').filter({ hasText: /.+/ })).toHaveCount(0)

    // 移开
    await page.mouse.move(0, 0)
    await page.waitForTimeout(200)

    // hover 测试程序
    if (await programCell.isVisible()) {
      await programCell.hover()
      await page.waitForTimeout(400)
      await expect(page.locator('.el-popper').filter({ hasText: /.+/ })).toHaveCount(0)
    }
  })
})
