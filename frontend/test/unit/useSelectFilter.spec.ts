import { describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import { useSelectFilter } from '../../src/pages/data/composables/useSelectFilter'

function mount<T extends string | number>(src: T[], sel: T[], limit?: number, focusOnOpen = false) {
  const source = ref(src) as { value: T[] }
  const selected = ref(sel) as { value: T[] }
  const emitted: T[][] = []
  const api = useSelectFilter<T>({
    source: () => source.value,
    selected: () => selected.value,
    onChange: (v) => emitted.push(v),
    limit,
    focusOnOpen,
  })
  return { api, source, selected, emitted }
}

describe('useSelectFilter', () => {
  it('kw 去空白并转小写', () => {
    const { api } = mount(['A', 'B'], [])
    api.filterMethod('  A b ')
    expect(api.kw.value).toBe('a b')
  })

  it('空关键词的 matches 是空数组，不是全量', () => {
    const { api } = mount(['A', 'B'], [])
    expect(api.matches.value).toEqual([])
  })

  it('matches 大小写不敏感，数字按子串匹配', () => {
    const { api } = mount<string>(['Alpha', 'Beta'], [])
    api.filterMethod('al')
    expect(api.matches.value).toEqual(['Alpha'])
    const nums = mount<number>([10123, 20000], [])
    nums.api.filterMethod('012')
    expect(nums.api.matches.value).toEqual([10123])
  })

  it('selectOptions 无关键词给全集，有关键词给匹配集', () => {
    const { api } = mount(['Alpha', 'Beta'], [])
    expect(api.selectOptions.value.map((o) => o.value)).toEqual(['Alpha', 'Beta'])
    api.filterMethod('be')
    expect(api.selectOptions.value.map((o) => o.value)).toEqual(['Beta'])
  })

  it('source 是响应式的：源列表异步换掉后 selectOptions 跟着走', () => {
    const { api, source } = mount<string>(['A', 'B'], [])
    expect(api.selectOptions.value.map((o) => o.value)).toEqual(['A', 'B'])
    source.value = ['C']
    expect(api.selectOptions.value.map((o) => o.value)).toEqual(['C'])
  })

  it('selectAll 尊重 limit', () => {
    const many = Array.from({ length: 250 }, (_, i) => i)
    const { api, emitted } = mount(many, [], 200)
    api.selectAll()
    expect(emitted[0]).toHaveLength(200)
  })

  it('selectMatches 尊重 limit（Enter 全选不能绕过上限）', () => {
    const many = Array.from({ length: 250 }, (_, i) => `s${i}`)
    const { api, emitted } = mount<string>(many, [], 200)
    api.filterMethod('s')
    api.selectMatches()
    expect(emitted[0]).toHaveLength(200)
  })

  it('clearAll 发空数组', () => {
    const { api, emitted } = mount(['A'], ['A'])
    api.clearAll()
    expect(emitted[0]).toEqual([])
  })

  it('selectMatches 并集去重、已选在前；空/无匹配不发', () => {
    const { api, emitted } = mount([5, 7, 9], [5])
    api.filterMethod('7')
    api.selectMatches()
    expect(emitted[0]).toEqual([5, 7])
    api.filterMethod('zzz')
    api.selectMatches()
    expect(emitted).toHaveLength(1)
  })

  it('Enter 只在有匹配时拦截并全选', () => {
    const { api, emitted } = mount(['Alpha'], [])
    const ev = { key: 'Enter', preventDefault: vi.fn(), stopPropagation: vi.fn() }
    api.filterMethod('al')
    api.onSelectKeydown(ev as unknown as KeyboardEvent)
    expect(ev.preventDefault).toHaveBeenCalled()
    expect(ev.stopPropagation).toHaveBeenCalled()
    expect(emitted[0]).toEqual(['Alpha'])
    const ev2 = { key: 'Enter', preventDefault: vi.fn(), stopPropagation: vi.fn() }
    api.filterMethod('zzz')
    api.onSelectKeydown(ev2 as unknown as KeyboardEvent)
    expect(ev2.preventDefault).not.toHaveBeenCalled()
  })

  it('关闭时清空 kw；无 selectRef 时打开不抛', () => {
    const { api } = mount(['A'], [])
    api.filterMethod('a')
    api.onVisibleChange(false)
    expect(api.kw.value).toBe('')
    expect(() => api.onVisibleChange(true)).not.toThrow()
  })

  it('focusOnOpen 时打开后聚焦过滤 input', async () => {
    const { api } = mount(['A'], [], undefined, true)
    const fakeInput = { value: '', focus: vi.fn() }
    api.selectRef.value = { $el: { querySelector: () => fakeInput } } as unknown as typeof api.selectRef.value
    api.onVisibleChange(true)
    await nextTick()
    expect(fakeInput.focus).toHaveBeenCalledTimes(1)
  })

  it('focusOnOpen: false 时打开不回填焦点', async () => {
    const { api } = mount(['A'], [], undefined, false)
    const fakeInput = { value: '', focus: vi.fn() }
    api.selectRef.value = { $el: { querySelector: () => fakeInput } } as unknown as typeof api.selectRef.value
    api.onVisibleChange(true)
    await nextTick()
    expect(fakeInput.focus).not.toHaveBeenCalled()
  })

  it('clearFilterInput 同步 EP 内部 input（DOM 契约）', () => {
    const { api } = mount(['A'], [])
    const fakeInput = { value: '1', dispatchEvent: vi.fn() }
    api.selectRef.value = { $el: { querySelector: () => fakeInput } } as unknown as typeof api.selectRef.value
    api.filterMethod('a')
    api.clearFilterInput()
    expect(api.kw.value).toBe('')
    expect(fakeInput.value).toBe('')
    expect(fakeInput.dispatchEvent).toHaveBeenCalledTimes(1)
    const event = fakeInput.dispatchEvent.mock.calls[0][0] as Event
    expect(event.type).toBe('input')
    expect(event.bubbles).toBe(true)
  })
})
