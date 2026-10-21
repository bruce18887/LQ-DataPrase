import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, listParams, selectParam, pickOutlierMode, ensureChartToggles } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 回归：「📊 范围对比」「📱 Site统计」在页面缩放后必须**无需横向滚动就同屏看全每一列**。
 *
 * 2026-09-14 修复前：左栏宽度 = el-col 的 25%，1920 视口 125% 缩放下只剩 307px，
 * 而两表的列宽由内容决定（范围对比 404px / Site统计 339px）→ Gap+Unit、>Max
 * 列在视口里根本看不到。旧用例把「表格内部能滚到最后一列」当通过口径，
 * 恰好掩盖了这一点（滚动条存在 ≠ 列可见）。
 *
 * 修复三处（详见各自文件注释）：
 *  - AnalysisTabLayout：左栏 min-width 385px（扣掉卡片内边距 30px 后容器 ~355px，
 *    两表内在宽实测 ~275 / ~319px），右栏改吃剩余空间；≤1120px 视口改纵向堆叠；
 *  - 范围对比：单位提到卡头（后端 unit 每个参数只有一个值），省掉一整列；
 *  - 两表单元格内边距 6px → 4px。
 *
 * 用例口径（升级后）：列清单固定 + 表格零横向溢出 + 最后一列右缘落在表格内。
 * 只留「滚动兜底」不成立也没关系 —— 极端内容仍可由表格自带横向滚动条兜底，
 * 但那是退化路径，不再作为通过条件。
 *
 * 2026-10-17 再加两条：**逐格不截断**（`cell.scrollWidth ≤ clientWidth`）与
 * **逐格单行**（`.cell` 高 / line-height < 1.6，即不足两行）。旧口径对「中间列被
 * .cell{overflow:hidden} 省略号吃掉」完全是瞎的 —— 它只看最后一列的右缘；而换行本身
 * （用户报的高度跳）更是没有任何一条断言承重。覆盖范围也从点名两张表扩到「左栏所有挂了
 * dp-table-dense 的表」，QQ图/箱线图 一起收口后自动进账。
 *
 * ⚠ 单行判据刻意用「行数比值」而不是像素常量：`style.zoom` 下 getBoundingClientRect
 * 返回缩放后的值而计算样式没有（实测 125% 档单行量到 23px = 18×1.25），写死 27px
 * 这种阈值在 150% 档就会假失败。
 */
const SINGLE = '.single-param-tab'
const RANGE = '范围对比'
const SITE = 'Site统计'
const RANGE_COLS = ['', 'Low', 'High', 'Gap']
const SITE_COLS = ['Site', 'Yield', 'Fail', '<Min', '>Max']
/** 单元格高 ÷ line-height：单行 = 缩放系数（1~1.5），两行 ≥ 2 → 1.6 是安全分界 */
const SINGLE_LINE_MAX_RATIO = 1.6

interface TableMetrics {
  cols: string[]
  /** 表格内部横向溢出量（>0 即需要横向滚动才能看全列） */
  innerOverflow: number
  /** 最后一列表头右缘超出表格右缘的像素（>0 即被裁） */
  lastColOverflow: number
  /** 行 label 是否带 " (cut)" 后缀（裁剪范围模式下最宽的行标签） */
  hasCut: boolean
  /** 最宽单元格超出自身可用宽的像素（>0 即被 EP 的 .cell{overflow:hidden} 静默截断） */
  cellClip: number
  /** 最大「单元格高 ÷ line-height」：≥SINGLE_LINE_MAX_RATIO 即有格换行 → 卡片高度随数据跳 */
  maxCellLines: number
  rowCount: number
  cardH: number
}

