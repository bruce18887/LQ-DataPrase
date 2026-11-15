import { test, expect } from '@playwright/test'
import path from 'node:path'
import fs from 'node:fs'
import { ACCOUNTS, DATA_DIR, PRIMARY_SAMPLE_FILE } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { apiGet, apiPost } from '../helpers/apiClient'
import { shellDjango } from '../helpers/djangoShell'
import { openRepairCenter } from '../helpers/repairCenterFlow'

/**
 * 数据修复中心（数据一致性检查升级版）e2e：
 * 孤立磁盘文件导入 / 孤立 DB 记录删除 / 缺失产品名修复（重读文件头）/ 修复后问题消失。
 * 重复项选保留一族（现 5 条）已于 2026-11-15 拆出至 `duplicate-keep.spec.ts`，
 * 其分层说明（「批3a · 第 3 项」）与 DUP 造数细节随该族一起搬到了那份文件。
 *
 * 造数方式：e2e 进程直接写后端 media（与 globalSetup seed 同模式），
 * 通过 API 导入 + Django shell 调整 DB 状态，UI 只做断言驱动。
 * 所有造数统一 REPAIR-E2E-<ts> 批次前缀，afterEach 清理。
 */

// 后端落盘位置跟着进程走：非 slot = `<仓库根>/test/e2e-data`，slot = 该 slot 自己的 data_dir。
// 两处都不再是仓库根 —— 仓库根 media/ 是迁移前的搁浅副本，本轮已把它从测试通路里摘掉。
const ADMIN_BATCH_DIR = path.join(DATA_DIR, 'media', 'data', ACCOUNTS.admin.username, 'batch')

const ts = Date.now()
const BATCH = `REPAIR-E2E-${ts}`
const REPAIR_FILE = `repair_x_${ts}.csv` // 无 B 前缀文件名（用于重读链）

