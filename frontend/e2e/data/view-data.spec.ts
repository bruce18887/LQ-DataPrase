import { test, expect, type Locator, type Page } from '@playwright/test'
import { SEEDED_FILES } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { openViewTab, openFileInViewTab } from '../helpers/viewTab'
import { captureDownload } from '../helpers/download'
import { elSelectByPlaceholder } from '../helpers/elplus'

/** 查看数据 tab（当前可见 section）的顶层容器 */
function viewScope(page: Page) {
  return page.locator('.content-section:visible').first()
}

/** 某文件的总行数（走后端 API 取基准，不把种子的行数写死进用例） */
async function browseTotal(page: Page, filename: string) {
  return page.evaluate(async (filename) => {
    const token = localStorage.getItem('access_token')
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
    const files = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, { headers }).then((r) => r.json())
    const file = ((files.results ?? files) as any[]).find((f: any) => f.filename === filename)
    const d = await fetch(`/api/v1/browse/?datafile_id=${file.id}&page_size=1`, { headers }).then((r) => r.json())
    return d.total as number
  }, filename)
}

/** 当前活动标签页那份表格的「共 N 条数据」行（隐藏实例仍在 DOM 里，必须 :visible） */
function visibleCountLine(page: Page) {
  return viewScope(page).locator('p:visible').filter({ hasText: '共 ' }).first()
}

/**
 * 从 /browse/ API 拿全量行，定位测试所需的确定性行：
 * - failIdx/failCols/binValue：首个 bin != 1 的行及其 __fail_cells__
 * - passIdx：首个 bin == 1 的行
 * - farIdx/farCol：首个「index >= 10 且 __fail_cells__ 首列即远列（headers index >= 50）」的行（346 列文件必在屏幕外）。
 *   必须是首列：goToFailCell 跳的是第一个可见 fail 列，素材若只「含」远列而首列是近列，
 *   横向滚动落在近列上，farCol 永远滚不进视图。必须 >= 10：贴着数据开头的行会让 ag-grid
 *   'middle' 的滚动量被 clamp 成 0，「居中」与「不居中」表现一致 → 垂直断言退化成空断言
 *   （实测取第 0 行时传 'middle' 照样全绿）。
 *   取最后一个而不是首个：首个这种行往往贴着数据开头，行在视口里的落点让 ag-grid 的 'middle'
 *   滚动量被 clamp 掉，「居中」与「不居中」表现一致 → 垂直断言退化成空断言
 *   （实测传 'middle' 也全绿，故改为取末位）。
 * - borderlineRowIdx/borderlineCol：首个「__fail_cells__ 恰为 [bin] 且带临界橙格」的行
 *   （bin26 形状：没有严格越限测试列，靠临界项解释 fail）
 */
/**
 * 负载下大响应体可能截断（Unexpected end of JSON input）——重试逻辑必须
 * 定义在 page.evaluate 内部（闭包不序列化）。
 */
async function fetchBinFailInfo(page: Page, filename: string) {
  return page.evaluate(async (filename) => {
    async function fetchJsonRetry(url: string, headers: Record<string, string>): Promise<any> {
      let lastErr: unknown = null
      for (let i = 0; i < 3; i++) {
        try {
          const r = await fetch(url, { headers })
          if (!r.ok) throw new Error(`HTTP ${r.status}`)
          return await r.json()
        } catch (e) {
          lastErr = e
          await new Promise((res) => setTimeout(res, 800))
        }
      }
      throw lastErr
    }
    const token = localStorage.getItem('access_token')
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
    const files = await fetchJsonRetry(`/api/v1/files/?search=${encodeURIComponent(filename)}`, headers)
    const file = ((files.results ?? files) as any[]).find((f: any) => f.filename === filename)
    const d = await fetchJsonRetry(`/api/v1/browse/?datafile_id=${file.id}&page_size=99999`, headers)
    // 传输格式压缩：headers + data（行值数组）+ fail_cells/borderline_cells 并行数组 → zip
    const colHeaders = (d.headers ?? []) as string[]
    const data = (d.data ?? []) as unknown[][]
    const failCells = (d.fail_cells ?? []) as string[][]
    const borderlineCells = (d.borderline_cells ?? []) as string[][]
    const rows: Record<string, any>[] = []
    for (let i = 0; i < data.length; i++) {
      const o: Record<string, any> = {
        __fail_cells__: failCells[i] ?? [],
        __borderline_cells__: borderlineCells[i] ?? [],
      }
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
      borderlineRowIdx: -1,
      borderlineCol: '',
      borderlineCount: 0,
      // 同一视口内相邻的两个 fail 行（菜单定位跟随点击点的素材）
      pairAIdx: -1,
      pairBIdx: -1,
      pairAValue: '',
      pairBValue: '',
    }
    const failSeen: { idx: number; value: string }[] = []
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
        if (info.pairAIdx === -1) {
          for (const prev of failSeen) {
            if (i - prev.idx <= 5) {
              info.pairAIdx = prev.idx
              info.pairBIdx = i
              info.pairAValue = prev.value
              info.pairBValue = String(v)
              break
            }
          }
        }
        failSeen.push({ idx: i, value: String(v) })
        if (fc.length > 1 && i >= 10) {
          // goToFailCell 跳的是 __fail_cells__ 里第一个可见 fail 列（测试列在前、bin 最后），
          // 所以素材必须让**首列**就是远列，否则横向滚动会落到近列、farCol 永远滚不进视图。
          // i >= 10：行要离顶够远，否则 'middle' 的滚动量被 clamp 成 0，居中与不居中同表现；
          // 同时留在首个 IRM 块（100 行）内，避免深行触发分块加载把 rowTop 挪动造成 flaky。
          const first = fc[0]
          if (info.farIdx === -1 && first && first !== bin && colHeaders.indexOf(first) >= 50) {
            info.farIdx = i
            info.farCol = first
          }
        }
        if (info.borderlineRowIdx === -1 && fc.length === 1 && fc[0] === bin) {
          const bc = (rows[i].__borderline_cells__ ?? []) as string[]
          if (bc.length) {
            info.borderlineRowIdx = i
            info.borderlineCol = bc[0]
            info.borderlineCount = bc.length
          }
        }
      } else if (info.passIdx === -1 && v !== null && v !== undefined && v !== '' && Number(v) === 1) {
        info.passIdx = i
      }
    }
    return info
  }, filename)
}

/**
 * 从 /browse/ API 取「显示测试列」测试素材：左起前两个非系统列 + bin 系统列。
 * 系统列 = 后端 page==1 权威下发的 system_columns（按格式记录级列；名称前缀
 * 启发式已废弃——测试项可能与记录列同名前缀，2026-08-25 BPD87500
 * Device_Fused_Flag1/2 误判）。注意：系统列块（13 列）会把目标测试列推到
 * 横向视口外，断言其可见前须先渐进横向滚动（表头虚拟化）。
 */
async function fetchFirstTestCols(page: Page, filename: string) {
  return page.evaluate(async (filename) => {
    const token = localStorage.getItem('access_token')
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
    const files = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, { headers }).then((r) => r.json())
    const file = ((files.results ?? files) as any[]).find((f: any) => f.filename === filename)
    const d = await fetch(`/api/v1/browse/?datafile_id=${file.id}&page_size=1`, { headers }).then((r) => r.json())
    const sys = new Set((d.system_columns ?? []) as string[])
    const testCols = (d.headers ?? []).filter((c: string) => !sys.has(c))
    return { testCol: testCols[0] ?? '', absentCol: testCols[1] ?? '', bin: d.bin_column as string }
  }, filename)
}

