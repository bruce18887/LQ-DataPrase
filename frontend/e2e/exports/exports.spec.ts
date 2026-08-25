import { test, expect, type Page, type Locator } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { PRIMARY_SAMPLE_FILE } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { uploadFile, expectUploadSuccess } from '../helpers/upload'
import { elSelectByPlaceholder } from '../helpers/elplus'

/**
 * 导出能力（@p2）：Gage Summary / Buyoff Form。
 *
 * 这两个功能都依赖数据库中已存在、可被选择的上传文件，且各自需要 >= 2 个文件
 * （Gage 的 8 个 Site 槽位 / Buyoff 的 FT/QA1/QA2 角色，generate 按钮在
 * assignedFileIds.length < 2 时为 disabled）。测试环境可能没有足够文件，故：
 *   1) 渲染测试始终执行（tab 内容、控件、生成按钮可见）；
 *   2) 下载测试在可选文件 < 2 时 test.skip + console.log；满足时分配文件并生成，
 *      以 waitForResponse(/generate.../，status<500) 作为稳健信号，下载断言为尽力而为。
 *
 * 注意：组件下载走 Blob + 动态 <a download> 点击，会触发真实 download 事件，
 * 因此可用 captureDownload 捕获 .xlsx。
 *
 * 选择器依据（已对照源码）：
 *   - DataManagement.vue:12-17  el-tab-pane label="Buyoff Form" / "Gage Summary"
 *   - GageSummary.vue:18         8 个 <el-select placeholder="选择文件">（Site 槽位）
 *   - GageSummary.vue:58-66      生成按钮文本含「生成 Gage Summary」，<2 时 disabled
 *   - GageSummary.vue:5          gageApi.generateSummary → POST /gage/generate_summary/
 *   - BuyoffForm.vue:15          3 个 <el-select placeholder="选择文件">（FT/QA1/QA2）
 *   - BuyoffForm.vue:99-107      生成按钮文本含「生成 Buyoff Form」，<2 时 disabled
 *   - BuyoffForm.vue:8           buyoffApi.generateForm → POST /buyoff/generate_form/
 *   - api/index.ts baseURL='/api/v1' → 实际路径 /api/v1/<...>
 */

/**
 * 切到指定 el-tab，等待其面板标题可见，返回“当前可见 tabpanel”作用域。
 *
 * 注意：el-tabs 默认会把所有 el-tab-pane 渲染进 DOM（非激活面板 display:none）。
 * GageSummary(8) 与 BuyoffForm(3) 都使用 placeholder="选择文件" 的 el-select，
 * 因此页面级定位会跨面板命中 8+3 个。必须用 :visible 过滤到当前激活面板，
 * 计数与交互才准确。
 */
async function openTab(page: Page, tabLabel: string, panelHeading: string) {
  await gotoApp(page, '/data')
  await page.getByRole('tab', { name: tabLabel }).click()
  await expect(page.getByRole('heading', { name: panelHeading })).toBeVisible({ timeout: 15_000 })
  // 文件列表由 DataManagement 的 loadFiles()（onMounted）拉取后作为 prop 传入，
  // 必须等 /files/ 返回才能保证 el-select 下拉有可选项，否则下拉为空。
  await page.waitForResponse(
    (r) => /\/files\/?(\?|$)/.test(r.url()) && r.status() === 200,
    { timeout: 15_000 },
  ).catch(() => {})
  return page.locator('[role="tabpanel"]:visible')
}

/**
 * 依次为前 N 个 el-select 选择不同文件。
 * el-select 选项 teleport 到 body（.el-select-dropdown__item），逐个打开并取“可用项”。
 * 返回成功分配的数量。
 */
async function assignFiles(page: Page, selects: Locator, want: number): Promise<number> {
  let assigned = 0
  const total = await selects.count()

  for (let i = 0; i < total && assigned < want; i++) {
    try {
      const sel = selects.nth(i)
      // 点开下拉
      await sel.click()
      const dropdown = page.locator('.el-select-dropdown:visible')
      await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
      await page.waitForTimeout(200)

      // 重试：首次打开可能 API 还未返回、选项为 0
      let options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
      let count = await options.count()
      if (count === 0) {
        await page.keyboard.press('Escape')
        await page.waitForTimeout(500)
        await sel.click()
        await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
        await page.waitForTimeout(200)
        options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
        count = await options.count()
      }

      if (count === 0) {
        await page.keyboard.press('Escape')
        break
      }

      await options.first().click()
      assigned++
      await dropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})
      await page.waitForTimeout(200)
    } catch (e) {
      await page.keyboard.press('Escape').catch(() => {})
      break
    }
  }
  return assigned
}

