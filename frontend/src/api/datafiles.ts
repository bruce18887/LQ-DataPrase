import api from './index'
import type { DataFile } from '../types'

export interface BatchDirInfo {
  name: string
  path: string
  file_count: number
  total_size: number
  registered: boolean
  files: DataFile[]
  /**
   * 已导入批次的明细后端每批只给前 500 条，这里是**被省略的条数**
   * （0 或缺省 = 明细已全量）。真实总数 = files.length + files_truncated。
   */
  files_truncated?: number
  /** 未注册目录的文件预览（文件名+大小，服务端最多 200 条） */
  preview_files?: Array<{ name: string; size: number }>
}

export interface ListFilesParams {
  page?: number
  /**
   * 每页条数。服务端 `DataFilePagination` 认它（`page_size_query_param`，见
   * `apps/datafiles/views/file_views.py:87-97`）；这里此前漏声明，跨用户只读页
   * 需要显式 20/50/100 三档，补上这个键而不是绕开类型。
   */
  page_size?: number
  search?: string
  product_code?: string
  format_type?: string
  file_type?: string
  ordering?: string
  /** 表头列筛选：文件名 contains（服务端生效，大小写不敏感） */
  filename__icontains?: string
  /** 表头列筛选：测试程序 contains（服务端生效，大小写不敏感） */
  program_name__icontains?: string
  /** 表头列筛选：标签精确匹配（服务端 Python 过滤，大小写不敏感） */
  tag?: string
  /** 上传时间范围筛选（YYYY-MM-DD，服务端按当天边界展开） */
  created_at__gte?: string
  created_at__lte?: string
  /** 文件大小范围筛选（字节） */
  file_size__gte?: number
  file_size__lte?: number
  /**
   * 管理员跨用户只读清单：目标用户 id。后端只在 `action == 'list'` 且具备
   * `data_view_all` 时认它，普通用户带它会 403（`apps/datafiles/views/admin_scope.py`）。
   * 详情/options 不受它影响 —— 放开的口子只有清单这一条。
   */
  owner_id?: number
  /** 列表包含已隐藏（文件管理页「全部」档）；缺省只返回未隐藏 */
  include_hidden?: number
  /** 只返回已隐藏（优先于 include_hidden） */
  hidden_only?: number
  combination_id?: number
  batch_no?: string
}

/** 下拉框用的轻量文件行（/files/options/ 契约：仅标量列，无 stage/data_date/owner） */
export interface FileOption {
  id: number
  filename: string
  file_type: string
  batch_name: string
  sub_batch: string
  format_type: string
  program_name: string
  product_code: string
  row_count: number | null
  col_count: number | null
  file_size: number
  source_mtime: string | null
  created_at: string
  status: string
  combination_id: number | null
  combination_name: string | null
  batch_no: string
}

export interface FileOptionsParams {
  /** 返回上限（后端默认 5000，最大 20000） */
  limit?: number
  /** 兼容旧下拉行为：同时返回解析失败（status='error'）的行 */
  include_error?: number
}

export interface BrowseParams {
  datafile_id: number
  page?: number
  page_size?: number
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
  /** 与 data 行并行：每行 bin!=1 且值恰好等于真规格窗端点的临界列（亮橙） */
  borderline_cells: string[][]
  total: number
  page: number
  page_size: number
  total_pages: number
  /** 当前筛选集（pass/site/filter_model）内的 fail 行数（IRM 下前端无法本地计算） */
  fail_row_count: number
  col_meta: Record<string, BrowseColMeta>
  bin_column: string
  /** 仅 page==1：全文件站点唯一值（未排序，前端排序） */
  site_options?: string[]
  /** 仅 page==1：可作数值分析的列名（右键直方图可用性判定） */
  numeric_columns?: string[]
  /** 仅 page==1：记录级列（系统列）——后端按格式权威下发，前端据此恒显示+前置 */
  system_columns?: string[]
}

