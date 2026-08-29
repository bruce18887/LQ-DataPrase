/**
 * 批次报表前端聚合工具 —— 阶段过滤时把 phases[] 中各文件的
 * 站点/Bin/UPH 数据按当前阶段临时汇总为批次级结构。
 *
 * 算法与后端 apps/batch_report/aggregation.py 保持一致（纯函数，便于测试）：
 * - aggregateSiteYield → site_pass_data 同构（Site/Yield/Total/PassCount）
 * - aggregateBinSiteTable → { bin_table_data, bin_site_columns } 同构
 * - aggregateUph → UphData 同构（UphCard.vue 消费）
 *
 * 仅当 stageFilter 非空时使用（未过滤时直接用后端批次级数据，避免双源漂移）。
 */

export interface BatchPhaseBin {
  name: string
  value: number
  pct: string
  sites?: Record<string, number>
}

export interface BatchUphSite {
  site: string
  tested: number
  uph: number
}

export interface BatchUph {
  uph: number
  avg_test_time: number
  total_tested: number
  total_time_seconds: number
  source: string
  by_site: BatchUphSite[]
  site_count: number
  warnings: string[]
}

/** phases[] 中聚合所需的子集结构（多余字段不影响）。 */
export interface BatchAggPhase {
  stage: string
  site_total?: Record<string, number>
  site_pass?: Record<string, number>
  bin_info?: BatchPhaseBin[]
  uph?: BatchUph | null
}

export interface SiteYieldRow {
  site: string
  pass: number
  total: number
  yield: number
}

export interface BinSiteTable {
  bin_table_data: Record<string, any>[]
  bin_site_columns: string[]
}

/** 站点排序：数字优先升序，其余按字符串（与后端 _site_sort_key 一致）。 */
function siteSortKey(a: string, b: string): number {
  const na = Number(a)
  const nb = Number(b)
  const fa = Number.isFinite(na)
  const fb = Number.isFinite(nb)
  if (fa && fb) return na - nb
  if (fa) return -1
  if (fb) return 1
  return a < b ? -1 : a > b ? 1 : 0
}

/** Bin 排序：Pass（1/Bin1）强制最前，数字升序，其余按字符串（与后端 _bin_sort_key 一致）。 */
function binSortKey(a: string, b: string): number {
  const isPassA = a === '1' || a === 'Bin1'
  const isPassB = b === '1' || b === 'Bin1'
  if (isPassA !== isPassB) return isPassA ? -1 : 1
  const na = Number(a)
  const nb = Number(b)
  const fa = Number.isFinite(na)
  const fb = Number.isFinite(nb)
  if (fa && fb) return na - nb
  if (fa) return -1
  if (fb) return 1
  return a < b ? -1 : a > b ? 1 : 0
}

/** 格式化原始 Bin 名为 'Bin N'（与后端 _format_bin_label 一致）。 */
function formatBinLabel(name: string): string {
  const n = Number(name)
  return Number.isFinite(n) ? `Bin ${n}` : `Bin ${name}`
}

/**
 * 按阶段汇总 Site 良率（pass/total/yield），与后端 site_pass_data 同构。
 * 仅保留该阶段有数据（total>0）的站点 —— 无数据的站点画 0% 会误导。
 */
export function aggregateSiteYield(
  phases: BatchAggPhase[],
  sortedSites: string[],
): SiteYieldRow[] {
  const agg = new Map<string, { pass: number; total: number }>()
  for (const site of sortedSites) agg.set(site, { pass: 0, total: 0 })

  for (const phase of phases) {
    for (const site of sortedSites) {
      const total = Number(phase.site_total?.[site] ?? 0)
      const pass = Number(phase.site_pass?.[site] ?? 0)
      const cur = agg.get(site)
      if (!cur || (total <= 0 && pass <= 0)) continue
      cur.pass += pass
      cur.total += total
    }
  }

  const rows: SiteYieldRow[] = []
  for (const site of sortedSites) {
    const cur = agg.get(site)!
    if (cur.total <= 0) continue
    rows.push({
      site,
      pass: cur.pass,
      total: cur.total,
      yield: Math.round((cur.pass / cur.total) * 10000) / 100,
    })
  }
  return rows
}

/**
 * 按阶段汇总 Bin × Site 交叉表（含 Total 行），
 * 输出与后端 aggregate_bin_site_table 完全同构。
 */