test.describe('@p2 导出 - Gage Summary', { tag: ['@p2', '@exports'] }, () => {
  test('Gage tab 控件渲染', async ({ page }) => {
    const panel = await openTab(page, 'Gage Summary', 'Gage Summary 生成')

    // 8 个 Site 槽位的文件选择器（EP 占位符是 span，用占位文本过滤；作用域到当前可见面板）
    const selects = elSelectByPlaceholder(panel, '选择文件')
    await expect(selects.first()).toBeVisible()
    expect(await selects.count()).toBe(8)

    // 选项 checkbox 与生成按钮可见（限定当前可见面板，两个面板都在 DOM 中）
    await expect(panel.getByText('只选择 Bin1 数据')).toBeVisible()
    await expect(panel.getByText('忽略无 Limit 测试项')).toBeVisible()
    const generateBtn = panel.getByRole('button', { name: /生成 Gage Summary/ })
    await expect(generateBtn).toBeVisible()
  })

  test('可选文件足够则生成并下载 xlsx', async ({ page }) => {
    test.slow() // 分配 dropdown + 下载可能耗时较长
    const panel = await openTab(page, 'Gage Summary', 'Gage Summary 生成')

    // 分配时用原始 .el-select（索引稳定；选中后占位文本会消失，不能用占位过滤集合）
    const selects = panel.locator('.el-select')
    const assigned = await assignFiles(page, selects, 2)

    if (assigned < 2) {
      console.log(`[gage] 可选上传文件不足（已分配 ${assigned}，需 >=2），跳过下载验证`)
      test.skip(true)
      return
    }

    const generateBtn = page.getByRole('button', { name: /生成 Gage Summary/ })
    await expect(generateBtn).toBeEnabled()

    // 并行等待响应 + 可选的下载事件（短超时），避免 download 未触发阻塞整个测试
    const respPromise = page.waitForResponse(
      (r) => /\/gage\/generate_summary\/?$/.test(new URL(r.url()).pathname),
      { timeout: 60_000 },
    )
    const dlPromise = page.waitForEvent('download', { timeout: 15_000 }).catch(() => null)

    await generateBtn.click()
    const [resp, dl] = await Promise.all([respPromise, dlPromise])
    expect(resp.status(), 'generate_summary 不应 5xx').toBeLessThan(500)

    if (dl) {
      const name = dl.suggestedFilename()
      console.log(`[gage] downloaded ${name}`)
      expect(name.toLowerCase()).toMatch(/\.xlsx$/)
    } else {
      console.log(`[gage] 未捕获下载（后端可能返回非文件响应），响应状态=${resp.status()}`)
    }
  })
})