/** 仅保留有值的查询参数 */
function cleanParams<T extends object>(params: T): Record<string, string | number> {
  const out: Record<string, string | number> = {}
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') out[k] = v as string | number
  }
  return out
}

export interface UploadOptions {
  combinationId?: number | null
  batchNo?: string
  tags?: string[]
}

export interface AssignCombinationInput {
  fileIds: number[]
  combinationId: number | null
  batchNo?: string | null
}

export interface CombineFilesOptions {
  combinationId?: number | null
  batchNo?: string
}

function appendUploadOptions(formData: FormData, options: UploadOptions) {
  if (options.combinationId != null) formData.append('combination_id', String(options.combinationId))
  if (options.batchNo) formData.append('batch_no', options.batchNo)
  if (options.tags?.length) formData.append('tags', JSON.stringify(options.tags))
}

export const datafilesApi = {
  upload(file: File, onProgress?: (pct: number) => void, options: UploadOptions = {}) {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('last_modified', String(file.lastModified))
    appendUploadOptions(formData, options)
    return api.post('/upload/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (e.total && onProgress) onProgress(Math.round((e.loaded * 100) / e.total))
      },
    })
  },
  uploadMultiple(files: File[], onProgress?: (pct: number) => void, options: UploadOptions = {}) {
    const formData = new FormData()
    for (const f of files) {
      formData.append('files', f)
      // 与 files 同序追加原始修改时间（epoch ms），供后端记录 source_mtime
      formData.append('last_modified', String(f.lastModified))
    }
    appendUploadOptions(formData, options)
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
  /**
   * 当前用户的磁盘占用。fresh=true 绕过后端 30s 分桶缓存：本地做完一次写操作
   * （上传/删除/组合/修复）后要立刻看到新数就带它。
   */
  getFileUsage(fresh = false) {
    return api.get<FileUsage>(
      '/files/usage/',
      fresh ? { params: { fresh: 1 } } : {},
    )
  },
  bulkDelete(ids: number[]) {
    return api.post('/files/bulk_delete/', { ids })
  },
  getProductCodes() {
    return api.get<{ product_codes: string[] }>('/files/product_codes/')
  },
  getFormatTypes() {
    return api.get<{ format_types: string[] }>('/files/format_types/')
  },
  /** 下拉框专用轻量清单：不计算 stage/data_date、不 join owner（默认仅 ready 行） */
  getOptions(params: FileOptionsParams = {}) {
    return api.get<{ results: FileOption[] }>('/files/options/', { params: cleanParams(params) })
  },
  /** 组合/追加多个单文件到批次（服务端物理移动到 batch/<name>/ 并更新记录；批次可已存在） */
  combineFiles(ids: number[], batchName: string, options: CombineFilesOptions = {}) {
    return api.post<{ combined: number; batch_name: string; files: DataFile[] }>(
      '/files/combine/', {
        ids,
        batch_name: batchName,
        ...(options.combinationId !== undefined
          ? { combination_id: options.combinationId }
          : {}),
        ...(options.batchNo ? { batch_no: options.batchNo } : {}),
      },
    )
  },
  assignCombination(input: AssignCombinationInput) {
    return api.post<DataFile[]>('/files/assign_combination/', {
      file_ids: input.fileIds,
      combination_id: input.combinationId,
      ...(input.batchNo !== undefined ? { batch_no: input.batchNo } : {}),
    })
  },
  /** 移出批次：批次文件物理移回 single/ 并恢复 file_type='single' */
  uncombineFiles(ids: number[]) {
    return api.post<{ moved: number; files: DataFile[] }>(
      '/files/uncombine/', { ids },
    )
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
  /** 切换隐藏（软隐藏：只影响选文件候选；PATCH 单字段） */
  setHidden(id: number, hidden: boolean) {
    return api.patch<DataFile>(`/files/${id}/`, { is_hidden: hidden })
  },
  setTags(id: number, tags: string[]) {
    return api.post<{ id: number; tags: string[] }>(`/files/${id}/set_tags/`, { tags })
  },
  listTags(prefix = '') {
    return api.post<{ tags: string[]; managed_tags: string[] }>('/files/list_tags/', { prefix })
  },

  // Data consistency check / repair center
  checkConsistency() {
    return api.get<ConsistencyCheckResult>('/consistency-check/')
  },
  fixConsistency(action: ConsistencyFixAction, keepIds?: number[]) {
    // import/fix may reparse many files — the axios default 30s timeout is
    // too tight for large orphan sets, so those calls get a 120s budget.
    const config = ['delete_orphaned_db', 'delete_orphaned_disk', 'delete_duplicates'].includes(action)
      ? {}
      : { timeout: 120_000 }
    // keep_ids 只在 delete_duplicates 上有意义；undefined 时**不写这个键**，
    // 让「老客户端不传」与服务端「按默认留最早」那条分支保持可区分（T1 钉着）。
    const body = keepIds ? { action, keep_ids: keepIds } : { action }
    return api.post<FixConsistencyResponse>('/consistency-check/', body, config)
  },
}

// ── Consistency check / repair center types ──────────────────────────

export interface OrphanedDbRecord {
  id: number
  filename: string
  batch_name: string
  sub_batch: string
  file_type: 'single' | 'batch'
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

export interface DuplicateGroupFile {
  id: number
  filename: string
  file_size: number
  file_type: 'single' | 'batch'
  batch_name: string
  sub_batch: string
  created_at: string
}

/** 重复文件组：文件名+大小完全相同的文件集合（files 按 id 升序，首条为保留项） */
export interface DuplicateGroup {
  filename: string
  file_size: number
  files: DuplicateGroupFile[]
}

export interface ConsistencyCheckResult {
  orphaned_db_count: number
  orphaned_db: OrphanedDbRecord[]
  orphaned_disk_count: number
  orphaned_disk: OrphanedDiskFile[]
  missing_product_code_count: number
  missing_product_code: MissingProductCodeFile[]
  duplicate_group_count: number
  duplicate_groups: DuplicateGroup[]
}

export type ConsistencyFixAction =
  | 'delete_orphaned_db'
  | 'delete_orphaned_disk'
  | 'import_orphaned_disk'
  | 'fix_product_codes'
  | 'delete_duplicates'

export interface FixConsistencyResponse {
  status: string
  action: ConsistencyFixAction
  deleted_count?: number
  /** 只作用于已展示组时，删完之后还剩几组（服务端删后实测，不是算术值） */
  remaining_groups?: number
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

/** GET /files/usage/ 的返回体：口径全在 apps/datafiles/storage_usage.py。 */
export interface UsageBucket {
  bytes: number
  count: number
}

export interface FileUsage {
  data_dir: string
  /** data 树（`media/data/<username>/`）的表观口径；浮层的分桶行加起来就是它 */
  bytes: number
  /** inode 去重口径（绊线用，界面不显示），同样只覆盖 data 树 */
  unique_bytes: number
  file_count: number
  /**
   * 作业产物树（`media/jobs/<user.id>/`）的表观体积与文件数。与 `bytes` **分开报**：
   * 两棵树的清退机制不同，合成一个数就再也拆不开（口径见 storage_usage.py 模块 docstring）。
   */
  jobs_bytes: number
  jobs_file_count: number
  /** chip 显示的那一个数 = `bytes + jobs_bytes`；服务端的差值恒等式不用它当分母 */
  total_bytes: number
  /** 根下第一段目录名为键（single / batch，散文件为空串）；不含 jobs */
  by_type: Record<string, UsageBucket>
  db_count: number
  db_bytes: number
  db_bytes_in_root: number
  db_outside_root_count: number
  db_outside_root_bytes: number
  mismatch_over_threshold: boolean
  mismatch_diff_bytes: number
  scanned_at: string
}
