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

/** 通过顶部「当前文件」下拉选择文件：先等 /files/ 返回，再打开下拉直接点目标（并行负载下最稳） */
async function pickFileFromBanner(page: Page, filename: string) {
  // banner 数据源加载完成（并行负载下可能延迟，避免下拉打开时选项为空）
  await page
    .waitForResponse((r) => /\/files\/\?page_size=9999/.test(r.url()) && r.status() === 200, {
      timeout: 30_000,
    })
    .catch(() => {})

  const fileSelect = viewScope(page).locator('.banner-file-select').first()
  await fileSelect.locator('.el-select__wrapper').click()
  const option = page
    .locator('.el-select-dropdown:visible .el-select-dropdown__item')
    .filter({ hasText: filename })
    .first()
  await expect(option).toBeVisible({ timeout: 30_000 })
  await option.click()
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
    const rows = (d.rows ?? []) as Record<string, any>[]
    const colHeaders = (d.headers ?? []) as string[]
    const bin = d.bin_column as string
    const parseFail = (r: Record<string, any>): string[] => JSON.parse(r.__fail_cells__ ?? '[]')
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

    // 再选文件 → 筛选应生效（请求带 pass_filter）
    const browseResp = page.waitForResponse(
      (r) => r.url().includes('/browse/') && r.url().includes('pass_filter=Pass'),
    )
    await pickFileFromBanner(page, SEEDED_FILES.CTA8280F_FT)
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

  test('@p1 Site 筛选：本地过滤表格 + 「Site X 过滤后」文案 + 恢复', async ({ page }) => {
    // CTA8280F 含多 Site 值（188 列 × 10000 行，JSON 规模小于 ETS88 的 1728 列）
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)

    // 全量行数（UI 文案）
    const totalText = (await viewScope(page).locator('p').filter({ hasText: '共 ' }).textContent()) ?? ''
    const allTotal = Number(totalText.match(/共\s*(\d+)/)?.[1] ?? 0)
    expect(allTotal).toBeGreaterThan(0)

    // 打开 Site 下拉看选项（需 >1 个 site 才有过滤意义）
    const siteSelect = viewScope(page).locator('.el-select:has(input[aria-label="站点筛选"])').first()
    await siteSelect.locator('.el-select__wrapper').click()
    const siteOptions = page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
    await expect(siteOptions.first()).toBeVisible({ timeout: 5_000 })
    const siteCount = await siteOptions.count()
    if (siteCount < 2) {
      test.skip(true, '该文件仅有单个 site，无过滤场景')
      return
    }
    const targetSite = (await siteOptions.nth(1).textContent())?.trim() ?? ''
    await siteOptions.nth(1).click()

    // 行数下降 + 「Site X 过滤后」文案
    await expect(
      viewScope(page).locator('p').filter({ hasText: 'Site' }).filter({ hasText: '过滤后' }),
    ).toBeVisible({ timeout: 10_000 })
    const afterText = (await viewScope(page).locator('p').filter({ hasText: '共 ' }).textContent()) ?? ''
    const afterTotal = Number(afterText.match(/共\s*(\d+)/)?.[1] ?? allTotal)
    expect(afterTotal, 'Site 过滤后行数应减少').toBeLessThan(allTotal)

    // 恢复全部 Site → 行数恢复全量
    const siteSelect2 = viewScope(page).locator('.el-select:has(input[aria-label="站点筛选"])').first()
    await siteSelect2.locator('.el-select__wrapper').click()
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').first().click()
    await expect(viewScope(page).locator('p').filter({ hasText: '共 ' })).toContainText(String(allTotal), {
      timeout: 10_000,
    })
  })

  test('@p2 列显隐：隐藏列多选下拉可隐藏列、取消后恢复', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.GAGE_S1)

    // 取第一个可见系统列名（如 Bin 列）作为操作目标
    const firstHeader = page.locator('.ag-header-cell').first()
    const colName = (await firstHeader.textContent())?.trim().split(' ')[0] ?? ''
    expect(colName).toBeTruthy()
    await expect(page.locator('.ag-header-cell').filter({ hasText: colName }).first()).toBeVisible()

    // 打开「隐藏列」多选下拉，勾选目标列
    const hideSelect = viewScope(page).locator('.el-select:has(input[aria-label="隐藏列"])').first()
    // 首次无选中 tag：点 wrapper 打开（placeholder 会遮挡 input）；有 tag 后改点 input（避免点到 tag 触发移除）
    const hideInput = hideSelect.locator('input[aria-label="隐藏列"]')
    await hideSelect.locator('.el-select__wrapper').click()
    const options = page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
    await expect(options.first()).toBeVisible({ timeout: 5_000 })
    await page.waitForTimeout(300)
    const target = options.filter({ hasText: colName }).first()
    await target.click({ force: true })
    await page.keyboard.press('Escape')
    await page.waitForTimeout(300)

    // 该列 header 消失（隐藏）
    await expect
      .poll(
        async () => page.locator('.ag-header-cell').filter({ hasText: colName }).count(),
        { timeout: 10_000 },
      )
      .toBe(0)

    // 再次打开取消勾选 → 列恢复
    await hideInput.click()
    await page.waitForTimeout(300)
    await page
      .locator('.el-select-dropdown:visible .el-select-dropdown__item')
      .filter({ hasText: colName })
      .first()
      .click({ force: true })
    await page.keyboard.press('Escape')
    await expect(page.locator('.ag-header-cell').filter({ hasText: colName }).first()).toBeVisible({
      timeout: 10_000,
    })
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
