import { test, expect, type Page } from '@playwright/test'
import { SEEDED_FILES } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { captureDownload } from '../helpers/download'
import { elSelectByPlaceholder } from '../helpers/elplus'

/**
 * 进入查看数据 tab：文件列表服务端搜索定位目标文件 → 点「查看」。
 * 服务端 search 不受分页/下拉时序影响，比 banner 下拉更稳。
 */
async function openViewTab(page: Page, filename: string) {
  await gotoApp(page, '/data')
  // 文件列表搜索（300ms debounce 后发请求）
  const searchInput = page.locator('input[placeholder="按文件名/程序名/标签搜索"]')
  await searchInput.fill(filename.slice(0, 15))
  // 注意：长文件名在行内 DOM 中被中间截断（如 BPD93204_FT1_ET…50_12252024.csv），
  // hasText 必须用前缀匹配而非完整文件名
  const row = page.locator('.el-table .el-table__row').filter({ hasText: filename.slice(0, 12) }).first()
  await expect(row).toBeVisible({ timeout: 30_000 })
  await row.locator('button').filter({ hasText: '查看' }).click()
  await expect(page.locator('.tab-btn.active')).toContainText('查看数据')
  await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })
}

/** 查看数据 tab（当前可见 section）的顶层容器 */
function viewScope(page: Page) {
  return page.locator('.content-section:visible').first()
}

/**
 * 从 /browse/ API 拿全量行，定位测试所需的确定性行：
 * - failIdx/failCols/binValue：首个 bin != 1 的行及其 __fail_cells__
 * - passIdx：首个 bin == 1 的行
 * - farIdx/farCol：首个「含非 bin fail 列且该列在 headers 中 index >= 50」的行（346 列文件必在屏幕外）
 * - binOnlyIdx：首个 __fail_cells__ 恰为 [bin] 的行（仅 bin fail，无测试列越限）
 */
async function fetchBinFailInfo(page: Page, filename: string) {
  return page.evaluate(async (filename) => {
    const token = localStorage.getItem('access_token')
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
    const files = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, { headers }).then((r) => r.json())
    const file = ((files.results ?? files) as any[]).find((f: any) => f.filename === filename)
    const d = await fetch(`/api/v1/browse/?datafile_id=${file.id}&page_size=99999`, { headers }).then((r) => r.json())
    // 传输格式压缩：headers + data（行值数组）+ fail_cells 并行数组 → zip 成行对象
    const colHeaders = (d.headers ?? []) as string[]
    const data = (d.data ?? []) as unknown[][]
    const failCells = (d.fail_cells ?? []) as string[][]
    const rows: Record<string, any>[] = []
    for (let i = 0; i < data.length; i++) {
      const o: Record<string, any> = { __fail_cells__: failCells[i] ?? [] }
      for (let j = 0; j < colHeaders.length; j++) o[colHeaders[j]] = data[i][j]
      rows.push(o)
    }
    const bin = d.bin_column as string
    // __fail_cells__ 已是原生数组（不再 JSON 字符串）
    const parseFail = (r: Record<string, any>): string[] => r.__fail_cells__ ?? []
    const info = {
      bin,
      failIdx: -1,
      binValue: '',
      failCols: [] as string[],
      passIdx: -1,
      farIdx: -1,
      farCol: '',
      binOnlyIdx: -1,
    }
    for (let i = 0; i < rows.length; i++) {
      const v = rows[i][bin]
      const isFail = v !== null && v !== undefined && v !== '' && Number(v) !== 1
      if (isFail) {
        const fc = parseFail(rows[i])
        if (info.failIdx === -1) {
          info.failIdx = i
          info.binValue = String(v)
          info.failCols = fc
        }
        if (info.farIdx === -1 && fc.length > 1) {
          const far = fc.find((c) => c !== bin && colHeaders.indexOf(c) >= 50)
          if (far) {
            info.farIdx = i
            info.farCol = far
          }
        }
        if (info.binOnlyIdx === -1 && fc.length === 1 && fc[0] === bin) {
          info.binOnlyIdx = i
        }
      } else if (info.passIdx === -1 && v !== null && v !== undefined && v !== '' && Number(v) === 1) {
        info.passIdx = i
      }
    }
    return info
  }, filename)
}

/**
 * 从 /browse/ API 取「显示测试列」测试素材：左起前两个非系统测试列
 * （渲染窗口内必可见）+ bin 系统列。系统列判定与 DataBrowserAgGrid.vue 的
 * isSystemCol 保持一致（token 前缀匹配，不做单字母子串扫描）。
 */
