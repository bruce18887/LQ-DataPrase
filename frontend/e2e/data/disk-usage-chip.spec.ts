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
 */

const CHIP = '.toolbar-left [data-testid="disk-usage-chip"]'
const USAGE_ROUTE = '**/api/v1/files/usage/**'

/** 浏览器里读一次端点（与 repair-center.spec.ts:36 同一种拿法）。 */
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
 * 不是为了省一次比对，而是为了让「组件偷偷读错字段」（bytes ↔ unique_bytes、
 * file_count ↔ db_count）这条路必须红——复用 src 里的同一个函数就只会证明同一条
 * 代码等于自己。
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

test.describe('磁盘占用 chip', { tag: ['@p2', '@data'] }, () => {
  test('chip 文案与端点返回体逐字一致（透传捕获，不靠再猜一次缓存桶）', async ({ page }) => {
    // 用 route 透传把 app 自己那一次读取的响应体留下来 —— 不能再 apiGet 一次去比：
    // 后端缓存是按 30s 分桶的，两次读取跨桶就会给出不同的 scanned_at/数值。
    let captured: any = null
    await page.route(USAGE_ROUTE, async (route) => {
      const response = await route.fetch()
      const json = await response.json()
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
    await expect(chip).toHaveText(`磁盘占用 ${bytesText(captured.bytes)}`)
    await expect(chip).not.toContainText('个文件')
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
    // 列表必须照常（占用是附赠信息，不许连累主功能）
    await expect(page.locator('.list-toolbar .section-count').first()).toBeVisible({ timeout: 20_000 })
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
    // 取 2 MiB ≈ 步长的 20 倍，跨档余量足够；值仍是 1/2 两个短整数 ⇒ unique 值集不随行数膨胀
    // （`files/options/` 的大小跟着 unique 值走，不跟着行数走，别拿长字符串凑体积）。
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
    await page.route(USAGE_ROUTE, async (route) => {
      const response = await route.fetch()
      const json = await response.json()
      captured = json
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
    const total = await popper.locator('.el-descriptions__cell').allInnerTexts()
    const joined = total.join(' ')
    for (const key of Object.keys(captured.by_type ?? {})) {
      const label = key === 'single' ? '单文件' : key === 'batch' ? '批次' : key
      expect(joined, `浮层里必须有 ${key} 这一桶`).toContain(label)
    }
    // ⚠ 这条原先断的是 `String(captured.file_count)`（整棵树总数）。Task 6c 之后 chip 只显体积、
    // 浮层里给的是**每桶**的计数，总数不再以任何形式出现（两桶时它根本不在文本里 ⇒ 假红），
    // 所以改成按桶断计数串 —— 判据跟着文案分工走，不是跟着旧断言的字面走。
    for (const [key, bucket] of Object.entries<any>(captured.by_type ?? {})) {
      const countText = `${bucket.count.toLocaleString()} 个文件`
      expect(joined, `浮层里必须有 ${key} 这一桶的「${countText}」`).toContain(countText)
      expect(joined, `浮层里必须有 ${key} 这一桶的体积`).toContain(bytesText(bucket.bytes))
    }
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
    const paths = [0, 1, 2].map((i) => {
      const p = path.join(os.tmpdir(), `e2e_usage_burst_${stamp}_${i}.csv`)
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
      await first
      // 等合并窗口**彻底收干**再计数：常数是量过的那道闸（USAGE_TRAIL_MS=800）的 2 倍 + 余量，
      // 不是拍脑袋。数早了会把「trailing 还没发」当成 ≤2 通过 —— 那是假绿。
      await page.waitForTimeout(2000)
      expect(fresh.length, 'leading 至少要有一次').toBeGreaterThan(0)
      // 写成 ≤2 而不是 ==2：三个响应若恰好被 Vue 合到同一 tick，只有 leading 一次也合规。
      expect(fresh.length, 'K 连发不许变成 K 次全盘扫描').toBeLessThanOrEqual(2)
    } finally {
      await deleteFilesByNameQuiet(page, 'e2e_usage_burst_')
      for (const p of paths) cleanupQuiet(p)
    }
  })
})
