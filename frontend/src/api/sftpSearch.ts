/**
 * SFTP 搜索 API 层：请求体契约 + SSE 事件类型 + 预设 CRUD（计划 Task 13 / spec §3.2、§3.8、§3.10）。
 *
 * **两个事实来源，都不是本文件**：
 * - 请求侧 27 个键名 = `apps/sftp/search/contracts.py` 的 `_KNOWN_KEYS`。后端对未知键
 *   一律 400（不静默忽略），所以这里多一个键、少一个键、或改一个下划线，用户点「搜索」
 *   就直接吃一句报错。对齐由 `tasks/_sftp_search_keycheck.py` 双向核对（不入库）。
 * - 事件侧 `kind` 与字段 = `apps/sftp/search/events.py`（码表）+ `runner.py`（生产者）。
 *   spec §3.8 是二手描述，它漏了 `done.cancelled` / `done.timed_out`，也把
 *   `stage.candidates` 说成恒为数字（grep 档实际发 `null`，见 runner.py:376）——
 *   本文件按**实际产出**对齐，不按 spec 对齐。
 *
 * 流式走共享 `postSse`（Task 12），不走 axios：全局 30s 超时会掐断长跑的搜索。
 */
import api from './index'
import { postSse } from '../utils/ssePost'

// ------------------------------------------------------------------ 请求契约

export type SearchMode = 'name' | 'content' | 'column'
export type SearchMatching = 'substring' | 'whole_word' | 'fuzzy'
export type SearchDepth = 'self' | 'children' | 'all' | 'custom'
export type SearchStage = 'listing' | 'scanning' | 'done'
export type SearchEngine = 'client' | 'grep'

/**
 * 搜索请求体。除 `roots` 与 `mode` 外全部可选——缺省与钳位由后端 `parse_spec` 负责，
 * 前端再抄一份默认值就是第三处漂移（表单的初始值在 `SearchCriteria` 里，那是 UI 决定）。
 * 键名与 `_KNOWN_KEYS` 逐字一致，不要「顺手」写成 camelCase。
 */
export interface SearchSpec {
  roots: string[]
  mode: SearchMode
  depth?: SearchDepth
  max_depth?: number | null
  prune_dirs?: string[]
  name_pattern?: string | null
  modified_after?: string | null
  modified_before?: string | null
  min_size?: number | null
  max_size?: number | null
  data_files_only?: boolean
  term?: string
  column_name?: string
  column_rows?: number
  matching?: SearchMatching
  case_sensitive?: boolean
  first_hit_per_file?: boolean
  matches_per_file?: number
  one_per_folder?: boolean
  workers?: number
  allow_server_grep?: boolean
  stop_after_listing?: boolean
  max_entries?: number
  max_candidates?: number
  max_matches?: number
  max_scan_bytes?: number
  timeout?: number
}

// ------------------------------------------------------------------ 事件契约

export interface CandidateItem {
  path: string
  name: string
  size: number
  /** epoch 秒（paramiko `st_mtime` 原值，前端自行格式化） */
  mtime: number
}

export interface MatchItem extends CandidateItem {
  line?: number
  snippet?: string
  /** mode=content 且客户端引擎：该文件的多次命中（`line`/`snippet` 是第一条） */
  hits?: { line: number; snippet: string }[]
  test_file?: string
  start_time?: string
  pts_modify_time?: string
  /** mode=column */
  values?: string[]
  column_name?: string
}

export interface HelloEvent {
  kind: 'hello'
  engine: SearchEngine
  engine_reason: string
  workers_actual: number
  roots: string[]
}

export interface StageEvent {
  kind: 'stage'
  stage: SearchStage
  /** grep 档没有候选阶段，实际发 `null`（runner.py `_run_grep`） */
  candidates: number | null
  matches: number
}

export interface CandidatesEvent {
  kind: 'candidates'
  /** 批合成帧：200 项或 200ms 攒一批，所以一帧可能几百项，也可能只有一项收尾 */
  items: CandidateItem[]
  total_so_far: number
}

export interface MatchEvent {
  kind: 'match'
  items: MatchItem[]
}