function tableMetrics(page: Page, title: string): Promise<TableMetrics | null> {
  return page.evaluate((t) => {
    const card = [...document.querySelectorAll<HTMLElement>('.left-panel .el-card')]
      .find((c) => c.querySelector('.table-header')?.textContent?.includes(t))
    const table = card?.querySelector<HTMLElement>('.el-table')
    if (!table) return null
    const wrap = table.querySelector<HTMLElement>('.el-scrollbar__wrap')
      ?? table.querySelector<HTMLElement>('.el-table__body-wrapper')
    // 列清单只看真实列：body 出现纵向滚动条时 EP 会在 thead 末尾塞一个 gutter 占位 th
    const ths = [...table.querySelectorAll<HTMLElement>('thead th')]
      .filter((th) => !th.classList.contains('gutter'))
    const last = ths[ths.length - 1]
    const cells = [...table.querySelectorAll<HTMLElement>('td .cell, th .cell')]
    const cellBox = (fn: (c: HTMLElement) => number) =>
      cells.length ? Math.max(...cells.map(fn)) : 0
    return {
      cols: ths.map((th) => th.textContent?.trim() ?? ''),
      innerOverflow: wrap ? wrap.scrollWidth - wrap.clientWidth : -1,
      lastColOverflow: last
        ? Math.round(last.getBoundingClientRect().right - table.getBoundingClientRect().right)
        : -1,
      cellClip: cellBox((c) => c.scrollWidth - c.clientWidth),
      maxCellLines: cellBox(
        (c) =>
          Math.round(
            (c.getBoundingClientRect().height /
              (parseFloat(getComputedStyle(c).lineHeight) || 18)) *
              100,
          ) / 100,
      ),
      rowCount: table.querySelectorAll('tbody tr.el-table__row').length,
      cardH: card.getBoundingClientRect().height,
      hasCut: [...table.querySelectorAll('tbody tr td:first-child')]
        .some((td) => td.textContent?.includes('(cut)')),
    }
  }, title)
}

/**
 * 对照组：把 `.cell` 临时改回修复前的口径（white-space:normal + padding 0 8px），
 * 量左栏所有密行表的最大单元格行数。它 ≥2 才说明「单行」这条断言在当前这一档真的
 * 承重；不承重也不失败 —— 与 (cut) 覆盖率注解同一套口径，用 annotations 如实记下来，
 * 别让它变成一条永远绿的空断言。
 */
function controlOldCssMaxLines(page: Page, scope: string): Promise<number> {
  return page.evaluate((s) => {
    const lines = (c: HTMLElement) =>
      c.getBoundingClientRect().height / (parseFloat(getComputedStyle(c).lineHeight) || 18)
    const st = document.createElement('style')
    st.textContent = '.el-table.dp-table-dense .cell{white-space:normal;padding:0 8px}'
    document.head.appendChild(st)
    let h = 0
    for (const table of [
      ...document.querySelectorAll<HTMLElement>(`${s} .left-panel .el-table.dp-table-dense`),
    ])
      for (const c of [...table.querySelectorAll<HTMLElement>('td .cell, th .cell')])
        h = Math.max(h, Math.round(lines(c) * 100) / 100)
    st.remove()
    return h
  }, scope)
}

/**
 * 合成最宽内容探针。种子夹具的样本量只有 4 位数，**旧 CSS 下它同样不换行**（对照组实测
 * 单行），所以「单行」断言在这份 fixture 上是绿的但不承重。这里把 Site 表整表改写成
 * 用户真实数据的形状（CONT_CS3 那一屏：5 位样本量 + 3 位 Fail，逐列同宽），
 * 在新旧两种 CSS 下各量一次：新口径必须仍是单行且不截断；旧口径应当复现换行。
 *
 * ⚠ 只撑宽 Yield 一列是**测不出来的**：auto 布局会让其余四列退回各自的 min-width
 * 让位（实测旧口径仍 1 行）。要复现换行必须整行同时变宽。
 */
const WORST_ROW = ['ALL Site', '99.588%(100000)', '190(0.539%)', '30(0.085%)', '160(0.454%)']