async function fetchFirstTestCols(page: Page, filename: string) {
  return page.evaluate(async (filename) => {
    const token = localStorage.getItem('access_token')
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
    const files = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, { headers }).then((r) => r.json())
    const file = ((files.results ?? files) as any[]).find((f: any) => f.filename === filename)
    const d = await fetch(`/api/v1/browse/?datafile_id=${file.id}&page_size=1`, { headers }).then((r) => r.json())
    const PREFIXES = ['soft_bin', 'sw_bin', 'hard_bin', 'site', 'serial', 'wafer', 'device']
    const EXACT = ['x', 'y', 'x_coord', 'y_coord']
    const isSystem = (c: string) => {
      const lower = c.split(' ')[0].split('(')[0].trim().toLowerCase()
      return EXACT.includes(lower) || PREFIXES.some((p) => lower === p || lower.startsWith(`${p}_`) || lower.startsWith(`${p} `))
    }
    const testCols = (d.headers ?? []).filter((c: string) => !isSystem(c))
    return { testCol: testCols[0] ?? '', absentCol: testCols[1] ?? '', bin: d.bin_column as string }
  }, filename)
}

/** 目标行若未渲染（rowBuffer=10 外的行），滚动垂直视口使其渲染（v33+ 垂直滚动在 ag-body-vertical-scroll-viewport） */
async function ensureRowRendered(page: Page, rowIndex: number) {
  const row = page.locator(`.ag-pinned-left-cols-container .ag-row[row-index="${rowIndex}"]`)
  if ((await row.count()) === 0) {
    await page
      .locator('.ag-body-vertical-scroll-viewport')
      .evaluate((el, idx) => { (el as HTMLElement).scrollTop = idx * 30 }, rowIndex)
  }
  await expect(row).toBeVisible({ timeout: 10_000 })
  return row
}

