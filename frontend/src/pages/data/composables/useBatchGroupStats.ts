import type { ComputedRef } from 'vue'

/** 批次分组模型（未注册目录除外） */
export interface BatchGroup {
  name: string
  files: any[]
  subBatchNames: string[]
  /**
   * 后端 `/batch-dirs/` 每批 `files` 封顶 500，这里记**被省略的条数**
   * （`files_truncated`，缺省/0 = 明细已全量）。省略行的 file_size/row_count 后端
   * 没下发，所以只有**条数**能补成真实总数，大小/行数仍只覆盖已列出的明细。
   */
  truncated?: number
}

export interface BatchStats {
  totalSize: number
  totalRows: number
  formats: string[]
  products: string[]
  stages: string[]
}

/** 分组聚合：总大小/总行数/格式/产品/阶段（阶段分布取前 3，页面卡片堆不爆） */
export function groupStats(group: BatchGroup): BatchStats {
  let totalSize = 0
  let totalRows = 0
  const formats = new Set<string>()
  const products = new Set<string>()
  const stages = new Set<string>()
  for (const f of group.files) {
    totalSize += Number(f.file_size) || 0
    totalRows += Number(f.row_count) || 0
    if (f.format_type) formats.add(f.format_type)
    if (f.product_code) products.add(f.product_code)
    if (f.stage) stages.add(f.stage as string)
  }
  return {
    totalSize,
    totalRows,
    formats: [...formats],
    products: [...products].slice(0, 4),
    stages: [...stages].slice(0, 3),
  }
}

export function groupFilesBySub(group: BatchGroup, sub: string) {
  return group.files.filter((f) => (f.sub_batch || '') === sub)
}

/** 按名称关键字过滤批次分组（大小写不敏感） */
export function filterBatchGroups(groups: ComputedRef<BatchGroup[]>, keyword: string): BatchGroup[] {
  const kw = keyword.trim().toLowerCase()
  if (!kw) return groups.value
  return groups.value.filter((g) => g.name.toLowerCase().includes(kw))
}

/** 批次真实文件数 = 已列出的明细 + 后端省略的条数 */
export function groupFileCount(group: BatchGroup): number {
  return group.files.length + (group.truncated || 0)
}

/** 跨批次求和（汇总条与 tab 角标用同一口径，别各算各的） */
export function sumFileCount(groups: BatchGroup[]): number {
  return groups.reduce((acc, g) => acc + groupFileCount(g), 0)
}

/** 明细被截断时的行内提示；未截断返回空串（模板据此不渲染） */
export function groupFilesCapHint(group: BatchGroup): string {
  const omitted = group.truncated || 0
  if (omitted <= 0) return ''
  return `共 ${groupFileCount(group)} 个文件，明细仅列出前 ${group.files.length} 个，`
    + `另有 ${omitted} 个未列出`
}
