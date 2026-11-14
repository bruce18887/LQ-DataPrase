// frontend/e2e/data/disk-usage-chip.spec.ts
import { test, expect, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { gotoApp, navByMenu } from '../helpers/nav'
import { uploadFile, uploadMultipleFiles } from '../helpers/upload'
import { cleanupQuiet, deleteFilesByNameQuiet } from '../helpers/cleanup'

/**
 * 磁盘占用 chip（批2 · 第 5 项）。
 *
 * 分层纪律：体积怎么算是后端 T1 的事（test_storage_usage_scan.py），这里只钉
 * 「渲染得出、坏了不连累列表、写完一次操作会重拉」。口径不在这里重算。
 * 空目录态（新用户目录为空时 chip 说 `0 B` 而不是 `--`）由 T2 钉，不在浏览器里重算：
 * P2 project 的 storageState 固定是 ADMIN_STATE（playwright.config.ts:144），换账号
 * 要走 helpers/auth.ts 的登录路径，代价比那条判据值钱，而它已被
 * `test/unit/diskUsage.spec.ts` 的 `usageChipText(base())` 完整钉住。
 *
 * ⚠ **本文件不是 intra-file 并行安全的**：case 3 的 `file_count + 1` 与 case 7 的 `fresh ≤ 2`
 * 读的是同一账号在同一棵树上的全局量，同文件用例并跑会互相推动计数（后果是**假红**，
 * 不是假绿）。门禁档 `scripts/e2e_pool.mjs:215` 固定 `--workers=1` 已经挡住了；
 * 手跑请用 `npx playwright test --project=P2 --workers=1 e2e/data/disk-usage-chip.spec.ts`，
 * 别用 `npm run test:e2e:p2`（它不锁 workers，config 是 `fullyParallel: true` +
 * `workers: min(6, cpus/2)`）。不加 `mode: 'serial'` 是有意的：serial 下一条红会把
 * 后面整片用例一起跳过，而本文件每条用例各守一个独立契约，牺牲可诊断性不值。
 */

const CHIP = '.toolbar-left [data-testid="disk-usage-chip"]'
const USAGE_ROUTE = '**/api/v1/files/usage/**'

/**
 * 浏览器里读一次端点（与 repair-center.spec.ts:36 同一种拿法）。
 * 这是本仓**第二**份同名副本，够不上抽 helper（三条相似行好过过早抽象）；
 * 出现第三份时就把它搬进 `e2e/helpers/`，别再往 spec 里复制。
 */
function apiGet(page: Page, url: string) {
  return page.evaluate(async (u) => {
    const token = localStorage.getItem('access_token')
    const res = await fetch(`/api/v1${u}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    return { status: res.status, body: await res.json() }
  }, url)
}

/**
 * 判据异源：spec 里**自己再实现一遍**四档格式化。
 * 复用 src 里的同一个函数只会证明同一段代码等于自己：档/小数位/取整方向都跟着一起错。
 * 「组件偷偷读错字段」这条路要红，靠的是 case 1 里把 `unique_bytes` 注入成与 `bytes` 不同
 * （那里有实测说明为什么非注入不可）。Task 6c 之后 chip 只有体积，所以浏览器侧唯一活的
 * 读错字段路径就是 `bytes ↔ unique_bytes`；计数类字段（file_count/db_count）不再出现在
 * chip 上，它们的分工由浮层那一条（case 4）与 T2 钉。
 * ⚠ 边界要说明白：这份副本**只覆盖有限数**，没有 src 那条 `null/undefined/非有限 ⇒ '--'` 的分支
 * （`utils/diskUsage.ts` 的 `usageBytesText` 有）。这里刻意不补：本文件的 `bytes` 全部来自真实
 * 返回体，非有限值到不了 ⇒ 补了就是给不可能的状态写代码。代价也说清楚——万一 src 那条 `'--'`
 * 分支被删（`null` 会渲染成 `null B`），浏览器侧不会红，是 T2 的「非有限值不产生 NaN 字样」那条
 * 在钉它（2026-11-14 终审点名，控制器判为「注释补齐」而非「加断码」）。
 */
function bytesText(bytes: number): string {
  const KiB = 1024
  const MiB = 1024 * KiB
  const GiB = 1024 * MiB
  if (bytes < KiB) return `${bytes} B`
  if (bytes < MiB) return `${(bytes / KiB).toFixed(1)} KB`
  if (bytes < GiB) return `${(bytes / MiB).toFixed(1)} MB`
  return `${(bytes / GiB).toFixed(2)} GB`
}

/**
 * spec 侧再实现一遍 src `utils/diskUsage.ts` 的 TYPE_LABELS 查表（异源纪律同上）。
 * 旧版这里是三元链 `key === 'single' ? … : key`，缺 `''` 分支：空串桶的期望串退化成
 * `toContain('')`，而 `toContain('')` 对任何字符串恒真 ⇒ 那一行断言**不可能红**。
 * 补全查表只是把期望串给对；这条判据真正的可失败性来自下面用例里的注入轮 ——
 * 种子树造不出 `''` 桶（UI 也造不出，理由写在该用例注释里），不注入就没人能红。
 */
const TYPE_LABELS: Record<string, string> = { single: '单文件', batch: '批次', '': '根目录散文件' }
function typeLabel(key: string): string {
  // 与 src 同款 own-property 查表（同一个 `Object.hasOwn`，src 与本副本都在 Node 侧跑）：
  // `??` 只挡 null/undefined，键取自文件系统，constructor/toString 这类原型键会从原型上
  // 取到函数（utils/diskUsage.ts 里 Object.hasOwn 那段教训）。
  return Object.hasOwn(TYPE_LABELS, key) ? TYPE_LABELS[key] : key
}

/** 注入桶（case 4）：GB 档 ⇒ bytesText 两位小数，与真实桶的 MB 档一位小数不同形；
 *  count ≥ 1000 ⇒ 千分位分隔符在 Node 侧与浏览器侧各走一遍（真实桶 87 个文件时根本碰不到）。 */
const ROOT_LOOSE_KEY = ''
const LOOSE_BYTES = 3.5 * 1024 ** 3 // 3758096384 ⇒ '3.50 GB'
const LOOSE_COUNT = 2048 // '2,048'（en-US 与 zh-CN 分组符同为逗号，本仓浏览器 locale 下两侧一致）

test.describe('磁盘占用 chip', { tag: ['@p2', '@data'] }, () => {
  test('chip 文案与端点返回体逐字一致（透传捕获，不靠再猜一次缓存桶）', async ({ page }) => {
    // 用 route 透传把 app 自己那一次读取的响应体留下来 —— 不能再 apiGet 一次去比：
    // 后端缓存是按 30s 分桶的，两次读取跨桶就会给出不同的 scanned_at/数值。
    let captured: any = null
    await page.route(USAGE_ROUTE, async (route) => {
      const response = await route.fetch()
      const json = await response.json()
      // ⚠ 必须**造出**两字段的差异，这句保护才活着：slot 的媒体树是 `fs.linkSync` 一一对硬链
      // 镜像（scripts/e2e_pool.mjs:113），实测模板树 91 个文件 / 重复 inode 0 个
      // ⇒ 树里每个 inode 只出现一次 ⇒ `unique_bytes` 天然等于 `bytes`，读错字段在这棵树上
      // 是**看不见的**（2026-11-14 复审现读，别把它当成已钉住）。
      // ⚠ 差异必须**大于显示档的最小步长**才看得见，算术与下面 case 3 同一条：MB 档一位小数
      // ⇒ 步长 0.1 MiB = 104,858 B，GB 档两位小数 ⇒ 10.49 MB。取 20 MiB 同时跨过两档，
      // 且不动 `bytes` 本身（chip 的期望串仍取自 `captured.bytes`）。
      json.unique_bytes = json.bytes - 20 * 1024 * 1024
      captured = json
      await route.fulfill({ response, json })
    })

    await gotoApp(page, '/data')
    const chip = page.locator(CHIP)
    await expect(chip).toBeVisible({ timeout: 20_000 })
    expect(captured, 'app 应当真的拉过一次 /files/usage/').not.toBeNull()
    expect(captured.file_count, 'seed 后 admin 至少该有一个文件').toBeGreaterThanOrEqual(1)
    // 2026-11-14 用户拍板（Task 6c）：chip **只显体积**，文件数在浮层分桶行里。
    // 左边那颗 `{{ total }} 个文件` 是列表作用域，chip 的 file_count 是整棵树，两个都写
    // 「N 个文件」会打架 —— 尤其激活刷新之后，Explorer 拷进来的文件只动 chip 不动表格。
    // 反向守卫排在精确串**之前**：`toHaveText` 一红就先抛，排在它后面的 `not.toContainText`
    // 永远当不上 killer（同 5b33828 那次的订正，装饰性断言比没有更坏）。
    await expect(chip).not.toContainText('个文件')
    await expect(chip).toHaveText(`磁盘占用 ${bytesText(captured.bytes)}`)
  })

  test('占用接口坏掉时列表照常渲染，chip 不出现', async ({ page }) => {
    await page.route(USAGE_ROUTE, (route) =>
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ code: 'internal_error', message: 'boom' }),
      }),
    )
    await gotoApp(page, '/data')
    // 「不连累列表」必须由**列表自己**来钉：`.list-toolbar .section-count` 只是工具栏外壳，
    // 它在 `files` 被清空、表格整片消失时照样可见 ⇒ 光断它等于没断这句（2026-11-14 复审现读）。
    // 原先那句 `.section-count` 可见性已删——它是被这句**包住**的（工具栏在 `.content-section`
    // 里，行都可见了它没有不可见），留着只会让下一个读者以为它就是「列表渲染」的判据。
    // 选择器与超时取的是本仓既有写法（data.spec.ts:199 同一选择器）。
    await expect(
      page.locator('.content-section:visible .el-table .el-table__row').first(),
    ).toBeVisible({ timeout: 15_000 })
    await expect(page.locator(CHIP)).toHaveCount(0)
  })

  test('上传一个文件后以 fresh=1 重拉，计数 +1 且 chip 变文案', async ({ page }) => {
    const uniqueName = `e2e_usage_${Date.now()}`
    const tmpPath = path.join(os.tmpdir(), `${uniqueName}.csv`)
    // ⚠ 载荷必须**大于显示档的最小步长**，否则「chip 变文案」这句在数学上不可能成立。
    // 计划初稿这里是 12 字节的 `col1,col2\n1,2\n`，而 slot 树实测 710.1 MB、MB 档是一位小数
    // ⇒ 步长 0.1 MiB = 104,858 B：12 字节推不动最后一位。2026-11-14 池实测三连红
    // `Received: "磁盘占用 710.1 MB"`，而同一条用例里在它之前的 `file_count + 1` 是**绿的**
    // ⇒ 红的是判据的载荷，不是实现（后端计入、fresh 重拉、渲染都成立）。
    // 取 2 MiB ≈ 步长的 20 倍，跨档余量足够；值仍是 1/2 两个短整数 ⇒ 这一列的 distinct 值
    // 恒为 2 个，分析页参数选择器与元数据缓存不随行数膨胀（别拿长字符串凑体积，那样每个
    // 单元格都变成一个唯一参数值）。⚠ 原先这里写的是「`files/options/` 的大小跟着 unique 值
    // 走，不跟着行数走」——**实测是反的**：该接口逐文件返回标量行（apps/datafiles/views/
    // file_views.py:288-294 的 `.values(...)`，一次一行，默认 limit 5000），它跟着的是**文件数**，
    // 与本文件的 CSV 行数无关（CSV 行数只进这一行的 `row_count`）。
    // ⚠ 反方向也要知道：加大载荷**不是免费的**。单文件上传路径在请求里同步整读这份 CSV
    // （apps/datafiles/views/_helpers.py:120-127：`parsed` 为 None 时就地 `parse_file_meta`，
    // 批导入才走事务外预解析），52.4 万行进一次 `read_csv`，DataFrame 再进进程级解析缓存。
    // 但把同一份体积换成「一行超长字符串」更糟（每个单元格都变成一个参数值），所以维持现形。
    // 若哪天树进 GB 档（步长变 0.01 GiB = 10.5 MB），这条会**响**而不是静默假绿 ⇒ 把这里加大。
    fs.writeFileSync(tmpPath, `col1,col2\n${'1,2\n'.repeat(512 * 1024)}`)

    try {
      await gotoApp(page, '/data')
      const chip = page.locator(CHIP)
      await expect(chip).toBeVisible({ timeout: 20_000 })
      const before = await apiGet(page, '/files/usage/?fresh=1')
      expect(before.status).toBe(200)
      const beforeText = await chip.innerText()

      // 先挂等待再触发：onUploadSuccess → notifyFilesChanged → loadUsage(true)
      // 是在上传响应之后才发生的，顺序反了就会等到超时。
      const refreshed = page.waitForResponse((r) =>
        r.url().includes('/api/v1/files/usage/') && r.url().includes('fresh=1'),
      )
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, tmpPath)

      const resp = await refreshed
      const after = await resp.json()
      expect(after.file_count, '刚上传的那一个文件必须被计入').toBe(before.body.file_count + 1)
      await expect(chip).not.toHaveText(beforeText)
    } finally {
      // R2③ 自建/自清：这一行 col1/col2 没有 Site 列，留在库里会顶到 files[0]
      // 污染按文件推进的其它用例（upload-csv-only.spec.ts:43-48 记过同一条）。
      await deleteFilesByNameQuiet(page, 'e2e_usage_')
      cleanupQuiet(tmpPath)
    }
  })

  test('浮层能展开并给出与 chip 同一份拆分', async ({ page }) => {
    let captured: any = null
    let injectLoose = false
    await page.route(USAGE_ROUTE, async (route) => {
      const response = await route.fetch()
      const json = await response.json()
      // captured 只存**真实**返回体：真实桶的期望串必须来自真实载荷，注入轮不许覆盖它。
      if (!injectLoose) captured = json
      else json.by_type[ROOT_LOOSE_KEY] = { bytes: LOOSE_BYTES, count: LOOSE_COUNT }
      await route.fulfill({ response, json })
    })
    await gotoApp(page, '/data')
    const chip = page.locator(CHIP)
    await expect(chip).toBeVisible({ timeout: 20_000 })
    await chip.hover()

    // popper 被 teleport 到 body：判据走 popper 自己的 class（本仓 e2e 纪律——
    // 用 :visible 判「哪个浮层开着」在同页多浮层时不可靠）。
    const popper = page.locator('.el-popper.disk-usage-popover')
    await expect(popper).toBeVisible({ timeout: 10_000 })
    const cells = popper.locator('.el-descriptions__cell')
    const total = await cells.allInnerTexts()
    const joined = total.join(' ')
    // 前置守卫排在两条循环之前：`by_type` 缺失时循环**零次**执行 = 整段假绿，而 Playwright
    // 在第一处失败就抛 ⇒ 守卫写晚了就当不上 killer（同 5b33828 的订正方向）。
    expect(captured, 'app 应当真的拉过一次 /files/usage/').not.toBeNull()
    expect(captured.by_type, '返回体必须带 by_type 对象；缺了它下面两条循环空转 ⇒ 假绿').toBeInstanceOf(Object)
    // 两处都**不加** `?? {}`：src 那侧同样刻意去掉了它（utils/diskUsage.ts 的 by_type 注释，
    // 仓规「不为不可能的状态写兜底」），spec 的异源副本留着就会比被测代码更宽容。
    for (const key of Object.keys(captured.by_type)) {
      expect(joined, `浮层里必须有 ${key} 这一桶`).toContain(typeLabel(key))
    }
    // ⚠ 这条原先断的是 `String(captured.file_count)`（整棵树总数）。Task 6c 之后 chip 只显体积、
    // 浮层里给的是**每桶**的计数，总数不再以任何形式出现（两桶时它根本不在文本里 ⇒ 假红），
    // 所以改成按桶断计数串 —— 判据跟着文案分工走，不是跟着旧断言的字面走。
    for (const [key, bucket] of Object.entries<any>(captured.by_type)) {
      const countText = `${bucket.count.toLocaleString()} 个文件`
      expect(joined, `浮层里必须有 ${key} 这一桶的「${countText}」`).toContain(countText)
      expect(joined, `浮层里必须有 ${key} 这一桶的体积`).toContain(bytesText(bucket.bytes))
    }

    /*
     * —— 合成形状轮：`by_type['']`（根目录散文件）——
     *
     * 为什么是**注入**而不是造出真实数据：`''` 桶是后端的合法形状但**不可经 UI 达到** ——
     * - `_iter_files` 按根下第一段建桶，直接躺在根下的散文件 `top === ''`
     *   （apps/datafiles/storage_usage.py:74，建桶在 :147-152）⇒ 返回体里出现 `''` 是
     *   契约内的事（资源管理器手工往数据根目录拷文件就会造出它，真实用户可达）。
     * - 但 UI 的**每一条落盘路径**都经 `_user_upload_dir`（apps/datafiles/views/_helpers.py:183
     *   把路径钉死为 `<user>/single|batch/`）：上传 file_views.py:549,568、组合为批次
     *   file_views.py:336-338、移出批次 file_views.py:420-424、ZIP 注册 _helpers.py:378-380
     *   ——没有任何视图把文件写到 `<user>/` 根下。所以「经由 UI 操作造出 '' 桶」做不到，
     *   而本仓 e2e 数据纪律是夹具或响应拦截、不动 slot 树磁盘（磁盘手术会污染共用
     *   这棵树的其它用例）。注入是**唯一不越界的造法**，不是因为它省事。
     * - 诚实边界：注入只加 by_type['']、不动 bytes/file_count 总量 ⇒「各桶之和 = 总量」
     *   这条后端恒等式（T1 钉着）在本轮载荷里是**被故意打破**的；浮层逐桶渲染
     *   （usageBreakdownRows 不读总量），所以打破它不影响本轮判据所守的渲染契约。
     *
     * 可失败性（2026-11-14 实测）：把 src TYPE_LABELS 的 `''` 映射改坏（→「批次」）后独占
     * slot 复跑，红**恰好落在这条注入段**且只有 case 4 红（其余 6 条仍绿）。首个红点是下面
     * 那句 `cells.filter({ hasText: typeLabel(ROOT_LOOSE_KEY) }).first()` 的渲染等待
     * （超时，element(s) not found），它替紧随其后的那句 `toContain(typeLabel(...))` 兜住了
     * 同一件事；再下面的「比第一轮恰好多一对 cell」是第二道闸。
     * ⚠ 这里一律**用语句本身当锚点、不写本文件行号**：这一段初稿写的是 `:220/:223/:229`，
     * d999853 在它上方加了 3 行就整体漂了（复审现读）——同文件的行号谁都守不住。
     * 反过来，把查表退化回旧三元链并不会让本段红 —— 本段守的是**渲染**，不是 spec 自己的
     * 期望串，这正是旧版 `toContain('')` 恒真装饰的病根所在。
     */
    expect(captured.by_type, '种子树不该已有空串桶（注入会覆盖真实值，让期望串失去异源）')
      .not.toHaveProperty(ROOT_LOOSE_KEY)
    injectLoose = true
    // R2①：先挂等待再触发。第二轮走客户端路由激活刷新（与下面 case 5 同一条通路），
    // 不能 gotoApp —— 整页重载会把 popper/hover 状态连带 route 之外的东西一起重置。
    const refetched = page.waitForResponse((r) => r.url().includes('/api/v1/files/usage/'))
    await navByMenu(page, '仪表板')
    await navByMenu(page, '数据管理')
    await refetched
    await expect(chip).toBeVisible({ timeout: 15_000 })
    await chip.hover()
    await expect(popper).toBeVisible({ timeout: 10_000 })
    // 响应返回 ≠ 组件已重渲染（还差 axios then + Vue tick），web-first 等注入行出现后再读文本；
    // 直接 allInnerTexts 会抓到上一轮的 DOM。这一等同时也是「渲染得出」的正判据。
    await expect(cells.filter({ hasText: typeLabel(ROOT_LOOSE_KEY) }).first()).toBeVisible({ timeout: 10_000 })
    const looseCells = await cells.allInnerTexts()
    const looseJoined = looseCells.join(' ')
    expect(looseJoined, '注入的空串桶必须渲染成「根目录散文件」').toContain(typeLabel(ROOT_LOOSE_KEY))
    expect(looseJoined, '注入桶体积必须出自 spec 自己的 bytesText（GB 档两位小数）').toContain(bytesText(LOOSE_BYTES))
    expect(looseJoined, '注入桶计数必须带千分位（toLocaleString 两侧各走一遍）').toContain(`${LOOSE_COUNT.toLocaleString()} 个文件`)
    // 不被真实桶循环吞掉：bordered descriptions 一行 = label + content 两个 .el-descriptions__cell
    // （element-plus 2.14.0 descriptions-cell 源码，th.el-descriptions__cell + td.el-descriptions__cell），
    // 第二轮比第一轮**恰好多一对**；组件把注入桶并进已有行或整行丢弃时差值就不是 2。
    expect(looseCells.length - total.length, '注入桶必须多出一整行（2 个 cell）；被合并/去重吞掉时此差值变化')
      .toBe(2)
    await expect(page.locator(CHIP)).toBeVisible()
  })

  /*
   * 下面三条是 Task 7 复审修复轮**欠下的浏览器判据**：那五个修复里 ①激活刷新 ②失败保留旧值
   * ④连发合并 都没有任何自动化测试能证明（T2 是 node 环境、仓内不装 @vue/test-utils，
   * `grep -rln "mount(" test/unit` 零命中）。不补上，这三条就只是"看起来对"的实现。
   */

  test('占用请求按激活刷新：首屏一次，离开再回来第二次', async ({ page }) => {
    // ⚠ 计数钩子必须在 gotoApp **之前**装：gotoApp 内部是 page.goto，落地那一刻首屏请求
    //    已经发完，装晚了数组永远空 —— 那会让第一条断言红得看不出原因。
    const urls: string[] = []
    page.on('request', (req) => {
      if (req.url().includes('/api/v1/files/usage/')) urls.push(req.url())
    })
    await gotoApp(page, '/data')
    await expect(page.locator(CHIP)).toBeVisible({ timeout: 20_000 })
    // 恰好 1 次才说明「进入即拉」只挂在一处：0 ⇒ onActivated 没挂上或挂错组件；
    // 2 ⇒ 有人把 loadUsage() 又加回了 onMounted（keep-alive 首进 mounted+activated 都触发，
    //    正是 DataManagement.vue:266-274 记过的那次双倍请求）。
    expect(urls, '首屏应恰好一次占用请求').toHaveLength(1)

    // 必须是**客户端路由**（点侧边栏），不能是 gotoApp：page.goto 是整页重载，
    // 重载后 mounted 也会重新跑一次，那条「只挂 activated」的判据就变成永真。
    await navByMenu(page, '仪表板')
    await expect(page.getByTestId('page-identity')).toContainText('仪表板')
    await navByMenu(page, '数据管理')
    await expect(page.locator(CHIP)).toBeVisible({ timeout: 15_000 })
    expect(urls, 'keep-alive 回来必须再拉一次（只挂 onMounted 时计数会停在 1）').toHaveLength(2)
  })

  test('占用接口先好后坏：chip 保留上一次的数，且只出声一条', async ({ page }) => {
    let mode: 'ok' | 'fail' = 'ok'
    await page.route(USAGE_ROUTE, async (route) => {
      if (mode === 'fail') {
        return route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ code: 'internal_error', message: '服务器内部错误', detail: null }),
        })
      }
      const response = await route.fetch()
      return route.fulfill({ response, json: await response.json() })
    })
    await gotoApp(page, '/data')
    const chip = page.locator(CHIP)
    await expect(chip).toBeVisible({ timeout: 20_000 })
    const good = await chip.innerText()
    expect(good, '前置：首屏应真的拿到一个数').toMatch(/^磁盘占用 /)

    mode = 'fail'
    await navByMenu(page, '仪表板')
    await navByMenu(page, '数据管理')
    // 这一条就是 Fix 2 的正判据：改回「失败置空」的话，红在「chip 不见了」而不是别处。
    await expect(chip, '瞬时故障不许把眼前的数拿走').toHaveText(good)
    // 出声恰好一条：拦截器对同一消息 2s 去重（api/index.ts:26-32），页面自己不该再补一句。
    // 计数**不加文案过滤**，理由同 data.spec.ts:970-975 —— 绕开拦截器的重复提示用文案筛不掉，
    // 而 .filter({hasText}) + toBeVisible 在两条时会撞 strict mode，红得像是选择器坏了。
    const errToasts = page.locator('.el-message--error')
    await expect(errToasts, '刷新失败必须出声，且只出声一次').toHaveCount(1)
    await expect(errToasts.first()).toContainText('服务器内部错误', { timeout: 10_000 })
  })

  test('连发三文件上传：写后刷新塌成 ≤2 次 fresh=1', async ({ page }) => {
    const stamp = Date.now()
    // 前缀**刻意不用** `e2e_usage_`：case 3 的清理是按前缀删的，而 `e2e_usage_burst_` 恰好以它
    // 开头 ⇒ 并行跑（`npm run test:e2e:p2` 不锁 workers）时 case 3 会把这三行一起删掉。
    const paths = [0, 1, 2].map((i) => {
      const p = path.join(os.tmpdir(), `e2e_burst_${stamp}_${i}.csv`)
      fs.writeFileSync(p, 'col1,col2\n1,2\n')
      return p
    })
    const fresh: string[] = []
    page.on('request', (req) => {
      const u = req.url()
      if (u.includes('/api/v1/files/usage/') && u.includes('fresh=1')) fresh.push(u)
    })
    try {
      await gotoApp(page, '/data')
      await expect(page.locator(CHIP)).toBeVisible({ timeout: 20_000 })
      const first = page.waitForResponse((r) =>
        r.url().includes('/api/v1/files/usage/') && r.url().includes('fresh=1'),
      )
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadMultipleFiles(page, paths)
      // 「至少刷新过一次」这句归下面这行：零次时它按超时红，消息直接说没等到响应。
      // 因此**不再**补一句 `expect(fresh.length).toBeGreaterThan(0)` —— 它排在 await 之后，
      // 0 根本走不到那行，是一句不可能红的装饰（同 5b33828 订正的那一类）。
      await first
      // 等合并窗口**彻底收干**再计数：常数是量过的那道闸（USAGE_TRAIL_MS=800）的 2 倍 + 余量，
      // 不是拍脑袋。数早了会把「trailing 还没发」当成 ≤2 通过 —— 那是假绿。
      await page.waitForTimeout(2000)
      // 写成 ≤2 而不是 ==2：三个响应若恰好被 Vue 合到同一 tick，只有 leading 一次也合规。
      expect(fresh.length, 'K 连发不许变成 K 次全盘扫描').toBeLessThanOrEqual(2)
    } finally {
      await deleteFilesByNameQuiet(page, 'e2e_burst_')
      for (const p of paths) cleanupQuiet(p)
    }
  })

  /*
   * 差值行的两条（Task 9）：注入一条钉「超阈值 ⇒ 多一行 + 差值取自 mismatch_diff_bytes」，
   * 真实树一条钉「未超阈值 ⇒ 一行都不许出现」。两条都从 chip 可见起步 —— 那一句同时是
   * `props.usage` 已就位的前置：占用没拉到时这一行本就不该出现，少了等待第二条会假绿。
   */

  test('占用差值超阈值时，数据修复中心多一行且文案带上那个差值', async ({ page }) => {
    // 透传注入：只翻 mismatch 两个字段，其余（bytes/file_count/by_type）保持真实，
    // 这样这一条同时钉住「行与 chip 读的是同一份数据」+「阈值驱动的是布尔而不是猜」。
    await page.route(USAGE_ROUTE, async (route) => {
      const response = await route.fetch()
      const json: any = await response.json()
      json.mismatch_over_threshold = true
      json.mismatch_diff_bytes = 123456789 // ⇒ MB 档一位小数 ⇒ 渲染成「差 117.7 MB」
      await route.fulfill({ response, json })
    })

    await gotoApp(page, '/data')
    await expect(page.locator(CHIP)).toBeVisible({ timeout: 20_000 })
    await page.locator('button').filter({ hasText: '数据修复' }).click()
    const dialog = page.locator('.el-dialog').filter({ hasText: '数据修复中心' })
    await expect(dialog).toBeVisible()
    await dialog.locator('button').filter({ hasText: '开始检查' }).click()
    await expect(dialog.locator('.el-descriptions')).toBeVisible({ timeout: 60_000 })

    const alert = dialog.locator('[data-testid="disk-mismatch-alert"]')
    await expect(alert).toBeVisible()
    await expect(alert).toContainText('清单与磁盘不一致')
    await expect(alert).toContainText('差 117.7 MB')
    // 只陈述、不动作（计划订正③）：产品里没有任何路径回写 file_size，挂一个「重新扫描」
    // 就是谎话。这一句排在两条正判据之后仍然活着 —— 前两条在「有按钮」时照样绿。
    await expect(alert.locator('button')).toHaveCount(0)
  })

  test('未超阈值时数据修复中心不显差值行', async ({ page }) => {
    // 不注入：读的是真实树。新口径（差值只比「注册行 ∩ 文件在盘」的交集，订正⑤）在本机
    // dev 树实测 ratio=0.0000、漂移 0 条 ⇒ 这一条是诚实的绿，不是靠夹具凑出来的。
    // 它若红了先跑 tasks/probe_batch2_diff_cause.py 归因：真有人改了盘上文件大小（合法出现，
    // 按实测数更新台账）就是实现把孤立记录又混回了差值 —— 那种情况改实现，别改这条迁就。
    await gotoApp(page, '/data')
    await expect(page.locator(CHIP)).toBeVisible({ timeout: 20_000 })
    await page.locator('button').filter({ hasText: '数据修复' }).click()
    const dialog = page.locator('.el-dialog').filter({ hasText: '数据修复中心' })
    await expect(dialog).toBeVisible()
    await dialog.locator('button').filter({ hasText: '开始检查' }).click()
    // 正判据排在 count(0) 之前：检查结果没渲染出来时这一行当然「不存在」，那是假绿。
    await expect(dialog.locator('.el-descriptions')).toBeVisible({ timeout: 60_000 })
    // ⚠ 按 **testid 的结构存在性**判，不按文案筛：把 `v-if="mismatchLine"` 去掉后
    // `:title` 是 null，EP 照样渲染出一条空的 warning 条，而 `.el-alert` 配
    // `filter({ hasText: '清单与磁盘不一致' })` 抓不到它 ⇒ 实测整轮 unexpected 0（2026-11-14
    // 变异轮）。这一条契约说的是「这一行出不出现」，不是「这行写了什么」。
    // 检查完成后的分支里本对话框没有别的 el-alert（前置那条 info 在 `v-if="!result"` 分支），
    // 所以按 testid 数比按 `.el-alert` 数更耐后续的卡片改动。
    await expect(dialog.locator('[data-testid="disk-mismatch-alert"]')).toHaveCount(0)
  })

  test('占用接口返回 204：chip 缺席，且一条错误提示都不许有', async ({ page }) => {
    // 终审 F3 的**前端**半边：用户名为 `..` / `.` 这类拼不出安全数据根目录的账号，服务端早退成 204
    // 而不是冒成 500。204 是成功响应 ⇒ 拦截器不出声，而 `usage` 拿到 falsy ⇒ chip 自然缺席。
    // 与 case 2 成对：那条钉「500 要出声」，这条钉「不可算 ≠ 坏了」。
    // ⚠ 这条**够不着后端**（2026-11-14 实测）：`page.route` 的 fulfill 把真实响应整个遮掉，
    // 把视图那支改回 `Response(status=500)` 再跑池 ⇒ `unexpected 0`，十例全绿。所以后端契约
    // 在 T1 钉（`test_files_usage_api.py` 的 `test_用户名拼不出安全目录时返回204而不是500`，
    // 同一个变异过去恰好 FAIL 1 例、其余 11 例过）。
    // 这条自己能被什么改红：前端给 falsy 的 usage 也画出一颗 `磁盘占用 --`，或给「成功但无返回体」
    // 的响应补一条提示 —— 两者都归这里的两句 `toHaveCount(0)`。
    await page.route(USAGE_ROUTE, (route) => route.fulfill({ status: 204 }))
    await gotoApp(page, '/data')
    await expect(
      page.locator('.content-section:visible .el-table .el-table__row').first(),
    ).toBeVisible({ timeout: 15_000 })
    await expect(page.locator(CHIP)).toHaveCount(0)
    await expect(page.locator('.el-message--error')).toHaveCount(0)
  })
})
