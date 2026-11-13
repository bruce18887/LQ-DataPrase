import { test, expect, type Page, type Locator } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { PRIMARY_SAMPLE_FILE, SEEDED_FILES } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { uploadFile, expectUploadSuccess } from '../helpers/upload'
import { elSelectByPlaceholder, EXPORT_PARAM_POPPER, popperOf } from '../helpers/elplus'
import { paramKeysFromHistogram, pickBoundedKeyword } from '../helpers/params'
import { expectWindowRows, MAX_WINDOW_ROWS, windowItems } from '../helpers/selectV2'

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
 * 定位与端点（行号会漂，所以只记符号）：两个 tab 由 `DataManagement.vue` 的 el-tab-pane 承接，
 * 表单在 `GageSummary.vue`（POST /gage/generate_summary/，8 个 placeholder="选择文件"）与
 * `BuyoffForm.vue`（POST /buyoff/generate_form/，3 个同名 placeholder）—— 正因为两边同名，
 * 页面级定位会跨面板命中 8+3 个，必须用 `:visible` 限定到当前激活面板。api/index.ts 的
 * baseURL='/api/v1' ⇒ 实际路径带该前缀。
 */

/**
 * 切到指定 el-tab，等待其面板标题可见，返回“当前可见 tabpanel”作用域。
 * el-tabs 把所有 pane 都渲染进 DOM（非激活的那块 display:none），所以作用域必须落在
 * 可见面板上 —— 计数与交互都靠它，见上面文件头那条「两边同名 placeholder」。
 */
async function openTab(page: Page, tabLabel: string, panelHeading: string) {
  await gotoApp(page, '/data')
  await page.getByRole('tab', { name: tabLabel }).click()
  await expect(page.getByRole('heading', { name: panelHeading })).toBeVisible({ timeout: 15_000 })
  // 这里**不要**再等 /files/：loadFiles() 在 onMounted 就发了，等它必须注册在
  // gotoApp 之前（R2④），注册晚了只会把 15s 超时烧满再被 catch 吞掉。「下拉有可选项」
  // 由下面的 waitForOptions 轮询保证 —— 那才是正确机制。
  return page.locator('[role="tabpanel"]:visible')
}

/**
 * 条件等待下拉选项就绪（数量 > 0）；超时仍为 0 时静默返回当前数量，由调用方决定是否走
 * Escape 重试 / skip 分支。（替代固定 waitForTimeout(200)：选项就绪快慢不定，固定等待两头都不稳）
 */
async function waitForOptions(options: Locator): Promise<number> {
  await expect
    .poll(() => options.count(), { timeout: 5_000 })
    .toBeGreaterThan(0)
    .catch(() => {})
  return options.count()
}

/**
 * 依次为前 N 个 el-select 选择不同文件；选项 teleport 到 body（.el-select-dropdown__item），
 * 逐个打开并取“可用项”，返回成功分配的数量。
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

      // 重试：首次打开可能 API 还未返回、选项为 0
      let options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
      let count = await waitForOptions(options)
      if (count === 0) {
        await page.keyboard.press('Escape')
        await dropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})
        await sel.click()
        await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
        options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
        count = await waitForOptions(options)
      }

      if (count === 0) {
        await page.keyboard.press('Escape')
        break
      }

      await options.first().click()
      assigned++
      await dropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})
    } catch (e) {
      await page.keyboard.press('Escape').catch(() => {})
      break
    }
  }
  return assigned
}

/**
 * 在指定 el-select 中按文件名选择选项（返回是否成功）。Gage 槽位 = 工位编号，需要把「含对应工位」
 * 的文件放到正确槽位，因此不能像 assignFiles 那样取任意可用项。
 */
async function pickOptionByName(page: Page, sel: Locator, name: string): Promise<boolean> {
  for (let attempt = 0; attempt < 2; attempt++) {
    await sel.click()
    const dropdown = page.locator('.el-select-dropdown:visible')
    await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
    const option = dropdown.locator('.el-select-dropdown__item', { hasText: name })
    if ((await option.count()) > 0) {
      await option.first().click()
      await dropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})
      return true
    }
    await page.keyboard.press('Escape')
    await dropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})
  }
  return false
}

