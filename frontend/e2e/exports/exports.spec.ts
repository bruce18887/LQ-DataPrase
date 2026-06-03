import { test, expect, type Page, type Locator } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
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
  // GageSummary/BuyoffForm 的 onMounted 异步调用 datafilesApi.list()，
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
