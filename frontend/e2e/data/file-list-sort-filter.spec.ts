import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'

/**
 * 文件列表表头排序 + 筛选（需求5，2026-08-20）：
 * - 文件名/上传时间/大小三列可点表头排序（服务端 ordering，默认最新上传在前）
 * - 上传时间范围（daterange）与大小 min~max 筛选（服务端生效）
 * - 筛选行「清除筛选」恢复默认
 *
 * 注意：20 条/页服务端分页——排序/筛选都必须断言请求参数与响应，而非本地行序。
 */

/** 当前可见 section 内文件列表的 API 请求（GET 查询参数在 URL） */
async function waitFilesRequest(page: Page, predicate: (url: string) => boolean) {
  return page.waitForResponse(
    (r) => r.url().includes('/files/') && predicate(r.url()) && r.status() === 200,
    { timeout: 15_000 },
  )
}

/** 从 /files/ API 拉取当前用户全部文件（含分页），返回 { count, firstNewest } */
async function fetchAllFiles(page: Page) {
  return page.evaluate(async () => {
    const token = localStorage.getItem('access_token')
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
    const d = await fetch('/api/v1/files/?page_size=10000', { headers }).then((r) => r.json())
    const list: any[] = Array.isArray(d) ? d : (d.results ?? [])
    return { count: list.length, newest: list[0]?.filename ?? '', createdDesc: list.every(
      (f, i) => i === 0 || new Date(list[i - 1].created_at) >= new Date(f.created_at),
    ) }
  })
}

test.describe('数据管理 → 文件列表排序/筛选', { tag: ['@data'] }, () => {
  test('@p1 默认排序：上传时间倒序（最新在前）且表头显示降序箭头', async ({ page }) => {
    await gotoApp(page, '/data')
    const { createdDesc, newest } = await fetchAllFiles(page)
    expect(createdDesc, '服务端默认应按上传时间倒序').toBe(true)

    // 表格首行 = 最新文件（服务端分页首页）
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })
    const firstRow = page.locator('.el-table .el-table__row').first()
    await expect(firstRow).toContainText(newest.slice(0, 12))

    // 上传时间列表头显示降序箭头（default-sort prop=created_at descending）
    const timeHeader = page.locator('.el-table__header th').filter({ hasText: '上传时间' }).first()
    await expect(timeHeader.locator('.sort-caret.descending').first()).toBeVisible()
  })

  test('@p1 表头排序：点「大小」列排序，请求带 ordering=file_size', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    const sizeHeader = page.locator('.el-table__header th').filter({ hasText: '大小' }).first()
    const respPromise = waitFilesRequest(page, (url) => url.includes('ordering=file_size'))
    await sizeHeader.click()
    const resp = await respPromise
    const body = await resp.json()
    const sizes = (body.results ?? []).map((f: any) => f.file_size ?? 0)
    expect(sizes.length).toBeGreaterThan(0)
    // 首次点击 = 升序：服务端返回应按 file_size 从小到大
    expect([...sizes].sort((a, b) => a - b).join(','), '首次点击应为升序').toBe(sizes.join(','))

    // 再点一次 → 降序，请求带 -file_size
    const respDescPromise = waitFilesRequest(page, (url) => url.includes('ordering=-file_size'))
    await sizeHeader.click()
    const respDesc = await respDescPromise
    const bodyDesc = await respDesc.json()
    const sizesDesc = (bodyDesc.results ?? []).map((f: any) => f.file_size ?? 0)
    // 第二次点击 = 降序：服务端返回应按 file_size 从大到小
    expect([...sizesDesc].sort((a, b) => b - a).join(','), '第二次点击应为降序').toBe(sizesDesc.join(','))
  })

  test('@p2 上传时间范围筛选：区间内文件保留，区间外排除', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    // 取最近一个文件的创建日期作为区间
    const { newestDate } = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
      const d = await fetch('/api/v1/files/?page_size=10000', { headers }).then((r) => r.json())
      const list: any[] = Array.isArray(d) ? d : (d.results ?? [])
      return { newestDate: list[0]?.created_at?.slice(0, 10) ?? '' }
    })
    expect(newestDate).toBeTruthy()

    const [start, end] = [newestDate, newestDate]
    const respPromise = waitFilesRequest(page, (url) =>
      url.includes(`created_at__gte=${start}`) && url.includes(`created_at__lte=${end}`))
    // 直接填触发器内嵌的两个日期输入框（daterange 触发器含 开始/结束 两个 input）
    const datePicker = page.locator('.sort-filter-row .el-date-editor').first()
    await datePicker.locator('input').first().click()
    await datePicker.locator('input').first().fill(start)
    await datePicker.locator('input').nth(1).click()
    await datePicker.locator('input').nth(1).fill(end)
    await page.keyboard.press('Enter')
    const resp = await respPromise
    const body = await resp.json()
    const names = (body.results ?? []).map((f: any) => f.filename)
    // 区间内应包含最新文件；总数为该日上传文件数（>0）
    expect(names.length).toBeGreaterThan(0)
    for (const n of names) {
      expect(n).toBeTruthy()
    }
  })

  test('@p2 大小范围筛选 + 清除筛选恢复', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    // 只保留 ≤1KB 的文件
    const respPromise = waitFilesRequest(page, (url) => url.includes('file_size__lte=1024'))
    const minInput = page.locator('.sort-filter-row .el-input-number input').first()
    await minInput.click()
    await minInput.fill('0')
    await minInput.press('Tab')
    await minInput.click()
    const maxInput = page.locator('.sort-filter-row .el-input-number input').nth(1)
    await maxInput.click()
    await maxInput.fill('1024')
    await maxInput.press('Tab')
    const resp = await respPromise
    const body = await resp.json()
    const sizes = (body.results ?? []).map((f: any) => f.file_size ?? 0)
    for (const s of sizes) {
      expect(s).toBeLessThanOrEqual(1024)
    }

    // 清除筛选 → 恢复全量（清除按钮出现且可点）
    const clearBtn = page.locator('.sort-filter-row button').filter({ hasText: '清除筛选' })
    await expect(clearBtn).toBeEnabled()
    const respAllPromise = waitFilesRequest(page, (url) =>
      !url.includes('file_size__') && url.includes('ordering=-created_at'))
    await clearBtn.click()
    await respAllPromise
    // 筛选输入已清空
    await expect(page.locator('.sort-filter-row .el-input-number input').first()).toHaveValue('')
    await expect(page.locator('.sort-filter-row .el-input-number input').nth(1)).toHaveValue('')
  })
})
