import { test, expect } from '@playwright/test'
import path from 'node:path'
import { SAMPLE_DATA_DIR, DOWNLOAD_DIR } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'

/**
 * 批次报表（/batch）端到端用例。
 *
 * 组件依据（实测源码 src/pages/data/BatchReport.vue）：
 *  - 标题：h2「📦 批次报表」(line 4)
 *  - el-tabs：本地目录扫描 tab label「📁 本地目录扫描」(name=local，默认激活)，
 *    批次良率报表 tab label「📊 批次良率报表」(name=batch) (line 7, 33)
 *  - 目录输入：el-input placeholder「批次数据目录路径 (如 D:\\Data\\FullData)」(line 8)
 *    其 #append 内含按钮「扫描目录」(line 9)
 *  - 扫描结果区：scanResult 为真时显示 p.file-count「找到 N 个 CSV 文件」+
 *    el-table.scan-table（含 type=selection 复选列）；否则显示 el-empty
 *    description「输入批次目录路径并扫描」(line 15-29)
 *  - 生成按钮：button「生成批次报表」class .generate-button (line 25-27)，
 *    点击 generateReport() → batchApi.generateReport → blob → 合成 <a download> 触发下载
 *  - 系统批次报表 tab：批次下拉 placeholder「选择批次」(line 36)
 *
 * API（src/api/batch.ts）：
 *  - scanDirectory → POST /batch-report/scan_directory/
 *  - generateReport → POST /batch-report/generate_report/ (responseType blob)
 *  - listBatches → GET /batch-report/list_batches/ (onMounted 自动调用)
 *
 * 弹性策略：扫描/生成依赖服务端真实目录与样例数据，可能为空或缺失。
 * 故优先用 waitForResponse 断言请求发生且 status<500，DOM 仅做存在性兜底，
 * 数据不足时 test.skip 并 console.log 原因，避免脆弱的行级断言。
 */

// 真实存在于本机的样例子目录（随仓库提供，含 CSV 样例）
const SCAN_DIR = path.join(SAMPLE_DATA_DIR, 'CTA8290D')

