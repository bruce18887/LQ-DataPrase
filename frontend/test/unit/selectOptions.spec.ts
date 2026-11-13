import { describe, expect, it } from 'vitest'

import {
  buildParamOptions,
  filterByKeyword,
  highlightSegments,
  sortPrefixFirst,
  toOptions,
} from '../../src/utils/selectOptions'

describe('toOptions', () => {
  it('字符串与数字都映射成 {value,label}，label 一律是字符串', () => {
    expect(toOptions(['A', 'B'])).toEqual([
      { value: 'A', label: 'A' },
      { value: 'B', label: 'B' },
    ])
    expect(toOptions([1, 2])).toEqual([
      { value: 1, label: '1' },
      { value: 2, label: '2' },
    ])
  })

  // el-select-v2 的 useProps.mjs:25-28 走 lodash.get(option,'label'|'value')，
  // 喂 string[] 是「静默空白行」。这条钉住映射不会退化。
  it('反向探针：产出项必须同时带 value 与 label 两个键', () => {
    for (const o of toOptions(['X'])) {
      expect(Object.keys(o).sort()).toEqual(['label', 'value'])
    }
  })
})

describe('filterByKeyword', () => {
  it('大小写不敏感子串匹配', () => {
    expect(filterByKeyword(['Kelvin_VIN', 'IBLK'], 'kel')).toEqual(['Kelvin_VIN'])
  })
  it('空关键词返回原集合（不复制、不改序）', () => {
    const items = ['B', 'A']
    expect(filterByKeyword(items, '')).toEqual(['B', 'A'])
  })
  it('关键词无需调用方预归一化：原始大小写同样匹配', () => {
    expect(filterByKeyword(['Kelvin_VIN', 'IBLK'], 'KEL')).toEqual(['Kelvin_VIN'])
  })
})

describe('sortPrefixFirst', () => {
  it('前缀匹配排在前面，其余按 localeCompare', () => {
    expect(sortPrefixFirst(['XPAR1', 'PAR1', 'APAR1'], 'par1')).toEqual(['PAR1', 'APAR1', 'XPAR1'])
  })
  it('不改动入参数组（排序必须在新数组上做）', () => {
    const items = ['b', 'a']
    sortPrefixFirst(items, '')
    expect(items).toEqual(['b', 'a'])
  })
  it('关键词原始大小写不影响前缀优先', () => {
    expect(sortPrefixFirst(['XPAR1', 'PAR1'], 'PAR1')).toEqual(['PAR1', 'XPAR1'])
  })
})

describe('highlightSegments', () => {
  it('命中片段标 mark=true，且大小写不敏感', () => {
    expect(highlightSegments('Kelvin_VIN', 'kelvin')).toEqual([
      { text: 'Kelvin', mark: true },
      { text: '_VIN', mark: false },
    ])
  })
  it('多处命中全部标出，顺序与原文一致', () => {
    expect(highlightSegments('AxAxA', 'ax').map((s) => s.text).join('')).toBe('AxAxA')
  })
  it('空关键词返回单个不标亮的整段', () => {
    expect(highlightSegments('ABC', '')).toEqual([{ text: 'ABC', mark: false }])
  })
  // ParamSelector.vue:145-149 记的 XSS 修复：不走 v-html，列名里的尖括号必须是字面文本。
  it('反向探针：列名含 HTML 片段时仍是字面文本，绝不产出标签', () => {
    const evil = '<img src=x onerror=alert(1)>'
    const segs = highlightSegments(evil, 'img')
    expect(segs.map((s) => s.text).join('')).toBe(evil)
    expect(JSON.stringify(segs)).not.toMatch(/<img/)
    expect(segs.some((s) => s.mark && s.text === 'img')).toBe(true)
  })
  it('正则元字符不需要转义（子串匹配，非正则）', () => {
    expect(highlightSegments('V+(1)', '+(').map((s) => s.mark)).toEqual([false, true, false])
  })
})

describe('buildParamOptions', () => {
  it('无关键词：保持原顺序，total = 全量长度', () => {
    const r = buildParamOptions(['B', 'A', 'C'], '')
    expect(r.options.map((o) => o.value)).toEqual(['B', 'A', 'C'])
    expect(r.total).toBe(3)
  })
  it('有关键词：过滤 + 前缀优先，total = 匹配数而不是渲染数', () => {
    const r = buildParamOptions(['XPAR1', 'PAR1', 'OTHER'], 'par1')
    expect(r.options.map((o) => o.value)).toEqual(['PAR1', 'XPAR1'])
    expect(r.total).toBe(2)
  })
  // 这条是「高亮按需」的承重判据：options 里一旦出现 segments 字段，
  // 就等于把 ParamSelector.vue:97-99 注释里 d1146dd 治掉的「每次击键建 N 份」放回来。
  it('反向探针：options 只带 value/label，**不得**预建高亮片段', () => {
    const r = buildParamOptions(['PAR1', 'PAR2'], 'par')
    for (const o of r.options) {
      expect(Object.keys(o).sort()).toEqual(['label', 'value'])
    }
  })
  // 与另外三个同族下拉一致（Serial/TestColumn/Export 三处都 trim，只有 ParamSelector
  // 过去不 trim）。纯空格查询 = 「没输入」，显示全量而不是空列表。
  it('纯空格关键词等价于无关键词：返回全量', () => {
    const r = buildParamOptions(['A', 'B'], '   ')
    expect(r.options.map((o) => o.value)).toEqual(['A', 'B'])
    expect(r.total).toBe(2)
  })
  it('关键词首尾空格被忽略，中间空格保留', () => {
    expect(buildParamOptions(['A B', 'AB', 'A  B'], '  a b ').options.map((o) => o.value)).toEqual(['A B'])
  })
  it('4570 项量级：total 是全量，且没有渲染截断', () => {
    const many = Array.from({ length: 4570 }, (_, i) => `P${i}`)
    const r = buildParamOptions(many, '')
    expect(r.total).toBe(4570)
    expect(r.options.length).toBe(4570)
  })
})
