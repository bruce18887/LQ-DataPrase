/**
 * 批量导出「测试项归类」纯函数层：只做匹配、冲突策略、预览计数与配置解析，
 * 不依赖 Vue / DOM，便于单测（T2 档）。UI 与导出接线在后续任务中消费这些导出。
 */

export type PatternType = 'prefix' | 'suffix' | 'contains'
export type ConflictStrategy = 'first' | 'specific' | 'multi'

export interface GroupPattern { type: PatternType; text: string }
export interface GroupRule { id: string; name: string; patterns: GroupPattern[] }
export interface GroupAssignment { name: string; params: string[] }
/**
 * 预览行：在请求分组形状上多一个 `configured` 标记。`false` 表示「名字已填、但没有一个
 * 有效条件」——这类分类不参与导出（`resolveGroups` 不会输出它），但必须在预览里留一行，
 * 否则用户刚打完分类名、还没来得及填条件时，那行会从预览里静默消失。
 * 自动「其他」行不是未配置行，其 `configured` 恒为 `true`。
 */
export interface GroupPreviewRow extends GroupAssignment { configured: boolean }
/** 预览口径：行含 0 命中的分类与未配置行，sheet 数按「参与项次」累加（多属会重复计）。 */
export interface GroupPreview {
  rows: GroupPreviewRow[]
  sheets: number
  conflicts: number
}
export interface GroupingConfig {
  groups: GroupRule[]
  strategy: ConflictStrategy
  maxItemsPerSheet: number
}

export const OTHER_GROUP_NAME = '其他'
export const MAX_ITEMS_OPTIONS = [30, 50, 100] as const
export const DEFAULT_MAX_ITEMS = 50

// 「最具体」的排序权重：后缀 > 包含 > 前缀；同权重时比条件文本长度，越长越具体
const TYPE_RANK: Record<PatternType, number> = { suffix: 3, contains: 2, prefix: 1 }
const STRATEGIES: ConflictStrategy[] = ['first', 'specific', 'multi']

export function newGroupId(): string {
  return `g_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`
}

export function defaultGroupingConfig(): GroupingConfig {
  return { groups: [], strategy: 'first', maxItemsPerSheet: DEFAULT_MAX_ITEMS }
}

// 只有「有名字且至少一个非空条件」的分类才参与匹配，空壳分类视为未配置
function validRules(rules: GroupRule[]): GroupRule[] {
  return rules.filter((r) => r.name.trim() && r.patterns.some((p) => p.text.trim()))
}

// 返回该分类对某个参数的最佳命中强度；未命中返回 null
function matchScore(param: string, rule: GroupRule): { rank: number; len: number } | null {
  const name = param.toLowerCase()
  let best: { rank: number; len: number } | null = null
  for (const pattern of rule.patterns) {
    const text = pattern.text.trim().toLowerCase()
    if (!text) continue
    const hit = pattern.type === 'prefix' ? name.startsWith(text)
      : pattern.type === 'suffix' ? name.endsWith(text)
        : name.includes(text)
    if (!hit) continue
    const score = { rank: TYPE_RANK[pattern.type], len: text.length }
    if (!best || score.rank > best.rank || (score.rank === best.rank && score.len > best.len)) best = score
  }
  return best
}

// 一次匹配的完整结果：有效规则、每条的桶、「其他」袋。resolveGroups 与 previewGroups
// 共用它 —— 两者只差「空桶要不要输出」，共用匹配内核才不会各算一套。
interface Bucketed { valid: GroupRule[]; buckets: Map<string, string[]>; other: string[] }

function bucketize(params: string[], rules: GroupRule[], strategy: ConflictStrategy): Bucketed {
  const valid = validRules(rules)
  const buckets = new Map<string, string[]>(valid.map((r) => [r.id, []]))
  const other: string[] = []
  for (const param of params) {
    const hits = valid
      .map((r) => ({ rule: r, score: matchScore(param, r) }))
      .filter((h): h is { rule: GroupRule; score: { rank: number; len: number } } => h.score !== null)
    if (hits.length === 0) { other.push(param); continue }
    if (strategy === 'multi') {
      for (const h of hits) buckets.get(h.rule.id)!.push(param)
      continue
    }
    // first：按规则声明顺序取第一个命中；specific：取「最具体」的那个
    let chosen = hits[0]
    if (strategy === 'specific') {
      for (const h of hits.slice(1)) {
        if (h.score.rank > chosen.score.rank
          || (h.score.rank === chosen.score.rank && h.score.len > chosen.score.len)) chosen = h
      }
    }
    buckets.get(chosen.rule.id)!.push(param)
  }
  return { valid, buckets, other }
}

export function resolveGroups(
  params: string[], rules: GroupRule[], strategy: ConflictStrategy,
): GroupAssignment[] {
  const { valid, buckets, other } = bucketize(params, rules, strategy)
  // 顺序沿用规则声明顺序；空分组不输出；「其他」永远排在最后
  const out = valid
    .map((r) => ({ name: r.name.trim(), params: buckets.get(r.id)! }))
    .filter((g) => g.params.length > 0)
  if (other.length) out.push({ name: OTHER_GROUP_NAME, params: other })
  return out
}

/**
 * 预览专用：**每个已命名分类都出行**，并恒追加自动「其他」行（最后）。
 * `resolveGroups` 会滤掉空分组（发请求时不需要它），但预览里两种「空」都必须看得见：
 * - 条件有效但 0 命中 → 正常计数行（`configured: true`，0 项）；
 * - 名字已填但无有效条件 → 占位行（`configured: false`，params 为空，不参与导出）。
 * 名字都空的新建行不出现 —— 那是还没开始的编辑，不是一份配置。
 *
 * sheet 数 = 1 张总览 + Σ ceil(行大小 / 上限)。多属策略下同一参数会出现在多行，
 * 因此这里的计数是**参与项次**（一处命中算一次），与后端按分类装箱的页数同口径。
 */
