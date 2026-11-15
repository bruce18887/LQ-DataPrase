import { describe, expect, it } from 'vitest'

import {
  DEFAULT_MAX_ITEMS,
  OTHER_GROUP_NAME,
  countConflicts,
  defaultGroupingConfig,
  estimateSheetCount,
  hasGroupingRules,
  parseGroupingConfig,
  resolveGroups,
  type GroupRule,
} from '../../src/pages/data/composables/exportGrouping'

const rule = (id: string, name: string, patterns: GroupRule['patterns']): GroupRule => ({ id, name, patterns })

const RULES: GroupRule[] = [
  rule('r1', 'LKG', [{ type: 'prefix', text: 'LKG_' }]),
  rule('r2', 'TRIM', [{ type: 'contains', text: 'Trim' }]),
  rule('r3', 'POST', [{ type: 'suffix', text: 'Trim_Post' }]),
]

describe('resolveGroups', () => {
  it('大小写不敏感，前缀/后缀/包含都命中', () => {
    const out = resolveGroups(['lkg_en', 'xx_trim_yy', 'zz_trim_post'], RULES, 'multi')
    expect(out.map((g) => g.name)).toEqual(['LKG', 'TRIM', 'POST'])
    expect(out[0].params).toEqual(['lkg_en'])
    expect(out[1].params).toEqual(['xx_trim_yy', 'zz_trim_post'])
    expect(out[2].params).toEqual(['zz_trim_post'])
  })

  it('首个命中：按规则顺序归类', () => {
    const out = resolveGroups(['lkg_trim_post'], RULES, 'first')
    expect(out).toEqual([{ name: 'LKG', params: ['lkg_trim_post'] }])
  })

  it('最具体：后缀优先于包含，包含优先于前缀', () => {
    const out = resolveGroups(['lkg_trim_post'], RULES, 'specific')
    expect(out).toEqual([{ name: 'POST', params: ['lkg_trim_post'] }])
  })

  it('未命中进其他且永远最后', () => {
    const out = resolveGroups(['misc_a', 'lkg_b'], RULES, 'first')
    expect(out.map((g) => g.name)).toEqual(['LKG', OTHER_GROUP_NAME])
    expect(out[1].params).toEqual(['misc_a'])
  })

  it('空名称/空条件的分类不参与匹配', () => {
    const rules = [rule('x', ' ', [{ type: 'prefix', text: 'A' }]), rule('y', 'B', [{ type: 'prefix', text: '  ' }])]
    expect(resolveGroups(['ABC'], rules, 'first')).toEqual([{ name: OTHER_GROUP_NAME, params: ['ABC'] }])
  })
})

describe('preview helpers', () => {
  it('冲突数 = 命中 >1 分类的参数个数', () => {
    expect(countConflicts(['lkg_trim_post', 'lkg_x', 'misc'], RULES)).toBe(1)
  })

  it('预计 sheet 数 = 1 + Σ ceil(组大小 / 上限)', () => {
    expect(estimateSheetCount([{ name: 'A', params: Array(120).fill('p') }], 50)).toBe(4)
    expect(estimateSheetCount([], 50)).toBe(1)
  })

  it('hasGroupingRules 只看「有名字且有非空条件」', () => {
    expect(hasGroupingRules(defaultGroupingConfig())).toBe(false)
    expect(hasGroupingRules({ groups: RULES, strategy: 'first', maxItemsPerSheet: 50 })).toBe(true)
  })

  it('parseGroupingConfig 容错：坏 JSON / 脏字段回退默认', () => {
    expect(parseGroupingConfig('not-json')).toEqual(defaultGroupingConfig())
    const parsed = parseGroupingConfig(JSON.stringify({
      groups: [{ name: 'A', patterns: [{ type: 'bogus', text: 'x' }, { type: 'prefix', text: 'P' }] }],
      strategy: 'nope',
      maxItemsPerSheet: 7,
    }))
    expect(parsed.strategy).toBe('first')
    expect(parsed.maxItemsPerSheet).toBe(DEFAULT_MAX_ITEMS)
    expect(parsed.groups[0].patterns).toEqual([{ type: 'prefix', text: 'P' }])
  })
})