test.describe('数据管理 → 查看数据页优化', { tag: ['@data'] }, () => {
  test('@p0 未选文件：空态引导 + 去文件列表按钮', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '查看数据' }).click()
    await expect(page.locator('.tab-btn.active')).toContainText('查看数据')

    const empty = viewScope(page).locator('.el-empty')
    await expect(empty).toBeVisible({ timeout: 10_000 })
    await expect(empty).toContainText('请先在上方选择文件')

    // 引导按钮切回文件列表 tab
    await empty.locator('button').filter({ hasText: '去文件列表选择' }).click()
    await expect(page.locator('.tab-btn.active')).toContainText('文件列表')
  })

  test('@p1 固定列：下拉选择列后固定到左侧', async ({ page }) => {
    // gage 文件 346 列足够验证列固定，且远小于 CTA8280F（10000 行）降低 dev 环境压力
    await openViewTab(page, SEEDED_FILES.GAGE_S1)
    await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })

    // 当前默认固定列（后端 bin_column）
    const pinnedBefore = (await page.locator('.ag-pinned-left-header').first().textContent()) ?? ''

    // 打开固定列下拉：选中后占位文本消失，用 aria-label 定位输入框所在 select，点击 wrapper 打开
    const pinSelect = viewScope(page).locator('.el-select:has(input[aria-label="固定列"])').first()
    await pinSelect.locator('.el-select__wrapper').click()
    // 等待下拉动画完成、选项渲染
    const options = page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
    await expect(options.first()).toBeVisible({ timeout: 5_000 })
    const count = await options.count()
    expect(count).toBeGreaterThan(1)

    let target = ''
    for (let i = 0; i < count; i++) {
      const t = (await options.nth(i).textContent())?.trim() ?? ''
      if (t && !pinnedBefore.includes(t)) {
        target = t
        break
      }
    }
    expect(target, '应存在非当前固定列的选项').not.toBe('')
    await options.filter({ hasText: target }).first().click()

    await expect(page.locator('.ag-pinned-left-header')).toContainText(target, { timeout: 10_000 })
  })

  test('@p1 Pass/Fail 筛选：未选文件时预选，选文件后生效', async ({ page }) => {
    await gotoApp(page, '/data')

    // 先用 API 拿全量与 Pass 过滤后的 total 作对比基准（search 精确定位文件，避免分页干扰）
    const totals = await page.evaluate(async (filename) => {
      const token = localStorage.getItem('access_token')
      const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
      const files = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, { headers }).then((r) => r.json())
      const file = ((files.results ?? files) as any[]).find((f: any) => f.filename === filename)
      const base = `/api/v1/browse/?datafile_id=${file.id}&page_size=1`
      const all = await fetch(base, { headers }).then((r) => r.json())
      const pass = await fetch(`${base}&pass_filter=Pass`, { headers }).then((r) => r.json())
      return { all: all.total, pass: pass.total }
    }, SEEDED_FILES.CTA8280F_FT)
    expect(totals.all).toBeGreaterThan(totals.pass)

    await page.locator('.tab-btn').filter({ hasText: '查看数据' }).click()

    // 未选文件时先选 Pass 筛选
    const pfSelect = elSelectByPlaceholder(viewScope(page), 'Pass/Fail筛选').first()
    await pfSelect.locator('.el-select__wrapper').click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: 'Pass' }).first().click()

    // 再选文件 → 筛选应生效（请求带 pass_filter）。
    // 注：banner 下拉在此流程（view tab 预选筛选后）不可靠（历史 A/B 预存在失败），
    // 改用文件列表服务端搜索 + 「查看」按钮的可靠路径（passfail 状态跨 tab 保留）。
    await page.locator('.tab-btn').filter({ hasText: '文件列表' }).click()
    const searchInput = page.locator('input[placeholder="按文件名/程序名/标签搜索"]')
    await searchInput.fill('DA35_BPC50338')
    const fileRow = page.locator('.el-table .el-table__row').filter({ hasText: 'DA35_BPC5033' }).first()
    await fileRow.waitFor({ state: 'visible', timeout: 30_000 })
    const browseResp = page.waitForResponse(
      (r) => r.url().includes('/browse/') && r.url().includes('pass_filter=Pass'),
      { timeout: 15_000 },
    )
    await fileRow.locator('button').filter({ hasText: '查看' }).click()
    expect((await browseResp).status()).toBe(200)

    // 行数与 Pass 总数一致
    await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })
    await expect(viewScope(page).locator('p').filter({ hasText: '条数据' })).toContainText(
      String(totals.pass),
      { timeout: 15_000 },
    )
  })

  test('@p2 导出：文件名取自源文件（Content-Disposition 优先）', async ({ page }) => {
    // 用 gage 小文件（100 行）验证导出：ETS88（1728 列）的 12MB Excel 经 Vite 代理转发会压垮 dev server
    await openViewTab(page, SEEDED_FILES.GAGE_S1)
    await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })

    const base = SEEDED_FILES.GAGE_S1.replace(/\.csv$/i, '')

    const xlsxResp = page.waitForResponse((r) => r.url().includes('/export/to_excel/'), {
      timeout: 180_000,
    })
    const xlsx = await captureDownload(
      page,
      async () => {
        await viewScope(page).locator('button').filter({ hasText: '导出 Excel' }).click()
      },
      'view-data',
      180_000,
    )
    expect((await xlsxResp).status(), 'to_excel 应 200').toBe(200)
    expect(xlsx.suggestedName).toBe(`${base}_analysis.xlsx`)

    const csvResp = page.waitForResponse((r) => r.url().includes('/export/to_csv/'), {
      timeout: 60_000,
    })
    const csv = await captureDownload(
      page,
      async () => {
        await viewScope(page).locator('button').filter({ hasText: '导出 CSV' }).click()
      },
      'view-data',
    )
    expect((await csvResp).status(), 'to_csv 应 200').toBe(200)
    expect(csv.suggestedName).toBe(`${base}_data.csv`)
  })

  test('@p1 Site 筛选：服务端过滤表格 + 「Site X 过滤后」文案 + 恢复', async ({ page }) => {
    // CTA8280F 含多 Site 值（188 列 × 10000 行，JSON 规模小于 ETS88 的 1728 列）
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)

    // 全量行数（UI 文案，来自首块响应的服务端 total）
    const totalText = (await viewScope(page).locator('p').filter({ hasText: '共 ' }).textContent()) ?? ''
    const allTotal = Number(totalText.match(/共\s*(\d+)/)?.[1] ?? 0)
    expect(allTotal).toBeGreaterThan(0)

    // 打开 Site 下拉看选项（来自 page==1 响应的 site_options；需 >1 个 site 才有过滤意义）
    const siteSelect = viewScope(page).locator('.el-select:has(input[aria-label="站点筛选"])').first()
    await siteSelect.locator('.el-select__wrapper').click()
    const siteOptions = page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
    await expect(siteOptions.first()).toBeVisible({ timeout: 5_000 })
    const siteCount = await siteOptions.count()
    if (siteCount < 2) {
      test.skip(true, '该文件仅有单个 site，无过滤场景')
      return
    }
    // 下拉项文本是「Site 2」，值才是 "2"（R4：断言用值不用 label）
    const targetSite = ((await siteOptions.nth(1).textContent())?.trim() ?? '').replace(/^Site\s*/i, '')
    // 服务端过滤：点选前注册 waitForResponse（300ms 防抖由 predicate 等待覆盖）
    const siteResp = page.waitForResponse(
      (r) => r.url().includes('/browse/') && r.url().includes(`site_filter=${encodeURIComponent(targetSite)}`),
      { timeout: 15_000 },
    )
    await siteOptions.nth(1).click()
    expect((await siteResp).status()).toBe(200)

    // 行数下降 + 「Site X 过滤后」文案（fail 计数来自服务端筛选集语义）
    await expect(
      viewScope(page).locator('p').filter({ hasText: 'Site' }).filter({ hasText: '过滤后' }),
    ).toBeVisible({ timeout: 10_000 })
    const afterText = (await viewScope(page).locator('p').filter({ hasText: '共 ' }).textContent()) ?? ''
    const afterTotal = Number(afterText.match(/共\s*(\d+)/)?.[1] ?? allTotal)
    expect(afterTotal, 'Site 过滤后行数应减少').toBeLessThan(allTotal)

    // 恢复全部 Site → 行数恢复全量（新请求不带 site_filter）
    const siteSelect2 = viewScope(page).locator('.el-select:has(input[aria-label="站点筛选"])').first()
    await siteSelect2.locator('.el-select__wrapper').click()
    const resetResp = page.waitForResponse(
      (r) => r.url().includes('/browse/') && r.url().includes('page=1') && !r.url().includes('site_filter='),
      { timeout: 15_000 },
    )
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').first().click()
    expect((await resetResp).status()).toBe(200)
    await expect(viewScope(page).locator('p').filter({ hasText: '共 ' })).toContainText(String(allTotal), {
      timeout: 10_000,
    })
  })

  test('@p1 服务端排序：点列头触发 sort_model 请求且顺序正确', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)

    // Kelvin_VIN 是测试列，在 188 列中超出视口（表头虚拟化）→ 渐进横向滚动表头
    // 直到目标列渲染（位置依赖列序，不能假设固定像素）
    await page.locator('.ag-header-viewport').evaluate(async (el) => {
      while (!el.querySelector('[col-id="Kelvin_VIN"]') && el.scrollLeft < el.scrollWidth) {
        el.scrollLeft += 400
        await new Promise((r) => setTimeout(r, 30))
      }
    })
    const header = page.locator('.ag-header-cell[col-id="Kelvin_VIN"]')
    await expect(header).toBeVisible({ timeout: 10_000 })

    // 点列头 → IRM sortChanged 自动重发（page=1 带 sort_model）
    const sortResp = page.waitForResponse(
      (r) => r.url().includes('/browse/') && r.url().includes('sort_model=') && r.url().includes('page=1'),
      { timeout: 15_000 },
    )
    await header.click()
    expect((await sortResp).status()).toBe(200)

    // 与 API 直连对照：asc 排序首块第一个 Kelvin_VIN 值 == grid 首行该列值
    const expected = await page.evaluate(async (filename) => {
      const token = localStorage.getItem('access_token')
      const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
      const files = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, { headers }).then((r) => r.json())
      const file = ((files.results ?? files) as any[]).find((f: any) => f.filename === filename)
      const sort = encodeURIComponent('[{"colId":"Kelvin_VIN","sort":"asc"}]')
      const d = await fetch(`/api/v1/browse/?datafile_id=${file.id}&page_size=1&sort_model=${sort}`, { headers }).then((r) => r.json())
      const vinIdx = d.headers.indexOf('Kelvin_VIN')
      return d.data[0][vinIdx]
    }, SEEDED_FILES.CTA8280F_FT)
    // 排序重载后横向滚动可能被重置 → 渐进滚动 body 直到 Kelvin_VIN 单元格渲染再断言
    await page.locator('.ag-center-cols-viewport').evaluate(async (el) => {
      const target = `.ag-row[row-index="0"] [col-id="Kelvin_VIN"]`
      while (!el.querySelector(target) && el.scrollLeft < el.scrollWidth) {
        el.scrollLeft += 400
        await new Promise((r) => setTimeout(r, 30))
      }
    })
    await expect(
      page.locator('.ag-center-cols-container .ag-row[row-index="0"] [col-id="Kelvin_VIN"]'),
    ).toContainText(String(expected), { timeout: 10_000 })
  })

  test('@p1 滚动加载分块：滚动到 8000 行触发第 81 块请求并渲染', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)
    await expect(page.locator('.ag-row').first()).toBeVisible({ timeout: 30_000 })

    // 垂直滚动到 8000 行 → IRM 请求 page=81（startRow 8000/100 + 1）
    const blockResp = page.waitForResponse(
      (r) => r.url().includes('/browse/') && r.url().includes('page=81'),
      { timeout: 15_000 },
    )
    await page.locator('.ag-body-vertical-scroll-viewport').evaluate((el) => { el.scrollTop = 8000 * 30 })
    expect((await blockResp).status()).toBe(200)
    await expect(
      page.locator('.ag-center-cols-container .ag-row[row-index="8000"]'),
    ).toBeVisible({ timeout: 15_000 })
  })

  test('@p1 Fail 筛选：fail_row_count 与 total 一致（筛选集语义）', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)
    await expect(page.locator('.ag-row').first()).toBeVisible({ timeout: 30_000 })

    // 切 Fail → 服务端过滤，筛选集内全为 fail 行 → 「Fail: N 行」==「共 N 条」
    const pfSelect = elSelectByPlaceholder(viewScope(page), 'Pass/Fail筛选').first()
    await pfSelect.locator('.el-select__wrapper').click()
    const failResp = page.waitForResponse(
      (r) => r.url().includes('/browse/') && r.url().includes('pass_filter=Fail'),
      { timeout: 15_000 },
    )
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: 'Fail' }).first().click()
    expect((await failResp).status()).toBe(200)

    const summary = viewScope(page).locator('p').filter({ hasText: '共 ' })
    await expect(summary).toContainText('Fail:', { timeout: 10_000 })
    const text = (await summary.textContent()) ?? ''
    const total = Number(text.match(/共\s*(\d+)/)?.[1] ?? 0)
    const fail = Number(text.match(/Fail:\s*(\d+)/)?.[1] ?? 0)
    expect(total).toBeGreaterThan(0)
    expect(fail, 'FAIL 筛选集内 fail 行数 == total').toBe(total)
  })

  test('@p1 表头列筛选：数值列过滤器服务端生效', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)
    await expect(page.locator('.ag-row').first()).toBeVisible({ timeout: 30_000 })

    // 先经 API 取 Kelvin_VIN 最小值作为筛选值（确定性：equals 该值必有匹配行）
    const minVal = await page.evaluate(async (filename) => {
      const token = localStorage.getItem('access_token')
      const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
      const files = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, { headers }).then((r) => r.json())
      const file = ((files.results ?? files) as any[]).find((f: any) => f.filename === filename)
      const sort = encodeURIComponent('[{"colId":"Kelvin_VIN","sort":"asc"}]')
      const d = await fetch(`/api/v1/browse/?datafile_id=${file.id}&page_size=1&sort_model=${sort}`, { headers }).then((r) => r.json())
      const vinIdx = d.headers.indexOf('Kelvin_VIN')
      return { min: d.data[0][vinIdx], fileId: file.id }
    }, SEEDED_FILES.CTA8280F_FT)

    // 同 filterModel 的 API total 对照基准
    const apiTotal = await page.evaluate(async (args) => {
      const token = localStorage.getItem('access_token')
      const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
      const fm = encodeURIComponent(JSON.stringify({ Kelvin_VIN: { filterType: 'number', type: 'equals', filter: args.min } }))
      const d = await fetch(`/api/v1/browse/?datafile_id=${args.fileId}&page_size=1&filter_model=${fm}`, { headers }).then((r) => r.json())
      return d.total
    }, { min: minVal.min, fileId: minVal.fileId })
    expect(apiTotal).toBeGreaterThan(0)

    // 渐进滚动表头到 Kelvin_VIN → hover 打开列菜单（默认即 filter 面板）
    await page.locator('.ag-header-viewport').evaluate(async (el) => {
      while (!el.querySelector('[col-id="Kelvin_VIN"]') && el.scrollLeft < el.scrollWidth) {
        el.scrollLeft += 400
        await new Promise((r) => setTimeout(r, 30))
      }
    })
    const header = page.locator('.ag-header-cell[col-id="Kelvin_VIN"]')
    await expect(header).toBeVisible({ timeout: 10_000 })
    await header.hover()
    await header.locator('.ag-header-icon, .ag-header-cell-menu-button').first().click()

    // filter 面板：默认算子 equals → 填值 + Apply（服务端场景 apply/reset 按钮）。
    // 注意 Apply 面板是 .ag-filter 的兄弟节点（.ag-menu 内），用 role 定位最稳
    const menu = page.locator('.ag-menu')
    await expect(menu).toBeVisible({ timeout: 10_000 })
    await menu.locator('input.ag-number-field-input').first().fill(String(minVal.min))
    const filterResp = page.waitForResponse(
      (r) => r.url().includes('/browse/') && r.url().includes('filter_model=') && r.url().includes('page=1'),
      { timeout: 15_000 },
    )
    await menu.getByRole('button', { name: 'Apply' }).click()
    expect((await filterResp).status()).toBe(200)

    // 行数收缩到 API 基准（服务端筛选集 total）
    await expect(viewScope(page).locator('p').filter({ hasText: '共 ' })).toContainText(String(apiTotal), {
      timeout: 10_000,
    })
  })

  test('@p1 显示测试列：选中后仅显示该测试列、系统列始终显示，清空恢复全部', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.GAGE_S1)

    // 左起前两个非系统测试列；bin 列（系统列）恒显示
    const { testCol, absentCol, bin } = await fetchFirstTestCols(page, SEEDED_FILES.GAGE_S1)
    expect(testCol).toBeTruthy()
    expect(absentCol).toBeTruthy()
    expect(bin).toBeTruthy()

    // 打开「显示测试列」多选下拉，勾选 testCol
    const selector = viewScope(page).locator('.test-col-selector:has(input[aria-label="显示测试列"])').first()
    await selector.locator('.el-select__wrapper').click()
    const options = page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
    await expect(options.first()).toBeVisible({ timeout: 5_000 })
    await page.waitForTimeout(300)
    await options.filter({ hasText: testCol }).first().click()
    await page.keyboard.press('Escape')
    await page.waitForTimeout(300)

    // 选中列可见；未选中的另一个测试列被过滤（恒不渲染）；系统列（bin）仍显示
    await expect(page.locator('.ag-header-cell').filter({ hasText: testCol }).first()).toBeVisible({
      timeout: 10_000,
    })
    await expect(page.locator('.ag-header-cell').filter({ hasText: absentCol })).toHaveCount(0)
    await expect(page.locator('.ag-header-cell').filter({ hasText: bin }).first()).toBeVisible({
      timeout: 10_000,
    })

    // 清空 → 恢复全部测试列（列数回到 346，水平滚动容器可滚动）
    await selector.locator('button').filter({ hasText: '清空' }).click()
    await expect
      .poll(
        () => page.evaluate(() => {
          const vp = document.querySelector('.ag-body-horizontal-scroll-viewport')
          return vp ? vp.scrollWidth > vp.clientWidth : false
        }),
        { timeout: 10_000 },
      )
      .toBe(true)
  })

  test('@p2 显示测试列：输入关键词 + Enter 全选匹配项', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.GAGE_S1)

    // 找出现频次最高的 3 字符前缀作为关键词（保证 ≥2 匹配）
    const { kw, matchCount, firstMatch } = await page.evaluate(async (filename) => {
      const token = localStorage.getItem('access_token')
      const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
      const files = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, { headers }).then((r) => r.json())
      const file = ((files.results ?? files) as any[]).find((f: any) => f.filename === filename)
      const d = await fetch(`/api/v1/browse/?datafile_id=${file.id}&page_size=1`, { headers }).then((r) => r.json())
      const PREFIXES = ['soft_bin', 'sw_bin', 'hard_bin', 'site', 'serial', 'wafer', 'device']
      const EXACT = ['x', 'y', 'x_coord', 'y_coord']
      const isSystem = (c: string) => {
        const lower = c.split(' ')[0].split('(')[0].trim().toLowerCase()
        return EXACT.includes(lower) || PREFIXES.some((p) => lower === p || lower.startsWith(`${p}_`) || lower.startsWith(`${p} `))
      }
      const testCols = (d.headers ?? []).filter((c: string) => !isSystem(c))
      const freq = new Map<string, number>()
      for (const c of testCols) {
        const p = c.slice(0, 3).toLowerCase()
        freq.set(p, (freq.get(p) ?? 0) + 1)
      }
      let best = ''
      let bestCount = 0
      for (const [p, n] of freq) {
        if (n > bestCount) { best = p; bestCount = n }
      }
      const matched = best ? testCols.filter((c: string) => c.toLowerCase().includes(best)) : []
      return { kw: best, matchCount: matched.length, firstMatch: matched[0] ?? '' }
    }, SEEDED_FILES.GAGE_S1)
    expect(kw).toBeTruthy()
    expect(matchCount).toBeGreaterThanOrEqual(2)

    const selector = viewScope(page).locator('.test-col-selector:has(input[aria-label="显示测试列"])').first()
    await selector.locator('.el-select__wrapper').click()
    const input = selector.locator('input[aria-label="显示测试列"]')
    // filterable 下拉：fill 不触发过滤，必须逐键输入
    await input.pressSequentially(kw)

    // footer 提示「匹配 N 项，按 Enter 全选」
    const hint = page.locator('.el-select-dropdown:visible .match-hint')
    await expect(hint).toContainText(`匹配 ${matchCount} 项`, { timeout: 5_000 })
    await input.press('Enter')

    // 全选后输入框自动清空；下拉保持打开，匹配列全部呈选中态（is-selected）
    await expect(input).toHaveValue('')
    await expect
      .poll(async () => {
        const opt = page
          .locator('.el-select-dropdown:visible .el-select-dropdown__item')
          .filter({ hasText: new RegExp(`^${firstMatch.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`) })
          .first()
        return (await opt.getAttribute('class'))?.includes('is-selected') ?? false
      }, { timeout: 5_000 })
      .toBe(true)
  })

  test('@p2 显示测试列：切换文件后选中集重置为全部显示', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.GAGE_S1)

    const { testCol, absentCol } = await fetchFirstTestCols(page, SEEDED_FILES.GAGE_S1)
    const selector = viewScope(page).locator('.test-col-selector:has(input[aria-label="显示测试列"])').first()
    await selector.locator('.el-select__wrapper').click()
    const options = page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
    await expect(options.first()).toBeVisible({ timeout: 5_000 })
    await page.waitForTimeout(300)
    await options.filter({ hasText: testCol }).first().click()
    await page.keyboard.press('Escape')
    await expect(page.locator('.ag-header-cell').filter({ hasText: absentCol })).toHaveCount(0)

    // banner 下拉切换文件 → 选中集重置，全部测试列恢复（水平滚动容器可滚动）
    const banner = page.locator('.active-file-banner:visible .banner-file-select').first()
    await banner.click()
    const bannerOptions = page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
    await bannerOptions.filter({ hasText: SEEDED_FILES.GAGE_S2.slice(0, 12) }).first().click()
    await expect
      .poll(
        () => page.evaluate(() => {
          const vp = document.querySelector('.ag-body-horizontal-scroll-viewport')
          return vp ? vp.scrollWidth > vp.clientWidth : false
        }),
        { timeout: 15_000 },
      )
      .toBe(true)
  })

  test('@p2 工具栏控件标签可见', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.GAGE_S1)
    const scope = viewScope(page)
    for (const label of ['显示测试列', 'Pass/Fail', 'Site', '列宽', '固定列']) {
      await expect(scope.locator('.ctl-label').filter({ hasText: label })).toBeVisible()
    }
  })

  test('@p2 列直方图：右键列头打开分布对话框（直方图 + CPK），右键数据区不弹', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.GAGE_S1)

    // 右键一个数值列的表头（如 SW_Bin）→ 直方图对话框打开
    const headerCell = page.locator('.ag-header-cell').filter({ hasText: 'SW_Bin' }).first()
    await expect(headerCell).toBeVisible({ timeout: 10_000 })
    await headerCell.click({ button: 'right' })

    const dialog = page.locator('.el-dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })
    await expect(dialog).toContainText('SW_Bin')
    await expect(dialog.locator('.stats-summary')).toBeVisible({ timeout: 20_000 })
    await expect(dialog).toContainText('CPK', { timeout: 20_000 })
    // 图表容器已渲染（echarts）
    await expect(dialog.locator('.chart-container')).toBeVisible({ timeout: 10_000 })
    // 弹窗尺寸已加大（原 720px 宽 / 380px 高）：默认视口 1280×720 下应为 960×504
    const dialogBox = await dialog.boundingBox()
    expect(dialogBox).not.toBeNull()
    expect(dialogBox!.width).toBeGreaterThan(900)
    const bodyBox = await dialog.locator('.hist-body').boundingBox()
    expect(bodyBox).not.toBeNull()
    expect(bodyBox!.height).toBeGreaterThanOrEqual(480)

    // 关闭
    await dialog.locator('.el-dialog__headerbtn').click()
    await expect(dialog).not.toBeVisible({ timeout: 5_000 })

    // 右键数据区单元格不弹窗（body 右键放行，保留浏览器菜单）
    const cell = page.locator('.ag-center-cols-container .ag-row').first().locator('.ag-cell').first()
    await expect(cell).toBeVisible({ timeout: 10_000 })
    await cell.click({ button: 'right' })
    await page.waitForTimeout(1_000)
    await expect(page.locator('.el-dialog')).not.toBeVisible({ timeout: 3_000 })
  })

  test('@p3 质量概览条：Total/Pass/Fail/Yield 与 /summary/ API 一致', async ({ page }) => {
    // GAGE_S1（100 行）：小文件避免 CTA8280F（10000 行）加载压力；API 对比必须用同一文件
    await openViewTab(page, SEEDED_FILES.GAGE_S1)

    const qualityBar = viewScope(page).locator('.quality-bar')
    await expect(qualityBar).toBeVisible({ timeout: 30_000 })

    // 从 API 拿 metrics 作对比基准
    const m = await page.evaluate(async (filename) => {
      const token = localStorage.getItem('access_token')
      const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
      const files = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, { headers }).then((r) => r.json())
      const file = ((files.results ?? files) as any[]).find((f: any) => f.filename === filename)
      const d = await fetch(`/api/v1/summary/?file_id=${file.id}`, { headers }).then((r) => r.json())
      return {
        total: d.metrics.total_rows,
        pass: d.metrics.pass_count,
        fail: d.metrics.fail_count,
        yield: d.metrics.yield_pct,
      }
    }, SEEDED_FILES.GAGE_S1)

    await expect(qualityBar.locator('.chip').filter({ hasText: 'Total' })).toContainText(
      m.total.toLocaleString(),
      { timeout: 10_000 },
    )
    await expect(qualityBar.locator('.chip').filter({ hasText: 'Pass' })).toContainText(
      m.pass.toLocaleString(),
    )
    await expect(qualityBar.locator('.chip').filter({ hasText: 'Fail' })).toContainText(
      m.fail.toLocaleString(),
    )
    await expect(qualityBar.locator('.chip').filter({ hasText: 'Yield' })).toContainText(`${m.yield}%`)
    // 质量条不含冗余的「CPK 低」参数 tag（alerts 里的质量警报保留）
    await expect(qualityBar).not.toContainText('CPK 低')
  })

  test('@p2 右键 Fail Bin 单元格：弹出定位菜单 + 各关闭路径', async ({ page }) => {
    // CTA8280F 含 1289 个 fail 行（GAGE 文件全 pass，无场景）
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)
    const info = await fetchBinFailInfo(page, SEEDED_FILES.CTA8280F_FT)
    if (info.failIdx === -1) test.skip(true, '种子文件无 fail 行')

    const failCell = page
      .locator(`.ag-pinned-left-cols-container .ag-row[row-index="${info.failIdx}"] .ag-cell`)
      .first()
    await expect(failCell).toBeVisible({ timeout: 30_000 })
    // fail 单元格红色高亮（light 主题 #dc2626）
    await expect(failCell).toHaveCSS('background-color', 'rgb(220, 38, 38)')

    // 右键 → 菜单可见，内容含菜单项 / 行号 / bin 值
    await failCell.click({ button: 'right' })
    const menu = page.locator('.bin-cell-menu')
    await expect(menu).toBeVisible({ timeout: 5_000 })
    await expect(menu).toContainText('定位到 Fail 单元格')
    await expect(menu).toContainText(`第 ${info.failIdx + 1} 行`)
    await expect(menu).toContainText(String(info.binValue))

    // 关闭路径 1：Escape
    await page.keyboard.press('Escape')
    await expect(menu).not.toBeVisible({ timeout: 3_000 })

    // 关闭路径 2：点击表格其他单元格
    await failCell.click({ button: 'right' })
    await expect(menu).toBeVisible({ timeout: 5_000 })
    await page.locator('.ag-center-cols-container .ag-row').first().locator('.ag-cell').first().click()
    await expect(menu).not.toBeVisible({ timeout: 3_000 })

    // 关闭路径 3：菜单开着滚表格（wheel）
    await failCell.click({ button: 'right' })
    await expect(menu).toBeVisible({ timeout: 5_000 })
    await page.mouse.wheel(0, 300)
    await expect(menu).not.toBeVisible({ timeout: 3_000 })

    // 关闭路径 4：再次右键 pass 单元格（且不弹新菜单）
    await failCell.click({ button: 'right' })
    await expect(menu).toBeVisible({ timeout: 5_000 })
    const passRow = await ensureRowRendered(page, info.passIdx)
    await passRow.locator('.ag-cell').first().click({ button: 'right' })
    await expect(menu).not.toBeVisible({ timeout: 3_000 })
    await page.waitForTimeout(500)
    await expect(page.locator('.bin-cell-menu')).toHaveCount(0)
    await expect(page.locator('.el-dialog')).not.toBeVisible()
  })

  test('@p2 右键 Pass Bin 单元格不弹菜单（放行浏览器菜单）', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)
    const info = await fetchBinFailInfo(page, SEEDED_FILES.CTA8280F_FT)

    const passRow = await ensureRowRendered(page, info.passIdx)
    await passRow.locator('.ag-cell').first().click({ button: 'right' })
    await page.waitForTimeout(600)
    await expect(page.locator('.bin-cell-menu')).toHaveCount(0)
    await expect(page.locator('.el-dialog')).not.toBeVisible()

    // 合成事件精确验证：未 preventDefault（浏览器复制菜单放行）
    const prevented = await passRow
      .locator('.ag-cell')
      .first()
      .evaluate((el) => {
        const ev = new MouseEvent('contextmenu', {
          bubbles: true,
          cancelable: true,
          clientX: 10,
          clientY: 10,
        })
        el.dispatchEvent(ev)
        return ev.defaultPrevented
      })
    expect(prevented).toBe(false)
  })

  test('@p2 菜单「定位到 Fail 单元格」：横向滚动到 fail 列 + flash', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)
    const info = await fetchBinFailInfo(page, SEEDED_FILES.CTA8280F_FT)
    if (info.farIdx === -1) test.skip(true, '无远列 fail 行')

    const farRow = await ensureRowRendered(page, info.farIdx)

    // 前置：farCol 在屏幕外（列虚拟化 → 无此 header 元素）
    await expect(page.locator(`.ag-header-cell[col-id="${info.farCol}"]`)).not.toBeVisible()

    const hScroll = page.locator('.ag-body-horizontal-scroll-viewport')
    const before = await hScroll.evaluate((el) => el.scrollLeft)

    // 右键该行 pinned bin 单元格 → 点菜单项
    await farRow.locator('.ag-cell').first().click({ button: 'right' })
    const menu = page.locator('.bin-cell-menu')
    await expect(menu).toBeVisible({ timeout: 5_000 })
    await menu.locator('.bin-cell-menu__item').click()
    await expect(menu).not.toBeVisible({ timeout: 3_000 })

    // 横向滚动发生（ensureColumnVisible）
    await expect
      .poll(async () => hScroll.evaluate((el) => el.scrollLeft), { timeout: 5_000 })
      .toBeGreaterThan(before)

    // farCol 列头与 fail 单元格已滚入视图
    await expect(page.locator(`.ag-header-cell[col-id="${info.farCol}"]`)).toBeVisible({
      timeout: 10_000,
    })
    const failCell = page.locator(
      `.ag-center-cols-container .ag-row[row-index="${info.farIdx}"] .ag-cell[col-id="${info.farCol}"]`,
    )
    await expect(failCell).toBeVisible({ timeout: 10_000 })

    // flash 高亮（~1s 瞬态类，poll 抓）
    await expect
      .poll(async () => (await failCell.getAttribute('class')) ?? '', { timeout: 3_000 })
      .toContain('ag-cell-data-changed')
  })

  test('@p2 仅 Bin fail 行：定位只 flash 不横向滚动', async ({ page }) => {
    // CTA8290D 含仅 bin fail 行（无测试列越限）；CTA8280F 的 fail 行均带越限测试列
    await openViewTab(page, SEEDED_FILES.CTA8290D_FT)
    const info = await fetchBinFailInfo(page, SEEDED_FILES.CTA8290D_FT)
    if (info.binOnlyIdx === -1) test.skip(true, '无仅 bin fail 行')

    const binRow = await ensureRowRendered(page, info.binOnlyIdx)
    const hScroll = page.locator('.ag-body-horizontal-scroll-viewport')
    const before = await hScroll.evaluate((el) => el.scrollLeft)

    const binCell = binRow.locator('.ag-cell').first()
    await binCell.click({ button: 'right' })
    const menu = page.locator('.bin-cell-menu')
    await expect(menu).toBeVisible({ timeout: 5_000 })
    await menu.locator('.bin-cell-menu__item').click()
    await expect(menu).not.toBeVisible({ timeout: 3_000 })

    // pinned bin 单元格 flash（目标列即 bin 列本身，无需横向滚动）
    await expect
      .poll(async () => (await binCell.getAttribute('class')) ?? '', { timeout: 3_000 })
      .toContain('ag-cell-data-changed')
    expect(await hScroll.evaluate((el) => el.scrollLeft)).toBe(before)
  })
})
