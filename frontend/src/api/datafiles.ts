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

/** 仅保留有值的查询参数 */
function cleanParams(params: ListFilesParams): Record<string, string | number> {
  const out: Record<string, string | number> = {}
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') out[k] = v
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
  browse(params: { page?: number; search?: string; passfail?: string }) {
    return api.get('/browse/', { params })
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

  // File tags
  setTags(id: number, tags: string[]) {
    return api.post<{ id: number; tags: string[] }>(`/files/${id}/set_tags/`, { tags })
  },
  listTags(prefix = '') {
    return api.post<{ tags: string[] }>('/files/list_tags/', { prefix })
  },

  // Data consistency check
  checkConsistency() {
    return api.get<{
      orphaned_db_count: number
      orphaned_disk_count: number
      orphaned_db: Array<{ id: number; filename: string; batch_name: string; file_path: string }>
      orphaned_disk: string[]
    }>('/consistency-check/')
  },
  fixConsistency(action: 'delete_orphaned_db' | 'delete_orphaned_disk') {
    return api.post<{ status: string; action: string; deleted_count: number }>('/consistency-check/', { action })
  },
}