/** 后端 page==1 下发的两个权威列名：Bin 列与序列列（四种格式序列列名各不相同） */
async function fetchPinDefaults(page: Page, filename: string) {
  return page.evaluate(async (filename) => {
    const token = localStorage.getItem('access_token')
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
    const files = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, { headers }).then((r) => r.json())
    const file = ((files.results ?? files) as any[]).find((f: any) => f.filename === filename)
    const d = await fetch(`/api/v1/browse/?datafile_id=${file.id}&page_size=1`, { headers }).then((r) => r.json())
    return {
      bin: (d.bin_column ?? '') as string,
      serial: (d.serial_column ?? '') as string,
      systemColumns: (d.system_columns ?? []) as string[],
    }
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

/**
 * 固定列容器里某一行的 **Bin 列**单元格。
 *
 * 不能用 `.ag-cell.first()`：固定列支持多选后，默认同时钉住 Bin 与序列列，
 * 而序列列在多数格式的列序里排在 Bin 之前 → 第一个固定单元格是序列列，
 * 右键它不弹 Bin 菜单、也没有红色高亮（2026-10-17 实测连带打红 3 条既有用例）。
 */
function binCell(row: Locator, bin: string) {
  return row.locator(`.ag-cell[col-id="${bin}"]`)
}

/**
 * 横向渐进滚动，直到 `probe`（文档级选择器）渲染出来。
 *
 * 三件事是实测出来的（手工探针跑在「查看数据」表格上，188 列 / 36400px 宽的那份 DA35 文件）：
 * ① `.ag-header-viewport`、`.ag-center-cols-viewport`、`.ag-body-horizontal-scroll-viewport`
 *   三者滚动量同步，写任意一个都带动表头与表体 —— 元素选择不是这里的关键。
 * ② 可滚上限是 `scrollWidth - clientWidth`（实测 35674 = 36400 - 726）。旧写法判
 *   `scrollLeft < scrollWidth` 永远为真 → 目标列一旦没渲染出来就是死循环，表现为整条用例
 *   60s 超时且没有任何断言消息（2026-09-20 全量跑实测）。
 * ③ `.ag-root` 刚出现时**列宽还没测出来**：实测那一刻 `scrollWidth === clientWidth === 926`、
 *   表头单元格数 0，约 265ms 后才变成 36400 / 6。在这之前既滚不动也探不到目标 → 必须先等
 *   可滚宽度出现，否则上面那条死循环就是必然。
 */
async function scrollGridUntil(page: Page, probe: string) {
  await page.locator('.ag-header-viewport').evaluate(async (el, sel) => {
    const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
    let max = 0
    for (let i = 0; i < 100; i++) {
      max = el.scrollWidth - el.clientWidth
      if (max > 0 || document.querySelector(sel)) break
      await wait(100)
    }
    for (let x = 0; max > 0; x += 400) {
      el.scrollLeft = Math.min(x, max)
      await wait(60)
      if (document.querySelector(sel) || x >= max) return
    }
  }, probe)
}

/**
 * 账号「默认每页行数」的读 / 写（与 `e2e/settings/page-size.spec.ts`、
 * `e2e/data/renderer-memory.spec.ts` 同形，本仓这条通路一直是各 spec 自带一份）。
 *
 * 收尾必须写回**原值**而不是硬编码默认：admin storageState 是共享账号（lessons 2026-09-19）。
 */
async function readPageSize(page: Page): Promise<number | null> {
  return page.evaluate(async () => {
    const resp = await fetch('/api/v1/auth/settings/', {
      headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
    })
    const data = await resp.json()
    return typeof data?.page_size === 'number' ? data.page_size : null
  })
}

async function putPageSize(page: Page, value: number): Promise<void> {
  const status = await page.evaluate(async (v) => {
    const resp = await fetch('/api/v1/auth/settings/', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify({ page_size: v }),
    })
    return resp.status
  }, value)
  expect(status, `PUT page_size=${value}`).toBe(200)
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

  test('@p1 固定列：默认钉住 Bin + 序列列（后端 serial_column 下发，前端不按名称猜）', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.GAGE_S1)
    const { bin, serial } = await fetchPinDefaults(page, SEEDED_FILES.GAGE_S1)
    expect(bin, '应下发 bin_column').toBeTruthy()
    expect(serial, 'CTA8290D 应解析出序列列（Serial_No）').toBeTruthy()

    // 固定列表头里两列都在
    const pinnedHeader = page.locator('.ag-pinned-left-header')
    await expect(pinnedHeader).toContainText(bin, { timeout: 10_000 })
    await expect(pinnedHeader).toContainText(serial)
    // 光看表头不够 —— 下拉里显示两个 tag 也会让表头文本命中。要的是真的落在
    // 固定列容器里的单元格。
    for (const c of [bin, serial]) {
      await expect(
        page.locator(`.ag-pinned-left-cols-container .ag-cell[col-id="${c}"]`).first(),
        `${c} 应在固定列容器内`,
      ).toBeVisible()
    }
  })

  test('@p1 固定列：多选，后选的列叠加而不是替换已钉住的列', async ({ page }) => {
    // gage 文件 346 列足够验证列固定，且远小于 CTA8280F（10000 行）降低 dev 环境压力
    await openViewTab(page, SEEDED_FILES.GAGE_S1)
    await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })

    const { bin, serial, systemColumns } = await fetchPinDefaults(page, SEEDED_FILES.GAGE_S1)
    const skip = new Set([bin, serial, ...systemColumns])

    // 打开固定列下拉（多选）：用 aria-label 定位输入框所在 select，点击 wrapper 打开
    const pinSelect = viewScope(page).locator('.el-select:has(input[aria-label="固定列"])').first()
    await pinSelect.locator('.el-select__wrapper').click()
    // 等待下拉动画完成、选项渲染（选项依赖 numericColumns 就位，负载下 5s 不够）
    const options = page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
    await expect(options.first()).toBeVisible({ timeout: 15_000 })
    const count = await options.count()
    expect(count).toBeGreaterThan(2)

    // 取两个「未固定且非系统列」的列作素材：系统列里的 Part_No/Dut_Pass/X_COORD 等
    // 被「默认隐藏列」设置 hide 掉了，钉一个隐藏列在界面上没有任何可见结果。
    const targets: string[] = []
    for (let i = 0; i < count && targets.length < 2; i++) {
      const t = (await options.nth(i).textContent())?.trim() ?? ''
      if (t && !skip.has(t)) {
        targets.push(t)
        await options.nth(i).click()
      }
    }
    expect(targets, '应存在两个未固定的列可作素材').toHaveLength(2)
    // 多选下拉点选项不收起，Escape 收回后再看表格
    await page.keyboard.press('Escape')

    const pinnedHeader = page.locator('.ag-pinned-left-header')
    for (const t of targets) {
      await expect(pinnedHeader, `后选的 ${t} 应进固定列`).toContainText(t, { timeout: 10_000 })
    }
    // 承重的一半：原有的 Bin / 序列列不能被后选挤掉（单选语义才会这样，那正是本次改掉的）
    for (const c of [bin, serial]) {
      await expect(
        page.locator(`.ag-pinned-left-cols-container .ag-cell[col-id="${c}"]`).first(),
        `多选后原有的 ${c} 不该被顶掉`,
      ).toBeVisible()
    }
    for (const t of targets) {
      await expect(
        page.locator(`.ag-pinned-left-cols-container .ag-cell[col-id="${t}"]`).first(),
      ).toBeVisible()
    }
  })

  test('@p1 Pass/Fail 筛选：未选文件时预选，切文件后筛选重置（契约升级）', async ({ page }) => {
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

    // 再选文件 → 筛选被重置（2026-09-06 契约：Site/PassFail/测试列/元信息属于
    // 旧文件，切文件一律重置避免旧口径误导，见 DataBrowserAgGrid watch(fileId)）。
    // 注：banner 下拉在此流程不可靠（历史 A/B 预存在失败），改用文件列表
    // 服务端搜索 + 「查看」按钮的可靠路径。
    await page.locator('.tab-btn').filter({ hasText: '文件列表' }).click()
    const searchInput = page.locator('input[placeholder="按文件名/程序名/标签搜索"]')
    await searchInput.fill('DA35_BPC50338')
    const fileRow = page.locator('.el-table .el-table__row').filter({ hasText: 'DA35_BPC5033' }).first()
    await fileRow.waitFor({ state: 'visible', timeout: 30_000 })
    const browseResp = page.waitForResponse(
      (r) => r.url().includes('/browse/') && !r.url().includes('pass_filter='),
      { timeout: 15_000 },
    )
    await fileRow.locator('button').filter({ hasText: '查看' }).click()
    expect((await browseResp).status()).toBe(200)

    // 行数与全量一致（未过滤），且 Pass/Fail 下拉回到空（重置生效的可观察状态）。
    // 注意用精确匹配：下拉占位符本身含「Pass」（Pass/Fail筛选），子串匹配恒假。
    await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })
    await expect(viewScope(page).locator('p').filter({ hasText: '条数据' })).toContainText(
      String(totals.all),
      { timeout: 15_000 },
    )
    await expect(pfSelect.getByText('Pass', { exact: true })).toHaveCount(0)
  })

  test('@p2 导出：文件名取自源文件（Content-Disposition 优先）', async ({ page }) => {
    // 用 gage 小文件（100 行）验证导出：ETS88（1728 列）的 12MB Excel 经 Vite 代理转发会压垮 dev server
    await openViewTab(page, SEEDED_FILES.GAGE_S1)
    await expect(page.locator('.ag-root').first()).toBeVisible({ timeout: 30_000 })

    const base = SEEDED_FILES.GAGE_S1.replace(/\.csv$/i, '')

    // 导出改成作业之后，这一发点击的链路是 POST /jobs/export_excel/ → 轮询 → download。
    // 断「三个端点都真的被用到」才是本批的接线证明：只断能下载到文件，
    // 那连旧的同步实现也能过，改了等于没测。
    const submitted = page.waitForResponse(
      (r) => r.url().includes('/jobs/export_excel/'), { timeout: 180_000 })
    const polled = page.waitForResponse(
      (r) => /\/jobs\/\d+\/$/.test(new URL(r.url()).pathname), { timeout: 180_000 })
    const served = page.waitForResponse(
      (r) => r.url().includes('/download/'), { timeout: 180_000 })

    const xlsx = await captureDownload(
      page,
      async () => {
        await viewScope(page).locator('button').filter({ hasText: '导出 Excel' }).click()
      },
      'view-data',
      180_000,
    )
    // 202 才是「提交完就走」；退回 200 说明后端走了同步降级（进程池没建起来），
    // 那种情况下这条用例应该红，让我们知道服务器档的池挂了，而不是悄悄放过。
    expect((await submitted).status(), '提交作业应 202（200=退回同步降级）').toBe(202)
    expect((await polled).status(), '轮询作业状态应 200').toBe(200)
    expect((await served).status(), '作业结果下载应 200').toBe(200)
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

    // Kelvin_VIN 是测试列，在 188 列中超出视口（表头虚拟化）→ 渐进横向滚动
    // 直到目标列渲染（位置依赖列序，不能假设固定像素）
    await scrollGridUntil(page, '.ag-header-cell[col-id="Kelvin_VIN"]')
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
    // 排序重载后横向滚动会被重置 → 再滚一次，直到首行 Kelvin_VIN 单元格渲染
    await scrollGridUntil(
      page,
      '.ag-center-cols-container .ag-row[row-index="0"] [col-id="Kelvin_VIN"]',
    )
    await expect(
      page.locator('.ag-center-cols-container .ag-row[row-index="0"] [col-id="Kelvin_VIN"]'),
    ).toContainText(String(expected), { timeout: 10_000 })
  })

  test('@p1 滚动加载分块：滚动到 8000 行触发覆盖该行的分块请求并渲染', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)
    await expect(page.locator('.ag-row').first()).toBeVisible({ timeout: 30_000 })

    // 分块大小来自账号设置 page_size，**不能写死 page=81**：2026-10-13 夜跑那轮账号
    // 漂到 page_size=200，实际请求是 page=41，写死的 81 永不出现 → 15s 超时 ×3 次重试。
    // 判据改成「请求的正是覆盖第 8000 行的那一块」，page_size 从它自己的 URL 现读。
    const blockResp = page.waitForResponse(
      (r) => {
        if (!r.url().includes('/browse/')) return false
        const q = new URL(r.url()).searchParams
        const size = Number(q.get('page_size')) || 100
        return Number(q.get('page')) === Math.floor(8000 / size) + 1
      },
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
    const failBody = await (await failResp).json()

    const summary = viewScope(page).locator('p').filter({ hasText: '共 ' })
    /**
     * 轮询到「行数列 == 服务端筛选集行数」为止 —— 不能只等 `Fail:` 出现：
     * 未过滤时 fail_row_count 也是 1289 > 0，那一段本来就渲染着，「等它出现」等于
     * 什么都没等，于是会读到 total=10000 / fail=1289 的旧渲染
     * （实测约 1/4 概率红，是这条判据自己的形状问题，不是本批改出来的）。
     */
    const readCounts = async () => {
      const text = (await summary.textContent()) ?? ''
      return {
        total: Number(text.match(/共\s*(\d+)/)?.[1] ?? 0),
        fail: Number(text.match(/Fail:\s*(\d+)/)?.[1] ?? 0),
      }
    }
    await expect
      .poll(async () => (await readCounts()).total, { timeout: 10_000 })
      .toBe(failBody.total)
    const { total, fail } = await readCounts()
    expect(total).toBeGreaterThan(0)
    expect(fail, '界面 Fail 行数应与后端 fail_row_count 一致').toBe(failBody.fail_row_count)
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

    // 渐进滚动到 Kelvin_VIN 表头 → hover 打开列菜单（默认即 filter 面板）
    await scrollGridUntil(page, '.ag-header-cell[col-id="Kelvin_VIN"]')
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

    // 选中列可见；未选中的另一个测试列被过滤（恒不渲染）；系统列（bin）仍显示。
    // 系统列块（记录级 13 列）把目标测试列推到横向视口外（表头虚拟化不挂载屏外
    // 表头单元格）→ 先渐进横向滚动到目标列渲染（位置依赖列序，不能假设像素）。
    await scrollGridUntil(page, `.ag-header-cell[col-id="${testCol}"]`)
    await expect(page.locator('.ag-header-cell').filter({ hasText: testCol }).first()).toBeVisible({
      timeout: 10_000,
    })
    await expect(page.locator('.ag-header-cell').filter({ hasText: absentCol })).toHaveCount(0)
    await expect(page.locator('.ag-header-cell').filter({ hasText: bin }).first()).toBeVisible({
      timeout: 10_000,
    })

    // 清空 → 恢复全部测试列（列数回到 346，水平滚动容器可滚动）。
    // 全选/清空收进了下拉 footer（不再常驻控件下方），所以要先展开下拉再点。
    await selector.locator('.el-select__wrapper').click()
    await page
      .locator('.el-select-dropdown:visible button')
      .filter({ hasText: '清空' })
      .first()
      .click()
    await page.keyboard.press('Escape')
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
      const sys = new Set((d.system_columns ?? []) as string[])
      const testCols = (d.headers ?? []).filter((c: string) => !sys.has(c))
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

  test('@p2 系统列按格式权威下发：前缀同名测试项（SITE_CHECK）不误判', async ({ page }) => {
    // 回归（2026-08-25 BPD87500 Device_Fused_Flag1/2 报告）：CTA8280F 种子文件的
    // SITE_CHECK 是测试项（[Data] 表第 14 列），旧实现因 site_ 前缀把它们误判为
    // 系统列 → 顶到最前且不可经「显示测试列」隐藏。新实现按后端 system_columns
    // 分类：SITE_CHECK 必须出现在「显示测试列」下拉中。
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)
    const { sysHas, testHas } = await page.evaluate(async (filename) => {
      const token = localStorage.getItem('access_token')
      const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
      const files = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, { headers }).then((r) => r.json())
      const file = ((files.results ?? files) as any[]).find((f: any) => f.filename === filename)
      const d = await fetch(`/api/v1/browse/?datafile_id=${file.id}&page_size=1`, { headers }).then((r) => r.json())
      const sys = new Set((d.system_columns ?? []) as string[])
      return {
        sysHas: sys.has('SITE_CHECK'),
        testHas: (d.headers ?? []).includes('SITE_CHECK') && !sys.has('SITE_CHECK'),
      }
    }, SEEDED_FILES.CTA8280F_FT)
    expect(sysHas).toBe(false)
    expect(testHas).toBe(true)

    // 「显示测试列」下拉必须包含 SITE_CHECK（旧实现误判系统列 → 不可选）
    const selector = viewScope(page).locator('.test-col-selector:has(input[aria-label="显示测试列"])').first()
    await selector.locator('.el-select__wrapper').click()
    const options = page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
    await expect(options.first()).toBeVisible({ timeout: 5_000 })
    await expect(options.filter({ hasText: 'SITE_CHECK' }).first()).toBeVisible({ timeout: 5_000 })
  })

  test('@p2 工具栏控件标签可见', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.GAGE_S1)
    const scope = viewScope(page)
    for (const label of ['显示测试列', 'Pass/Fail', 'Site', '列宽', '固定列']) {
      await expect(scope.locator('.ctl-label').filter({ hasText: label })).toBeVisible()
    }
  })

  test('@p2 列直方图：右键列头先出菜单，点「展示分布图」打开对话框，右键数据区不弹', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.GAGE_S1)

    // 右键一个数值列的表头（如 SW_Bin）→ 先出菜单，不再直接开图
    const headerCell = page.locator('.ag-header-cell').filter({ hasText: 'SW_Bin' }).first()
    await expect(headerCell).toBeVisible({ timeout: 10_000 })
    await headerCell.click({ button: 'right' })

    const menu = page.locator('.header-context-menu')
    await expect(menu).toBeVisible({ timeout: 5_000 })
    await expect(menu).toContainText('复制列名')
    await expect(menu).toContainText('展示分布图')
    await menu.locator('.header-context-menu__item').filter({ hasText: '展示分布图' }).click()
    await expect(menu).not.toBeVisible({ timeout: 3_000 })

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

    // 右键数据区单元格不弹窗/不弹菜单（body 右键放行，保留浏览器菜单）
    const cell = page.locator('.ag-center-cols-container .ag-row').first().locator('.ag-cell').first()
    await expect(cell).toBeVisible({ timeout: 10_000 })
    await cell.click({ button: 'right' })
    await page.waitForTimeout(1_000)
    await expect(page.locator('.el-dialog')).not.toBeVisible({ timeout: 3_000 })
    await expect(page.locator('.header-context-menu')).toHaveCount(0)
    await expect(page.locator('.bin-cell-menu')).toHaveCount(0)
  })

  test('@p2 表头菜单：复制列名写入剪贴板并给成功提示', async ({ page }) => {
    await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
    await openViewTab(page, SEEDED_FILES.GAGE_S1)

    const headerCell = page.locator('.ag-header-cell').filter({ hasText: 'SW_Bin' }).first()
    await expect(headerCell).toBeVisible({ timeout: 10_000 })
    await headerCell.click({ button: 'right' })

    const menu = page.locator('.header-context-menu')
    await expect(menu).toBeVisible({ timeout: 5_000 })
    await menu.locator('.header-context-menu__item').filter({ hasText: '复制列名' }).click()
    await expect(menu).not.toBeVisible({ timeout: 3_000 })
    await expect(page.locator('.el-message').filter({ hasText: '已复制' })).toBeVisible({ timeout: 3_000 })
    const copied = await page.evaluate(() => navigator.clipboard.readText())
    expect(copied).toBe('SW_Bin')
  })

  test('@p2 表头菜单：非数值列分布图置灰且不打开对话框', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.GAGE_S1)

    // 取首个「测试列且非数值」的列（系统列里的 QR_Code 默认隐藏，不能拿来测）。
    // 这类列通常是全空测试项，但仍在 headers/表头里。
    const nonNumericCol = await page.evaluate(async (filename) => {
      const token = localStorage.getItem('access_token')
      const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
      const files = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, { headers }).then((r) => r.json())
      const file = ((files.results ?? files) as any[]).find((f: any) => f.filename === filename)
      const d = await fetch(`/api/v1/browse/?datafile_id=${file.id}&page_size=1`, { headers }).then((r) => r.json())
      const sys = new Set((d.system_columns ?? []) as string[])
      const num = new Set((d.numeric_columns ?? []) as string[])
      return ((d.headers ?? []) as string[]).find((c) => !sys.has(c) && !num.has(c)) ?? ''
    }, SEEDED_FILES.GAGE_S1)
    expect(nonNumericCol, 'GAGE 文件应有非数值测试列').not.toBe('')

    const colSel = `.ag-header-cell[col-id="${nonNumericCol}"]`
    await scrollGridUntil(page, colSel)
    const headerCell = page.locator(colSel).first()
    await expect(headerCell).toBeVisible({ timeout: 10_000 })
    await headerCell.click({ button: 'right' })

    const menu = page.locator('.header-context-menu')
    await expect(menu).toBeVisible({ timeout: 5_000 })
    await expect(menu).toContainText('复制测试项名字')
    const histItem = menu.locator('.header-context-menu__item').filter({ hasText: '展示分布图' })
    await expect(histItem).toHaveClass(/is-disabled/)
    await expect(histItem).toContainText('非数值列')
    await histItem.click({ force: true })
    await page.waitForTimeout(500)
    await expect(page.locator('.el-dialog')).not.toBeVisible()
  })

  test('@p2 行高亮：右键序列号出菜单，点菜单项高亮/取消', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.GAGE_S1)
    const { serial } = await fetchPinDefaults(page, SEEDED_FILES.GAGE_S1)
    expect(serial, 'GAGE 文件应有序列列').not.toBe('')

    const row0 = page.locator('.ag-pinned-left-cols-container .ag-row[row-index="0"]')
    await expect(row0).toBeVisible({ timeout: 10_000 })
    const serialCell = row0.locator(`.ag-cell[col-id="${serial}"]`)
    await expect(serialCell).toHaveClass(/row-highlight-trigger/)

    const menu = page.locator('.row-highlight-menu')
    const menuItem = menu.locator('.row-highlight-menu__item')

    // 右键只出菜单，不直接切换高亮
    await serialCell.click({ button: 'right' })
    await expect(menu).toBeVisible({ timeout: 5_000 })
    await expect(menu).toContainText('第 1 行')
    await expect(menuItem).toContainText('高亮此行')
    await expect(row0).not.toHaveClass(/row-highlight/)
    await menuItem.click()
    await expect(menu).not.toBeVisible({ timeout: 3_000 })
    await expect(row0).toHaveClass(/row-highlight/)

    // 第二行同样通过菜单高亮，两行可同时高亮
    const row1 = page.locator('.ag-pinned-left-cols-container .ag-row[row-index="1"]')
    await expect(row1).toBeVisible({ timeout: 10_000 })
    const row1Serial = row1.locator(`.ag-cell[col-id="${serial}"]`)
    await row1Serial.click({ button: 'right' })
    await expect(menu).toBeVisible({ timeout: 5_000 })
    await expect(menu).toContainText('第 2 行')
    await menuItem.click()
    await expect(row0).toHaveClass(/row-highlight/)
    await expect(row1).toHaveClass(/row-highlight/)

    // 再右键第一行 → 菜单项变为取消高亮
    await serialCell.click({ button: 'right' })
    await expect(menu).toBeVisible({ timeout: 5_000 })
    await expect(menuItem).toContainText('取消高亮')
    await menuItem.click()
    await expect(row0).not.toHaveClass(/row-highlight/)
    await expect(row1).toHaveClass(/row-highlight/)

    // 序列号右键不会被 Bin/表头菜单截走
    await expect(page.locator('.bin-cell-menu')).toHaveCount(0)
    await expect(page.locator('.header-context-menu')).toHaveCount(0)
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

    const failCell = binCell(
      page.locator(`.ag-pinned-left-cols-container .ag-row[row-index="${info.failIdx}"]`),
      info.bin,
    )
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
    await binCell(passRow, info.bin).click({ button: 'right' })
    await expect(menu).not.toBeVisible({ timeout: 3_000 })
    await page.waitForTimeout(500)
    await expect(page.locator('.bin-cell-menu')).toHaveCount(0)
    await expect(page.locator('.el-dialog')).not.toBeVisible()
  })

  test('@p2 Bin 右键菜单：菜单开着时换行右键仍跟随新坐标', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)
    const info = await fetchBinFailInfo(page, SEEDED_FILES.CTA8280F_FT)
    if (info.pairAIdx === -1) test.skip(true, '无相邻 fail 行')

    const rowA = await ensureRowRendered(page, info.pairAIdx)
    const rowB = await ensureRowRendered(page, info.pairBIdx)
    const cellA = binCell(rowA, info.bin)
    const cellB = binCell(rowB, info.bin)
    await expect(cellA).toBeVisible({ timeout: 10_000 })
    await expect(cellB).toBeVisible({ timeout: 10_000 })

    const menu = page.locator('.bin-cell-menu')
    const expectAt = async (point: { x: number; y: number }) => {
      const box = await menu.boundingBox()
      expect(box).not.toBeNull()
      expect(Math.abs(box!.x - point.x), `menu x=${box!.x} click x=${point.x}`).toBeLessThan(6)
      expect(Math.abs(box!.y - point.y), `menu y=${box!.y} click y=${point.y}`).toBeLessThan(6)
    }
    // 直接派发 contextmenu：不经过 pointer/mousedown，复现「菜单已开着时再次右键」
    // 时 visible 一直为 true 的路径（旧实现只监听 visible，坐标会停在上一次点击处）。
    const dispatchContextMenu = (loc: Locator) =>
      loc.evaluate((el) => {
        const r = el.getBoundingClientRect()
        const x = r.left + r.width / 2
        const y = r.top + r.height / 2
        el.dispatchEvent(new MouseEvent('contextmenu', {
          bubbles: true, cancelable: true, button: 2, clientX: x, clientY: y,
        }))
        return { x, y }
      })

    const pA = await dispatchContextMenu(cellA)
    await expect(menu).toBeVisible({ timeout: 5_000 })
    await expect(menu).toContainText(`第 ${info.pairAIdx + 1} 行`)
    await expectAt(pA)

    const pB = await dispatchContextMenu(cellB)
    await expect(menu).toContainText(`第 ${info.pairBIdx + 1} 行`)
    await expectAt(pB)
  })

  /**
   * 页面缩放档下，右键菜单必须仍然出现在右键的那个点上。
   *
   * 浏览器档的缩放是 useZoom 往 `<html>` 上写 CSS `zoom`：它把整棵文档（含 Teleport 到
   * body 的 `position: fixed` 菜单）一起放大，而 `MouseEvent.clientX/Y` 与
   * `getBoundingClientRect()` 仍是**未缩放的视口 px**。把 clientX 直接写进 `left`
   * 等于再乘一次 zoom ⇒ 偏移量随「距视口左上角的距离」线性增长（2026-10-18 探针实测：
   * 1.25 档偏 163×113px，1.5 档整块菜单被推出视口）。Electron 档走
   * `webContents.setZoomFactor`，两套坐标同源，实测偏移 0–1px ⇒ zoom 读回来恒为 1。
   *
   * 判据只比较 `getBoundingClientRect()` 与事件 clientX/Y —— 两者都是视口 px，同一
   * 坐标空间；不混 offsetWidth/clientWidth（lessons 2026-09-06「zoom 缩放下的尺寸
   * 测量陷阱」），也不用 `locator.boundingBox()`（实测它与 DOM 不同源，见下面 measure()）。
   * zoom=1 那档是对照组：改前改后都必须绿，用来证明失败不是夹具或夹紧造成的。
   */
  test('@p2 右键菜单在页面缩放下跟随右键点（CSS zoom 坐标空间）', async ({ page }) => {
    /**
     * 视口拉高到 1400：查看数据页的工具栏 + 标签 + 表头把表体顶边压到 local y≈400，
     * 默认 720 高的视口里，1.5 档连「渲染窗口最上一行」都会越过底边（实测 639+109>720），
     * 夹紧必然介入 ⇒ 那条档位在 720 高下根本测不到空间换算。
     */
    await page.setViewportSize({ width: 1280, height: 1400 })
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)
    const info = await fetchBinFailInfo(page, SEEDED_FILES.CTA8280F_FT)
    if (info.failIdx === -1) test.skip(true, '无 fail 行')

    // 记下产品真正收到的 clientX/Y，而不是「我以为点在哪」
    await page.evaluate(() => {
      ;(window as any).__ctxPoint = null
      document.addEventListener(
        'contextmenu',
        (e: MouseEvent) => { (window as any).__ctxPoint = { x: e.clientX, y: e.clientY } },
        true,
      )
    })

    const menu = page.locator('.bin-cell-menu')
    /**
     * 量位置一律走 page.evaluate 里的 getBoundingClientRect()。
     *
     * 刻意不用 `locator.boundingBox()`：2026-10-18 探针实测它与 DOM 不同源，而且差值
     * **不是** zoom 倍率（同一格 zoom=1 时 PW 报 (558.5,348.5)、DOM rect 与事件 clientX
     * 都是 (605,363)），拿它去比 clientX 就是拿两套空间互比。DOM rect 与 clientX 逐档
     * 完全相等，所以两者互比才成立。
     */
    const measure = () =>
      page.evaluate(() => {
        const el = document.querySelector('.bin-cell-menu')
        const r = el?.getBoundingClientRect()
        return {
          click: (window as any).__ctxPoint as { x: number; y: number },
          menu: r ? { x: r.left, y: r.top, right: r.right, bottom: r.bottom } : null,
          vp: { w: window.innerWidth, h: window.innerHeight },
        }
      })

    try {
      for (const zoom of [1, 1.25, 1.5]) {
        // 与 useZoom 浏览器档完全同构的那一步
        await page.evaluate((z) => {
          document.documentElement.style.zoom = String(z)
        }, zoom)

        /**
         * 把目标行滚到渲染窗口的最上一行，让右键点尽量远离视口底边。
         *
         * 不这么做的话，靠下的行在高倍档会让「右键点 + 菜单高」越过视口底边，夹紧合法地
         * 把菜单往上挪 —— 判据就退化成「夹紧对不对」，量不到空间换算（实测 1.25 档挪 55px）。
         * 下面那条「夹紧不参与」是硬前置，滚不到位就直接红并报出坐标，不会静默退化。
         */
        await page.locator('.ag-body-vertical-scroll-viewport').evaluate((el, idx) => {
          ;(el as HTMLElement).scrollTop = idx * 30
        }, info.failIdx)
        const row = await ensureRowRendered(page, info.failIdx)
        const cell = binCell(row, info.bin)
        await expect(cell).toBeVisible({ timeout: 10_000 })

        await cell.click({ button: 'right' })
        await expect(menu).toBeVisible({ timeout: 5_000 })
        // 菜单确实是为这一行弹的 ⇒ 右键真的落在了目标格子上
        await expect(menu).toContainText(`第 ${info.failIdx + 1} 行`)

        const m = await measure()
        expect(m.menu, `zoom=${zoom} 量不到菜单`).not.toBeNull()
        const menuW = m.menu!.right - m.menu!.x
        const menuH = m.menu!.bottom - m.menu!.y
        const edge = 8 * zoom // 留白是 local px，画出来占 8*zoom 视口 px
        // 硬前置而不是可跳过的分支：夹紧一旦介入，下面的恒等式量的就不是空间换算了
        expect(
          m.click.y + menuH,
          `zoom=${zoom} 右键点 ${m.click.y}+菜单高 ${menuH} 越过视口底边 ${m.vp.h}，夹紧会介入`,
        ).toBeLessThanOrEqual(m.vp.h - edge)
        expect(
          m.click.x + menuW,
          `zoom=${zoom} 右键点 ${m.click.x}+菜单宽 ${menuW} 越过视口右缘 ${m.vp.w}，夹紧会介入`,
        ).toBeLessThanOrEqual(m.vp.w - edge)

        expect(Math.abs(m.menu!.x - m.click.x), `zoom=${zoom} menu.x=${m.menu!.x} click.x=${m.click.x}`).toBeLessThan(6)
        expect(Math.abs(m.menu!.y - m.click.y), `zoom=${zoom} menu.y=${m.menu!.y} click.y=${m.click.y}`).toBeLessThan(6)
        // 夹紧的边界也得算在同一套空间里：菜单整体不得被推出视口
        expect(m.menu!.right, `zoom=${zoom} 菜单右缘出视口`).toBeLessThanOrEqual(m.vp.w + 1)
        expect(m.menu!.bottom, `zoom=${zoom} 菜单下缘出视口`).toBeLessThanOrEqual(m.vp.h + 1)

        await page.keyboard.press('Escape')
        await expect(menu).not.toBeVisible({ timeout: 3_000 })
      }
    } finally {
      await page.evaluate(() => document.documentElement.style.removeProperty('zoom'))
    }
  })

  test('@p2 右键 Pass Bin 单元格不弹菜单（放行浏览器菜单）', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)
    const info = await fetchBinFailInfo(page, SEEDED_FILES.CTA8280F_FT)

    const passRow = await ensureRowRendered(page, info.passIdx)
    await binCell(passRow, info.bin).click({ button: 'right' })
    await page.waitForTimeout(600)
    await expect(page.locator('.bin-cell-menu')).toHaveCount(0)
    await expect(page.locator('.el-dialog')).not.toBeVisible()

    // 合成事件精确验证：未 preventDefault（浏览器复制菜单放行）
    const prevented = await binCell(passRow, info.bin).evaluate((el) => {
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

  test('@p2 菜单「定位到 Fail 单元格」：横向滚动到 fail 列 + flash，垂直不甩回正中', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)
    const info = await fetchBinFailInfo(page, SEEDED_FILES.CTA8280F_FT)
    if (info.farIdx === -1) test.skip(true, '无远列 fail 行')

    const farRow = await ensureRowRendered(page, info.farIdx)
    const vScroll = page.locator('.ag-body-vertical-scroll-viewport')

    /**
     * 目标行顶缘相对垂直视口顶缘的偏移（px）；行未渲染时返回 null。
     *
     * 返回 null 而不是抛错：滚动后 ag-grid 会重排行 DOM，读盒模型的瞬间正好处在
     * 「旧行已卸载、新行还没挂上」的窗口里，抛错会让重钉循环变成偶发红。
     */
    const rowOffset = async (): Promise<number | null> => {
      const vpBox = await vScroll.boundingBox()
      const rowBox = await farRow.boundingBox()
      if (!vpBox || !rowBox) return null
      return rowBox.y - vpBox.y
    }
    /**
     * 把目标行**钉**在视口顶部并等它钉住（偏移 ≤1px 才放行）。
     *
     * 必须迭代而不是「写一次 scrollTop 就算数」：深行的 rowTop 会随 IRM 分块加载漂移，
     * 写完 scrollTop 之后的重排会把行推到别处。实测过一次性写法让行正好漂到居中位，
     * 于是 'middle' 算出的目标滚动量与当前位置相等 → 甩动不发生 → 垂直断言当场变空。
     */
    async function pinRowToViewportTop() {
      for (let i = 0; i < 12; i++) {
        const off = await rowOffset()
        if (off !== null && Math.abs(off) <= 1) return off
        if (off !== null) {
          await vScroll.evaluate((el, d) => { (el as HTMLElement).scrollTop += d }, off)
        }
        await page.waitForTimeout(200)
      }
      throw new Error(`目标行钉不到视口顶部（rowTop 持续漂移），farIdx=${info.farIdx}`)
    }

    await pinRowToViewportTop()
    const vpBox = await vScroll.boundingBox()
    expect(vpBox, '垂直视口无盒模型').not.toBeNull()
    const centerOffset = (vpBox!.height - 30) / 2
    // 承重前置之一：居中位本身要有可测位移。视口矮到 centerOffset≈0 时，
    // 'middle' 与不传 position 算出的滚动量相同，下面的判据会永远全绿。
    expect(centerOffset, `视口可用高仅 ${vpBox!.height}px，居中位移不可辨 → 垂直判据会哑`).toBeGreaterThan(30)
    // 承重前置之二：滚动量必须大于居中位。行贴着数据开头时 scrollTop 已经是最小的 0，
    // 'middle' 的目标值算出来是负数、被 clamp 回 0 —— 实测 farIdx=0 时两种实现同样不动。
    const vBefore = await vScroll.evaluate((el) => el.scrollTop)
    expect(
      vBefore,
      `滚动量 ${vBefore} 不大于居中位 ${Math.round(centerOffset)}px，'middle' 会被 clamp → 垂直判据会哑`,
    ).toBeGreaterThan(centerOffset)
    // 承重前置之三：跳之前行就不在正中附近，否则「没被甩到正中」这句是白说的
    const offBefore = await rowOffset()
    expect(offBefore, '跳转前行未钉在可判位置').not.toBeNull()
    expect(
      Math.abs(offBefore! - centerOffset),
      `跳转前偏移 ${Math.round(offBefore!)} 已接近居中位 ${Math.round(centerOffset)} → 判据会哑`,
    ).toBeGreaterThan(30)

    // 前置：farCol 在屏幕外（列虚拟化 → 无此 header 元素）
    await expect(page.locator(`.ag-header-cell[col-id="${info.farCol}"]`)).not.toBeVisible()

    const hScroll = page.locator('.ag-body-horizontal-scroll-viewport')
    const before = await hScroll.evaluate((el) => el.scrollLeft)

    // 右键该行 pinned bin 单元格 → 点菜单项
    await binCell(farRow, info.bin).click({ button: 'right' })
    const menu = page.locator('.bin-cell-menu')
    await expect(menu).toBeVisible({ timeout: 5_000 })
    await menu.locator('.bin-cell-menu__item').click()
    await expect(menu).not.toBeVisible({ timeout: 3_000 })

    // 横向滚动发生（ensureColumnVisible）
    await expect
      .poll(async () => hScroll.evaluate((el) => el.scrollLeft), { timeout: 5_000 })
      .toBeGreaterThan(before)

    /**
     * 垂直判据：跳完之后行**不许落在视口正中**。
     *
     * 为什么不判「scrollTop 一动不动」（第一版的写法）：深行的 rowTop 会随 IRM 分块加载
     * 漂移，实测同一 scrollTop 下行 y 在 481/652 之间跳过，也实测到行被漂出视口后
     * ag-grid 做一次最小滚动把它拉回边缘 —— 那是**正确行为**，判它红就是自己造 flaky。
     *
     * 用户抱怨的形状是「行被甩回正中」，所以判的是三种合法落位之外的东西：
     * 原地（滚动量未变）、贴顶、贴底。'middle' 的落位是居中，与这三条都差半屏。
     */
    const vpH = vpBox!.height
    await expect
      .poll(
        async () => {
          const off = await rowOffset()
          if (off === null) return 'unrendered'
          const nowTop = await vScroll.evaluate((el) => el.scrollTop)
          const atTop = off <= 2
          const atBottom = off >= vpH - 32
          const unmoved = nowTop === vBefore
          return atTop || atBottom || unmoved ? 'ok' : `off=${Math.round(off)} center=${Math.round(centerOffset)} scrollTop ${vBefore}→${nowTop}`
        },
        { timeout: 5_000 },
      )
      .toBe('ok')

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

  test('@p2 临界橙格：bin-only fail 行标橙，右键定位跳到第一个临界列', async ({ page }) => {
    // ETS88 真实文件：bin26 行没有任何严格越限测试列，只有 4 个卡在规格窗端点的临界项
    await openViewTab(page, SEEDED_FILES.ETS88_FT)
    const info = await fetchBinFailInfo(page, SEEDED_FILES.ETS88_FT)
    if (info.borderlineRowIdx === -1) test.skip(true, '无 bin-only + 临界行')

    const row = await ensureRowRendered(page, info.borderlineRowIdx)
    const binTargetCell = binCell(row, info.bin)
    await expect(binTargetCell).toBeVisible({ timeout: 30_000 })

    // 横向滚到第一个临界列，确认渲染为橙色（light：amber-600 #f59e0b）
    const orangeSel =
      `.ag-center-cols-container .ag-row[row-index="${info.borderlineRowIdx}"] ` +
      `.ag-cell[col-id="${info.borderlineCol}"]`
    await scrollGridUntil(page, orangeSel)
    const orangeCell = page.locator(orangeSel)
    await expect(orangeCell).toBeVisible({ timeout: 15_000 })
    await expect(orangeCell).toHaveCSS('background-color', 'rgb(245, 158, 11)')

    // 固定列里的 Bin 单元格始终可见：右键 → 菜单显示临界数 → 定位
    await binTargetCell.click({ button: 'right' })
    const menu = page.locator('.bin-cell-menu')
    await expect(menu).toBeVisible({ timeout: 5_000 })
    await expect(menu).toContainText(`${info.borderlineCount} 个临界`)
    await menu.locator('.bin-cell-menu__item').click()
    await expect(menu).not.toBeVisible({ timeout: 3_000 })

    // flash 只持续约 1s；等它结束后底色必须仍是橙色
    await expect
      .poll(async () => (await orangeCell.getAttribute('class')) ?? '', { timeout: 3_000 })
      .toContain('ag-cell-data-changed')
    await expect
      .poll(async () => (await orangeCell.getAttribute('class')) ?? '', { timeout: 5_000 })
      .not.toContain('ag-cell-data-changed')
    await expect(orangeCell).toHaveCSS('background-color', 'rgb(245, 158, 11)')
  })

  /**
   * 顶部带高度契约（2026-10-17 把操作按钮并入文件横幅、全选/清空收进下拉、
   * 加上多文件标签条之后定的）。
   *
   * 两条断言各挡一种回归，缺一不可：
   * - 表格上缘 413px：谁再往顶部带加一行而没同步 `TABLE_TOP_OFFSET`，这里红。
   * - 表格高 == innerHeight - 290：常量被改动而没重新量顶部带，这里红。
   * 两个数都是实测（1280/1440/1920/2560 四档宽度下顶部带同为 413px，不折行）。
   */
  test('@p2 顶部带：操作按钮在文件横幅内，表格高度与实测占位对齐', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)

    const banner = page.locator('.active-file-banner:visible').first()
    await expect(banner).toBeVisible()
    for (const label of ['加载数据', '导出 Excel', '导出 CSV']) {
      await expect(
        banner.locator('button').filter({ hasText: label }).first(),
        `「${label}」应在文件横幅右端，而不是另占一行`,
      ).toBeVisible()
    }

    // 全选/清空只活在下拉 footer 里：常驻控件下方会把筛选行从 54px 撑到 75px
    await expect(
      viewScope(page).locator('.test-col-selector .col-actions'),
    ).toHaveCount(0)

    // 顶部带是异步凑齐的（质量条要等 /summary/、行数提示要等首块），量早了 y 会偏小。
    // 等它凑齐 + loading 遮罩退场，再量一次定型的几何。
    await expect(page.locator('.quality-bar:visible')).toBeVisible({ timeout: 15_000 })
    await expect(page.getByText(/共\s+\d+\s+条数据/).first()).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.el-loading-mask:visible')).toHaveCount(0)

    const band = await page.locator('.ag-grid-wrapper').boundingBox()
    expect(band, '表格容器无盒模型').not.toBeNull()
    expect(Math.round(band!.y), '表格上缘位置变了，但 TABLE_TOP_OFFSET 没跟着重量').toBe(413)
    const innerH = await page.evaluate(() => window.innerHeight)
    expect(band!.height, '表格高度不再等于 innerHeight - TABLE_TOP_OFFSET(290)').toBe(innerH - 290)
  })

  test('@p1 多标签：两个文件各占一个标签，后开的不覆盖先开的', async ({ page }) => {
    // 两份都用小文件：后端是单进程，多标签用例本来就要多解析一次，
    // 拿 10000 行那份做素材会把同文件里其它用例的 30s 搜索等待挤爆（实测 flaky）
    await openViewTab(page, SEEDED_FILES.GAGE_S1)
    await openFileInViewTab(page, SEEDED_FILES.GAGE_S2)

    const chips = viewScope(page).locator('.vf-tab:not(.vf-tab--add)')
    await expect(chips).toHaveCount(2)
    await expect(chips.nth(1)).toHaveClass(/is-active/)
    // 活动标签的横幅显示 S2，标签 1 的横幅（隐藏实例里）仍是 S1 ——
    // 两份 ag-grid 实例并存，后开的没把先开的顶掉
    const banners = viewScope(page).locator('.active-file-banner')
    await expect(banners.nth(1)).toContainText(SEEDED_FILES.GAGE_S2.slice(0, 11))
    await expect(banners.nth(0)).toContainText(SEEDED_FILES.GAGE_S1.slice(0, 11))

    await chips.nth(0).click()
    await expect(banners.nth(0)).toBeVisible()
    await expect(banners.nth(1)).not.toBeVisible()
  })

  test('@p2 多标签：切走再切回，自己的筛选与固定列状态不丢', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.CTA8280F_FT)
    const totalA = await browseTotal(page, SEEDED_FILES.CTA8280F_FT)
    const failA = await page.evaluate(async (filename) => {
      const token = localStorage.getItem('access_token')
      const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
      const files = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, { headers }).then((r) => r.json())
      const file = ((files.results ?? files) as any[]).find((f: any) => f.filename === filename)
      const d = await fetch(
        `/api/v1/browse/?datafile_id=${file.id}&page_size=1&pass_filter=Fail`,
        { headers },
      ).then((r) => r.json())
      return d.total as number
    }, SEEDED_FILES.CTA8280F_FT)
    expect(failA).toBeGreaterThan(0)
    expect(failA).toBeLessThan(totalA)

    // 在标签 1 上把 Pass/Fail 切到 Fail
    const pfInput = page.locator('input[aria-label="Pass/Fail筛选"]:visible').first()
    await pfInput.evaluate((el) => el.closest('.el-select')!.querySelector<HTMLElement>('.el-select__wrapper')!.click())
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter({ hasText: 'Fail' }).first().click()
    await expect(visibleCountLine(page)).toContainText(`共 ${failA}`, { timeout: 30_000 })

    // 开第二个标签：它是全新的状态，不能继承标签 1 的 Fail 筛选
    await openFileInViewTab(page, SEEDED_FILES.GAGE_S1)
    await expect(visibleCountLine(page)).not.toContainText('Fail:', { timeout: 30_000 })

    // 切回标签 1：Fail 筛选必须还在（这就是「同时打开多个文件来看」的全部意义）
    await viewScope(page).locator('.vf-tab:not(.vf-tab--add)').nth(0).click()
    await expect(visibleCountLine(page)).toContainText(`共 ${failA}`, { timeout: 30_000 })
    // 读选中的文本而不是 input.value：Pass/Fail 这个 el-select 不是 filterable，
    // EP 把选中项渲染成 .el-select__selected-item，input 恒为空串
    await expect(
      page.locator('.el-select:visible').filter({ has: page.locator('input[aria-label="Pass/Fail筛选"]') }).first(),
      '切回来的标签应保留它自己的 Pass/Fail 选择',
    ).toContainText('Fail')
  })

  test('@p2 多标签：关闭激活邻居、只剩一个时不给关、「+」开空白页出空态', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.GAGE_S1)
    await openFileInViewTab(page, SEEDED_FILES.GAGE_S2)

    const chips = viewScope(page).locator('.vf-tab:not(.vf-tab--add)')
    const banners = viewScope(page).locator('.active-file-banner')
    await expect(chips).toHaveCount(2)
    // 关掉活动的标签 2 → 激活邻居（标签 1），显示 S1
    await chips.nth(1).locator('.vf-tab__close').click()
    await expect(chips).toHaveCount(1)
    await expect(chips.nth(0)).toHaveClass(/is-active/)
    await expect(banners.nth(0)).toContainText(SEEDED_FILES.GAGE_S1.slice(0, 11))
    // 只剩一个标签时不提供关闭入口（防止把页面关没）
    await expect(chips.locator('.vf-tab__close')).toHaveCount(0)

    // 「+」开一个空白标签 → 空态引导，而不是残留上一个文件
    await viewScope(page).locator('.vf-tab--add').click()
    await expect(chips).toHaveCount(2)
    await expect(chips.nth(1)).toHaveClass(/is-active/)
    await expect(viewScope(page).locator('.el-empty:visible')).toContainText('请先在上方选择文件')
  })

  /**
   * 生命周期回归（生产实测 2026-10-22 06:45:39 两条 `AG Grid: warning #26`）。
   *
   * 形状：`gridApi` 由 `onGridReady` 赋值（composables/useBinCellMenu.ts:39-41）**且从不置空**，
   * 而「账号设置 → 默认每页行数」是在 `onMounted` 里 await 回来后才套用的
   * （applyBlockSize → purgeInfiniteCache）。标签在设置响应落地**之前**被关掉，续体就会打在
   * 已销毁的 grid 上 ⇒ 控制台一条 #26。行没被销毁时它只是个多余 purge，看不出来。
   *
   * 两个前置不是可选的（缺任一条本用例在未修复代码上**必绿＝假绿**，实测记录见
   * tasks/ 报告）：① page_size 必须 ≠ 初值 100 —— 相等时 applyBlockSize 提前 return，
   * 根本走不到 purge；② 必须把那条 GET 拖住（route stall），否则「挂载→关标签」的窗口
   * 只有几十毫秒，靠 Playwright 的手速撞它 = flaky。
   *
   * ⚠ 分工（别把本用例读成「生命周期守卫都靠 e2e」）：本条钉的是**时序**（异步续体在卸载后
   * 落地），下面那条「窄→宽」钉的是**purge 删除**（换文件只留一发 page=1）。而
   * `liveGridApi()` 里 `isDestroyed()` 那道闸（grid 先于组件销毁：清横幅 / 404）在本文件里
   * **没有射程** —— 那种情形下不存在会被它挡住的未销毁调用，删掉守卫这两条仍全绿，
   * 只有 T2 `test/unit/useIrmSizing.spec.ts` 钉得住。
   */
  test('@p1 关闭标签时不触发已销毁 grid 的 AG Grid #26 警告', async ({ page }) => {
    const warns: string[] = []
    page.on('console', (m) => {
      if (m.type() === 'warning') warns.push(m.text())
    })

    // 设置必须在挂载之前落库（网格是 onMounted 才读它），所以先 goto 再 PUT 再装 stall
    await gotoApp(page, '/dashboard')
    const original = await readPageSize(page)
    await putPageSize(page, 200)
    try {
      await page.route(/\/auth\/settings\/?$/, async (route) => {
        await new Promise((r) => setTimeout(r, 3_000))
        await route.continue()
      })

      await openViewTab(page, SEEDED_FILES.GAGE_S1)
      // 关掉标签需要场上有两个标签（closeViewTab 在只剩一个时直接 return）
      await viewScope(page).locator('.vf-tab--add').click()
      await expect(viewScope(page).locator('.vf-tab:not(.vf-tab--add)')).toHaveCount(2)
      await viewScope(page).locator('.vf-tab:not(.vf-tab--add)').nth(0).locator('.vf-tab__close').click()
      await expect(viewScope(page).locator('.vf-tab:not(.vf-tab--add)')).toHaveCount(1)

      // 等被拖住的设置续体落地（3s stall + 余量）；不等到它就没断言承重
      await page.waitForTimeout(4_000)
      expect(
        warns.filter((w) => /#26|has been destroyed/.test(w)),
        `不该再有已销毁 grid 的调用，实测警告：\n${warns.join('\n')}`,
      ).toEqual([])
    } finally {
      await page.unroute(/\/auth\/settings\/?$/)
      await putPageSize(page, original ?? 100)
    }
  })

  /**
   * 块预算接线（D3：口径变更必须可见）。
   *
   * 判据是可观察的出站请求，不是内部 ref：1,728 列那份 ETS88 在设置 500 时，
   * 实际请求必须带上钳位后的 `page_size=205`（`floor(355029/1728)`，常数推导见
   * docs/reference/renderer-memory-baseline-2026-10-22.md §6），并且页面上要能读出
   * 「从 500 降为 205」这句提示。设置回写走 finally（共享账号）。
   */
  test('@p1 千列文件：每页行数按列数预算压低且提示可见', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    const original = await readPageSize(page)
    try {
      await putPageSize(page, 500)
      const firstBrowse = page.waitForRequest(
        (req) => /\/api\/v1\/browse\//.test(req.url()) && req.method() === 'GET',
      )
      await openViewTab(page, SEEDED_FILES.ETS88_FT)
      const url = new URL((await firstBrowse).url())
      expect(url.searchParams.get('page_size'), '1,728 列 × 500 行超单块格数预算，必须被钳到 205').toBe('205')

      const hint = viewScope(page).locator('[title*="每页行数"]').first()
      await expect(hint).toBeVisible({ timeout: 30_000 })
      await expect(hint).toContainText('205')
      await expect(hint).toHaveAttribute('title', /1728.*500.*205/)
    } finally {
      await putPageSize(page, original ?? 100)
    }
  })

  /**
   * 同标签「窄 → 宽」：驻留块数的新快照必须真的换上（Important 2，这是生产主路径）。
   *
   * 形状为什么必须是这两个文件、这个设置：`page_size=100`（出厂默认）下
   * GAGE_S1（142 列）⇒ 块大小 100、cap 20；换成 ETS88（1,728 列）⇒ **块大小仍是 100**
   * （100×1728=172,800 未超单块格数预算 355,029，钳位不介入），只有 cap 20 → 8
   * （`floor(1,420,118 / 172,800)`）。而 ag-grid 只给 `datasource` / `cacheBlockSize` 挂了
   * resetCache 监听（`main.esm.mjs:55682-55683`），块大小没变 ⇒ 修复前这条路上没有任何
   * 重建入口，活的 cache 一直按窄文件那份 20 块快照驱逐（≈117 MiB 照旧驻留）。
   *
   * 判据是**出站 `/browse/` 的 page 参数**，两条都在同一个标签内、都不可省：
   * ① 横幅切过去之后 `page=1` 恰好一次 —— 钉的是「换文件分支删掉 `reload()` 里的 purge」。
   *    留着 purge 的话 `purgeCache → onCacheUpdated → storeUpdated`（`:55585-55593`）会把
   *    可见块再打一遍，叠上新 datasource 那次 reset ⇒ 同一块两发 page=1（本用例的 `toHaveLength(1)` 红）。
   * ② 向下翻过新 cap（8 块）再滚回顶部，必须**再来一发 `page=1`** —— 块 0 被驱逐过才会重取；
   *    仍按 20 块驱逐（未修复）时它还在缓存里，滚回去零请求 ⇒ `toBeGreaterThan` 红。
   *
   * ②只能在这里测：驱逐是 ag-grid `InfiniteCache.purgeBlocksIfNeeded` 的行为
   * （`:55477-55496`，读 `this.params.maxBlocksInCache`），T2 只钉得住「两个数算得对」。
   * ⚠ 反过来，本次补的 `isDestroyed()` 守卫**不在本文件的射程里**：它挡的是「grid 已销毁而
   * 组件仍挂载」（清横幅 / 404），那种情形下 e2e 里没有会被它挡住的调用，删掉守卫这三条用例
   * 仍全绿 ⇒ 只有 T2（`test/unit/useIrmSizing.spec.ts` 的「grid 先于组件销毁」）钉得住。
   *
   * page_size 是共享账号的设置：finally 无条件写回原值，末尾把写回结果读回来核对。
   */
  test('@p1 同标签窄→宽：cap 换了快照就看得见驱逐（滚回顶部要重取 page=1）', async ({ page }) => {
    // 1,728 列 × 100 行的块要渲染 9 次，60s 的默认额度不够（同 renderer-memory 的处理）
    test.setTimeout(180_000)
    /** 只看 `page=1` 的出站请求：块 0 有没有被驱逐，就问它会不会再取一次 */
    const page1: string[] = []
    page.on('request', (req) => {
      const u = new URL(req.url())
      if (u.pathname.endsWith('/api/v1/browse/') && u.searchParams.get('page') === '1') {
        page1.push(`${u.searchParams.get('datafile_id')}@${u.searchParams.get('page_size')}`)
      }
    })

    await gotoApp(page, '/dashboard')
    const original = await readPageSize(page)
    let restored: number | null = null
    try {
      await putPageSize(page, 100)
      await openViewTab(page, SEEDED_FILES.GAGE_S1)
      // 窄文件的首块到位（`共 N 条数据` 只在 dataLoaded 后渲染）：那份 cache 的快照就是 cap 20
      await expect(
        viewScope(page).locator('p').filter({ hasText: '共 ' }).first(),
      ).toBeVisible({ timeout: 30_000 })

      // 同一标签内用横幅换文件（新开标签是另一条通路：那份 cache 天生就是新快照，测不到这个缺口）
      page1.length = 0
      const banner = page.locator('.active-file-banner:visible .banner-file-select').first()
      await banner.click()
      await page
        .locator('.el-select-dropdown:visible .el-select-dropdown__item')
        .filter({ hasText: SEEDED_FILES.ETS88_FT.slice(0, 12) })
        .first()
        .click()

      // ① 首块恰好一发 page=1（等一拍再判：多余的那发是同 tick 的 purge 造成的，晚不到哪儿去）
      await expect.poll(() => page1.length, '切到宽文件后必须取到首块').toBeGreaterThan(0)
      await page.waitForTimeout(2_000)
      expect(page1, `换文件只需 datasource 换身份那一次取数，实测 page=1：${page1.join(', ')}`).toHaveLength(1)

      // 向下逐块翻过新 cap（8 块）：块大小 100 行 × 行高 30px，必须按块位递进（滚到底=一步跳到末块）
      const vp = page.locator('.ag-body-vertical-scroll-viewport').first()
      for (let block = 1; block <= 9; block++) {
        const got = page
          .waitForResponse((r) => /\/browse\//.test(r.url()), { timeout: 30_000 })
          .then(() => true)
          .catch(() => false)
        await vp.evaluate((el, top) => {
          ;(el as HTMLElement).scrollTop = top
        }, block * 100 * 30)
        await got
      }

      // ② 滚回顶部：块 0 已被按新 cap 驱逐 ⇒ 必须重新取 page=1
      const before = page1.length
      await vp.evaluate((el) => {
        ;(el as HTMLElement).scrollTop = 0
      })
      await expect
        .poll(() => page1.length, '滚回顶部必须重新取 page=1：说明驻留块数用的是新快照')
        .toBeGreaterThan(before)
    } finally {
      // finally 里不抛（`renderer-memory.spec.ts:129-133` 同口径）：PUT 抛会盖掉 try 里的原始失败，
      // 所以把结果留到末尾用读回值判红。共享账号，绝不把 100 之外的值留在场上。
      await putPageSize(page, original ?? 100).catch(() => undefined)
      restored = await readPageSize(page).catch(() => null)
    }
    expect(restored, '收尾必须把共享账号的 page_size 写回原值').toBe(original ?? 100)
  })

  test('@p2 默认隐藏列：记录列默认隐藏，更新隐藏列设置后重新显示', async ({ page }) => {
    // 设置默认隐藏列（系统设置同源）；finally 恢复默认（[] → 后端回退默认 8 列）
    const putHidden = (cols: string[]) =>
      page.evaluate(async (cols) => {
        await fetch('/api/v1/auth/settings/', {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${localStorage.getItem('access_token')}`,
          },
          body: JSON.stringify({ default_hidden_columns: cols }),
        })
      }, cols)

    const HIDDEN = ['Part_No', 'Dut_Pass', 'X_COORD', 'Y_COORD', 'QR_Code', 'Start_T', 'Alarm', 'Data_Cnt']
    // 先进入应用任意页（localStorage 可用），再写入设置；finally 恢复默认
    await gotoApp(page, '/settings')
    await putHidden(HIDDEN)
    try {
      await openViewTab(page, SEEDED_FILES.GAGE_S1)

      // 未隐藏的记录列（Serial_No/Site_No/SW_Bin/Test_Time）渲染；隐藏列不渲染
      await expect(page.locator('.ag-header-cell[col-id="Serial_No"]').first()).toBeVisible({
        timeout: 30_000,
      })
      await expect(page.locator('.ag-header-cell[col-id="SW_Bin"]').first()).toBeVisible({
        timeout: 10_000,
      })
      for (const col of HIDDEN) {
        await expect(page.locator(`.ag-header-cell[col-id="${col}"]`)).toHaveCount(0)
      }

      // 隐藏/可见由上面的 DOM 断言充分覆盖。原先经 __vueParentComponent 读
      // grid api 的 colDef.hide 断言是 dev-only 探针——生产构建的 Vue 不在
      // DOM 元素上挂组件实例，恒返回 null（preview webServer 上线后暴露）。

      // 重新显示 Part_No：系统设置是隐藏列的权威事实源（grid 无列菜单 UI 可用，
      // 且 view 页不把文件选择写进 URL——reload 会丢失选中文件得到空网格），
      // 更新设置后走一次完整重导航（openViewTab 会重挂 DataBrowserAgGrid、
      // onMounted 重读 getSettings），Part_No 回到表头
      await putHidden(HIDDEN.filter((c) => c !== 'Part_No'))
      await openViewTab(page, SEEDED_FILES.GAGE_S1)
      await expect(page.locator('.ag-header-cell[col-id="Part_No"]').first()).toBeVisible({
        timeout: 30_000,
      })
    } finally {
      await putHidden([])
    }
  })

  test('@p2 ETS88 文件末尾不渲染 Data Collection 尾部元数据行', async ({ page }) => {
    await openViewTab(page, SEEDED_FILES.ETS88_FT)

    // API 基准：total 只含真实数据行（文件末尾 2 行 Data Collection Start/Stop Date
    // 元数据由解析器剔除 —— 用户报告：它们显示在 ag-grid 末尾 + Bin=NaN 被误计 FAIL）
    const ref = await page.evaluate(async (filename) => {
      const token = localStorage.getItem('access_token')
      const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
      const files = await fetch(`/api/v1/files/?search=${encodeURIComponent(filename)}`, { headers }).then((r) => r.json())
      const file = ((files.results ?? files) as any[]).find((f: any) => f.filename === filename)
      const base = `/api/v1/browse/?datafile_id=${file.id}&page_size=100`
      const first = await fetch(`${base}&page=1`, { headers }).then((r) => r.json())
      const total: number = first.total
      const lastPage: number = Math.max(1, Math.ceil(total / 100))
      const last = await fetch(`${base}&page=${lastPage}`, { headers }).then((r) => r.json())
      const rows = (last.data ?? []) as unknown[][]
      const lastRow = rows[rows.length - 1] ?? []
      return {
        total,
        // 末行真实数据的 Serial #（第 2 列）；元数据行此处是 NaN
        lastSerial: String(lastRow[1] ?? ''),
        // 末块不应含 Data Collection 元数据行（列 0 是标签）
        containsMeta: rows.some((r) => String(r[0]).includes('Data Collection')),
      }
    }, SEEDED_FILES.ETS88_FT)

    expect(ref.containsMeta, 'API 末块不应含 Data Collection 元数据行').toBe(false)
    expect(ref.lastSerial, '末行应是真实数据行（Serial # 非空）').not.toBe('')
    expect(ref.total).toBeGreaterThan(0)

    // 表格行数文案与 API total 一致（含元数据行的旧实现 total=数据行+2）
    await expect(viewScope(page).locator('p').filter({ hasText: '共 ' })).toContainText(
      String(ref.total),
      { timeout: 15_000 },
    )

    // 垂直滚动到最后一行 → 渲染的是真实数据（Serial #），而不是 Data Collection。
    // 行文本要跨两个容器取：Serial # 现在默认被钉进固定列，只看 center 会漏掉它。
    const lastRow = page.locator(`.ag-center-cols-container .ag-row[row-index="${ref.total - 1}"]`)
    if ((await lastRow.count()) === 0) {
      await page
        .locator('.ag-body-vertical-scroll-viewport')
        .evaluate((el, top) => { (el as HTMLElement).scrollTop = top }, (ref.total - 1) * 30)
    }
    await expect(lastRow).toBeVisible({ timeout: 15_000 })
    const idx = ref.total - 1
    const lastRowText = async () =>
      (
        await page
          .locator(
            `.ag-pinned-left-cols-container .ag-row[row-index="${idx}"], ` +
              `.ag-center-cols-container .ag-row[row-index="${idx}"]`,
          )
          .allTextContents()
      ).join('|')
    await expect.poll(lastRowText, { timeout: 15_000 }).toContain(ref.lastSerial)
    expect(await lastRowText()).not.toContain('Data Collection')
  })
})
