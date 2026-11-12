import { test, expect, type Response } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { gotoApp } from '../helpers/nav'
import { uploadFile } from '../helpers/upload'
import { cleanupQuiet, deleteFilesByNameQuiet } from '../helpers/cleanup'
import { loginAs } from '../helpers/auth'
import { filePicker } from '../helpers/params'

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

  test.afterAll(async ({ browser }) => {
    for (const p of paths) cleanupQuiet(p)
    // 上传产生的 DataFile 行必须一并删：磁盘-only 清理留下的残留行按 -created_at
    // 顶到 files[0]，污染后续用例的文件选择（同 serial-no-column afterAll 的实测教训）。
    // storageState 显式清空：newContext 会继承 admin.json 登录态，/login 被弹回。
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    const page = await ctx.newPage()
    await loginAs(page, 'admin')
    await deleteFilesByNameQuiet(page, 'e2e_page_list_')
    await ctx.close()
  })

  test('分析页文件下拉显示全部文件，与数据管理页总数一致', async ({ page }) => {
    // 上传 21 个文件（> PAGE_SIZE=20 的临界形态）。旧实现一次注入 21 个 + 「重进 /data
    // 读分页 total」轮询等待，有三个叠加缺陷（2026-11-12 全量+独占实测）：
    // ① 阈值「≥21」被种子库背景计数（≥21）第一轮就满足，等待形同虚设；
    // ② 轮询里的 gotoApp 整页导航会中断在飞的上传 POST，21 个里只有 ~13 个真正落库；
    // ③ el-upload multiple 并发 21 个 POST 时 vite preview 代理会丢响应（后端 21×201
    //    全部落库，浏览器侧只收到 16 个响应）——数响应也等不齐。
    // 最后一个上传落在「分页读 → API 读」之间就是 99≠100 flake。
    // 改为逐个上传 + 逐个等 POST /upload/ 的 2xx 响应（响应驱动、期间不导航、不压代理）。
    // 本用例判的是文件数一致性，不是并发上传性能；桌面版直连 Django origin 无此代理层。
    test.setTimeout(120_000)
    await gotoApp(page, '/data')
    await page.locator('button').filter({ hasText: '上传文件' }).click()

    let uploaded = 0
    const onUploadResp = (r: Response) => {
      if (r.url().includes('/api/v1/upload/') && r.request().method() === 'POST' &&
          r.status() >= 200 && r.status() < 300) uploaded++
    }
    page.on('response', onUploadResp)
    try {
      for (let i = 0; i < paths.length; i++) {
        await uploadFile(page, paths[i])
        await expect.poll(() => uploaded, {
          timeout: 30_000,
          message: `第 ${i + 1}/${paths.length} 个文件上传未落库（POST /upload/ 2xx 计数）`,
        }).toBeGreaterThanOrEqual(i + 1)
      }
    } finally {
      page.off('response', onUploadResp)
    }

    // 全部落库后读一次分页 total（文件列表 Tab 只含 single，与 API singles 同口径）
    await gotoApp(page, '/data')
    const totalText = await page
      .locator('.el-pagination__total').first()
      .textContent({ timeout: 15_000 })
    const totalCount = Number((totalText ?? '').match(/\d+/)?.[0] ?? 0)
    expect(totalCount, '分页 total 应读到正数').toBeGreaterThan(0)

    // 分析页：打开文件下拉，数选项
    await gotoApp(page, '/analysis')
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    const fileSel = filePicker(page)
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

/**
 * 进分析页的 `files/options` 计数判据（Task 5 复审补齐 · 裁定 R19）。
 *
 * **为什么必须落在 `analysis` 档**：`scripts/affected-rules.mjs:33` 把
 * `frontend/src/pages/analysis/` 映射到 `['analysis']`。`AnalysisPage.vue:56` 已把
 * 「进入即拉」收成 `onActivated` 单挂，但此前钉这条的请求数只在别的档里
 * （`e2e/data/data.spec.ts:908-924` 量 `/data` 的 `page_size=9999`；
 * `e2e/dashboard/dashboard.spec.ts:573-596` 量 `/dashboard` 的 `files/options/`）
 * ⇒ 有人把 `onMounted(loadFiles)` 加回 `AnalysisPage.vue`，快门禁跑 `analysis` 档
 * **什么都抓不到**：本文件 :87 那条只断言下拉「≥ 21 个选项」，翻倍请求照样过
 * （数到 2 条仍是 ≥21），它只能抓「一条没发」不能抓「发了两条」。守卫放错档 = 无门禁。
 *
 * 判据口径与 dashboard 那条同源（lessons R2④）：计数器装在 `gotoApp` **之前**；
 * 用精确长度 `toHaveLength(1)` 而非 `≤1` ⇒ 回归成 0 条（首拉整个丢失）同样红。
 * 谓词 `/\/files\/options\/(\?|$)/` 锚住路径结尾，只吃 `/files/options/` 这一形状
 * （`/files/?…` 全量列表、`/files/product_codes/`、`/files/format_types/` 都不同形）。
 * 发起方唯一性先 grep 再断言：`frontend/src` 里 `getOptions` 命中**两个调用点**
 * （`AnalysisPage.vue:68` 与 `DashboardPage.vue:169`）再加**一处定义**
 * （`api/datafiles.ts:154-156`，本句下面那条讲的就是它）—— 别说成「只命中两处」，
 * 那条 grep 一直是三行，写成两处会让人以为谓词少看了一个文件。而 `gotoApp` 走 `page.goto`
 * 整页加载，进 `/analysis` 不会挂载 DashboardPage ⇒ 计数只可能来自本页 `loadFiles`；
 * `api/datafiles.ts:154-156` 是裸 `api.get`（无缓存、无单飞）⇒ 钩子翻倍 ⇒ 请求必然翻倍。
 *
 * 落地信号用**响应本身**而不是 tab 可见：`files.length === 0` 时模板只渲染 el-empty
 * （`AnalysisPage.vue:3`，没有任何 tab），UI 判据会把「请求已发出但列表恰好为空」
 * 误读成超时；`waitForResponse` 只证明「首拉已返回」，随后 2s 静置让同帧的
 * mounted→activated 那第二条有机会被计数器抓到（两条都在同一帧发出，2s 远够）。
 */
test.describe('进分析页：导航期文件选项只拉一次', { tag: ['@p1', '@analysis'] }, () => {
  test('@p1 进分析页只发一次 files/options', async ({ page }) => {
    const hits: string[] = []
    page.on('request', (r) => {
      if (/\/files\/options\/(\?|$)/.test(r.url())) hits.push(r.url())
    })
    const first = page.waitForResponse(
      (r) => /\/files\/options\/(\?|$)/.test(r.url()),
      { timeout: 30_000 },
    )

    await gotoApp(page, '/analysis')
    await first
    await page.waitForTimeout(2_000)

    expect(
      hits,
      `一次导航到 /analysis 发出了 ${hits.length} 条 files/options，应为 1 条：${JSON.stringify(hits)}`,
    ).toHaveLength(1)
  })
})
