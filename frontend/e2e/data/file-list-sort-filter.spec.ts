import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { openHeaderFilter, selectHeaderFilterOption } from '../helpers/colfilter'

/**
 * 数据管理 → 文件列表：表头筛选 + 排序 + 列宽可达性（2026-08-29 需求 4/5/6）。
 * - 产品/格式/标签：表头下拉筛选（服务端参数 product_code/format_type/tag）
 * - 文件名/测试程序：表头 contains 输入（filename__icontains/program_name__icontains）
 * - 排序保留：文件名/上传时间/大小 表头排序（服务端 ordering，默认最新上传在前）
 * - 列宽：窄视口下列保持 min-width + 横向滚动条常显，所有列可达
 *
 * 注意：20 条/页服务端分页——排序/筛选都必须断言请求参数与响应，而非本地行序。
 */

/** 当前可见 section 内文件列表的 API 请求（GET 查询参数在 URL） */
async function waitFilesRequest(page: Page, predicate: (url: string) => boolean) {
  return page.waitForResponse(
    (r) => r.url().includes('/files/') && predicate(r.url()) && r.status() === 200,
    { timeout: 15_000 },
  )
}

/** 从 /files/ API 拉取当前用户全部文件（含分页），返回 { count, firstNewest } */
async function fetchAllFiles(page: Page) {
  return page.evaluate(async () => {
    const token = localStorage.getItem('access_token')
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
    const d = await fetch('/api/v1/files/?page_size=10000', { headers }).then((r) => r.json())
    const list: any[] = Array.isArray(d) ? d : (d.results ?? [])
    return { count: list.length, newest: list[0]?.filename ?? '', createdDesc: list.every(
      (f, i) => i === 0 || new Date(list[i - 1].created_at) >= new Date(f.created_at),
    ) }
  })
}