function probeWidestRows(
  page: Page,
  title: string,
): Promise<{ newLines: number; oldLines: number; clip: number }> {
  return page.evaluate(({ t, worst }) => {
    const card = [...document.querySelectorAll<HTMLElement>('.left-panel .el-card')]
      .find((c) => c.querySelector('.table-header')?.textContent?.includes(t))
    const table = card?.querySelector<HTMLElement>('.el-table')
    if (!table) return { newLines: -1, oldLines: -1, clip: -1 }
    const lines = (c: HTMLElement) =>
      c.getBoundingClientRect().height / (parseFloat(getComputedStyle(c).lineHeight) || 18)
    const cells = [
      ...[...table.querySelectorAll<HTMLElement>('tbody tr')].flatMap((tr) =>
        [...tr.querySelectorAll<HTMLElement>('td .cell')].map((c, i) => ({
          c,
          text: worst[i] ?? '',
        })),
      ),
    ]
    const saved = cells.map((x) => x.c.textContent ?? '')
    const measure = () => {
      let l = 0
      let clip = 0
      for (const c of [...table.querySelectorAll<HTMLElement>('td .cell, th .cell')]) {
        l = Math.max(l, Math.round(lines(c) * 100) / 100)
        clip = Math.max(clip, Math.round(c.scrollWidth - c.clientWidth))
      }
      return { l, clip }
    }
    cells.forEach((x) => { x.c.textContent = x.text })
    const now = measure()
    const st = document.createElement('style')
    st.textContent = '.el-table.dp-table-dense .cell{white-space:normal;padding:0 8px}'
    document.head.appendChild(st)
    const old = measure()
    st.remove()
    cells.forEach((x, i) => { x.c.textContent = saved[i] })
    return { newLines: now.l, oldLines: old.l, clip: now.clip }
  }, { t: title, worst: WORST_ROW })
}

/**
 * 「挂了 dp-table-dense 的表」= 声明了「单元格一律单行」的表，逐张钉死两件事：
 * **不截断**（clip）与**不换行**（行数）。扫全栏而不是只点名两张：QQ图/箱线图
 * 2026-10-17 一起收口，将来再挂这张类自动进账。
 *
 * ⚠ 「零横向滚动」**不在这里**，仍只由 `expectNoClippedColumns` 对 范围对比/Site统计
 * 两张常驻表承诺（2026-09-14 的原始口径）。箱线图卡的「组」列是 `Bin <任意串名> · n=<位数>`，
 * 宽度需求没有上界，拿左栏下限去钉它等于让最坏数据决定所有人的图表区宽度；
 * 它溢出时走表格自带横向滚动条兜底（实测 125% 档溢出 ~12px）。
 *
 * ⚠ `requireTitles`：QQ图/箱线图两张卡是 `v-if` 挂在**账号级图表记忆**上的，
 * 不显式勾选就全靠环境状态决定扫到几张 —— 全量池里它扫到了箱线图并抓出真红，
 * 而单跑这个文件时只扫到两张、静默通过（见 lessons 2026-10-17）。要钉死覆盖就必须点名。
 */