test.describe.serial('数据修复中心', { tag: ['@p2', '@data'] }, () => {
  const orphanDir = path.join(ADMIN_BATCH_DIR, BATCH)

  test.beforeEach(async ({ page }) => {
    await gotoApp(page, '/data')
  })

  test.afterEach(() => {
    // 清理批次目录与 DB 行（导入/修复产生的数据一并清掉）
    fs.rmSync(orphanDir, { recursive: true, force: true })
    try {
      shellDjango(
        `DataFile.objects.filter(owner__username='admin', batch_name='${BATCH}').delete()`,
      )
    } catch {
      // 环境清理失败不阻塞用例
    }
  })

  test('孤立磁盘文件可导入到数据库', async ({ page }) => {
    test.skip(!fs.existsSync(PRIMARY_SAMPLE_FILE), '样例数据缺失，跳过')
    fs.mkdirSync(orphanDir, { recursive: true })
    // 唯一名复制：PRIMARY_SAMPLE_FILE 与 seed 数据同名，直接复制会导致
    // 按文件名查找时命中 seed 的 single 行
    const srcName = `e2e_repair_${ts}_${Math.floor(Math.random() * 1e6)}.csv`
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, path.join(orphanDir, srcName))

    await openRepairCenter(page)
    const card = page.locator('[data-testid="orphaned-disk-card"]')
    await expect(card).toBeVisible({ timeout: 15_000 })
    await expect(card).toContainText(BATCH)
    await expect(card).toContainText(srcName)

    // 卡片外壳（MaintenanceCard）的 scoped 样式确实还在生效：操作栏靠 --bg-2 上色、
    // 12px 内边距、标题行两端对齐。四张卡的这段规则此前各存一份，收拢成一个外壳后
    // 「元素归哪个组件的 scope」是会变的 —— 丢了规则这里 padding 就是 0px、背景透明。
    // 断言用计算样式而非 class 名：class 在但规则没匹配上也会红。
    const footerBox = await card.locator('.card-footer').evaluate((el) => {
      const s = getComputedStyle(el)
      return { pad: s.paddingTop, justify: s.justifyContent, bg: s.backgroundColor }
    })
    expect(footerBox.pad, '操作栏内边距').toBe('12px')
    expect(footerBox.justify, '操作栏左右对齐').toBe('space-between')
    expect(footerBox.bg).not.toBe('rgba(0, 0, 0, 0)')
    await expect(card.locator('.card-header .card-title')).toHaveText('孤立磁盘文件')

    // 双主题（R7）：卡片外壳只认 CSS token，night 下同一批规则必须照样生效。
    // 夹具文件在磁盘上留到 afterEach，reload 后重新检查仍会列出这张卡。
    await page.addInitScript(() => localStorage.setItem('theme', 'night'))
    await page.reload()
    await openRepairCenter(page)
    await expect(card).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'night')
    const nightFooterBox = await card.locator('.card-footer').evaluate((el) => {
      const s = getComputedStyle(el)
      return { pad: s.paddingTop, bg: s.backgroundColor }
    })
    expect(nightFooterBox.pad, 'night: 操作栏内边距').toBe('12px')
    expect(nightFooterBox.bg, 'night: 操作栏仍有底色').not.toBe('rgba(0, 0, 0, 0)')

    await card.locator('.el-checkbox').first().click() // 导入确认
    await card.locator('button').filter({ hasText: '导入到数据库' }).click()
    await expect(page.getByText(/已导入 \d+ 个孤立文件/).first()).toBeVisible({ timeout: 15_000 })
    // 自己的文件不再孤立（轮询 API：不依赖卡片是否因环境文件消失/残留）
    await expect.poll(async () => {
      const { body } = await apiGet(page, '/consistency-check/')
      return (body.orphaned_disk ?? []).map((f: any) => f.filename)
    }, { timeout: 15_000 }).not.toContain(srcName)

    const { body } = await apiGet(page, '/files/?page_size=9999')
    const files: any[] = Array.isArray(body) ? body : (body.results ?? [])
    const row = files.find((f) => f.filename === srcName)
    expect(row, '导入后应存在 DataFile 记录').toBeTruthy()
    expect(row.batch_name).toBe(BATCH)
    expect(row.file_type).toBe('batch')
  })

  test('孤立数据库记录可删除', async ({ page }) => {
    test.skip(!fs.existsSync(PRIMARY_SAMPLE_FILE), '样例数据缺失，跳过')
    fs.mkdirSync(orphanDir, { recursive: true })
    const srcName = `e2e_repair_${ts}_${Math.floor(Math.random() * 1e6)}.csv`
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, path.join(orphanDir, srcName))
    // 先导入注册，再删掉磁盘文件 → 成为孤立 DB 记录
    const imp = await apiPost(page, '/batch-dirs/import/', { dir_name: BATCH })
    expect(imp.status).toBe(201)
    fs.rmSync(orphanDir, { recursive: true, force: true })

    await openRepairCenter(page)
    const card = page.locator('[data-testid="orphaned-db-card"]')
    // delete_orphaned_db 是全量语义——并行 worker 可能已把本行删掉，
    // 卡片因此不出现；此时跳过 UI 操作，统一以「行消失」为终态断言。
    // 先等待检查结果渲染（isVisible 不等待，直接判断会误读为未出现）。
    await expect(card).toBeVisible({ timeout: 10_000 }).catch(() => {})
    if (await card.isVisible()) {
      await card.locator('.el-checkbox').click()
      await card.locator('button').filter({ hasText: '删除孤立记录' }).click()
      await expect(page.getByText(/已删除 .* 条孤立数据库记录/).first()).toBeVisible({ timeout: 15_000 })
    }
    // 本行删除后无残留（轮询 API，不依赖卡片是否消失）
    await expect.poll(async () => {
      const { body } = await apiGet(page, '/files/?page_size=9999')
      const files: any[] = Array.isArray(body) ? body : (body.results ?? [])
      return files.find((f) => f.filename === srcName)
    }, { timeout: 15_000 }).toBeUndefined()
  })

  test('缺失产品名可修复（重读文件头）', async ({ page }) => {
    fs.mkdirSync(orphanDir, { recursive: true })
    fs.writeFileSync(path.join(orphanDir, REPAIR_FILE), [
      '[CTA8280F]',
      'TestFileName,BPD60320.pts',
      '[Data]',
      'col1,col2',
      'mm,mm',
      '0,0',
      '1,1',
      '1,1',
      '1,1',
    ].join('\n'))
    const imp = await apiPost(page, '/batch-dirs/import/', { dir_name: BATCH })
    expect(imp.status).toBe(201)
    // 模拟"注册时未能识别"：清空 product_code 与 program_name
    shellDjango(
      `DataFile.objects.filter(owner__username='admin', filename='${REPAIR_FILE}').update(product_code='', program_name='')`,
    )
    // 环境存在大量缺失行（seed 文件 product_code 全空），GET 列表截断前 50 条、
    // 新行 id 最大排在截断之外——"需重读文件"标志的精确断言由后端单测覆盖
    // （test_fix_reparses_file_for_program_name），此处只断言全量计数与修复生效。
    const before = await apiGet(page, '/consistency-check/')
    expect(before.body.missing_product_code_count).toBeGreaterThan(0)

    await openRepairCenter(page)
    const card = page.locator('[data-testid="missing-product-code-card"]')
    await expect(card).toBeVisible({ timeout: 15_000 })
    await card.locator('.el-checkbox').click()
    await card.locator('button').filter({ hasText: '修复缺失产品名' }).click()
    await expect(page.getByText(/已修复 \d+ 条产品名/).first()).toBeVisible({ timeout: 20_000 })

    const { body } = await apiGet(page, '/files/?page_size=9999')
    const files: any[] = Array.isArray(body) ? body : (body.results ?? [])
    const fixed = files.find((f) => f.filename === REPAIR_FILE)
    expect(fixed?.product_code, '修复后应从文件头重读出产品名').toBe('BPD60320')
  })

  test('修复后本批次问题全部消失', async ({ page }) => {
    // serial 保证前 3 个用例已执行且 afterEach 已清理本批次数据
    await openRepairCenter(page)
    await expect(page.locator('[data-testid="orphaned-db-card"]')).toBeHidden({ timeout: 15_000 })
    const diskCard = page.locator('[data-testid="orphaned-disk-card"]')
    if (await diskCard.isVisible()) {
      await expect(diskCard).not.toContainText(BATCH)
    }
    const missingCard = page.locator('[data-testid="missing-product-code-card"]')
    if (await missingCard.isVisible()) {
      await expect(missingCard).not.toContainText(REPAIR_FILE)
    }
  })
})
