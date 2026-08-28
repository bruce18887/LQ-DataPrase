import type { ComputedRef } from 'vue'

/** 批次分组模型（未注册目录除外） */
export interface BatchGroup {
  name: string
  files: any[]
  subBatchNames: string[]
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