async function expectEveryDenseTableSingleLine(page: Page, label = '', requireTitles: string[] = []) {
  const found = await page.evaluate(({ scope, maxLines }) => {
    return [
      ...document.querySelectorAll<HTMLElement>(`${scope} .left-panel .el-table.dp-table-dense`),
    ].map((table) => {
      const cells = [...table.querySelectorAll<HTMLElement>('td .cell, th .cell')]
      const box = (fn: (c: HTMLElement) => number) =>
        cells.length ? Math.max(...cells.map(fn)) : 0
      const wrap = table.querySelector<HTMLElement>('.el-scrollbar__wrap') ?? table
      return {
        title:
          table
            .closest('.el-card')
            ?.querySelector('.table-header')
            ?.textContent?.trim()
            .slice(0, 12) ?? '?',
        clip: Math.round(box((c) => c.scrollWidth - c.clientWidth)),
        lines:
          Math.round(
            box(
              (c) =>
                c.getBoundingClientRect().height /
                (parseFloat(getComputedStyle(c).lineHeight) || 18),
            ) * 100,
          ) / 100,
        overflow: wrap ? wrap.scrollWidth - wrap.clientWidth : -1,
        maxLines,
      }
    })
  }, { scope: SINGLE, maxLines: SINGLE_LINE_MAX_RATIO })
  // 防空转：一张都没扫到就是选择器失效，必须红
  expect(found.length, '左栏应至少扫到 范围对比 + Site统计 两张密行表').toBeGreaterThanOrEqual(2)
  for (const want of requireTitles)
    expect(found.map((t) => t.title), `${label}应扫到「${want}」卡（图表记忆没勾上？覆盖不能靠环境状态）`)
      .toContainEqual(expect.stringContaining(want))
  for (const t of found) {
    expect(t.clip, `${t.title}：单元格被 .cell{overflow:hidden} 截断`).toBeLessThanOrEqual(1)
    expect(
      t.lines,
      `${t.title}：出现换行单元格（最高 ${t.lines} 行，上界 ${SINGLE_LINE_MAX_RATIO}）`,
    ).toBeLessThan(t.maxLines)
  }
  const ctrl = await controlOldCssMaxLines(page, SINGLE)
  test.info().annotations.push({
    type: 'nowrap-control',
    description:
      `${label}旧 CSS 口径下最高单元格 ${ctrl} 行：` +
      (ctrl >= SINGLE_LINE_MAX_RATIO
        ? `≥${SINGLE_LINE_MAX_RATIO} ⇒ 这一档确实会换行，上面的单行断言承重`
        : `<${SINGLE_LINE_MAX_RATIO} ⇒ 这一档的样本数据不换行，承重证据见 widest-row-probe 注解`) +
      `；各表横向溢出 ${found.map((t) => `${t.title}=${t.overflow}px`).join(' ')}`,
  })
}

/**
 * 合成最宽内容 + 对照，逐视口跑：新口径必须单行不截断，旧口径负责证明这条断言承重。
 * 种子夹具的样本量只有 4 位数，光靠它「单行」断言是绿的但不承重（实测旧 CSS 也不换行），
 * 所以每个视口档都要拿用户那份最宽行再压一次。
 */
async function expectWidestRowsStaySingleLine(page: Page, label = '') {
  const probe = await probeWidestRows(page, SITE)
  expect(probe.newLines, `${label}合成最宽行后换行（${probe.newLines} 行）`).toBeLessThan(
    SINGLE_LINE_MAX_RATIO,
  )
  expect(probe.clip, `${label}合成最宽行后被省略号截断（${probe.clip}px）`).toBeLessThanOrEqual(1)
  test.info().annotations.push({
    type: 'widest-row-probe',
    description:
      `${label}合成最宽行：新口径 ${probe.newLines} 行 / 旧口径 ${probe.oldLines} 行` +
      (probe.oldLines >= SINGLE_LINE_MAX_RATIO
        ? ' ⇒ 旧口径复现换行，这条探针承重'
        : ' ⇒ 旧口径也没换行，这一档不触发（左栏宽到放得下旧口径 414px 内在宽）'),
  })
}

/** 两张表都要：列清单正确、零横向溢出、最后一列完整落在表格内、全栏密行表单行不截断 */
async function expectNoClippedColumns(page: Page, label = '') {
  const expected: [string, string[]][] = [[RANGE, RANGE_COLS], [SITE, SITE_COLS]]
  for (const [title, cols] of expected) {
    await expect
      .poll(async () => (await tableMetrics(page, title)) !== null, {
        message: `${title} 应已渲染`,
      })
      .toBe(true)
    const m = (await tableMetrics(page, title))!
    expect(m.cols, `${title} 列清单`).toEqual(cols)
    expect(m.innerOverflow, `${title} 不应需要横向滚动才能看全列`).toBeLessThanOrEqual(1)
    expect(m.lastColOverflow, `${title} 最后一列右缘应在表格内`).toBeLessThanOrEqual(1)
    expect(m.cellClip, `${title} 单元格被截断`).toBeLessThanOrEqual(1)
    expect(m.maxCellLines, `${title} 出现换行单元格`).toBeLessThan(SINGLE_LINE_MAX_RATIO)
  }
  await expectEveryDenseTableSingleLine(page, label)
  await expectWidestRowsStaySingleLine(page, label)
}

