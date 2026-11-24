import { describe, expect, it } from 'vitest'
import { managedTagsFor, mergeDisplayTags } from '../../src/utils/combinationTags'

describe('combinationTags', () => {
  it('无批次只生成组合标签', () => {
    expect(managedTagsFor('gage', '')).toEqual(['gage'])
  })

  it('有批次生成组合与组合批次标签', () => {
    expect(managedTagsFor('gage', 'BE01-2608130015')).toEqual([
      'gage',
      'gage / BE01-2608130015',
    ])
  })

  it('未分组不生成系统标签', () => {
    expect(managedTagsFor(null, 'BE01-2608130015')).toEqual([])
  })

  it('展示合并且大小写不敏感去重', () => {
    expect(mergeDisplayTags(['Gage', 'manual'], ['gage', 'gage / BE01'])).toEqual([
      'Gage',
      'manual',
      'gage / BE01',
    ])
  })
})
