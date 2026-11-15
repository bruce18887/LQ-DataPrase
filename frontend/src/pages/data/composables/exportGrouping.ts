/**
 * 批量导出「测试项归类」纯函数层：只做匹配、冲突策略、预览计数与配置解析，
 * 不依赖 Vue / DOM，便于单测（T2 档）。UI 与导出接线在后续任务中消费这些导出。
 */

export type PatternType = 'prefix' | 'suffix' | 'contains'
export type ConflictStrategy = 'first' | 'specific' | 'multi'

export interface GroupPattern { type: PatternType; text: string }
export interface GroupRule { id: string; name: string; patterns: GroupPattern[] }
export interface GroupAssignment { name: string; params: string[] }
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

export function resolveGroups(
  params: string[], rules: GroupRule[], strategy: ConflictStrategy,
): GroupAssignment[] {
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
  // 顺序沿用规则声明顺序；空分组不输出；「其他」永远排在最后
  const out = valid
    .map((r) => ({ name: r.name.trim(), params: buckets.get(r.id)! }))
    .filter((g) => g.params.length > 0)
  if (other.length) out.push({ name: OTHER_GROUP_NAME, params: other })
  return out
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
