import { describe, expect, it } from 'vitest'

import {
  DEFAULT_MAX_ITEMS,
  OTHER_GROUP_NAME,
  countConflicts,
  defaultGroupingConfig,
  estimateSheetCount,
  hasGroupingRules,
  parseGroupingConfig,
  previewGroups,
  resolveGroups,
  validateGroupingConfig,
  type GroupRule,
  type GroupingConfig,
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

  it('同一分类内多条件为或：命中任一条件即归入该分类', () => {
    const rules = [rule('o1', 'MIX', [{ type: 'prefix', text: 'ZZZ_' }, { type: 'contains', text: 'abc' }])]
    expect(resolveGroups(['xx_abc_yy'], rules, 'first')).toEqual([{ name: 'MIX', params: ['xx_abc_yy'] }])
  })

  it('首个命中：按规则顺序归类', () => {
    const out = resolveGroups(['lkg_trim_post'], RULES, 'first')
    expect(out).toEqual([{ name: 'LKG', params: ['lkg_trim_post'] }])
  })

  it('最具体：后缀优先于包含，包含优先于前缀', () => {
    const out = resolveGroups(['lkg_trim_post'], RULES, 'specific')
    expect(out).toEqual([{ name: 'POST', params: ['lkg_trim_post'] }])
  })

  it('最具体：同类型时条件文本更长者胜出', () => {
    const rules = [
      rule('s1', 'SHORT', [{ type: 'contains', text: 'trim' }]),
      rule('s2', 'LONG', [{ type: 'contains', text: 'trim_post' }]),
    ]
    expect(resolveGroups(['lkg_trim_post'], rules, 'specific')).toEqual([{ name: 'LONG', params: ['lkg_trim_post'] }])
  })

  it('最具体：权重与长度并列时取声明更靠前的规则', () => {
    const rules = [
      rule('e1', 'EARLY', [{ type: 'contains', text: 'abc' }]),
      rule('e2', 'LATE', [{ type: 'contains', text: 'bcd' }]),
    ]
    expect(resolveGroups(['xabcdx'], rules, 'specific')).toEqual([{ name: 'EARLY', params: ['xabcdx'] }])
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

  it('预计 sheet 数：上限 ≤0 时回退默认上限', () => {
    expect(estimateSheetCount([], 0)).toBe(1)
    expect(estimateSheetCount([{ name: 'A', params: Array(120).fill('p') }], 0)).toBe(4)
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

  it('parseGroupingConfig(null) 返回默认配置', () => {
    expect(parseGroupingConfig(null)).toEqual(defaultGroupingConfig())
  })
})

describe('previewGroups', () => {
  const withEmpty = [RULES[0], rule('r9', 'EMPTY', [{ type: 'prefix', text: 'NOPE_' }]), RULES[1]]

  it('每个已配置分类都出现（含 0 命中），「其他」永远最后，行序=声明序', () => {
    const out = previewGroups(['lkg_a', 'misc_b'], withEmpty, 'first')
    expect(out.rows.map((r) => r.name)).toEqual(['LKG', 'EMPTY', 'TRIM', OTHER_GROUP_NAME])
    expect(out.rows[0].params).toEqual(['lkg_a'])
    expect(out.rows[1].params).toEqual([])
    expect(out.rows[3].params).toEqual(['misc_b'])
  })

  it('无有效规则时只剩「其他」一行，且它承载全部参数', () => {
    expect(previewGroups(['a', 'b'], [], 'first').rows)
      .toEqual([{ name: OTHER_GROUP_NAME, params: ['a', 'b'] }])
    expect(previewGroups(['a'], [rule('x', ' ', [{ type: 'prefix', text: 'A' }])], 'first').rows)
      .toEqual([{ name: OTHER_GROUP_NAME, params: ['a'] }])
  })

  it('多属：一项可同时占多行，sheet 数按参与项次计（不是按去重后的参数数）', () => {
    const out = previewGroups(['lkg_trim_post'], RULES, 'multi', 50)
    expect(out.rows.map((r) => r.name)).toEqual(['LKG', 'TRIM', 'POST', OTHER_GROUP_NAME])
    expect(out.rows.map((r) => r.params.length)).toEqual([1, 1, 1, 0])
    // 1 张总览 + 3 个各含 1 项的块 = 4；按「去重后 1 个参数」算只会得到 2
    expect(out.sheets).toBe(4)
  })

  it('sheet 数按每页上限分页（ceil），与 estimateSheetCount 同口径', () => {
    const many = Array.from({ length: 65 }, (_v, i) => `lkg_${i}`)
    const out = previewGroups(many, [RULES[0]], 'first', 30)
    expect(out.rows[0].params).toHaveLength(65)
    expect(out.sheets).toBe(1 + Math.ceil(65 / 30))
    // 不传上限时回退默认上限
    expect(previewGroups(many, [RULES[0]], 'first').sheets)
      .toBe(1 + Math.ceil(65 / DEFAULT_MAX_ITEMS))
  })

  it('冲突数沿用 countConflicts（命中多个分类的参数个数）', () => {
    expect(previewGroups(['lkg_trim_post', 'misc'], RULES, 'first').conflicts).toBe(1)
  })
})

describe('validateGroupingConfig', () => {
  const config = (groups: GroupRule[]): GroupingConfig =>
    ({ groups, strategy: 'first', maxItemsPerSheet: DEFAULT_MAX_ITEMS })
  const onePattern = [{ type: 'prefix' as const, text: 'X' }]

  it('分类名 trim 后为空 → 返回错误文案', () => {
    expect(validateGroupingConfig(config([rule('a', '   ', onePattern)])))
      .toBe('分类名不能为空')
  })

  it('分类名 trim 后重复 → 返回带名字的错误文案', () => {
    expect(validateGroupingConfig(config([rule('a', 'LKG', onePattern), rule('b', ' LKG ', onePattern)])))
      .toBe('分类名重复：LKG')
  })

  it('分类名不得占用「其他」这个保留名', () => {
    expect(validateGroupingConfig(config([rule('a', OTHER_GROUP_NAME, onePattern)])))
      .toBe('分类名不能是「其他」')
    expect(validateGroupingConfig(config([rule('a', ` ${OTHER_GROUP_NAME} `, onePattern)])))
      .toBe('分类名不能是「其他」')
  })

  it('合法配置（含无分类、空条件）返回 null', () => {
    expect(validateGroupingConfig(defaultGroupingConfig())).toBe(null)
    expect(validateGroupingConfig(config([rule('a', 'LKG', onePattern), rule('b', 'TRIM', onePattern)])))
      .toBe(null)
    // 空条件不参与匹配，但名字合法 ⇒ 不拦提交
    expect(validateGroupingConfig(config([rule('a', 'LKG', [{ type: 'prefix', text: '  ' }])])))
      .toBe(null)
  })
})
