import api from './index'
import type { DataFile } from '../types'

export interface BatchDirInfo {
  name: string
  path: string
  file_count: number
  total_size: number
  registered: boolean
  files: DataFile[]
}

export interface ListFilesParams {
  page?: number
  search?: string
  product_code?: string
  format_type?: string
  file_type?: string
  ordering?: string
}

export interface BrowseParams {
  datafile_id: number
  page?: number
  page_size?: number
  search?: string
  pass_filter?: string
  site_filter?: string
  /** ag-grid sortModel JSON 字符串（IRM 服务端排序） */
  sort_model?: string
  /** ag-grid filterModel JSON 字符串（IRM 服务端列过滤） */
  filter_model?: string
}

export interface BrowseColMeta {
  unit: string
  min: string
  max: string
}

export interface BrowseResponse {
  headers: string[]
  /** 行值数组（与 headers 对齐；性能优化：records 对象数组 → values 行值数组） */
  data: unknown[][]
  /** 与 data 行并行：每行的 fail 列名列表（原生数组，pass 行为 []） */
  fail_cells: string[][]
  total: number
  page: number
  page_size: number
  total_pages: number
  /** 当前筛选集（search/pass/site）内的 fail 行数（IRM 下前端无法本地计算） */
  fail_row_count: number
  col_meta: Record<string, BrowseColMeta>
  bin_column: string
  /** 仅 page==1：全文件站点唯一值（未排序，前端排序） */
  site_options?: string[]
  /** 仅 page==1：可作数值分析的列名（右键直方图可用性判定） */
  numeric_columns?: string[]
}

/** 仅保留有值的查询参数 */
function cleanParams<T extends object>(params: T): Record<string, string | number> {
  const out: Record<string, string | number> = {}
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') out[k] = v as string | number
  }
  return out
}

export const datafilesApi = {
  upload(file: File, onProgress?: (pct: number) => void) {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('last_modified', String(file.lastModified))
    return api.post('/upload/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (e.total && onProgress) onProgress(Math.round((e.loaded * 100) / e.total))
      },
    })
  },
  uploadMultiple(files: File[], onProgress?: (pct: number) => void) {
    const formData = new FormData()
    for (const f of files) {
      formData.append('files', f)
      // 与 files 同序追加原始修改时间（epoch ms），供后端记录 source_mtime
      formData.append('last_modified', String(f.lastModified))
    }
    return api.post('/upload/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (e.total && onProgress) onProgress(Math.round((e.loaded * 100) / e.total))
      },
    })
  },
  list() {
    return api.get('/files/')
  },
  listFiles(params: ListFilesParams = {}) {
    return api.get('/files/', { params: cleanParams(params) })
  },
  bulkDelete(ids: number[]) {
    return api.post('/files/bulk_delete/', { ids })
  },
  getProductCodes() {
    return api.get<{ product_codes: string[] }>('/files/product_codes/')
  },
  activate(id: number) {
    return api.put(`/activate/${id}/`)
  },
  remove(id: number) {
    return api.delete(`/files/${id}/`)
  },
  browse(params: BrowseParams) {
    return api.get<BrowseResponse>('/browse/', { params: cleanParams(params) })
  },
  history() {
    return api.get('/history/')
  },

  // Batch directory management
  listBatchDirs() {
    return api.get<BatchDirInfo[]>('/batch-dirs/')
  },
  importBatchDir(dirName: string) {
    return api.post('/batch-dirs/import/', { dir_name: dirName })
  },
  deleteBatchDir(dirName: string) {
    return api.delete(`/batch-dirs/${encodeURIComponent(dirName)}/`)
  },
  deleteSubBatch(batchName: string, subBatchName: string) {
    return api.delete(`/batch-dirs/${encodeURIComponent(batchName)}/sub/${encodeURIComponent(subBatchName)}/`)
  },

  // File tags
  setTags(id: number, tags: string[]) {
    return api.post<{ id: number; tags: string[] }>(`/files/${id}/set_tags/`, { tags })
  },
  listTags(prefix = '') {
    return api.post<{ tags: string[] }>('/files/list_tags/', { prefix })
  },

  // Data consistency check / repair center
  checkConsistency() {
    return api.get<ConsistencyCheckResult>('/consistency-check/')
  },
  fixConsistency(action: ConsistencyFixAction) {
    // import/fix may reparse many files — the axios default 30s timeout is
    // too tight for large orphan sets, so those calls get a 120s budget.
    const config = action === 'delete_orphaned_db' || action === 'delete_orphaned_disk'
      ? {}
      : { timeout: 120_000 }
    return api.post<FixConsistencyResponse>('/consistency-check/', { action }, config)
  },
}

// ── Consistency check / repair center types ──────────────────────────

export interface OrphanedDbRecord {
  id: number
  filename: string
  batch_name: string
  sub_batch: string
  file_path: string
}

export interface OrphanedDiskFile {
  path: string
  filename: string
  batch_name: string
  sub_batch: string
}

export interface MissingProductCodeFile {
  id: number
  filename: string
  batch_name: string
  sub_batch: string
  file_type: 'single' | 'batch'
  preview_code: string
  reparse_needed: boolean
  file_missing: boolean
}

export interface ConsistencyCheckResult {
  orphaned_db_count: number
  orphaned_db: OrphanedDbRecord[]
  orphaned_disk_count: number
  orphaned_disk: OrphanedDiskFile[]
  missing_product_code_count: number
  missing_product_code: MissingProductCodeFile[]
}

export type ConsistencyFixAction =
  | 'delete_orphaned_db'
  | 'delete_orphaned_disk'
  | 'import_orphaned_disk'
  | 'fix_product_codes'

export interface FixConsistencyResponse {
  status: string
  action: ConsistencyFixAction
  deleted_count?: number
  imported_count?: number
  skipped_count?: number
  fixed_count?: number
  still_missing_count?: number
  results?: Array<{
    id: number
    filename: string
    product_code: string
    status: 'fixed' | 'still_missing'
    reason: '' | 'no_match' | 'file_missing'
  }>
}
