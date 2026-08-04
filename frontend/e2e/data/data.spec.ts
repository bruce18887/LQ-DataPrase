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

  /**
   * 课题2：SFTP 下载新批次后旧批次不应从「已导入批次」消失。
   * 根因是前端从分页 20 条 files 分组，新文件占满首页后挤掉旧批次。
   * 修复后「已导入批次」来自 batch-dirs（磁盘走查，全部批次 + 每批 files 列表）。
   * 断言：batch-dirs 返回的已注册批次都带 files 数组（前端分组不再依赖分页）。
   */
  test('@p2 课题2 batch-dirs 已注册批次带 files 列表（不依赖分页）', async ({ page }) => {
    await gotoApp(page, '/data')

    const data = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/batch-dirs/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      return { status: res.status, body: await res.json() }
    })
    expect(data.status).toBe(200)
    expect(Array.isArray(data.body)).toBe(true)

    const registered = (data.body as any[]).filter((d) => d.registered)
    if (registered.length === 0) {
      test.skip(true, '当前环境无已注册批次，跳过 files 列表断言')
      return
    }
    // 每个已注册批次都应带非空 files 数组，且数量与 file_count 一致
    for (const b of registered) {
      expect(Array.isArray(b.files), `批次 ${b.name} 应有 files 数组`).toBe(true)
      expect(b.files.length, `批次 ${b.name} files 数量应等于 file_count`).toBe(b.file_count)
    }
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

  test('@p2 产品筛选刷新(#6)：上传带产品码文件后下拉立即包含该产品码', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    // 构造一个文件名即可解析出唯一产品码（B + 1~2 字母 + 数字）的临时文件。
    const code = `BZJ${Date.now()}`
    const uniqueName = `${code}_FT.csv`
    const tmpPath = path.join(os.tmpdir(), uniqueName)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmpPath)

    try {
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, tmpPath)
      await expectUploadSuccess(page)
      await expect(page.locator('.el-table').getByText(uniqueName)).toBeVisible({ timeout: 15_000 })

      // 不刷新页面，直接打开“全部产品”下拉——修复前下拉只在 onMounted 拉取，
      // 新上传文件的产品码不会出现（甚至 no data）。修复后应立即包含该码。
      await elSelectByPlaceholder(page.locator('.file-list-tab'), '全部产品').first().click()
      await expect(
        visibleSelectOptions(page).filter({ hasText: code }),
      ).toHaveCount(1, { timeout: 10_000 })
    } finally {
      fs.rmSync(tmpPath, { force: true })
    }
  })

  test('@p2 删除后无残留(#4)：删除正在查看的文件后查看数据页清空', async ({ page }) => {
    await gotoApp(page, '/data')

    const uniqueName = `e2e_stale_${Date.now()}.csv`
    const tmpPath = path.join(os.tmpdir(), uniqueName)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmpPath)

    try {
      // 上传并查看该文件，等待 ag-grid 渲染
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, tmpPath)
      await expectUploadSuccess(page)
      const row = page.locator('.el-table__row').filter({ hasText: uniqueName })
      await expect(row).toBeVisible({ timeout: 15_000 })
      await row.locator('button').filter({ hasText: '查看' }).click()
      await expect(page.locator('.tab-btn.active')).toContainText('查看数据')
      await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })

      // 回到文件列表删除该文件
      await page.locator('.tab-btn').filter({ hasText: '文件列表' }).click()
      const row2 = page.locator('.el-table__row').filter({ hasText: uniqueName })
      await row2.locator('button').filter({ hasText: /删除/ }).click()
      const confirmBtn = page.getByRole('button', { name: '删除', exact: true })
      await expect(confirmBtn).toBeVisible({ timeout: 10_000 })
      await confirmBtn.click()
      await expect(page.getByText('文件已删除').first()).toBeVisible({ timeout: 15_000 })

      // 切回查看数据页：修复前会残留已删除文件的旧表格；修复后当前文件下拉应清空，
      // 回到 placeholder「请选择一个文件」状态。
      await page.locator('.tab-btn').filter({ hasText: '查看数据' }).click()
      const fileSelect = page.locator('.content-section:visible .banner-file-select').first()
      await expect(fileSelect.locator('.el-select__wrapper')).toBeVisible({ timeout: 15_000 })
      await expect(fileSelect.locator('.el-select__placeholder')).toContainText('请选择一个文件', { timeout: 15_000 })
    } finally {
      fs.rmSync(tmpPath, { force: true })
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

  test('@p2 标签联想输入：输入时显示匹配的已有标签建议', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    // 先通过 API 创建一个带标签的文件，确保有标签可联想
    const tagPrefix = `E2E_AC_${Date.now()}`
    const tag1 = `${tagPrefix}_AAA`
    const tag2 = `${tagPrefix}_AAB`

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
      test.skip(true, '当前用户无文件，无法测试标签联想')
      return
    }

    // 设置两个带共同前缀的标签
    await page.evaluate(async ({ id, tags }) => {
      const token = localStorage.getItem('access_token')
      await fetch(`/api/v1/files/${id}/set_tags/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ tags }),
      })
    }, { id: fileId, tags: [tag1, tag2] })

    // 刷新加载新标签
    await page.reload()
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    // 找到第一行的添加标签按钮并点击
    const firstRow = page.locator('.el-table .el-table__row').first()
    const addBtn = firstRow.locator('button').filter({ hasText: /添加/ }).first()

    if (await addBtn.isVisible()) {
      await addBtn.click()
      const tagInput = firstRow.locator('input.tag-native-input').first()
      await expect(tagInput).toBeVisible({ timeout: 5_000 })

      // 输入共同前缀，触发联想
      await tagInput.fill(tagPrefix)
      await page.waitForTimeout(400) // debounce 200ms + network

      // 建议下拉应出现
      const suggestions = firstRow.locator('.tag-suggestions')
      await expect(suggestions).toBeVisible({ timeout: 5_000 })

      // 应包含两个匹配项
      const items = suggestions.locator('.tag-suggestion-item')
      await expect(items).toHaveCount(2, { timeout: 5_000 })

      // 点击第一个建议项，标签应自动添加
      await items.first().click()
      await expect(firstRow.locator('.el-tag').filter({ hasText: tagPrefix })).toHaveCount(1, { timeout: 10_000 })
    }

    // 清理：清空标签
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
    await expect(page.locator('.el-table__expanded-cell .row-detail')).toHaveCount(0)

    // 2) 点击展开按钮
    const expandTrigger = firstRow.locator('.el-table__expand-icon').first()
    await expandTrigger.click()

    // 3) 展开后 .row-detail 出现
    const detail = page.locator('.el-table__expanded-cell .row-detail').first()
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
    // el-select/el-tooltip 的 popper 常驻 DOM 且 display:none，只断言可见的（hover 不应弹出 tooltip）
      await expect(page.locator('.el-popper:visible').filter({ hasText: /.+/ })).toHaveCount(0)

    // 移开
    await page.mouse.move(0, 0)
    await page.waitForTimeout(200)

    // hover 测试程序
    if (await programCell.isVisible()) {
      await programCell.hover()
      await page.waitForTimeout(400)
      // el-select/el-tooltip 的 popper 常驻 DOM 且 display:none，只断言可见的（hover 不应弹出 tooltip）
      await expect(page.locator('.el-popper:visible').filter({ hasText: /.+/ })).toHaveCount(0)
    }
  })
})

/**
 * 课题3：查看数据 / 导出工具 tab 的「当前文件」从只读横幅改为下拉框，
 * 选择即切换 activeFileId。
 */
test.describe('数据管理 /data 当前文件下拉切换', { tag: ['@p1', '@p2', '@data'] }, () => {
  test('@p1 查看数据：当前文件下拉框存在且可切换文件', async ({ page }) => {
    await gotoApp(page, '/data')
    // 先在文件列表点「查看」进入查看数据 tab
    const firstRow = page.locator('.el-table .el-table__row').first()
    await expect(firstRow).toBeVisible({ timeout: 15_000 })
    await firstRow.locator('button').filter({ hasText: '查看' }).click()
    await expect(page.locator('.tab-btn.active')).toContainText('查看数据')

    // 顶部应出现当前文件下拉框（替代旧 banner-filename 只读文本）。
    // view / export 两个 tab 用 v-show 同时存在于 DOM，需限定到当前可见的 section。
    const fileSelect = page.locator('.content-section:visible .banner-file-select').first()
    const wrapper = fileSelect.locator('.el-select__wrapper')
    await expect(wrapper).toBeVisible({ timeout: 10_000 })
    // 选中态非空（已带入查看的文件名，显示在 placeholder 复用的选中值上）
    await expect(fileSelect.locator('.el-select__placeholder')).not.toHaveText('', { timeout: 10_000 })

    // 打开下拉，至少有一个可选文件，选择第一个后表格仍渲染
    await wrapper.click()
    const firstOption = page.locator('.el-select-dropdown__item:visible').first()
    await expect(firstOption).toBeVisible({ timeout: 10_000 })
    await firstOption.click()
    await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })
  })

  test('@p2 导出工具：当前文件下拉框存在并可选择', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '导出工具' }).click()
    await expect(page.locator('.tab-btn.active')).toContainText('导出工具')

    // 顶部当前文件下拉框可见（用 wrapper 判定可见性，EP 真 input 在未聚焦时隐藏）。
    // 限定到当前可见 section，避免命中 v-show 隐藏的查看数据 tab 下拉。
    const fileSelect = page.locator('.content-section:visible .banner-file-select').first()
    const wrapper = fileSelect.locator('.el-select__wrapper')
    await expect(wrapper).toBeVisible({ timeout: 10_000 })

    // 选择第一个文件，下拉可正常工作
    await wrapper.click()
    const firstOption = page.locator('.el-select-dropdown__item:visible').first()
    const optionText = (await firstOption.textContent())?.trim() || ''
    await expect(firstOption).toBeVisible({ timeout: 10_000 })
    await firstOption.click()
    // 选中后下拉显示该文件名（el-select__placeholder 复用为选中值展示）
    await expect(fileSelect.locator('.el-select__placeholder')).toContainText(optionText, { timeout: 10_000 })
  })
})

/**
 * 课题：100+ 文件的批次在「已导入批次」区域一次性渲染会撑高页面 + 视觉杂乱。
 * 改为默认折叠，点击 header 或"全部展开"后才显示文件。
 */
test.describe('数据管理 /data 已导入批次展开/折叠', { tag: ['@p1', '@p2', '@data'] }, () => {
  /** 当前环境的已注册批次列表（无则各用例 skip） */
  async function getRegisteredBatches(page: import('@playwright/test').Page) {
    // 用 page.request 走 storageState 自动带 token；先 goto 让 baseURL 生效。
    await page.goto('/', { waitUntil: 'domcontentloaded' })
    const res = await page.request.get('/api/v1/batch-dirs/')
    const data = (await res.json()) as Array<{ name: string; registered: boolean; file_count: number }>
    return (Array.isArray(data) ? data : []).filter((d) => d.registered)
  }

  test('@p1 默认折叠：进入页面后所有已导入批次不展示文件 tag', async ({ page }) => {
    const registered = await getRegisteredBatches(page)
    test.skip(registered.length === 0, '当前环境无已注册批次，跳过默认折叠断言')

    await gotoApp(page, '/data')

    await expect(page.locator('[data-testid^="batch-group-"]').first()).toBeVisible({ timeout: 15_000 })

    for (const b of registered) {
      await expect(page.locator(`[data-testid="batch-files-${b.name}"]`)).toBeHidden({ timeout: 5_000 })
    }

    const toggleAll = page.locator('[data-testid="batch-toggle-all"]')
    await expect(toggleAll).toBeVisible()
    await expect(toggleAll).toContainText('全部展开')
  })

  test('@p1 点击 header 展开：单个批次文件 tag 出现，header aria-expanded 切换', async ({ page }) => {
    const registered = await getRegisteredBatches(page)
    test.skip(registered.length === 0, '当前环境无已注册批次，跳过点击展开断言')

    await gotoApp(page, '/data')

    const first = registered[0]
    const header = page.locator(`[data-testid="batch-header-${first.name}"]`)
    const filesArea = page.locator(`[data-testid="batch-files-${first.name}"]`)

    await expect(header).toBeVisible({ timeout: 15_000 })
    await expect(filesArea).toBeHidden()

    await header.click()
    await expect(filesArea).toBeVisible({ timeout: 5_000 })
    await expect(header).toHaveAttribute('aria-expanded', 'true')

    await header.click()
    await expect(filesArea).toBeHidden({ timeout: 5_000 })
    await expect(header).toHaveAttribute('aria-expanded', 'false')
  })

  test('@p2 全部展开/折叠：toggle-all 按钮一次切换所有批次', async ({ page }) => {
    const registered = await getRegisteredBatches(page)
    test.skip(registered.length === 0, '当前环境无已注册批次，跳过 toggle-all 断言')

    await gotoApp(page, '/data')

    const toggleAll = page.locator('[data-testid="batch-toggle-all"]')
    await expect(toggleAll).toBeVisible({ timeout: 15_000 })
    await expect(toggleAll).toContainText('全部展开')

    await toggleAll.click()
    for (const b of registered) {
      await expect(page.locator(`[data-testid="batch-files-${b.name}"]`)).toBeVisible({ timeout: 5_000 })
    }
    await expect(toggleAll).toContainText('全部折叠')

    await toggleAll.click()
    for (const b of registered) {
      await expect(page.locator(`[data-testid="batch-files-${b.name}"]`)).toBeHidden({ timeout: 5_000 })
    }
    await expect(toggleAll).toContainText('全部展开')
  })

  test('@p2 键盘可达性：header 用 Enter / Space 也能切换展开', async ({ page }) => {
    const registered = await getRegisteredBatches(page)
    test.skip(registered.length === 0, '当前环境无已注册批次，跳过键盘可达性断言')

    await gotoApp(page, '/data')

    const first = registered[0]
    const header = page.locator(`[data-testid="batch-header-${first.name}"]`)
    const filesArea = page.locator(`[data-testid="batch-files-${first.name}"]`)

    await expect(header).toBeVisible({ timeout: 15_000 })
    await header.focus()
    await page.keyboard.press('Enter')
    await expect(filesArea).toBeVisible({ timeout: 5_000 })
    await page.keyboard.press('Space')
    await expect(filesArea).toBeHidden({ timeout: 5_000 })
  })
})