test.describe('@p2 导出 - Buyoff Form', { tag: ['@p2', '@exports'] }, () => {
  test('Buyoff tab 控件渲染', async ({ page }) => {
    const panel = await openTab(page, 'Buyoff Form', 'Buyoff Form 生成')

    // 3 个角色（FT / QA1 / QA2）的文件选择器（EP 占位符是 span，用占位文本过滤）
    const selects = elSelectByPlaceholder(panel, '选择文件')
    await expect(selects.first()).toBeVisible()
    expect(await selects.count()).toBe(3)

    // 选项与两个动作按钮可见（限定当前可见面板）
    await expect(panel.getByText('只选择 Bin1 数据')).toBeVisible()
    await expect(panel.getByRole('button', { name: /分析共同测试项/ })).toBeVisible()
    await expect(panel.getByRole('button', { name: /生成 Buyoff Form/ })).toBeVisible()
  })

  test('可选文件足够则生成并下载 xlsx', async ({ page }) => {
    test.slow()
    const panel = await openTab(page, 'Buyoff Form', 'Buyoff Form 生成')

    const selects = panel.locator('.el-select')
    const assigned = await assignFiles(page, selects, 2)

    if (assigned < 2) {
      console.log(`[buyoff] 可选上传文件不足（已分配 ${assigned}，需 >=2），跳过下载验证`)
      test.skip(true)
      return
    }

    const generateBtn = page.getByRole('button', { name: /生成 Buyoff Form/ })
    await expect(generateBtn).toBeEnabled()

    const respPromise = page.waitForResponse(
      (r) => /\/buyoff\/generate_form\/?$/.test(new URL(r.url()).pathname),
      { timeout: 60_000 },
    )
    const dlPromise = page.waitForEvent('download', { timeout: 15_000 }).catch(() => null)

    await generateBtn.click()
    const [resp, dl] = await Promise.all([respPromise, dlPromise])
    expect(resp.status(), 'generate_form 不应 5xx').toBeLessThan(500)

    if (dl) {
      const name = dl.suggestedFilename()
      console.log(`[buyoff] downloaded ${name}`)
      expect(name.toLowerCase()).toMatch(/\.xlsx$/)
    } else {
      console.log(`[buyoff] 未捕获下载（后端可能返回非文件响应），响应状态=${resp.status()}`)
    }
  })
})

/**
 * 回归用例：GageSummary / BuyoffForm 的文件下拉必须与数据库实时同步。
 *
 * 两个组件曾各自在 onMounted 拉一次 /files/（无 page_size、无 filesVersion/
 * onActivated 刷新），而 DataManagement 的 tab 用 v-show + keep-alive 常驻，
 * 导致上传新文件后切换到 Gage/Buyoff tab 时下拉仍是旧列表，必须整页 reload
 * 才可见新文件。修复后文件列表由 DataManagement 统一刷新并作为 prop 传入，
 * 本测试验证：上传 → 切 tab（不 reload）→ 下拉立即出现新文件。
 */
test.describe('@p2 导出 - 文件列表与数据库同步', { tag: ['@p2', '@exports'] }, () => {
  test('上传新文件后 Gage / Buyoff 下拉无需 reload 即可见新文件', async ({ page }) => {
    const uniqueName = `e2e_sync_${Date.now()}_${Math.floor(Math.random() * 1e6)}.csv`
    const tmpPath = path.join(os.tmpdir(), uniqueName)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmpPath)

    try {
      await gotoApp(page, '/data')

      // 文件列表 tab：展开上传区并上传新文件（参照 data.spec.ts 上传流程）
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, tmpPath)
      await expectUploadSuccess(page)

      // 上传会 bump filesVersion → DataManagement 重新拉取 /files/（page_size 9999）
      await page.waitForResponse(
        (r) => /\/files\/?(\?|$)/.test(r.url()) && r.request().method() === 'GET' && r.status() === 200,
        { timeout: 15_000 },
      ).catch(() => {})

      // 切到 Gage Summary tab（不 reload），打开第一个 Site 槽位下拉，新文件必须出现
      await page.getByRole('tab', { name: 'Gage Summary' }).click()
      const gagePanel = page.locator('[role="tabpanel"]:visible')
      await expect(gagePanel.getByRole('heading', { name: 'Gage Summary 生成' })).toBeVisible()
      await gagePanel.locator('.el-select').first().click()
      const gageDropdown = page.locator('.el-select-dropdown:visible')
      await expect(gageDropdown.getByText(uniqueName)).toBeVisible({ timeout: 15_000 })
      await page.keyboard.press('Escape')

      // 切到 Buyoff Form tab，第一个角色下拉同样必须出现新文件
      await page.getByRole('tab', { name: 'Buyoff Form' }).click()
      const buyoffPanel = page.locator('[role="tabpanel"]:visible')
      await expect(buyoffPanel.getByRole('heading', { name: 'Buyoff Form 生成' })).toBeVisible()
      await buyoffPanel.locator('.el-select').first().click()
      const buyoffDropdown = page.locator('.el-select-dropdown:visible')
      await expect(buyoffDropdown.getByText(uniqueName)).toBeVisible({ timeout: 15_000 })
      await page.keyboard.press('Escape')
    } finally {
      fs.rmSync(tmpPath, { force: true })
    }
  })
})

