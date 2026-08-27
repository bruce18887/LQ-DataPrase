import { test, expect } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { gotoApp } from '../helpers/nav'
import { uploadMultipleFiles, expectUploadSuccess } from '../helpers/upload'
import { cleanupQuiet } from '../helpers/cleanup'

/**
 * 文件列表完整性：分析页文件选择框数量与数据管理页一致（回归钉）。
 *
 * 缺陷形态（用户报告）：分析页文件下拉只有 20 个文件（DRF 默认分页类忽略
 * `page_size` query param，`?page_size=9999` 被静默截断为 PAGE_SIZE=20），
 * 数据管理页分页表格 count 显示全量 → 两处数量不一致，点「修复」无效
 * （一致性检查修的是孤儿文件，与分页无关）。修复后 `page_size` 生效，
 * 下拉显示全部文件。
 *
 * 断言设计（修复前必失败）：
 *  - 上传 21 个文件（> PAGE_SIZE 20）后，分析页下拉选项数 ≥ 21（修复前 = 20）；
 *  - 数据管理页分页 total == 分析页下拉选项数（同一 /files/ 全量口径）。
 */

const SINGLE = '.single-param-tab'

const MIN_CSV = [
  'CTA8280F,',
  'Device Name,TEST_DEVICE,',
  '[Data]',
  'Index_No,Dut_No,Serial_No,Site_No,Dut_Pass,SW_Bin,KELVIN_VIN,',
  'Unit,Unit,Unit,Unit,Unit,Unit,ohm,',
  'Min,Min,Min,Min,Min,Min,0,',
  'Max,Max,Max,Max,Max,Max,2,',
  '1,1,1,1,TRUE,1,1.0,',
  '',
].join('\n')

/** 超过 PAGE_SIZE=20 的文件数——分页截断缺陷的临界形态 */
const FILE_COUNT = 21

test.describe('文件列表完整性：分析页下拉与数据管理页数量一致', { tag: ['@p1', '@analysis'] }, () => {
  let paths: string[] = []

  test.beforeAll(() => {
    const stamp = Date.now()
    for (let i = 0; i < FILE_COUNT; i++) {
      const p = path.join(os.tmpdir(), `e2e_page_list_${stamp}_${i}.csv`)
      fs.writeFileSync(p, MIN_CSV, 'utf-8')
      paths.push(p)
    }
  })

  test.afterAll(() => {
    for (const p of paths) cleanupQuiet(p)
  })

  test('分析页文件下拉显示全部文件，与数据管理页总数一致', async ({ page }) => {
    // 上传 21 个文件（el-upload multiple 一次注入；multiple 模式逐文件发 POST，
    // toast 出现不代表全部完成——下方轮询文件列表直至 21 个全到位）
    await gotoApp(page, '/data')
    await page.locator('button').filter({ hasText: '上传文件' }).click()
    await uploadMultipleFiles(page, paths)
    await expectUploadSuccess(page)

    let totalCount = 0
    await expect.poll(
      async () => {
        await gotoApp(page, '/data') // 重进触发 loadFiles，分页 total 为全量 count
        const t = await page
          .locator('.el-pagination__total').first()
          .textContent({ timeout: 10_000 })
          .catch(() => null)
        totalCount = Number((t ?? '').match(/\d+/)?.[0] ?? 0)
        return totalCount
      },
      { timeout: 120_000, message: '上传的 21 个文件未全部进入文件列表' },
    ).toBeGreaterThanOrEqual(FILE_COUNT)

    // 分析页：打开文件下拉，数选项
    await gotoApp(page, '/analysis')
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    const fileSel = page.locator('.el-select').first()
    await expect(fileSel).toBeVisible({ timeout: 15_000 })
    await fileSel.click()
    const options = page.locator('.el-select-dropdown__item:visible')
    await expect(options.first()).toBeVisible({ timeout: 15_000 })
    const dropdownCount = await options.count()
    // 修复前 page_size 被忽略 → 恒为 20；修复后 ≥ 21（我们上传的全部可见）
    expect(dropdownCount, '分析页下拉必须显示全部文件（修复前被截断为 20）').toBeGreaterThanOrEqual(FILE_COUNT)
    await page.keyboard.press('Escape')

    // 口径（2026-08-29 起）：数据管理「文件列表」Tab 只显示单文件（file_type=single），
    // 批次文件移到「批次数据」Tab；分析页下拉仍是全量（single+batch）。
    // 故改为三方对照：UI 总数 == API 单文件数；分析下拉 == API 全量数。
    const api = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const d = await fetch('/api/v1/files/?page_size=10000', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }).then((r) => r.json())
      const list: any[] = Array.isArray(d) ? d : (d.results ?? [])
      return {
        total: list.length,
        singles: list.filter((f) => f.file_type === 'single').length,
      }
    })
    expect(totalCount, `数据管理页 total=${totalCount} 应与单文件 API 数=${api.singles} 一致`).toBe(api.singles)
    expect(dropdownCount, `分析页下拉=${dropdownCount} 应与全量 API 数=${api.total} 一致`).toBe(api.total)
    expect(api.total, '全量应不小于单文件数').toBeGreaterThanOrEqual(api.singles)
  })
})
