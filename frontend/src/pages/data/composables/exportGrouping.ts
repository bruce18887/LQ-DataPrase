/**
 * 批量导出「测试项归类」纯函数层：只做匹配、冲突策略、预览计数与配置解析，
 * 不依赖 Vue / DOM，便于单测（T2 档）。UI 与导出接线在后续任务中消费这些导出。
 */

export type PatternType = 'prefix' | 'suffix' | 'contains'
export type ConflictStrategy = 'first' | 'specific' | 'multi'

export interface GroupPattern { type: PatternType; text: string }
export interface GroupRule { id: string; name: string; patterns: GroupPattern[] }
export interface GroupAssignment { name: string; params: string[] }
/** 预览口径：行含 0 命中的分类，sheet 数按「参与项次」累加（多属会重复计）。 */
export interface GroupPreview {
  rows: GroupAssignment[]
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
 * 预览专用：**每个已配置分类都出行（含 0 命中）**，并恒追加自动「其他」行。
 * `resolveGroups` 会滤掉空分组（发请求时不需要它），但预览里「配了却没人命中」是
 * 用户最需要看见的信息，所以两者必须分开。
 *
 * sheet 数 = 1 张总览 + Σ ceil(行大小 / 上限)。多属策略下同一参数会出现在多行，
 * 因此这里的计数是**参与项次**（一处命中算一次），与后端按分类装箱的页数同口径。
 */
export function previewGroups(
  params: string[], rules: GroupRule[], strategy: ConflictStrategy, maxItems?: number,
): GroupPreview {
  const { valid, buckets, other } = bucketize(params, rules, strategy)
  const rows: GroupAssignment[] = valid
    .map((r) => ({ name: r.name.trim(), params: buckets.get(r.id)! }))
  rows.push({ name: OTHER_GROUP_NAME, params: other })
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
