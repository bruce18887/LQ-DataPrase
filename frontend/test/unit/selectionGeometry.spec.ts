import { describe, it, expect } from 'vitest'
import {
  normalizeRect, intersectRects, normalizeRange, pickSerials, mergeSerials,
  valueRangeWithOverflow, subsetPanelTitle, buildSubsetRequest,
  type DataPoint,
} from '../../src/pages/analysis/composables/selectionGeometry'

describe('normalizeRect', () => {
  it(' sorts corners', () => {
    expect(normalizeRect({ x: 10, y: 20 }, { x: 2, y: 5 }))
      .toEqual({ x0: 2, y0: 5, x1: 10, y1: 20 })
  })
})

describe('intersectRects', () => {
  const a = { x0: 0, y0: 0, x1: 10, y1: 10 }
  it('returns overlap', () => {
    expect(intersectRects(a, { x0: 5, y0: 5, x1: 15, y1: 15 }))
      .toEqual({ x0: 5, y0: 5, x1: 10, y1: 10 })
  })
  it('returns null when disjoint', () => {
    expect(intersectRects(a, { x0: 20, y0: 20, x1: 30, y1: 30 })).toBeNull()
  })
  it('returns null for edge-only touch', () => {
    expect(intersectRects(a, { x0: 10, y0: 0, x1: 20, y1: 10 })).toBeNull()
  })
})

describe('normalizeRange', () => {
  it('orders ascending', () => {
    expect(normalizeRange(5, 2)).toEqual([2, 5])
    expect(normalizeRange(2, 5)).toEqual([2, 5])
  })
})

describe('pickSerials', () => {
  const pts: DataPoint[] = [
    { x: 0, y: 1.0, serial: 1 },
    { x: 1, y: 2.0, serial: 2 },
    { x: 2, y: 3.0, serial: 3 },
    { x: 3, y: NaN, serial: 4 },
  ]
  it('inclusive bounds on both axes', () => {
    expect(pickSerials(pts, [1, 2], [2.0, 3.0])).toEqual([2, 3])
  })
  it('skips non-finite y', () => {
    expect(pickSerials(pts, [0, 3], [0, 10])).toEqual([1, 2, 3])
  })
  it('empty when out of range', () => {
    expect(pickSerials(pts, [10, 20], [0, 10])).toEqual([])
  })
})

describe('mergeSerials', () => {
  it('dedupes preserving first-seen order', () => {
    expect(mergeSerials([[3, 1], [1, 2], [3]])).toEqual([3, 1, 2])
  })
})

describe('valueRangeWithOverflow (D6)', () => {
  const centers = [-0.1, 0.5, 1.0, 1.5, 2.1] // [0]=underflow, [-1]=overflow
  it('normal range unchanged', () => {
    expect(valueRangeWithOverflow(0.4, 1.2, centers)).toEqual({ lo: 0.4, hi: 1.2 })
  })
  it('hi reaching overflow center → null', () => {
    expect(valueRangeWithOverflow(0.4, 2.1, centers)).toEqual({ lo: 0.4, hi: null })
  })
  it('lo reaching underflow center → null', () => {
    expect(valueRangeWithOverflow(-0.1, 1.2, centers)).toEqual({ lo: null, hi: 1.2 })
  })
  it('both edges → both null', () => {
    expect(valueRangeWithOverflow(-0.1, 2.1, centers)).toEqual({ lo: null, hi: null })
  })
  it('short centers array leaves range unchanged', () => {
    expect(valueRangeWithOverflow(0.4, 2.1, [1.0])).toEqual({ lo: 0.4, hi: 2.1 })
  })
})

describe('subsetPanelTitle', () => {
  it('value_range with unbounded hi', () => {
    expect(subsetPanelTitle('P1', { kind: 'value_range', lo: 9, hi: null }, 3))
      .toBe('P1 子集 · n=3 · [9, +∞]')
  })
  it('serials count', () => {
    expect(subsetPanelTitle('P1', { kind: 'serials', serials: [1, 2, 3] }, 3))
      .toBe('P1 子集 · n=3 · 3 颗序列')
  })
  it('null n while loading', () => {
    expect(subsetPanelTitle('P1', { kind: 'value_range', lo: 0, hi: 1 }, null))
      .toBe('P1 子集 · [0, 1]')
  })
  it('rounds float bounds for display', () => {
    expect(subsetPanelTitle('P1', { kind: 'value_range', lo: 0.30000000000000004, hi: 1.2000000000000002 }, 2))
      .toBe('P1 子集 · n=2 · [0.3, 1.2]')
  })
})

describe('buildSubsetRequest', () => {
  const ctx = {
    fileId: 7, ignoreNoLimit: true, ignoreNoTestValue: true, dataOnlyBin1: true,
    onlyFailTestItem: true, onlyLowCpk: true, iqrMultiplier: 2.0,
    chartConfig: ['limit', 'kde', 'kde_full'],
  }
  it('forces DR + null custom limits + carries selection', () => {
    const sel = { kind: 'value_range' as const, lo: 9, hi: null }
    const body = buildSubsetRequest(ctx, 'P1', sel)
    expect(body.file_id).toBe(7)
    expect(body.params).toEqual(['P1'])
    expect(body.range_type).toBe('DR')
    expect(body.custom_low).toBeNull()
    expect(body.custom_high).toBeNull()
    expect(body.data_only_bin1).toBe(true)
    expect(body.iqr_multiplier).toBe(2.0)
    expect(body.ignore_no_limit).toBe(true)
    expect(body.ignore_no_test_value).toBe(true)
    expect(body.only_fail_test_item).toBe(true)
    expect(body.only_low_cpk).toBe(true)
    expect(body.selection).toEqual(sel)
  })
  it('kde_variant all when kde_full checked', () => {
    const body = buildSubsetRequest(ctx, 'P1', { kind: 'value_range', lo: 0, hi: 1 })
    expect(body.include_kde).toBe(true)
    expect(body.kde_variant).toBe('all')
  })
  it('kde_variant filtered when kde checked without kde_full', () => {
    const body = buildSubsetRequest({ ...ctx, chartConfig: ['limit', 'kde'] }, 'P1',
      { kind: 'value_range', lo: 0, hi: 1 })
    expect(body.include_kde).toBe(true)
    expect(body.kde_variant).toBe('filtered')
  })
  it('kde off when not configured', () => {
    const body = buildSubsetRequest({ ...ctx, chartConfig: ['limit'] }, 'P1',
      { kind: 'value_range', lo: 0, hi: 1 })
    expect(body.include_kde).toBe(false)
    expect(body.kde_variant).toBeNull()
  })
})