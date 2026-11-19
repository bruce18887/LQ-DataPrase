import { computed, nextTick, ref, type ComputedRef, type Ref } from 'vue'
import { filterByKeyword, toOptions, type SelectOption } from '../../../utils/selectOptions'

interface SelectElLike { $el?: HTMLElement }

export interface UseSelectFilterOptions<T extends string | number> {
  source: () => T[]
  selected: () => T[]
  onChange: (value: T[]) => void
  limit?: number
  focusOnOpen?: boolean
}

export interface UseSelectFilterReturn<T extends string | number> {
  selectRef: Ref<SelectElLike | undefined>
  kw: ComputedRef<string>
  matches: ComputedRef<T[]>
  selectOptions: ComputedRef<SelectOption[]>
  filterMethod: (query: string) => void
  clearFilterInput: () => void
  onVisibleChange: (visible: boolean) => void
  onSelectKeydown: (event: KeyboardEvent) => void
  selectAll: () => void
  clearAll: () => void
  selectMatches: () => void
}

export function useSelectFilter<T extends string | number>(
  opts: UseSelectFilterOptions<T>,
): UseSelectFilterReturn<T> {
  const filterText = ref('')
  const selectRef = ref<SelectElLike>()

  const kw = computed(() => filterText.value.trim().toLowerCase())

  /** 空关键词必须自己给 []：filterByKeyword 空串返回入参本身（引用契约），
   *  透传会把「没输入」变成「全匹配」⇒ footer 谎报 + Enter 变成全选全集 */
  const matches = computed<T[]>(() =>
    kw.value ? filterByKeyword(opts.source(), filterText.value) : [])

  /** v2 的 filter-method 不过滤（useSelect.mjs:114-132）⇒ 预过滤 */
  const selectOptions = computed(() =>
    toOptions(kw.value ? matches.value : opts.source()))

  const applyLimit = (list: T[]): T[] =>
    opts.limit != null && list.length > opts.limit ? list.slice(0, opts.limit) : list

  const filterInput = (): HTMLInputElement | null | undefined =>
    selectRef.value?.$el?.querySelector('input')

  const clearFilterInput = () => {
    filterText.value = ''
    const input = filterInput()
    if (input) {
      input.value = ''
      input.dispatchEvent(new Event('input', { bubbles: true }))
    }
  }

  const filterMethod = (query: string) => { filterText.value = query }

  const selectMatches = () => {
    if (matches.value.length === 0) return
    opts.onChange(applyLimit([...new Set<T>([...opts.selected(), ...matches.value])]))
    clearFilterInput()
  }

  const onSelectKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Enter' && matches.value.length > 0) {
      event.preventDefault()
      event.stopPropagation()
      selectMatches()
    }
  }

  const onVisibleChange = (visible: boolean) => {
    if (!visible) return clearFilterInput()
    if (opts.focusOnOpen) nextTick(() => filterInput()?.focus())
  }

  const selectAll = () => opts.onChange(applyLimit([...opts.source()]))
  const clearAll = () => opts.onChange([])

  return { selectRef, kw, matches, selectOptions, filterMethod,
           clearFilterInput, onVisibleChange, onSelectKeydown, selectAll, clearAll, selectMatches }
}