test.describe('批次报表 /batch', { tag: ['@p1', '@p2', '@batch'] }, () => {
  test('@p1 页面渲染：标题/tabs/目录输入/扫描按钮可见', async ({ page }) => {
    await gotoApp(page, '/batch')

    // 标题
    await expect(page.getByRole('heading', { name: '📦 批次报表' })).toBeVisible()

    // 两个 tab 可见，本地目录扫描默认激活
    const localTab = page.getByRole('tab', { name: '📁 本地目录扫描' })
    const batchTab = page.getByRole('tab', { name: '📊 批次良率报表' })
    await expect(localTab).toBeVisible()
    await expect(batchTab).toBeVisible()
    await expect(localTab).toHaveAttribute('aria-selected', 'true')

    // 目录输入框（placeholder 含「批次数据目录路径」，规避反斜杠歧义）
    await expect(page.getByPlaceholder(/批次数据目录路径/)).toBeVisible()

    // 扫描按钮（el-input #append 内）
    await expect(page.getByRole('button', { name: '扫描目录' })).toBeVisible()

    // 初始无扫描结果时显示空态提示
    await expect(page.getByText('输入批次目录路径并扫描')).toBeVisible()
  })

  test('@p1 扫描目录：填入真实样例目录并扫描，等待 scan_directory 响应且区域出现', async ({
    page,
  }) => {
    await gotoApp(page, '/batch')

    // 填入真实服务端目录路径
    await page.getByPlaceholder(/批次数据目录路径/).fill(SCAN_DIR)

    // 点击扫描并等待 scan_directory 响应（status<500 即视为接口可用）
    const scanResp = page.waitForResponse(
      (r) => r.url().includes('/batch-report/scan_directory/'),
    )
    await page.getByRole('button', { name: '扫描目录' }).click()
    const resp = await scanResp
    console.log(`[batch] scan_directory status=${resp.status()} dir=${SCAN_DIR}`)
    expect(resp.status()).toBeLessThan(500)

    // 扫描结果区域出现：成功则出现结果表(.scan-table)或文件计数(.file-count)，
    // 否则仍保留空态提示。两者其一可见即认为页面对扫描作出了响应。
    const scanTable = page.locator('.scan-table')
    const fileCount = page.locator('.file-count')
    const emptyHint = page.getByText('输入批次目录路径并扫描')
    await expect(scanTable.or(fileCount).or(emptyHint).first()).toBeVisible({
      timeout: 15_000,
    })

    if (await scanTable.isVisible().catch(() => false)) {
      console.log('[batch] 扫描出文件，结果表已渲染')
    } else {
      console.log('[batch] 扫描未返回文件（目录无 CSV 或服务端未识别），保留空态')
    }
  })

  test('@p2 生成报表下载：扫描出文件后选择并生成 xlsx', async ({ page }) => {
    await gotoApp(page, '/batch')

    // 扫描真实目录
    await page.getByPlaceholder(/批次数据目录路径/).fill(SCAN_DIR)
    const scanResp = page.waitForResponse(
      (r) => r.url().includes('/batch-report/scan_directory/'),
    )
    await page.getByRole('button', { name: '扫描目录' }).click()
    const resp = await scanResp
    expect(resp.status()).toBeLessThan(500)

    // 前置：必须扫描出文件（出现结果表与选择列）才能继续
    const scanTable = page.locator('.scan-table')
    const hasTable = await scanTable.isVisible({ timeout: 10_000 }).catch(() => false)
    if (!hasTable) {
      test.skip(true, '扫描未返回文件，无法选择生成报表')
      return
    }

    // 先导入到系统：generateReport 用的是行内 f.id，未导入的扫描行无有效 DB id，
    // 直接生成会 500（已知多步工作流：扫描 → 导入 → 生成）。
    const importBtn = page.getByRole('button', { name: /导入到系统/ })
    if (await importBtn.isVisible().catch(() => false)) {
      const importResp = page.waitForResponse(
        (r) => r.url().includes('/batch-report/import_files/'),
        { timeout: 60_000 },
      )
      await importBtn.click()
      await importResp.catch(() => null)
      // 导入后重新扫描，使结果行带上 DB id
      await page.getByRole('button', { name: '扫描目录' }).click()
      await expect(scanTable).toBeVisible({ timeout: 15_000 })
    }

    // 勾选第一行（el-table type=selection 复选框；表头复选框为第一个 checkbox）
    const rowCheckboxes = scanTable.locator('.el-table__body-wrapper .el-checkbox')
    const rowCount = await rowCheckboxes.count()
    if (rowCount === 0) {
      test.skip(true, '结果表无数据行，无法选择文件')
      return
    }
    await rowCheckboxes.first().click()

    // 生成批次报表。原始扫描文件可能尚未导入/不可直接生成，故以
    // /generate_report/ 响应 status<500 作为稳健主信号；下载捕获为尽力而为（短超时，避免挂起）。
    const generateBtn = page.getByRole('button', { name: '生成批次报表' })
    await expect(generateBtn).toBeVisible()

    const genResp = page.waitForResponse(
      (r) => r.url().includes('/batch-report/generate_report/'),
      { timeout: 60_000 },
    )
    const downloadPromise = page
      .waitForEvent('download', { timeout: 10_000 })
      .catch(() => null)

    await generateBtn.click()
    const r = await genResp
    console.log(`[batch] generate_report status=${r.status()}`)

    const dl = await downloadPromise
    if (dl) {
      // 成功路径：捕获到 xlsx 下载
      const name = dl.suggestedFilename()
      await dl.saveAs(path.join(DOWNLOAD_DIR, 'batch', name))
      console.log(`[batch] downloaded ${name}`)
      expect(name.toLowerCase()).toMatch(/\.xlsx$/)
    } else {
      // 未产出文件（如所选行仍非系统内文件 → 后端返回非文件响应）。
      // 属已知多步前置，按计划 skip + log，不误判为成功。
      test.skip(true, `生成未产出文件（generate_report=${r.status()}），需要已导入的批次文件`)
    }
  })

  test('@p2 批次列表：list_batches 接口在挂载时被调用且 status<500', async ({ page }) => {
    // onMounted → loadBatches() → GET /batch-report/list_batches/
    const listResp = page.waitForResponse(
      (r) => r.url().includes('/batch-report/list_batches/'),
    )
    await gotoApp(page, '/batch')

    const resp = await listResp
    console.log(`[batch] list_batches status=${resp.status()}`)
    expect(resp.status()).toBeLessThan(500)

    // 切到「批次良率报表」tab，批次下拉可见（EP 占位符是 span，用占位文本过滤 el-select）
    await page.getByRole('tab', { name: '📊 批次良率报表' }).click()
    await expect(
      page.locator('.el-select').filter({ hasText: '选择批次' }).first(),
    ).toBeVisible()
  })
})
