import fs from 'node:fs'
import path from 'node:path'
import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { startSftpServer, type SftpTestServer } from '../helpers/sftpServer'
import { ensureDisconnected, manualConnect, waitTableReady } from '../helpers/sftpSearchFlow'

/**
 * SFTP 目录列表的封顶与「加载更多」（B1 前端落地）。
 *
 * 后端 `list_files` 一次最多 500 条（`LIST_LIMIT_DEFAULT`），响应带 `total`/`truncated`。
 * 这条判据要同时拦住三种回归：
 * ① 前端把「已加载条数」当「目录总条数」报给用户（徽章那句）；
 * ② 「加载更多」没把游标传给后端、反复要同一页 ⇒ 用**集合**而不是行数来判：
 *   第二页必须补上第一页缺的那一个名字，且合并后 501 个名字互不重复；
 * ③ 翻页时前端按本地重排当游标 ⇒ 同样被「不重不漏」抓住。
 *
 * 具体哪个文件落哪一页取决于后端排序（默认 mtime desc，501 个文件同秒写出时靠什么兜底
 * 不在前端契约里），所以不指名某个文件，只取「第一页缺集」再验证第二页正好补齐它。
 *
 * 根目录是反向对照：没截断就不该出现分页徽章和按钮。连接后会先跳上次访问目录
 * （`last_visit`，设计行为），所以判根目录前要先点面包屑 Home 回根 —— 与
 * `connectAndOpenSearch` 同一套走法。
 *
 * 跑法：`node scripts/e2e_pool.mjs --slots=1 -- e2e/sftp/list-cap-load-more.spec.ts`
 */

const PAGE_SIZE = 500
const TOTAL = PAGE_SIZE + 1

const ROWS = '.file-table .el-table__body-wrapper tr.el-table__row'
const NAMES = '.file-table .el-table__row .file-name'
const PAGING_BADGE = '[data-sftp-list-paging]'
const LOAD_MORE = '[data-sftp-load-more]'
const HOME_CRUMB = '.toolbar-card .el-breadcrumb__item'

/** 远端 `many/` 的全部条目名（与 writeManyTree 一一对应） */
const ALL_NAMES = Array.from({ length: TOTAL }, (_, i) => `F${String(i).padStart(4, '0')}.csv`)

function writeManyTree(root: string) {
  const dir = path.join(root, 'many')
  fs.mkdirSync(dir, { recursive: true })
  for (const name of ALL_NAMES) fs.writeFileSync(path.join(dir, name), 'a,b\n1,2\n')
}

async function loadedNames(page: Page): Promise<string[]> {
  return page.locator(NAMES).allInnerTexts()
}

test.describe('@p2 SFTP 目录分页封顶', { tag: ['@p2', '@sftp'] }, () => {
  let server: SftpTestServer | undefined

  test.beforeAll(async () => {
    server = await startSftpServer()
    writeManyTree(server.root)
  })

  test.afterAll(() => { server?.stop() })

  test('满目录首页封顶 500 并如实报进度，加载更多补齐缺的那一项', async ({ page }) => {
    test.setTimeout(180_000)
    await gotoApp(page, '/sftp')
    await ensureDisconnected(page)
    await manualConnect(page, server!)
    await page.waitForTimeout(500)                 // 让「跳到上次访问目录」先落地
    await page.locator(HOME_CRUMB).first().click() // Home 回根
    await waitTableReady(page)

    // 反向对照：根目录只有几个条目，没截断就不该有任何分页控件
    await expect(page.locator(PAGING_BADGE)).toHaveCount(0)
    await expect(page.locator(LOAD_MORE)).toHaveCount(0)

    await page.locator('.file-name', { hasText: /^many$/ }).first().click()
    await expect(page.locator(ROWS)).toHaveCount(PAGE_SIZE, { timeout: 60_000 })
    await expect(page.locator(PAGING_BADGE)).toContainText(`已加载 ${PAGE_SIZE} / ${TOTAL} 项`)

    const firstPage = await loadedNames(page)
    expect(firstPage).toHaveLength(PAGE_SIZE)
    const missing = ALL_NAMES.filter((n) => !firstPage.includes(n))
    expect(missing).toHaveLength(1)

    await page.locator(LOAD_MORE).click()
    await expect(page.locator(ROWS)).toHaveCount(TOTAL, { timeout: 60_000 })
    const all = await loadedNames(page)
    expect(all).toHaveLength(TOTAL)
    expect(new Set(all).size).toBe(TOTAL)          // 两页拼接不重复
    expect(all).toContain(missing[0])              // 第一页缺的那一项确实被补上

    // 取完就不该再挂着进度徽章和按钮
    await expect(page.locator(PAGING_BADGE)).toHaveCount(0)
    await expect(page.locator(LOAD_MORE)).toHaveCount(0)
  })
})
