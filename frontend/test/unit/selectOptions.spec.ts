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
  it('空关键词返回入参本身（同一引用，零拷贝）', () => {
    const items = ['B', 'A']
    expect(filterByKeyword(items, '')).toEqual(['B', 'A'])
    // 万级列表在「没输入」这条最常见路径上省一次拷贝；契约是**同一引用**，
    // 改成 [...items] 本例即红（2026-11-13 质量复审 M-1/M-3）。
    expect(filterByKeyword(items, '')).toBe(items)
  })
  it('关键词无需调用方预归一化：原始大小写同样匹配', () => {
    expect(filterByKeyword(['Kelvin_VIN', 'IBLK'], 'KEL')).toEqual(['Kelvin_VIN'])
  })
  // 这条是「签名为什么收 Array<string|number>」的判据：Task 6 的序列号下拉候选是 number[]，
  // 只把 TS 类型放宽而行为仍按 string 处理（`it.toLowerCase` 当场 TypeError），本条即红。
  it('收 number[]：按十进制字面匹配，不是数值比较', () => {
    expect(filterByKeyword([1, 12, 21, 2], '1')).toEqual([1, 12, 21])
    expect(filterByKeyword([1, 12, 21, 2], '2')).toEqual([12, 21, 2])
  })
  // 泛型签名（`T extends string | number`）的判据：SerialSelector 把返回值原样当 number[] 用
  // （clamp() 的入参、emit('update:modelValue') 的载荷），签名退成 Array<string|number> 时
  // 下面两行的赋值就红。注意 vitest **不做类型检查**，这条由 `npm run build` 的 `vue-tsc -b`
  // 执行（tsconfig.json 引用 tsconfig.unit.json，其 include 覆盖 test/unit）——
  // 删掉 `: number[]` / `: string[]` 标注本条就退化成普通运行时断言，判据即失声。
  it('类型面：返回的元素类型 = 入参的元素类型（number[] 进 ⇒ number[] 出，无需转型）', () => {
    const nums: number[] = filterByKeyword([1, 12, 21, 2], '1')
    const strs: string[] = filterByKeyword(['Kelvin_VIN', 'IBLK'], 'kel')
    expect(nums).toEqual([1, 12, 21])
    expect(strs).toEqual(['Kelvin_VIN'])
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
    expect(sortPrefixFirst(items, '')).not.toBe(items)
  })
  it('关键词原始大小写不影响前缀优先', () => {
    expect(sortPrefixFirst(['APAR1', 'PAR1'], 'PAR1')).toEqual(['PAR1', 'APAR1'])
  })
  it('收 number[]：按字符串前缀与 localeCompare 排，不做数值排序', () => {
    // '1' < '12' < '2' 是字符串序；数值序会把 2 排在 12 前面 —— 这条钉住走的是前者，
    // 与 el-select-v2 实际显示的 label（`String(value)`）一致。
    expect(sortPrefixFirst([12, 2, 1], '1')).toEqual([1, 12, 2])
  })
})

describe('highlightSegments', () => {
  it('命中片段标 mark=true，且大小写不敏感', () => {
    expect(highlightSegments('Kelvin_VIN', 'kelvin')).toEqual([
      { text: 'Kelvin', mark: true },
      { text: '_VIN', mark: false },
    ])
  })
  // 与 filterByKeyword/sortPrefixFirst 同一归一化契约：关键词首尾空格不影响高亮。
  // 少了这一步就会出现「过滤命中、高亮不命中」的自相矛盾（2026-11-13 质量复审 I-1）。
  it('关键词首尾空格不影响高亮命中', () => {
    expect(highlightSegments('PAR1', '  PAR  ')).toEqual([
      { text: 'PAR', mark: true },
      { text: '1', mark: false },
    ])
  })
  it('空文本仍返回一段（调用方可以安全地 v-for 而不必判空数组）', () => {
    expect(highlightSegments('', 'x')).toEqual([{ text: '', mark: false }])
  })
  it('多处命中全部标出，顺序与原文一致', () => {
    expect(highlightSegments('AxAxA', 'ax')).toEqual([
      { text: 'Ax', mark: true },
      { text: 'Ax', mark: true },
      { text: 'A', mark: false },
    ])
  })
  it('空关键词返回单个不标亮的整段', () => {
    expect(highlightSegments('ABC', '')).toEqual([{ text: 'ABC', mark: false }])
  })
  // XSS 修复的来处：ParamSelector 的 highlightSegments 历史实现（提交 03ba0c5
  // 「参数选择器XSS」）——不走 v-html，列名里的尖括号必须是字面文本。
  // 锚点写符号+提交而不是行号：组件那边一改一删行号就指错地方（2026-11-13 批1 Task 5）。
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
  // 就等于把性能批 d1146dd 治掉的「每次击键给全部匹配项建一份 segments」（原注释在
  // ParamSelector 的 listView 历史实现里，1,702 项的文件上每次击键建 1,702 份）放回来。
  // 锚点用提交号而不是组件行号：本批 Step 3 就把那段删掉了。
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
  // 一条 it 只管一件事：下面两条同源于「过滤与高亮共用归一化契约」，但红法不同 ——
  // 「拼接无损」红在 highlightSegments 丢/多字符，「必命中一段」红在两侧归一化不一致。
  // 塞进同一条 it 时前者会先抛，后者这半个判据当场失声（2026-11-13 质量复审 #7）。
  const INVARIANT_PARAMS = [
    'PAR1', 'OTHER', 'A B', 'a  b', 'Kelvin_VIN', 'IBLK', 'V+(1)', 'XPAR1', 'P AR', 'par1x', '',
  ]
  const INVARIANT_QUERIES = [
    '  ', 'par', 'PAR ', ' a b ', 'kelvin', '+(', 'P AR', 'XPAR1 ', 'PAR1', 'A', '',
  ]
  it('不变量（无损）：分段拼回去逐字等于原 label', () => {
    for (const query of INVARIANT_QUERIES) {
      for (const o of buildParamOptions(INVARIANT_PARAMS, query).options) {
        const segs = highlightSegments(String(o.label), query)
        expect(segs.map((s) => s.text).join(''), `拼接无损: ${query}/${o.label}`).toBe(o.label)
      }
    }
  })
  // I-1 的真判据：过滤侧与高亮侧共用同一归一化契约 ⇒ 凡被 buildParamOptions 放行的项，
  // 用同一个原始 query 去算高亮必须至少命中一段。两侧各自 trim 不等于二者一致。
  it('不变量（一致）：被过滤命中的每一项，高亮必命中至少一段', () => {
    for (const query of INVARIANT_QUERIES) {
      if (!query.trim()) continue
      for (const o of buildParamOptions(INVARIANT_PARAMS, query).options) {
        expect(
          highlightSegments(String(o.label), query).some((s) => s.mark),
          `过滤命中但高亮没命中: query=${JSON.stringify(query)} label=${o.label}`,
        ).toBe(true)
      }
    }
  })
})
