/**
 * FileSelect 的过滤 / 排序 / 置顶 / 富信息行纯逻辑。
 *
 * 从 `FileSelect.vue` 抽出，供组件与 T2 单测共同使用：组件只负责模板与事件，
 * 这里不含任何 Vue 响应式依赖，可独立验证。候选规模上限 5000/9999 条，
 * 因此排序与匹配保持 O(n) / O(n log n)，不做逐项正则编译。
 */
import type { DataFile } from '../../types'
import { formatSize, formatTime } from '../../utils/format'

/** el-select-v2 的 option 形状：value/label 供下拉，file 供行 slot 渲染富信息 */
export interface FileSelectOption {
  value: number
  label: string
  file: DataFile
}

/** 查询词归一化：去首尾空白 + 小写。matchFile / fileRank 假定入参已经归一化。 */
export function normalizeQuery(raw: string): string {
  return raw.trim().toLowerCase()
}

/** 匹配：文件名、程序、批次、组合名或批次号任一包含（对齐后端 search_fields） */
export function matchFile(
  f: Pick<DataFile, 'filename' | 'program_name' | 'batch_name' | 'combination_name' | 'batch_no'>,
  query: string,
): boolean {
  if (!query) return true
  return [
    f.filename,
    f.program_name,
    f.batch_name,
    f.combination_name,
    f.batch_no,
  ].some((value) => (value ?? '').toLowerCase().includes(query))
}

/** 排序权重：0=filename 前缀 > 1=filename 包含 > 2=其它字段命中 */
export function fileRank(f: Pick<DataFile, 'filename'>, query: string): number {
  const name = (f.filename ?? '').toLowerCase()
  if (name.startsWith(query)) return 0
  if (name.includes(query)) return 1
  return 2
}

/**
 * 排序：无 query 保持 files 原序；有 query 按权重 + localeCompare 平局决胜。
 * 已选按 pinnedOrder（选中顺序）置顶，其余项保持排序结果且不重复。
 */
export function sortFiles(
  files: DataFile[],
  query: string,
  pinnedOrder: number[],
): DataFile[] {
  const ranked = query
    ? [...files].sort((a, b) => {
        const r = fileRank(a, query) - fileRank(b, query)
        return r !== 0 ? r : a.filename.localeCompare(b.filename)
      })
    : files
  if (!pinnedOrder.length) return ranked
  const pinnedSet = new Set(pinnedOrder)
  const pinned = pinnedOrder
    .map((id) => ranked.find((f) => f.id === id))
    .filter((f): f is DataFile => Boolean(f))
  const rest = ranked.filter((f) => !pinnedSet.has(f.id))
  return [...pinned, ...rest]
}

/** 排序后的下拉选项：value=id，label=filename，file 原样带出 */
export function buildFileOptions(
  files: DataFile[],
  query: string,
  pinnedOrder: number[],
): FileSelectOption[] {
  return sortFiles(files, query, pinnedOrder).map((f) => ({
    value: f.id,
    label: f.filename ?? '',
    file: f,
  }))
}

/** 富信息行：program · 组合 · format · 批次号 · N 行 · 大小 · 上传时间（空值跳过） */
export function metaText(f: DataFile): string {
  return [
    f.program_name,
    f.combination_name,
    f.format_type,
    f.batch_no,
    `${f.row_count ?? 0} 行`,
    f.file_size ? formatSize(f.file_size) : '',
    f.created_at ? formatTime(f.created_at) : '',
  ]
    .filter(Boolean)
    .join(' · ')
}
