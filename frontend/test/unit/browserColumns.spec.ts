/**
 * T2：查看数据表格的列定义与单元格着色。
 *
 * 红/橙优先级是这条链路的承重判据：橙格来自新的 `__borderline_cells__`，
 * 红格来自既有 `__fail_cells__`；两者同时命中时必须红。把这些规则从
 * DataBrowserAgGrid.vue 抽成纯函数，才能在 0.4s 的 vitest 里钉住。
 */
import { describe, expect, it } from 'vitest'

import {
  browserCellStyle,
  buildBrowserColumnDefs,
  headerMenuCopyLabel,
} from '../../src/pages/data/components/browser/browserColumns'

const LIGHT_RED = { backgroundColor: 'var(--error-2)', color: '#ffffff', fontWeight: 'bold' }
const DARK_RED = { backgroundColor: '#b91c1c', color: '#fecaca', fontWeight: 'bold' }
const LIGHT_ORANGE = { backgroundColor: '#f59e0b', color: '#451a03', fontWeight: 'bold' }
const DARK_ORANGE = { backgroundColor: '#f9a825', color: '#451a03', fontWeight: 'bold' }

function params(field: string, data: Record<string, any> | null) {
  return { colDef: { field }, data }
}

describe('browserCellStyle', () => {
  it('fail_cells 命中 → 红色（light/dark 各一套）', () => {
    const data = { __fail_cells__: ['A'], __borderline_cells__: [] }
    expect(browserCellStyle(params('A', data), false)).toEqual(LIGHT_RED)
    expect(browserCellStyle(params('A', data), true)).toEqual(DARK_RED)
  })

  it('borderline_cells 命中 → 橙色（light/dark 各一套）', () => {
    const data = { __fail_cells__: [], __borderline_cells__: ['B'] }
    expect(browserCellStyle(params('B', data), false)).toEqual(LIGHT_ORANGE)
    expect(browserCellStyle(params('B', data), true)).toEqual(DARK_ORANGE)
  })

  it('同一单元格同时命中红与橙 → 红优先', () => {
    const data = { __fail_cells__: ['C'], __borderline_cells__: ['C'] }
    expect(browserCellStyle(params('C', data), false)).toEqual(LIGHT_RED)
  })

  it('未命中 / 无行数据 / 无字段 → 不着色', () => {
    expect(browserCellStyle(params('D', { __fail_cells__: ['A'] }), false)).toBeNull()
    expect(browserCellStyle(params('D', null), false)).toBeNull()
    expect(browserCellStyle({ colDef: {}, data: { __fail_cells__: ['D'] } }, false)).toBeNull()
  })
})

describe('buildBrowserColumnDefs', () => {
  const opts = {
    displayCols: ['A', 'B', 'SERIAL'],
    colMeta: {
      A: { unit: 'ohm', min: '0', max: '2' },
      B: { unit: '-', min: '', max: '' },
      SERIAL: { unit: '', min: '', max: '' },
    },
    numericColumns: ['A', 'SERIAL'],
    defaultHiddenCols: ['B'],
    pinnedCols: ['SERIAL'],
    highlightTriggerCol: 'SERIAL',
    highlightTriggerKind: 'serial' as 'serial' | 'bin',
    isSystemCol: (c: string) => c === 'SERIAL',
    isDark: false,
  }

  function defs(overrides: Partial<typeof opts> = {}) {
    return buildBrowserColumnDefs({ ...opts, ...overrides })
  }

  it('表头带单位与限值，系统列不带单位时不追加空括号', () => {
    const byField = Object.fromEntries(defs().map((d: any) => [d.field, d]))
    expect(byField.A.headerName).toBe('A (ohm) [0, 2]')
    expect(byField.B.headerName).toBe('B')
    expect(byField.SERIAL.headerName).toBe('SERIAL')
  })

  it('数值列挂 number filter，其余挂 text filter', () => {
    const byField = Object.fromEntries(defs().map((d: any) => [d.field, d]))
    expect(byField.A.filter).toBe('agNumberColumnFilter')
    expect(byField.B.filter).toBe('agTextColumnFilter')
  })

  it('默认隐藏列 hide=true，固定列 pinned=left', () => {
    const byField = Object.fromEntries(defs().map((d: any) => [d.field, d]))
    expect(byField.B.hide).toBe(true)
    expect(byField.SERIAL.pinned).toBe('left')
  })

  it('只有高亮触发列带手型类与表头提示', () => {
    const byField = Object.fromEntries(defs().map((d: any) => [d.field, d]))
    expect(byField.SERIAL.cellClass).toBe('row-highlight-trigger')
    expect(byField.SERIAL.headerTooltip).toContain('点击序列号')
    expect(byField.A.cellClass).toBeUndefined()
    expect(byField.A.headerTooltip).toBeUndefined()
  })

  it('无序列列退回 Bin 时提示文案随触发列变化', () => {
    const byField = Object.fromEntries(
      defs({ highlightTriggerCol: 'A', highlightTriggerKind: 'bin' }).map((d: any) => [d.field, d]),
    )
    expect(byField.A.headerTooltip).toContain('点击 Bin')
    expect(byField.SERIAL.cellClass).toBeUndefined()
  })

  it('保留隐藏的 __fail_cells__ 占位列', () => {
    const sentinel = defs().find((d: any) => d.field === '__fail_cells__')
    expect(sentinel).toMatchObject({ hide: true })
  })
})

describe('headerMenuCopyLabel', () => {
  it('测试项与系统列使用不同文案', () => {
    expect(headerMenuCopyLabel(false)).toBe('复制测试项名字')
    expect(headerMenuCopyLabel(true)).toBe('复制列名')
  })
})
