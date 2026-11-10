/**
 * 审计页（Task 11）的三件纯逻辑：事件标签、筛选转 query、detail 单行摘要。
 *
 * 事件码清单住在后端 `apps/accounts/audit.py` 的 `AUDIT_EVENTS`，分页边界与查询参数名住在
 * `apps/accounts/views.py`，username 快照列宽住在 `apps/accounts/models.py`。跨语言没有
 * 共享类型，下面这几份数字与标签就是**第二副本**，而副本不会自己保鲜：保鲜由
 * `test/unit/audit.spec.ts` 刮那三份源码来钉（后端挪一个数、加一个码、改一个参数名而这里
 * 没跟上就红）。别把「反正测试会红」当成免改理由——红的是判据，产品文案仍然贴着旧标签。
 */

export const AUDIT_EVENT_LABELS: Record<string, string> = {
  login_success: '登录成功',
  login_failure: '登录失败',
  account_locked: '账号锁定',
  account_unlocked: '账号解锁',
  password_changed: '自助修改密码',
  password_reset: '管理员重置密码',
  user_created: '创建账号',
  user_updated: '更新账号',
  user_deleted: '删除账号',
  system_paths_changed: '存储路径变更',
}

/** 事件码的唯一清单在后端；这里只抄它管得着的三件事：码、中文标签、未知码怎么显示。
 *  查表必须走 own-property：`AUDIT_EVENT_LABELS['toString']` 会从原型上取到一个 Function，
 *  而 `??` 只挡 null/undefined —— 未登记的码（后端只留 warning、不拒写，所以它真会进表）
 *  若撞上原型名，页面就会把「function toString(){…}」当事件名显示出来。 */
export const auditEventLabel = (event: string): string =>
  Object.hasOwn(AUDIT_EVENT_LABELS, event) ? AUDIT_EVENT_LABELS[event] : event

export interface AuditFilters {
  event: string
  username: string
  dateFrom: string
  dateTo: string
  page: number
  pageSize: number
}

/** `views.py` 的 `AUDIT_PAGE_SIZE_DEFAULT` / `AUDIT_PAGE_SIZE_MAX`：接受域是 1–100，超限是 400 而不是静默夹。 */
export const AUDIT_PAGE_SIZE_DEFAULT = 50
export const AUDIT_PAGE_SIZE_MAX = 100

/**
 * `models.py` 的 `actor_username.max_length`（后端 `audit.USERNAME_MAX_LENGTH` 由它现推）。
 * 本模块只把它交给 Task 11 当输入框的 maxlength：搜索词本身不许长到后端收不下，
 * 而不是在转 query 时悄悄截——库里存的快照就截到这个宽度，截半句再搜会得到
 * 「前缀能匹配上的那些行」，在取证页上这是一份看着合理的假答案。
 */
export const USERNAME_QUERY_MAX = 150

/** 表格一格里只放一行：120 是给「不折行、不撑破列宽」定的预算，看全量交给详情弹窗。
 *  这道打码只管摘要这一行 —— 弹窗要展示原始 detail，就得走同一套键名规则，别裸贴 JSON。 */
const DETAIL_SUMMARY_MAX = 120

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
/** 后端 `strptime('%Y-%m-%d')` 连 `2026-1-5` 都收（现量），只认两位是前端的线，不是后端的。 */
const LOOSE_DATE_RE = /^(\d{4})-(\d{1,2})-(\d{1,2})$/

/**
 * 把日期收成后端线里的 `YYYY-MM-DD`：完整的补零（`2026-1-5` → `2026-01-05`），
 * 真半截的（`2026-11`）交回空串 = 不发这个条件。
 * 不这么做的后果不是「后端报 400」而是**静默丢条件**：用户填了 `2026-1-5`，前端不发日期，
 * 于是拿到一份看着像「全部事件」的结果 —— 取证页上一份合理但错的行集，比一个错误提示坏得多。
 */
const normalizeDay = (raw: string): string => {
  if (DATE_RE.test(raw)) return raw
  const m = LOOSE_DATE_RE.exec(raw)
  if (!m) return ''
  return `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}`
}

/** 键名启发式（不是内容扫描）：值里含口令而键名不含 pass/token/secret 时抓不住，那道闸在后端白名单。 */
const SECRET_KEY_RE = /pass|token|secret/i

const REDACTED = '•••'
const EMPTY_TEXT = '空'
const ELLIPSIS = '…'
const PLACEHOLDER = '—'

export const defaultAuditFilters = (): AuditFilters => ({
  event: '',
  username: '',
  dateFrom: '',
  dateTo: '',
  page: 1,
  pageSize: AUDIT_PAGE_SIZE_DEFAULT,
})

/** 非法页码交给 DRF 分页是 404（`NotFound`），所以这里只管把值收成合法整数，不猜「用户想去第几页」。 */
const normalizePage = (page: number): number =>
  Number.isFinite(page) ? Math.max(1, Math.trunc(page)) : 1

/** 夹进后端接受域，而不是回落默认：用户挑 200 条/页时给他 100 条，比发一个必 400 的请求有用。 */
const normalizePageSize = (size: number): number => {
  if (!Number.isFinite(size)) return AUDIT_PAGE_SIZE_DEFAULT
  return Math.min(AUDIT_PAGE_SIZE_MAX, Math.max(1, Math.trunc(size)))
}

export function buildAuditQuery(filters: AuditFilters): Record<string, string | number> {
  const query: Record<string, string | number> = {
    page: normalizePage(filters.page),
    page_size: normalizePageSize(filters.pageSize),
  }
  const event = filters.event.trim()
  if (event) query.event = event
  const username = filters.username.trim()
  if (username) query.username = username
  const dateFrom = normalizeDay(filters.dateFrom.trim())
  if (dateFrom) query.date_from = dateFrom
  const dateTo = normalizeDay(filters.dateTo.trim())
  if (dateTo) query.date_to = dateTo
  return query
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return EMPTY_TEXT
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.length ? value.map(renderValue).join('/') : EMPTY_TEXT
  try {
    // replacer 对每一层键都走一遍，所以嵌套的口令字段也一起打码；循环引用在这行抛，交给下面兜住。
    return JSON.stringify(value, (key, nested) => (key && SECRET_KEY_RE.test(key) ? REDACTED : nested))
  } catch {
    return ELLIPSIS
  }
}

/** detail 的单行摘要。后端今天写进去的十个 detail 全是 dict，但那是**调用点**的纪律：
 *  `JSONField(default=dict)` 只管缺省、不约束类型，`audit._insert()` 那句 `detail or {}`
 *  也会照收一个非空的 list —— 所以这里的非对象分支不是「不会走到」。 */
export function summarizeDetail(detail: unknown): string {
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return PLACEHOLDER
  const parts = Object.entries(detail).map(([key, value]) =>
    SECRET_KEY_RE.test(key) ? `${key}=${REDACTED}` : `${key}=${renderValue(value)}`,
  )
  if (!parts.length) return PLACEHOLDER
  const text = parts.join('，')
  return text.length > DETAIL_SUMMARY_MAX ? `${text.slice(0, DETAIL_SUMMARY_MAX - 1)}${ELLIPSIS}` : text
}