/**
 * 回归用例：ExportToolsTab (数据管理 → 导出工具) 的 Sigma Limit / Excel / PPT
 * 三个按钮曾因 useExport 解构出错的 `exportSigma is not a function` 全部静默失败。
 * 此测试断言：
 *   1) 「忽略无Limit」复选框可见
 *   2) 选择文件后点击「导出 Sigma Limit」会发出 /export/sigma_limit/ 请求
 *   3) 不会在控制台抛出 `exportSigma is not a function` / `exportBatch is not a function`
 */
test.describe('@p2 导出 - Export Tools Tab', { tag: ['@p2', '@exports'] }, () => {
  test('Sigma Limit 按钮可点击并触发后端请求（回归 exportSigma is not a function）', async ({ page }) => {
    const consoleErrors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })
    page.on('pageerror', (err) => consoleErrors.push(err.message))

    await gotoApp(page, '/data')
    // 切到 "导出工具" tab (DataManagement.vue tabs-nav > button.tab-btn)
    await page.locator('.tab-btn').filter({ hasText: '导出工具' }).click()

    // 等待 /files/ 返回，确保 banner 下拉有可选文件
    await page.waitForResponse(
      (r) => /\/files\/?(\?|$)/.test(r.url()) && r.status() === 200,
      { timeout: 15_000 },
    ).catch(() => {})

    // 在父级 banner 中选择第一个文件 (DataManagement.vue 当前文件选择器)，重试一次防并行负载竞态
    const fileSelect = page.locator('.active-file-banner:visible .el-select').first()
    await fileSelect.click()
    const dropdown = page.locator('.el-select-dropdown:visible')
    await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
    await page.waitForTimeout(200)
    let options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
    let count = await options.count()
    if (count === 0) {
      console.log('[export-tools] 文件下拉为空，重试一次')
      await page.keyboard.press('Escape')
      await page.waitForTimeout(500)
      await fileSelect.click()
      await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
      await page.waitForTimeout(200)
      options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
      count = await options.count()
    }
    if (count === 0) {
      console.log('[export-tools] 可选文件为空，跳过点击断言')
      await page.keyboard.press('Escape')
      test.skip(true, '无可用上传文件')
      return
    }
    await options.first().click()
    await dropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})
    await page.waitForTimeout(200)

    // 等待参数列表加载（ExportToolsTab.vue 拉 /analysis/histogram/）
    await page.waitForResponse(
      (r) => /\/analysis\/histogram\/?/.test(new URL(r.url()).pathname) && r.status() === 200,
      { timeout: 15_000 },
    ).catch(() => {})

    // 选择第一个参数，确保批量导出按钮可用
    const paramSelect = page.locator('.export-tools .el-select').filter({ hasText: '点击选择要导出的参数' }).first()
    await paramSelect.click()
    const paramDropdown = page.locator('.el-select-dropdown:visible')
    await paramDropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
    const paramOptions = paramDropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
    if (await paramOptions.count() > 0) {
      await paramOptions.first().click()
    }
    await paramDropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})

    // ExportToolsTab 内的关键控件可见（使用 exact 避免匹配到其他 tab 的相似文本）
    await expect(page.getByText('批量导出参数分布图')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText('忽略无Limit')).toBeVisible()
    await expect(page.getByText('Limit', { exact: true })).toBeVisible()
    await expect(page.getByText('6σ', { exact: true })).toBeVisible()

    const sigmaBtn = page.getByRole('button', { name: /导出 Sigma Limit/ })
    const xlsxBtn = page.getByRole('button', { name: /批量导出 Excel/ })
    const pptxBtn = page.getByRole('button', { name: /批量导出 PPT/ })
    await expect(sigmaBtn).toBeVisible()
    await expect(xlsxBtn).toBeVisible()
    await expect(pptxBtn).toBeVisible()

    // 点击导出 Sigma Limit：必须触发 /export/sigma_limit/ 200 请求
    const respPromise = page.waitForResponse(
      (r) => /\/export\/sigma_limit\/?$/.test(new URL(r.url()).pathname),
      { timeout: 30_000 },
    )
    await sigmaBtn.click()
    const resp = await respPromise
    expect(resp.status(), 'sigma_limit 不应 5xx').toBeLessThan(500)

    // 核心回归断言：使用错误的函数名应抛出的 TypeError 不应出现
    const offendingErrors = consoleErrors.filter((e) =>
      /exportSigma is not a function|exportBatch is not a function/.test(e),
    )
    expect(offendingErrors, '不应出现 exportSigma/exportBatch 解析错误').toEqual([])
  })

  test('选择多个参数后可批量导出 Excel（覆盖全选路径）', async ({ page }) => {
    test.slow()

    const consoleErrors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text())
    })
    page.on('pageerror', (err) => consoleErrors.push(err.message))

    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '导出工具' }).click()

    await page.waitForResponse(
      (r) => /\/files\/?(\?|$)/.test(r.url()) && r.status() === 200,
      { timeout: 15_000 },
    ).catch(() => {})

    // 选择第一个文件（重试一次：并行负载下 /files/ API 可能未返回、选项为 0）
    const fileSelect = page.locator('.active-file-banner:visible .el-select').first()
    await fileSelect.click()
    const dropdown = page.locator('.el-select-dropdown:visible')
    await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
    await page.waitForTimeout(200)
    let options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
    if (await options.count() === 0) {
      await page.keyboard.press('Escape')
      await page.waitForTimeout(500)
      await fileSelect.click()
      await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
      await page.waitForTimeout(200)
      options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
    }
    if (await options.count() === 0) {
      await page.keyboard.press('Escape')
      test.skip(true, '无可用上传文件')
      return
    }
    await options.first().click()
    await dropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})
    await page.waitForTimeout(200)

    // 等待参数列表加载
    await page.waitForResponse(
      (r) => /\/analysis\/histogram\/?/.test(new URL(r.url()).pathname) && r.status() === 200,
      { timeout: 15_000 },
    ).catch(() => {})

    // 全选参数：E2E 环境参数过多时可能导致后端超时，因此最多选 20 个
    const panel = page.locator('.export-tools')
    const paramSelect = panel.locator('.el-select').filter({ hasText: '点击选择要导出的参数' }).first()
    await paramSelect.click()
    const paramDropdown = page.locator('.el-select-dropdown:visible')
    await paramDropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
    const paramOptions = paramDropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
    const paramCount = await paramOptions.count()
    if (paramCount === 0) {
      await page.keyboard.press('Escape')
      test.skip(true, '该文件无可导出参数')
      return
    }
    const selectLimit = Math.min(paramCount, 20)
    for (let i = 0; i < selectLimit; i++) {
      await paramOptions.nth(i).click()
    }
    await page.keyboard.press('Escape')
    await paramDropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})

    // 确认已选计数
    await expect(panel.locator('.step-count')).toContainText(`已选 ${selectLimit}`)

    // 批量导出 Excel：后端大图生成可能较慢，给 180 秒超时
    const respPromise = page.waitForResponse(
      (r) => /\/export\/batch_charts\/?$/.test(new URL(r.url()).pathname),
      { timeout: 180_000 },
    )
    const dlPromise = page.waitForEvent('download', { timeout: 180_000 }).catch(() => null)

    const xlsxBtn = page.getByRole('button', { name: /批量导出 Excel/ })
    await expect(xlsxBtn).toBeEnabled()
    await xlsxBtn.click()

    const [resp, dl] = await Promise.all([respPromise, dlPromise])
    expect(resp.status(), 'batch_charts 不应 5xx/超时').toBeLessThan(500)

    if (dl) {
      const name = dl.suggestedFilename()
      console.log(`[export-tools] downloaded ${name}`)
      expect(name.toLowerCase()).toMatch(/\.xlsx$/)
    } else {
      console.log(`[export-tools] 未捕获下载，响应状态=${resp.status()}`)
    }

    const offendingErrors = consoleErrors.filter((e) =>
      /exportSigma is not a function|exportBatch is not a function/.test(e),
    )
    expect(offendingErrors, '不应出现 exportSigma/exportBatch 解析错误').toEqual([])
  })

  test('输入关键字按 Enter 可全选匹配参数（过滤 + 清空 + 增量累计）', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '导出工具' }).click()

    await page.waitForResponse(
      (r) => /\/files\/?(\?|$)/.test(r.url()) && r.status() === 200,
      { timeout: 15_000 },
    ).catch(() => {})

    // 选择第一个文件（重试一次：并行负载下 /files/ API 可能未返回、选项为 0）
    const fileSelect = page.locator('.active-file-banner:visible .el-select').first()
    await fileSelect.click()
    const dropdown = page.locator('.el-select-dropdown:visible')
    await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
    await page.waitForTimeout(200)
    let options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
    if (await options.count() === 0) {
      await page.keyboard.press('Escape')
      await page.waitForTimeout(500)
      await fileSelect.click()
      await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
      await page.waitForTimeout(200)
      options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
    }
    if (await options.count() === 0) {
      await page.keyboard.press('Escape')
      test.skip(true, '无可用上传文件')
      return
    }
    await options.first().click()
    await dropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})
    await page.waitForTimeout(200)

    // 等待参数列表加载
    await page.waitForResponse(
      (r) => /\/analysis\/histogram\/?/.test(new URL(r.url()).pathname) && r.status() === 200,
      { timeout: 15_000 },
    ).catch(() => {})

    const panel = page.locator('.export-tools')

    // 打开参数下拉：读取全部参数名，并点选第 2 个（合并语义基线：已选 1，下拉保持打开）
    const paramSelect = panel.locator('.el-select').filter({ hasText: '点击选择要导出的参数' }).first()
    await paramSelect.click()
    let paramDropdown = page.locator('.el-select-dropdown:visible')
    await paramDropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
    await page.waitForTimeout(200)
    let paramOptions = paramDropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
    let P = (await paramOptions.allTextContents()).map((n) => n.trim()).filter(Boolean)
    if (P.length < 2) {
      // 重试一次：参数列表请求可能未完成
      await page.keyboard.press('Escape')
      await paramDropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})
      await page.waitForTimeout(500)
      await paramSelect.click()
      paramDropdown = page.locator('.el-select-dropdown:visible')
      await paramDropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
      await page.waitForTimeout(200)
      paramOptions = paramDropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
      P = (await paramOptions.allTextContents()).map((n) => n.trim()).filter(Boolean)
    }
    if (P.length < 2) {
      await page.keyboard.press('Escape')
      test.skip(true, '该文件参数不足 2 个')
      return
    }
    await paramOptions.nth(1).click()
    await expect(panel.locator('.step-count')).toContainText('已选 1 /')

    // 关键字 = 第一个参数名的前 6 字符（保证 ≥1 匹配），N 从页面参数列表自算
    const kw = P[0].slice(0, 6)
    const matchesArr = P.filter((p) => p.toLowerCase().includes(kw.toLowerCase()))
    const N = matchesArr.length
    expect(N, '关键字应至少匹配 1 个参数').toBeGreaterThanOrEqual(1)

    // filterable 输入框（EP 将 aria-label 绑在 input 本身，见 select2.mjs:217）：填入关键字 → 下拉过滤 + footer 提示匹配数
    const input = panel.locator('.el-select__input').first()
    await input.fill(kw)
    await expect(paramDropdown.locator('.match-hint')).toContainText(`匹配 ${N} 项，按 Enter 全选`)

    // Enter 全选：已选 = {P[1]} ∪ 匹配集（P[1] 可能在匹配集中，用 Set 算实际值）
    const expected = new Set([P[1], ...matchesArr]).size
    await input.press('Enter')
    await expect(panel.locator('.step-count')).toContainText(`已选 ${expected} / 共 ${P.length} 个`)

    // 全选后输入框自动清空 → 可继续输入其它关键字（增量累计）
    await expect(input).toHaveValue('')
    const kw2 = P[0].slice(0, 5)
    const matchesArr2 = P.filter((p) => p.toLowerCase().includes(kw2.toLowerCase()))
    const expected2 = new Set([P[1], ...matchesArr, ...matchesArr2]).size
    await input.fill(kw2)
    await input.press('Enter')
    await expect(panel.locator('.step-count')).toContainText(`已选 ${expected2} / 共 ${P.length} 个`)
  })
})