test.describe('数据管理 → 文件列表排序/筛选', { tag: ['@data'] }, () => {
  test('@p1 默认排序：上传时间倒序（最新在前）且表头显示降序箭头', async ({ page }) => {
    await gotoApp(page, '/data')
    const { createdDesc } = await fetchAllFiles(page)
    expect(createdDesc, '服务端默认应按上传时间倒序').toBe(true)

    // 表格首行 = 最新上传的单文件。并行 worker 同时上传会让「最新」在断言窗口内变化——
    // 收敛轮询：不一致就重取 API 最新值再对（新上传者只会把首行换成更新文件，最终必然匹配）。
    await expect.poll(async () => {
      const { newest } = await fetchAllFiles(page)
      const firstRow = page.locator('.el-table .el-table__row').first()
      const text = await firstRow.textContent()
      return text?.includes(newest.slice(0, 12)) ?? false
    }, { timeout: 15_000 }).toBe(true)

    // 上传时间列表头显示降序箭头（default-sort prop=created_at descending）
    const timeHeader = page.locator('.el-table__header th').filter({ hasText: '上传时间' }).first()
    await expect(timeHeader.locator('.sort-caret.descending').first()).toBeVisible()
  })

  test('@p1 表头排序：点「大小」列排序，请求带 ordering=file_size', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    const sizeHeader = page.locator('.el-table__header th').filter({ hasText: '大小' }).first()
    const respPromise = waitFilesRequest(page, (url) => url.includes('ordering=file_size'))
    await sizeHeader.click()
    const resp = await respPromise
    const body = await resp.json()
    const sizes = (body.results ?? []).map((f: any) => f.file_size ?? 0)
    expect(sizes.length).toBeGreaterThan(0)
    // 首次点击 = 升序：服务端返回应按 file_size 从小到大
    expect([...sizes].sort((a, b) => a - b).join(','), '首次点击应为升序').toBe(sizes.join(','))

    // 再点一次 → 降序，请求带 -file_size
    const respDescPromise = waitFilesRequest(page, (url) => url.includes('ordering=-file_size'))
    await sizeHeader.click()
    const respDesc = await respDescPromise
    const bodyDesc = await respDesc.json()
    const sizesDesc = (bodyDesc.results ?? []).map((f: any) => f.file_size ?? 0)
    // 第二次点击 = 降序：服务端返回应按 file_size 从大到小
    expect([...sizesDesc].sort((a, b) => b - a).join(','), '第二次点击应为降序').toBe(sizesDesc.join(','))
  })

  test('@p2 表头筛选-产品下拉：请求带 product_code，列表只剩该产品', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    // 取任一产品的编码作为筛选值
    const { codes } = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/files/product_codes/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }).then((r) => r.json())
      return { codes: res.product_codes ?? [] }
    })
    test.skip(codes.length === 0, '环境无产品编码，跳过')
    const pick = codes[0]

    await openHeaderFilter(page, 'product')
    const respPromise = waitFilesRequest(page, (url) => url.includes(`product_code=${encodeURIComponent(pick)}`))
    await selectHeaderFilterOption(page, 'product', pick)
    const resp = await respPromise
    const body = await resp.json()
    const files: any[] = body.results ?? []
    expect(files.length).toBeGreaterThan(0)
    for (const f of files) {
      expect(f.product_code).toBe(pick)
    }

    // 清除筛选 → 恢复全量（请求不带 product_code）
    const clearBtn = page.locator('[data-testid="col-filter-clear-product"]')
    await expect(clearBtn).toBeVisible()
    const respAllPromise = waitFilesRequest(page, (url) => !url.includes('product_code='))
    await clearBtn.click()
    await respAllPromise
  })

  test('@p2 表头筛选-格式下拉：请求带 format_type', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    const { formats } = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/files/format_types/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }).then((r) => r.json())
      return { formats: res.format_types ?? [] }
    })
    test.skip(formats.length === 0, '环境无格式数据，跳过')
    const pick = formats[0]

    await openHeaderFilter(page, 'format')
    const respPromise = waitFilesRequest(page, (url) => url.includes(`format_type=${encodeURIComponent(pick)}`))
    await selectHeaderFilterOption(page, 'format', pick)
    const resp = await respPromise
    const body = await resp.json()
    const files: any[] = body.results ?? []
    expect(files.length).toBeGreaterThan(0)
    for (const f of files) {
      expect(f.format_type).toBe(pick)
    }
  })

  test('@p2 表头筛选-文件名输入：请求带 filename__icontains', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    const { sample } = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const d = await fetch('/api/v1/files/?page_size=10000', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }).then((r) => r.json())
      const list: any[] = Array.isArray(d) ? d : (d.results ?? [])
      return { sample: list[0]?.filename?.slice(0, 6) ?? '' }
    })
    test.skip(!sample, '环境无文件，跳过')

    await openHeaderFilter(page, 'filename')
    const respPromise = waitFilesRequest(page, (url) => url.includes(`filename__icontains=${encodeURIComponent(sample)}`))
    // el-input 的 attrs 落在原生 input 上（inheritAttrs:false），testid 即 input 本身
    await page.locator('[data-testid="col-filter-input-filename"]').fill(sample)
    const resp = await respPromise
    const body = await resp.json()
    const files: any[] = body.results ?? []
    expect(files.length).toBeGreaterThan(0)
    for (const f of files) {
      expect(f.filename.toLowerCase()).toContain(sample.toLowerCase())
    }
  })

  test('@p2 表头筛选-测试程序输入：请求带 program_name__icontains', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    const { sample } = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const d = await fetch('/api/v1/files/?page_size=10000', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }).then((r) => r.json())
      const list: any[] = Array.isArray(d) ? d : (d.results ?? [])
      const withProgram = list.find((f: any) => f.program_name)
      return { sample: withProgram?.program_name?.slice(0, 4) ?? '' }
    })
    test.skip(!sample, '环境无程序名，跳过')

    await openHeaderFilter(page, 'program')
    const respPromise = waitFilesRequest(page, (url) => url.includes(`program_name__icontains=${encodeURIComponent(sample)}`))
    await page.locator('[data-testid="col-filter-input-program"]').fill(sample)
    const resp = await respPromise
    const body = await resp.json()
    const files: any[] = body.results ?? []
    expect(files.length).toBeGreaterThan(0)
    for (const f of files) {
      expect((f.program_name || '').toLowerCase()).toContain(sample.toLowerCase())
    }
  })

  test('@p2 表头筛选-标签下拉：请求带 tag，仅含该标签', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    // 给最新一个文件挂唯一标签（API 造数），再按标签筛选
    const tagValue = `e2e_hdr_${Date.now()}`
    const { fileId } = await page.evaluate(async (tv) => {
      const token = localStorage.getItem('access_token')
      const d = await fetch('/api/v1/files/?page_size=10000', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }).then((r) => r.json())
      const list: any[] = Array.isArray(d) ? d : (d.results ?? [])
      const target = list.find((f: any) => f.file_type === 'single')
      if (!target) return { fileId: 0 }
      await fetch(`/api/v1/files/${target.id}/set_tags/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ tags: [...(target.tags ?? []), tv] }),
      })
      return { fileId: target.id }
    }, tagValue)
    test.skip(!fileId, '环境无单文件，跳过')

    // 刷新页面：标签下拉数据源（listTags）在 onMounted 加载，新标签需重建
    await page.reload()
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    await openHeaderFilter(page, 'tag')
    const respPromise = waitFilesRequest(page, (url) => url.includes(`tag=${encodeURIComponent(tagValue)}`))
    await selectHeaderFilterOption(page, 'tag', tagValue)
    const resp = await respPromise
    const body = await resp.json()
    const files: any[] = body.results ?? []
    expect(files.length).toBeGreaterThan(0)
    for (const f of files) {
      expect(Array.isArray(f.tags) ? f.tags : []).toContain(tagValue)
    }
  })

  test('@p2 列宽优化：窄视口下列保持 min-width，横向滚动后所有列可达', async ({ page }) => {
    await page.setViewportSize({ width: 1180, height: 800 })
    await gotoApp(page, '/data')
    await expect(page.locator('.el-table .el-table__row').first()).toBeVisible({ timeout: 15_000 })

    // ① 横向滚动条常显（CSS 覆盖 opacity=1，thumb 始终可见）
    await expect(page.locator('.el-table .el-scrollbar__bar.is-horizontal').first())
      .toHaveCSS('opacity', '1')

    // ② 窄视口下表格内容超出容器（min-width 生效，未被压缩吞掉）
    const bodyWrap = page.locator('.el-table__body-wrapper .el-scrollbar__wrap').first()
    await expect.poll(async () => {
      return bodyWrap.evaluate((el) => (el as HTMLElement).scrollWidth - (el as HTMLElement).clientWidth)
    }).toBeGreaterThan(0)

    // ③ 横向滚动到最右后，「大小」列表头完整进入可视区域（所有列可达）
    await bodyWrap.evaluate((el) => { (el as HTMLElement).scrollLeft = (el as HTMLElement).scrollWidth })
    const sizeHeader = page.locator('.el-table__header th').filter({ hasText: '大小' }).first()
    await expect(sizeHeader).toBeInViewport({ timeout: 5_000 })
  })

  test('@p2 文件名换行：默认开启（设置 filename_wrap 控制，切换后生效）', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.content-section:visible .el-table .el-table__row').first())
      .toBeVisible({ timeout: 15_000 })

    // ① 默认开启：文件名 cell 打换行 class（最多 3 行显示完整名）
    const wrapCells = page.locator('.content-section:visible .file-name-wrap')
    await expect(wrapCells.first()).toBeVisible({ timeout: 10_000 })
    expect(await wrapCells.count()).toBeGreaterThan(0)

    // ② 设置关闭 → 刷新 → 单行截断（换行 class 消失）
    await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      await fetch('/api/v1/auth/settings/', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ filename_wrap: false }),
      })
    })
    await page.reload()
    await expect(page.locator('.content-section:visible .el-table .el-table__row').first())
      .toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.content-section:visible .file-name-wrap')).toHaveCount(0)

    // ③ 恢复默认开启（避免污染其它用例/用户偏好）
    await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      await fetch('/api/v1/auth/settings/', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ filename_wrap: true }),
      })
    })
  })
})