/** 一次批量导出带的参数上限：旧实现按位置点 `min(渲染项数, 20)` 个，那个 20 躲的是「参数过多时
 *  后端导出超时」。换成「输入关键词 → Enter 全选匹配集」后这个界必须保住，否则一次全选出上千个。 */
const EXPORT_PARAM_SELECT_CAP = 20

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

  // 槽位 = 工位编号：S1 分配含 Site 1 的文件、S2 分配含 Site 2 的文件，
  // 生成只含各工位数据的 xlsx（不再把文件里的全部工位混在一起）。
  test('按槽位工位过滤并生成下载 xlsx', async ({ page }) => {
    test.slow() // 分配 dropdown + 下载可能耗时较长
    const panel = await openTab(page, 'Gage Summary', 'Gage Summary 生成')

    const selects = panel.locator('.el-select')
    const ok1 = await pickOptionByName(page, selects.nth(0), SEEDED_FILES.GAGE_S1)
    const ok2 = await pickOptionByName(page, selects.nth(1), SEEDED_FILES.GAGE_S2)
    if (!ok1 || !ok2) {
      console.log('[gage] 未找到预期的 gage 样例文件，跳过下载验证')
      test.skip(true)
      return
    }

    const generateBtn = page.getByRole('button', { name: /生成 Gage Summary/ })
    await expect(generateBtn).toBeEnabled()

    const respPromise = page.waitForResponse(
      (r) => /\/gage\/generate_summary\/?$/.test(new URL(r.url()).pathname),
      { timeout: 60_000 },
    )
    const dlPromise = page.waitForEvent('download', { timeout: 15_000 }).catch(() => null)

    await generateBtn.click()
    const [resp, dl] = await Promise.all([respPromise, dlPromise])
    expect(resp.status(), '正确分配工位应返回 200').toBe(200)

    if (dl) {
      const name = dl.suggestedFilename()
      console.log(`[gage] downloaded ${name}`)
      expect(name.toLowerCase()).toMatch(/\.xlsx$/)
    } else {
      console.log('[gage] 未捕获下载事件（响应仍为 200）')
    }
  })

  // 槽位文件不含该工位的数据 → 后端 400，前端弹出具体原因，不下载。
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

    // 在父级 banner 中选择第一个文件 (DataManagement.vue 当前文件选择器)，重试一次防并行负载竞态
    const fileSelect = page.locator('.active-file-banner:visible .el-select').first()
    await fileSelect.click()
    const dropdown = page.locator('.el-select-dropdown:visible')
    await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
    let options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
    let count = await waitForOptions(options)
    if (count === 0) {
      console.log('[export-tools] 文件下拉为空，重试一次')
      await page.keyboard.press('Escape')
      await dropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})
      await fileSelect.click()
      await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
      options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
      count = await waitForOptions(options)
    }
    if (count === 0) {
      console.log('[export-tools] 可选文件为空，跳过点击断言')
      await page.keyboard.press('Escape')
      test.skip(true, '无可用上传文件')
      return
    }
    // 等待参数列表加载（ExportToolsTab.vue 选文件后拉 /analysis/histogram/）
    // 注册必须先于触发点击（R2④：响应先到则永远等不到）
    const histogramResp = page
      .waitForResponse(
        (r) => /\/analysis\/histogram\/?/.test(new URL(r.url()).pathname) && r.status() === 200,
        { timeout: 15_000 },
      )
      .catch(() => null)
    await options.first().click()
    await dropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})
    await histogramResp

    // 选择第一个参数，确保批量导出按钮可用
    const paramSelect = page.locator('.export-tools .el-select').filter({ hasText: '点击选择要导出的参数' }).first()
    await paramSelect.click()
    const paramDropdown = page.locator('.el-select-dropdown:visible')
    await paramDropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
    const paramOptions = paramDropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
    if (await paramOptions.count() > 0) {
      await paramOptions.first().click()
    }
    // 多选下拉点选项不会自动收起。以前 popper 空间不够会向上翻，恰好没挡住下面的导出按钮；
    // 页头删除后下方腾出 104px，它改成向下展开，正好把「导出 Sigma Limit」整个盖住 → 点击被
    // popper 接走，30s 后响应等不到。所以这里显式收起并断言真的收起了（原来那句
    // waitFor({state:'hidden'}).catch(()=>{}) 把等待吞掉，等于没等）。
    await page.keyboard.press('Escape')
    await expect(paramDropdown).toBeHidden({ timeout: 5_000 })

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

    // 选择第一个文件（重试一次：并行负载下 /files/ API 可能未返回、选项为 0）
    const fileSelect = page.locator('.active-file-banner:visible .el-select').first()
    await fileSelect.click()
    const dropdown = page.locator('.el-select-dropdown:visible')
    await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
    let options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
    let count = await waitForOptions(options)
    if (count === 0) {
      await page.keyboard.press('Escape')
      await dropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})
      await fileSelect.click()
      await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
      options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
      count = await waitForOptions(options)
    }
    if (count === 0) {
      await page.keyboard.press('Escape')
      test.skip(true, '无可用上传文件')
      return
    }
    // 等待参数列表加载（注册先于触发点击，R2④）
    const histogramResp = page
      .waitForResponse(
        (r) => /\/analysis\/histogram\/?/.test(new URL(r.url()).pathname) && r.status() === 200,
        { timeout: 15_000 },
      )
      .catch(() => null)
    await options.first().click()
    await dropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})
    await histogramResp

    // 「选哪些参数、选几个」从**响应**算，选中走产品自己的「输入关键词 → Enter 全选匹配」。
    // 旧实现是数 DOM 选项再按位置点前 min(count, 20) 行：迁 el-select-v2 后 DOM 只有虚拟窗口那
    // 约 11 行，nth(11..19) 根本不存在，而「按位置取数」本身也不是合法判据（2026-11-13 批1 Task 8）。
    const panel = page.locator('.export-tools')
    const paramSelect = panel.locator('.el-select').filter({ hasText: '点击选择要导出的参数' }).first()
    await paramSelect.click()
    const paramPopper = popperOf(page, EXPORT_PARAM_POPPER)
    await expect(paramPopper).toBeVisible({ timeout: 5_000 })
    const P = await paramKeysFromHistogram(histogramResp)
    if (P.length < 2) {
      await page.keyboard.press('Escape')
      test.skip(true, '该文件可导出参数不足 2 个')
      return
    }
    const bound = pickBoundedKeyword(P, EXPORT_PARAM_SELECT_CAP)
    // 造不出「≥2 且有界」的关键词时**红**而不是 skip：skip 等于把这条判据删掉
    // （param-dropdown-full-list.spec.ts:132 同一条纪律）—— 换夹具或改策略，别放行。
    if (!bound) throw new Error(`参数全集 ${P.length} 项里造不出匹配数 ∈ [2, ${EXPORT_PARAM_SELECT_CAP}] 的关键词`)
    const input = panel.locator('.el-select__input').first()
    await input.fill(bound.kw)
    // footer 的匹配数来自组件的 matches（渲染侧读数），期望值来自响应 ⇒ 异源交叉
    await expect(paramPopper.locator('.match-hint')).toContainText(`匹配 ${bound.count} 项`)
    await input.press('Enter')
    await expect(panel.locator('.step-count')).toContainText(`已选 ${bound.count} / 共 ${P.length} 个`)
    await page.keyboard.press('Escape')
    await expect(paramPopper).toBeHidden({ timeout: 5_000 })

    // 批量导出 Excel 已改走作业（提交 202 → 轮询 → 下载），这里等的是作业端点。
    // 大图渲染仍可能慢，保留 180s。
    const submitPromise = page.waitForResponse(
      (r) => r.url().includes('/jobs/export_batch_charts/'),
      { timeout: 180_000 },
    )
    const pollPromise = page.waitForResponse(
      (r) => /\/jobs\/\d+\/$/.test(new URL(r.url()).pathname),
      { timeout: 180_000 },
    )
    const dlPromise = page.waitForEvent('download', { timeout: 180_000 }).catch(() => null)

    const xlsxBtn = page.getByRole('button', { name: /批量导出 Excel/ })
    await expect(xlsxBtn).toBeEnabled()
    await xlsxBtn.click()

    const [submit, poll, dl] = await Promise.all([submitPromise, pollPromise, dlPromise])
    // 202 = 「拿号就走」；退回 200 说明进程池没建起来、后端走了同步降级，
    // 那正是本片要防的形态，必须红给我们看。
    expect(submit.status(), '提交批量导出作业应 202').toBe(202)
    expect(poll.status(), '轮询作业状态应 200').toBe(200)
    expect(submit.status(), '提交作业不应 5xx').toBeLessThan(500)

    if (dl) {
      const name = dl.suggestedFilename()
      console.log(`[export-tools] downloaded ${name}`)
      expect(name.toLowerCase()).toMatch(/\.xlsx$/)
    } else {
      // 保留既有宽松语义（没捕到下载只记日志）—— 收紧它属于另一件事，
      // 不在本次迁移里顺手改，否则红了分不清是迁移坏了还是本来就没下载。
      console.log(`[export-tools] 未捕获下载，提交状态=${submit.status()}`)
    }

    const offendingErrors = consoleErrors.filter((e) =>
      /exportSigma is not a function|exportBatch is not a function/.test(e),
    )
    expect(offendingErrors, '不应出现 exportSigma/exportBatch 解析错误').toEqual([])
  })

  test('输入关键字按 Enter 可全选匹配参数（过滤 + 清空 + 增量累计）', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '导出工具' }).click()

    // 选择**指定**文件（重试一次：并行负载下 /files/ API 可能未返回、选项为 0）。Task 9B 起不再是
    // `options.first()`：默认那一发只有 41 个参数，「第 301 项够得着」这个用户报的形状在 41 项上
    // 表示不出来（41 < 旧封顶 300，截不截断长成一个样）；ETS88 现测 1,723 个参数，与
    // param-dropdown-full-list 同一份夹具。
    const fileSelect = page.locator('.active-file-banner:visible .el-select').first()
    await fileSelect.click()
    const dropdown = page.locator('.el-select-dropdown:visible')
    await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
    let options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
    let count = await waitForOptions(options)
    if (count === 0) {
      await page.keyboard.press('Escape')
      await dropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})
      await fileSelect.click()
      await dropdown.waitFor({ state: 'visible', timeout: 5_000 }).catch(() => {})
      options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
      count = await waitForOptions(options)
    }
    if (count === 0) {
      await page.keyboard.press('Escape')
      test.skip(true, '无可用上传文件')
      return
    }
    // 等待参数列表加载（注册先于触发点击，R2④）
    const histogramResp = page
      .waitForResponse(
        (r) => /\/analysis\/histogram\/?/.test(new URL(r.url()).pathname) && r.status() === 200,
        { timeout: 15_000 },
      )
      .catch(() => null)
    // 自动等到 /files/options/ 落地为止；夹具真的不在这台库里就是**红**，不改 skip
    const bigFileOption = options.filter({ hasText: SEEDED_FILES.ETS88_FT }).first()
    await expect(bigFileOption, `导出夹具里找不到 ${SEEDED_FILES.ETS88_FT} ⇒ 大列表判据无从谈起`).toBeVisible({
      timeout: 15_000,
    })
    await bigFileOption.click()
    await dropdown.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {})
    await histogramResp

    const panel = page.locator('.export-tools')

    // 打开参数下拉：点选第 2 个（合并语义基线：已选 1，下拉保持打开）
    const paramSelect = panel.locator('.el-select').filter({ hasText: '点击选择要导出的参数' }).first()
    await paramSelect.click()
    const paramPopper = popperOf(page, EXPORT_PARAM_POPPER)
    await expect(paramPopper).toBeVisible({ timeout: 5_000 })
    const paramOptions = paramPopper.locator('.el-select-dropdown__item:not(.is-disabled)')
    await waitForOptions(paramOptions)

    // 参数全集取**响应的 results 键**（取法与「为什么不用 listParams」见 helpers/params.ts），不数 DOM：
    // 本控件迁 el-select-v2（2026-11-13 批1 Task 8）**之前**，DOM 里是被 DROPDOWN_RENDER_CAP=300
    // 截断的渲染项，数出来已经小于全集；迁完截断没了，但 DOM 只剩虚拟窗口那约 11 行 ——
    // 两头都不等于全集，被测契约始终是「过滤/计数/Enter 全选作用于完整集合，只有渲染成窗口」。
    const P = await paramKeysFromHistogram(histogramResp)
    if (P.length < 2) {
      await page.keyboard.press('Escape')
      test.skip(true, '该文件参数不足 2 个')
      return
    }
    // 反截断正向判据（Task 9B，与 param-dropdown-full-list / file-correlation 同构）：**未输入关键词**
    // 时量窗口行数 —— 这一屏的候选是整份 1,723 项全集 ⇒ 虚拟化没生效挂 1,723 行、旧封顶 300 放回来
    // 挂 300 行，两种都红（41 项的默认夹具上「300」压根表示不出来，这就是换夹具的意义）。
    // 界与推导在 helpers/selectV2.ts；红了换更大的夹具，别改成 skip。
    expect(P.length, `导出夹具的参数数应当 > 界 ${MAX_WINDOW_ROWS}，现测 ${P.length} 项`).toBeGreaterThan(MAX_WINDOW_ROWS)
    await expectWindowRows(windowItems(page, EXPORT_PARAM_POPPER), P.length, '导出参数下拉（未输入关键词）')
    // 点的仍是 DOM 第 2 行，但身份从这一行自己的文本取：按位置认作 P[1] 的话，虚拟窗口重排/点错行时期望值跟着一起错
    const row2 = paramOptions.nth(1)
    const picked = (await row2.textContent())?.trim() ?? ''
    expect(picked, '第 2 行取到空文本 ⇒ 用例接线坏了，别让空串静默进 Set 少算一项').not.toBe('')
    await row2.click()
    await expect(panel.locator('.step-count')).toContainText('已选 1 /')

    // 关键字 = 第一个参数名的前 6 字符（保证 ≥1 匹配），N 从页面参数列表自算
    const kw = P[0].slice(0, 6)
    const matchesArr = P.filter((p) => p.toLowerCase().includes(kw.toLowerCase()))
    const N = matchesArr.length
    expect(N, '关键字应至少匹配 1 个参数').toBeGreaterThanOrEqual(1)

    // filterable 输入框（v2 把 aria-label 绑在 input 本身，见 `select-v2/src/select.mjs:209`）：
    // 填入关键字 → 下拉过滤 + footer 提示匹配数。**逐字**（Task 9B）而 N 从响应侧的 P 算（与产品
    // 异源）⇒ 挡「footer 数的是窗口那 11 行」「文案改回『共 N 项』」「加回『仅显示前 N』」三种回退。
    const input = panel.locator('.el-select__input').first()
    await input.fill(kw)
    await expect(paramPopper.locator('.match-hint')).toHaveText(`匹配 ${N} 项，按 Enter 全选`)

    // Enter 全选：已选 = {picked} ∪ 匹配集（picked 可能在匹配集中，用 Set 算实际值）
    const expected = new Set([picked, ...matchesArr]).size
    await input.press('Enter')
    await expect(panel.locator('.step-count')).toContainText(`已选 ${expected} / 共 ${P.length} 个`)

    // 全选后输入框自动清空 → 可继续输入其它关键字（增量累计）
    await expect(input).toHaveValue('')
    const kw2 = P[0].slice(0, 5)
    const matchesArr2 = P.filter((p) => p.toLowerCase().includes(kw2.toLowerCase()))
    const expected2 = new Set([picked, ...matchesArr, ...matchesArr2]).size
    await input.fill(kw2)
    await input.press('Enter')
    await expect(panel.locator('.step-count')).toContainText(`已选 ${expected2} / 共 ${P.length} 个`)
  })
})
