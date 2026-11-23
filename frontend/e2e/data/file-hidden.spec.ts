import { test, expect, type Locator, type Page } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { PRIMARY_SAMPLE_FILE } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { uploadFile, expectUploadSuccess } from '../helpers/upload'
import { filePicker } from '../helpers/params'
import { popperOf } from '../helpers/elplus'

/**
 * 文件隐藏（软隐藏）接线证明：
 *  - 隐藏后文件列表仍可见（徽标 + 「已隐藏」筛选档）
 *  - 隐藏文件仍能从「查看」/行点击打开（同一 viewFile 链路），且「查看数据」标签页显示真实文件名（元数据面不排除隐藏）
 *  - 分析页下拉候选默认排除隐藏文件
 *  - 取消隐藏后候选恢复
 * 组合语义（include_hidden / hidden_only / 分面 / 仪表板回退）由 T1
 * `apps/datafiles/tests_hidden.py` 承载，这里只证明接线不证明组合。
 *
 * 两处下拉一律按**实例级 popper-class** 取选项（`popperOf`），不用全局
 * `.el-select-dropdown:visible`：收起那 ~150ms 的 leave 过渡帧里 `:visible` 与
 * `[aria-hidden="false"]` 一起脏，会挑中正在退出的上一个面板（机理见
 * `helpers/elplus.ts` 的 `popperOf` 注释）。
 */

/**
 * finally 复位：即使中途断言失败，也不把「隐藏行」留给后续 spec。
 *
 * 同 slot 的后继 spec 用 `/files/?page_size=10000` 做基线，而列表缺省排除隐藏
 * ⇒ 残留的隐藏行会让它们的数量差凭空少一条。页面已崩时 evaluate 会 reject，
 * 由调用方 `.catch(() => {})` 吞掉，不能盖住原始错误。
 */
async function unhideByName(page: Page, filename: string) {
  await page.evaluate(async (name: string) => {
    const token = localStorage.getItem('access_token')
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (token) headers.Authorization = `Bearer ${token}`
    const d = await fetch(
      `/api/v1/files/?page_size=100&include_hidden=1&search=${encodeURIComponent(name)}`,
      { headers },
    ).then((r) => r.json())
    const list: any[] = Array.isArray(d) ? d : (d.results ?? [])
    for (const f of list) {
      if (f.filename === name && f.is_hidden) {
        await fetch(`/api/v1/files/${f.id}/`, {
          method: 'PATCH',
          headers,
          body: JSON.stringify({ is_hidden: false }),
        })
      }
    }
  }, filename)
}

/**
 * 夜间置灰回归哨兵：隐藏行的 `.size-badge` 在 light / night 两套主题下都必须
 * 落到 `--text-2`（Task 4 的永久护栏，夜间那条覆盖曾被删掉）。
 *
 * token 的 computed 值用临时探针 span 现场解析，不把 rgb 字面量写死；
 * 读完恢复原主题，不把用例自己的主题改动留给后续步骤。
 */
async function expectHiddenRowGray(page: Page, row: Locator) {
  const badge = row.locator('.size-badge')
  await expect(badge).toBeVisible()
  const original = await page.evaluate(
    () => document.documentElement.getAttribute('data-theme') ?? 'light',
  )
  for (const theme of ['light', 'night'] as const) {
    const { actual, expected } = await badge.evaluate((el, t: 'light' | 'night') => {
      document.documentElement.setAttribute('data-theme', t)
      const probe = document.createElement('span')
      probe.style.color = 'var(--text-2)'
      document.body.appendChild(probe)
      const expected = getComputedStyle(probe).color
      probe.remove()
      return { actual: getComputedStyle(el).color, expected }
    }, theme)
    expect(actual, `${theme}: 隐藏行 size 单元格应为 --text-2`).toBe(expected)
  }
  await page.evaluate((t: string) => document.documentElement.setAttribute('data-theme', t), original)
}