/** 轮转测试项：每格必须单行，且卡片高度只允许由行数解释 */
async function assertSingleLineAcrossParams(page: Page, params: string[]) {
  const seen: { param: string; rows: number; cardH: number; lines: number }[] = []
  for (const name of params.slice(0, 6)) {
    await selectParam(page, name)
    await waitLoadingGone(page.locator(SINGLE))
    const m = await tableMetrics(page, SITE)
    if (!m) continue // 该参数没渲染出站点表 → 不参与高度不变量
    seen.push({ param: name, rows: m.rowCount, cardH: Math.round(m.cardH), lines: m.maxCellLines })
  }
  expect(seen.length, '至少 3 个参数进入样本，否则这条断言是空转').toBeGreaterThanOrEqual(3)

  for (const s of seen)
    expect(s.lines, `${s.param}：Site统计 出现换行单元格（${s.lines} 行）`).toBeLessThan(
      SINGLE_LINE_MAX_RATIO,
    )

  // 同一行数必须给出同一卡片高度（≤2px 吸收边框与取整）
  const byRows = new Map<number, number[]>()
  for (const s of seen) byRows.set(s.rows, [...(byRows.get(s.rows) ?? []), s.cardH])
  for (const [rows, hs] of byRows)
    if (hs.length > 1)
      expect(
        Math.max(...hs) - Math.min(...hs),
        `${rows} 行时卡片高度抖动：${hs.join('/')}`,
      ).toBeLessThanOrEqual(2)

  const label = `切完 ${seen.length} 个测试项之后：`
  await expectEveryDenseTableSingleLine(page, label, [RANGE, SITE, 'QQ图统计', '箱线图统计'])
  await expectWidestRowsStaySingleLine(page, label)
  test.info().annotations.push({
    type: 'site-height',
    description: seen.map((s) => `${s.param}=${s.rows}行/${s.cardH}px`).join(' '),
  })
}

/** 在给定时间内等范围对比表出现 (cut) 行标签；没有则返回 false（不抛错） */
async function hasCutWithin(page: Page, ms: number): Promise<boolean> {
  try {
    await expect
      .poll(async () => (await tableMetrics(page, RANGE))?.hasCut ?? false, { timeout: ms })
      .toBe(true)
    return true
  } catch {
    return false
  }
}

/** 打开单文件分析并选中第一个参数，返回抽样的参数列表 */
async function openSingleTab(page: Page): Promise<string[]> {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, RECOMMENDED.analysis)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
  const params = await listParams(page)
  expect(params.length).toBeGreaterThan(0)
  await selectParam(page, params[0])
  await waitLoadingGone(page.locator(SINGLE))
  await expect(page.locator(`${SINGLE} .el-table__row`).first()).toBeVisible({ timeout: 15_000 })
  return params
}