export function aggregateBinSiteTable(
  phases: BatchAggPhase[],
  sortedSites: string[],
): BinSiteTable {
  const columns = sortedSites.map(String)
  const binSiteCounts = new Map<string, Map<string, number>>()

  for (const phase of phases) {
    for (const binfo of phase.bin_info ?? []) {
      const binName = String(binfo.name ?? '')
      let siteMap = binSiteCounts.get(binName)
      if (!siteMap) {
        siteMap = new Map()
        binSiteCounts.set(binName, siteMap)
      }
      const sites = binfo.sites ?? {}
      for (const [site, count] of Object.entries(sites)) {
        const key = String(site)
        siteMap.set(key, (siteMap.get(key) ?? 0) + Number(count || 0))
      }
    }
  }

  if (binSiteCounts.size === 0 || columns.length === 0) {
    return { bin_table_data: [], bin_site_columns: [] }
  }

  const colTotals = new Map<string, number>(columns.map((c) => [c, 0]))
  let grandTotal = 0
  const binTableData: Record<string, any>[] = []

  for (const binName of [...binSiteCounts.keys()].sort((a, b) => binSortKey(a, b))) {
    const siteMap = binSiteCounts.get(binName)!
    const row: Record<string, any> = { bin: formatBinLabel(binName) }
    let rowTotal = 0
    for (const col of columns) {
      const count = siteMap.get(col) ?? 0
      row[col] = count
      rowTotal += count
      colTotals.set(col, (colTotals.get(col) ?? 0) + count)
    }
    row.all_site = rowTotal
    grandTotal += rowTotal
    binTableData.push(row)
  }

  const totalRow: Record<string, any> = { bin: 'Total' }
  for (const col of columns) totalRow[col] = colTotals.get(col) ?? 0
  totalRow.all_site = grandTotal
  binTableData.push(totalRow)

  return { bin_table_data: binTableData, bin_site_columns: columns }
}

/**
 * 按阶段汇总 UPH（与后端 aggregate_uph 算法一致：从各文件已暴露的
 * total_time_seconds / avg_test_time / by_site 反推串行时间再重算）。
 */
export function aggregateUph(phases: BatchAggPhase[]): BatchUph {
  let totalTested = 0
  let totalTimeSeconds = 0
  let totalSerialSeconds = 0
  let phasesMissing = 0
  const mergedWarnings: string[] = []
  const siteAgg = new Map<string, { tested: number; serial: number }>()

  for (const phase of phases) {
    const uph = phase.uph
    if (!uph) {
      phasesMissing += 1
      continue
    }
    const phTested = Math.trunc(Number(uph.total_tested ?? 0) || 0)
    const phTime = Number(uph.total_time_seconds ?? 0) || 0
    const phAvg = Number(uph.avg_test_time ?? 0) || 0

    for (const w of uph.warnings ?? []) {
      if (!mergedWarnings.includes(w)) mergedWarnings.push(w)
    }

    if (phTested <= 0 || phTime <= 0) {
      phasesMissing += 1
      continue
    }

    totalTested += phTested
    totalTimeSeconds += phTime
    totalSerialSeconds += phAvg * phTested

    for (const site of uph.by_site ?? []) {
      const siteId = String(site.site ?? '')
      const sTested = Math.trunc(Number(site.tested ?? 0) || 0)
      const sUph = Number(site.uph ?? 0) || 0
      if (sTested <= 0) continue
      let entry = siteAgg.get(siteId)
      if (!entry) {
        entry = { tested: 0, serial: 0 }
        siteAgg.set(siteId, entry)
      }
      entry.tested += sTested
      if (sUph > 0) {
        // 该站点串行秒数 = tested * 3600 / uph
        entry.serial += (sTested * 3600.0) / sUph
      }
    }
  }

  if (phasesMissing > 0) {
    mergedWarnings.push(`${phasesMissing} 个文件缺少 UPH 数据，批次 UPH 为部分汇总`)
  }

  if (totalTested === 0 || totalTimeSeconds <= 0) {
    return {
      uph: 0,
      avg_test_time: 0,
      total_tested: 0,
      total_time_seconds: 0,
      source: 'batch',
      by_site: [],
      site_count: 0,
      warnings: mergedWarnings,
    }
  }

  const uphVal = (totalTested / totalTimeSeconds) * 3600.0
  const avgTestTime = totalTested > 0 ? totalSerialSeconds / totalTested : 0

  const bySite: BatchUphSite[] = [...siteAgg.keys()]
    .sort((a, b) => siteSortKey(a, b))
    .map((siteId) => {
      const s = siteAgg.get(siteId)!
      const sUph = s.serial > 0 ? (3600.0 * s.tested) / s.serial : 0
      return { site: siteId, tested: s.tested, uph: Math.round(sUph * 10) / 10 }
    })

  return {
    uph: Math.round(uphVal * 10) / 10,
    avg_test_time: Math.round(avgTestTime * 1000) / 1000,
    total_tested: totalTested,
    total_time_seconds: Math.round(totalTimeSeconds * 10) / 10,
    source: 'batch',
    by_site: bySite,
    site_count: bySite.length,
    warnings: mergedWarnings,
  }
}