export interface ProgressEvent {
  kind: 'progress'
  stage: string
  /** `total: null` = 不定档（listing 阶段与 grep 档全程），进度组件必须三态 */
  done: number
  total: number | null
  elapsed_s: number
  files_scanned: number
  bytes_scanned: number
}

export interface NoticeEvent {
  kind: 'notice'
  /** 码表事实来源 = `events.py` 的 CLAMPED_TEXT / TRUNCATION_TEXT */
  code: string
  message: string
}

export interface ErrorEvent {
  kind: 'error'
  scope: 'file' | 'dir' | 'fatal'
  /** `scope='fatal'` 时后端发 `null`（search_views `_safe_stream`） */
  path: string | null
  message: string
}

export interface DoneEvent {
  kind: 'done'
  matched: number
  scanned: number
  elapsed_s: number
  /** `limits_hit` 非空即结果不完整：前端必须常驻提示，不可手动关闭 */
  truncated: boolean
  limits_hit: string[]
  engine: SearchEngine
  /** 用户取消导致的收尾（达到 max_matches 的自停不算取消） */
  cancelled: boolean
  timed_out: boolean
}

export type SearchEvent =
  | HelloEvent
  | StageEvent
  | CandidatesEvent
  | MatchEvent
  | ProgressEvent
  | NoticeEvent
  | ErrorEvent
  | DoneEvent

/**
 * store 里 `SearchRun.notices` / `.errors` 用的名字（计划 Task 14 的接口段就这么写的，
 * 但 Task 13 的类型块里没有它们——这里补两个**别名**而不是重定义字段：
 * 事件载荷只有一份形状，另写一份接口就是等着漂移的两处）。
 */
export type SearchNotice = NoticeEvent
export type SearchError = ErrorEvent

// ------------------------------------------------------------------ 预设契约

export interface SearchPresetItem {
  id: number
  name: string
  spec: SearchSpec
  updated_at: string
}

/** 未连接哨兵：`search_views` 在会话缺失时回 `400 {"error": "not_connected"}`。 */
export const NOT_CONNECTED_SENTINEL = 'not_connected'

/**
 * 这句 400 文案是不是「压根没连接」。
 *
 * 两种拼法都要认：后端实际哨兵是 `not_connected`（`search_views.py:153`），
 * 而 spec §3.13 的散文写作 "not connected"。漏判的后果是把「请先连接」的引导
 * 显示成一句英文裸文本，用户不知道下一步做什么。
 */
export function isNotConnectedMessage(message: string | null | undefined): boolean {
  const text = (message || '').trim().toLowerCase()
  return text === NOT_CONNECTED_SENTINEL
    || text.includes('not_connected')
    || text.includes('not connected')
}

// ------------------------------------------------------------------ API

const SEARCH_URL = '/sftp/search/'

export const sftpSearchApi = {
  /**
   * 跑一次搜索：`POST /sftp/search/` → SSE，逐事件回调。
   *
   * 错误**只抛不吞**（调用方 store 负责收口）：流开始前的失败是
   * `400 {"error": msg}` → `Error(msg)`；取消是 `AbortError`。
   * 事件 `kind` 原样透传，本层不做任何过滤——过滤一处就得在两处维护字段。
   */
  async run(
    spec: SearchSpec,
    onEvent: (e: SearchEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    // 对象字面量展开：`SearchSpec` 是 interface，直接传给 `Record<string, unknown>`
    // 会缺隐式索引签名（TS 规则），展开一次即可，运行时与 JSON.stringify 都不变。
    const body: Record<string, unknown> = { ...spec }
    await postSse(SEARCH_URL, body, data => onEvent(data as SearchEvent), signal)
  },
  /** 本人预设列表（后端按 `-updated_at` 排序，跨用户不可见） */
  async presets(): Promise<{ presets: SearchPresetItem[] }> {
    const resp = await api.get('/sftp/search_presets/')
    return resp.data
  },
  /** 存预设：同名即覆盖（后端 `overwrite` 缺省 true），校验不过 400 */
  async savePreset(name: string, spec: SearchSpec): Promise<SearchPresetItem> {
    const resp = await api.post('/sftp/search_presets/save/', { name, spec })
    return resp.data
  },
  async deletePreset(id: number): Promise<void> {
    await api.post('/sftp/search_presets/delete/', { id })
  },
}