test.describe('@p2 表格随缩放完整显示每一列', { tag: ['@p2', '@analysis'] }, () => {
  test('100% 与应用缩放 125% 下两表全列同屏可见（含裁剪范围最宽场景）', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    const params = await openSingleTab(page)

    // 1) 100%
    await expectNoClippedColumns(page, '100% 视口 1920：')

    // 2) 125%：这里直接给 <html> 设 style.zoom 只是**模拟**「有效视口被压小」的布局形态
    //    （原生页面缩放同样把 1920 压成 1536 CSS px）。应用自己不再产生这个写法——
    //    useZoom 现在只在 Electron 档经 setZoomFactor 生效，浏览器档整个交给浏览器原生缩放。
    await page.evaluate(() => { document.documentElement.style.zoom = '1.25' })
    await expectNoClippedColumns(page, '应用缩放 125%：')

    // 3) 最宽场景：裁剪范围 → 行 label 带 " (cut)"（label 列最宽）。
    //    该后缀只在参数**确实有异常值**时出现（useFiltered = hasOutliers && 模式≠off），
    //    而哪些参数有异常值取决于数据 → 在抽样参数里找第一个带 (cut) 的。
    await pickOutlierMode(page, '裁剪范围')
    let cutCovered = (await tableMetrics(page, RANGE))?.hasCut ?? false
    for (const name of cutCovered ? [] : params) {
      await selectParam(page, name)
      await waitLoadingGone(page.locator(SINGLE))
      cutCovered = await hasCutWithin(page, 3_000)
      if (cutCovered) break
    }
    // 一个都没找到也不失败：本用例的不变量（列不裁）与 label 是否带后缀无关，
    // 只是没覆盖到最宽情况，用注解如实记录下来。
    test.info().annotations.push({
      type: 'cut-suffix',
      description: cutCovered ? '已覆盖带 (cut) 的最宽行标签' : '抽样参数均无异常值，未覆盖 (cut)',
    })
    await expectNoClippedColumns(page, '125% + 裁剪范围最宽标签：')
  })

  test('浏览器缩放 125%（1536 视口）下两表全列同屏可见', async ({ page }) => {
    // 浏览器 Ctrl+`+` 到 125%：1920 物理像素只剩 1536 CSS px，是同一问题的另一条路径
    await page.setViewportSize({ width: 1536, height: 864 })
    await openSingleTab(page)
    await expectNoClippedColumns(page, '浏览器 125%（1536 视口，左栏贴着下限）：')
  })

  test('窄视口（1024）左栏整行堆叠，页面无横向溢出', async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 900 })
    await openSingleTab(page)

    const left = (await page.locator(`${SINGLE} > .main-row > .left-panel`).boundingBox())!
    const right = (await page.locator(`${SINGLE} > .main-row > .right-panel`).boundingBox())!
    expect(right.y, '图表区应落在左栏下方（纵向堆叠）').toBeGreaterThan(left.y + left.height - 4)
    expect(left.width, '堆叠后左栏占整行').toBeGreaterThan(600)

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow, '页面不应横向溢出').toBeLessThanOrEqual(1)
    await expectNoClippedColumns(page, '窄 1024（左栏整行堆叠）：')
  })

  /**
   * 2026-10-17 用户报的主症状：同一文件下切测试项，Site统计 卡片高度一直跳。
   * 根因不是「行数变了」，是 `:cell-style` 的 nowrap 从未命中装文字的 `.cell`
   * （EP 的 `.el-table .cell{white-space:normal}` 直接命中，赢过继承）+ auto 布局
   * 按内容重分配列宽 → 同样 15 字符的 Yield 在两个测试项下分别拿到 103px（拆两行）
   * 和 115px（单行）。所以这里钉的是「**高度只允许由行数解释**」。
   */
  test('切测试项时 Site统计 每格单行、卡片高度只随行数变化', async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 })
    const params = await openSingleTab(page)
    // QQ图/箱线图两张卡是 `v-if` + **账号级图表记忆**：不显式勾上，本用例能扫到几张表
    // 全看环境状态（全量池里扫到箱线图并抓出真红，单跑这个文件却只扫到两张静默通过）。
    // 只翻动本用例改掉的，收尾还原，别把 toggle 漏给同 slot 的后续用例。
    const flipped = await ensureChartToggles(page, { qq: true, box: true })
    try {
      for (const t of ['QQ图统计', '箱线图统计'])
        await expect(
          page.locator(`${SINGLE} .el-card`).filter({ hasText: t }).first(),
          `${t} 卡应随勾选渲染出来`,
        ).toBeVisible({ timeout: 20_000 })
      await assertSingleLineAcrossParams(page, params)
    } finally {
      if (flipped.length) {
        const restore: Record<string, boolean> = {}
        for (const k of flipped) restore[k] = false
        await ensureChartToggles(page, restore as Parameters<typeof ensureChartToggles>[1])
      }
    }
  })
})