export function previewGroups(
  params: string[], rules: GroupRule[], strategy: ConflictStrategy, maxItems?: number,
): GroupPreview {
  const { valid, buckets, other } = bucketize(params, rules, strategy)
  const validIds = new Set(valid.map((r) => r.id))
  // 行序 = 声明序；有效分类与未配置分类各自在自己的位置出行，不重排
  const rows: GroupPreviewRow[] = []
  for (const r of rules) {
    const name = r.name.trim()
    if (!name) continue
    if (validIds.has(r.id)) rows.push({ name, params: buckets.get(r.id)!, configured: true })
    else rows.push({ name, params: [], configured: false })
  }
  rows.push({ name: OTHER_GROUP_NAME, params: other, configured: true })
  return {
    rows,
    sheets: estimateSheetCount(rows, maxItems ?? DEFAULT_MAX_ITEMS),
    conflicts: countConflicts(params, rules),
  }
}

/**
 * 提交前自校验（R13）：只查分类名这一层 —— trim 后不得为空、不得重复、不得占用
 * 保留名「其他」。通过返回 null，否则返回一句可直接给用户看的中文。
 *
 * 不查「有没有配条件」：空壳分类本来就视为未配置（`hasGroupingRules` 同口径），
 * 拦下来只会让「先加分类、后填条件」这种正常编辑顺序报错。
 */
export function validateGroupingConfig(config: GroupingConfig): string | null {
  const seen = new Set<string>()
  for (const group of config.groups) {
    const name = group.name.trim()
    if (!name) return '分类名不能为空'
    if (name === OTHER_GROUP_NAME) return '分类名不能是「其他」'
    if (seen.has(name)) return `分类名重复：${name}`
    seen.add(name)
  }
  return null
}

/**
 * 导出前的分类名闸：**只有确有有效规则时**才跑 `validateGroupingConfig`。
 *
 * 全是空壳分类（名字没填、或条件全空）时导出请求根本不带 `groups`，
 * 旧版式照常工作 —— 这时拦下来只会让「先加分类、后填条件」的中间态没法导出。
 * 一旦确有规则要发出去，空名分类就会在请求里静默消失（预览有行、导出没块），
 * 所以那种情况仍按 `validateGroupingConfig` 拦。返回 null 表示放行。
 */
export function groupingValidationError(config: GroupingConfig): string | null {
  return hasGroupingRules(config) ? validateGroupingConfig(config) : null
}

export function countConflicts(params: string[], rules: GroupRule[]): number {
  const valid = validRules(rules)
  return params.filter((p) => valid.filter((r) => matchScore(p, r) !== null).length > 1).length
}

// 预览口径：1 张汇总 sheet + 每组的 ceil(组大小 / 上限)
export function estimateSheetCount(groups: GroupAssignment[], maxItems: number): number {
  const cap = maxItems > 0 ? maxItems : DEFAULT_MAX_ITEMS
  return 1 + groups.reduce((sum, g) => sum + Math.ceil(g.params.length / cap), 0)
}

export function hasGroupingRules(config: GroupingConfig): boolean {
  return validRules(config.groups).length > 0
}

/**
 * 导出格式闸（R15）：后端对 `pptx` 直接拒绝 groups（`groups_not_supported` → 400），
 * 而作业提交是 arraybuffer 请求，前端读不到响应里的错误码，用户只会看到一句英文的
 * 「Request failed with status code 400」。所以在提交前就把这条路显式堵死，给一句能执行的中文。
 * 返回 null 表示放行；只拦「PPT + 确实配了有效规则」这一种组合，无规则时 PPT 照常导出。
 */
export function groupingExportBlocked(format: string, config: GroupingConfig): string | null {
  if (format === 'pptx' && hasGroupingRules(config)) {
    return 'PPT 不支持测试项归类：请先删除分类或改用 Excel 导出'
  }
  return null
}

// 容错解析：坏 JSON 整体回退默认；脏字段逐项丢弃或回退，不让一条坏数据毁掉整份配置
export function parseGroupingConfig(raw: string | null): GroupingConfig {
  const fallback = defaultGroupingConfig()
  if (!raw) return fallback
  try {
    const data = JSON.parse(raw) as Partial<GroupingConfig>
    const groups = Array.isArray(data.groups) ? data.groups : []
    const cleaned: GroupRule[] = groups
      .filter((g): g is GroupRule => !!g && typeof g.name === 'string' && Array.isArray(g.patterns))
      .map((g) => ({
        id: typeof g.id === 'string' && g.id ? g.id : newGroupId(),
        name: g.name,
        patterns: g.patterns
          .filter((p) => !!p && ['prefix', 'suffix', 'contains'].includes(p.type) && typeof p.text === 'string')
          .map((p) => ({ type: p.type, text: p.text })),
      }))
    return {
      groups: cleaned,
      strategy: STRATEGIES.includes(data.strategy as ConflictStrategy)
        ? (data.strategy as ConflictStrategy) : 'first',
      maxItemsPerSheet: (MAX_ITEMS_OPTIONS as readonly number[]).includes(data.maxItemsPerSheet as number)
        ? (data.maxItemsPerSheet as number) : DEFAULT_MAX_ITEMS,
    }
  } catch {
    return fallback
  }
}