test.describe('文件隐藏（软隐藏）', { tag: ['@p1', '@data'] }, () => {
  test('隐藏：仅文件列表可见；分析页下拉排除；取消隐藏后恢复', async ({ page }) => {
    // 9MB 样例上传 + 解析，随后两次整页重进（/data ↔ /analysis）
    test.setTimeout(120_000)

    await gotoApp(page, '/data')

    const name = `e2e_hidden_${Date.now()}.csv`
    const tmpPath = path.join(os.tmpdir(), name)
    fs.copyFileSync(PRIMARY_SAMPLE_FILE, tmpPath)

    try {
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, tmpPath)
      await expectUploadSuccess(page)

      const row = page.locator('.content-section:visible .el-table .el-table__row')
        .filter({ hasText: name })
      await expect(row).toHaveCount(1, { timeout: 15_000 })

      // 隐藏：行保留 + 徽标
      await row.locator('button').filter({ hasText: '隐藏' }).click()
      await expect(row).toContainText('已隐藏', { timeout: 10_000 })

      // 隐藏状态筛选：未隐藏档看不到，已隐藏档能看到。选项按本下拉自己的 popper 取
      // （`popper-class="dp-hidden-filter-popper"`）。
      const filter = page.getByTestId('hidden-filter')
      const filterOptions = popperOf(page, 'dp-hidden-filter-popper').locator('.el-select-dropdown__item')
      await filter.click()
      await filterOptions.filter({ hasText: '未隐藏' }).click()
      await expect(row).toHaveCount(0, { timeout: 10_000 })

      await filter.click()
      await filterOptions.filter({ hasText: '已隐藏' }).click()
      await expect(row).toHaveCount(1, { timeout: 10_000 })

      // 夜间置灰哨兵（两套主题各一遍）
      await expectHiddenRowGray(page, row)

      // 分析页下拉：默认排除隐藏
      await gotoApp(page, '/analysis')
      const picker = filePicker(page, 'single')
      await expect(picker).toBeVisible({ timeout: 15_000 })
      // 先等候选列表落定（自动选中的文件标签来自 /files/options/ 的 options），
      // 否则「无匹配文件」可能只是候选还没到，断言等于没牙
      await expect(picker).toContainText('.csv', { timeout: 15_000 })
      await picker.click()
      await picker.locator('input').first().fill(name)
      const pickerPopper = popperOf(page, 'dp-file-picker-single')
      await expect(pickerPopper.locator('.el-select-dropdown__empty'))
        .toHaveText('无匹配文件', { timeout: 10_000 })
      await page.keyboard.press('Escape')

      // 回文件列表取消隐藏
      await gotoApp(page, '/data')
      const row2 = page.locator('.content-section:visible .el-table .el-table__row')
        .filter({ hasText: name })
      await expect(row2).toContainText('已隐藏', { timeout: 15_000 })

      // 元数据护栏（终审 Important #1）：隐藏后重新进入 /data 会重拉全量列表
      // （`include_hidden=1`），此时打开隐藏文件，「查看数据」标签页必须显示真实文件名。
      // 必须等这次重拉完成再断言 —— 隐藏前的旧快照里该文件仍是未隐藏，拿它做判据
      // 无论 `include_hidden` 在不在都绿（2026-11-22 lessons 第 7 条同形）。
      await row2.locator('button').filter({ hasText: '查看' }).click()
      await expect(page.locator('.tab-btn.active')).toContainText('查看数据')
      await expect(page.locator('.view-file-tabs')).toContainText(name)
      await page.locator('.tab-btn').filter({ hasText: '文件列表' }).click()
      // 切回列表后行仍处隐藏态，接着走取消隐藏
      await expect(row2).toContainText('已隐藏')

      await row2.locator('button').filter({ hasText: '取消隐藏' }).click()
      await expect(row2).not.toContainText('已隐藏', { timeout: 10_000 })

      // 分析页下拉恢复
      await gotoApp(page, '/analysis')
      const picker2 = filePicker(page, 'single')
      await expect(picker2).toBeVisible({ timeout: 15_000 })
      await expect(picker2).toContainText('.csv', { timeout: 15_000 })
      await picker2.click()
      await picker2.locator('input').first().fill(name)
      await expect(
        popperOf(page, 'dp-file-picker-single').locator('.el-select-dropdown__item').first(),
      ).toContainText(name, { timeout: 10_000 })
      await page.keyboard.press('Escape')
    } finally {
      // 失败也要复位隐藏标记（页面已崩则吞掉），再删本地临时文件
      await unhideByName(page, name).catch(() => {})
      fs.rmSync(tmpPath, { force: true })
    }
  })
})
