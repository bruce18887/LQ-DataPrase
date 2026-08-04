import { ref, nextTick, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { datafilesApi } from '../../../api/datafiles'

/**
 * Composable encapsulating all tag editing logic for file list tables.
 *
 * Works with both server-side paginated lists (FileListTab) and
 * client-side sliced lists (SingleFileTable) via the `filesSource` parameter.
 *
 * @param filesSource - A reactive ref to the array of file rows currently
 *   displayed. Used to find a row by id when auto-committing a suggestion.
 * @param onTagChanged  - Optional callback invoked after a tag is added or
 *   removed, so the parent can emit an event or trigger a refresh.
 */
export function useTagEditing(
  filesSource: Ref<any[]>,
  onTagChanged?: (row: any) => void,
) {
  const editingId = ref<number | null>(null)
  const newTagValue = ref('')
  const tagInputRef = ref<any>(null)
  const tagSuggestions = ref<string[]>([])
  const showTagSuggestions = ref(false)
  const selectedSuggestionIdx = ref(-1)

  let blurTimer: ReturnType<typeof setTimeout> | null = null
  let tagSuggestTimer: ReturnType<typeof setTimeout> | undefined

  function startAddTag(row: any) {
    editingId.value = row.id
    newTagValue.value = ''
    tagSuggestions.value = []
    showTagSuggestions.value = false
    selectedSuggestionIdx.value = -1
    nextTick(() => {
      const el = (tagInputRef.value as any)?.$el ?? tagInputRef.value
      if (el && typeof el.focus === 'function') el.focus()
    })
  }

  function scheduleBlurCommit(row: any) {
    if (blurTimer) clearTimeout(blurTimer)
    blurTimer = setTimeout(() => {
      blurTimer = null
      if (editingId.value !== row.id) return
      const t = newTagValue.value.trim()
      if (t) {
        commitNewTag(row)
      } else {
        editingId.value = null
        newTagValue.value = ''
      }
    }, 150)
  }

  async function commitNewTag(row: any) {
    const t = newTagValue.value.trim()
    if (!t) {
      editingId.value = null
      newTagValue.value = ''
      return
    }
    const current = Array.isArray(row.tags) ? row.tags : []
    if (current.some((x: string) => x.toLowerCase() === t.toLowerCase())) {
      ElMessage.warning(`标签「${t}」已存在`)
      editingId.value = null
      newTagValue.value = ''
      return
    }
    const next = [...current, t]
    try {
      const { data } = await datafilesApi.setTags(row.id, next)
      row.tags = data.tags
      onTagChanged?.(row)
      ElMessage.success(`已添加标签「${t}」`)
    } catch {
      // 错误 toast 由 axios 拦截器统一弹出
    } finally {
      editingId.value = null
      newTagValue.value = ''
    }
  }

  async function removeTag(row: any, tag: string) {
    const current = Array.isArray(row.tags) ? row.tags : []
    const next = current.filter((x: string) => x.toLowerCase() !== tag.toLowerCase())
    if (next.length === current.length) return
    try {
      const { data } = await datafilesApi.setTags(row.id, next)
      row.tags = data.tags
      onTagChanged?.(row)
      ElMessage.success(`已移除标签「${tag}」`)
    } catch {
      // 错误 toast 由 axios 拦截器统一弹出
    }
  }

  // Tag autocomplete suggestions
  async function fetchTagSuggestions(prefix: string) {
    if (!prefix.trim()) {
      tagSuggestions.value = []
      showTagSuggestions.value = false
      return
    }
    try {
      const { data } = await datafilesApi.listTags(prefix.trim())
      tagSuggestions.value = data.tags ?? []
      showTagSuggestions.value = tagSuggestions.value.length > 0
      selectedSuggestionIdx.value = -1
    } catch {
      tagSuggestions.value = []
      showTagSuggestions.value = false
    }
  }

  function onTagInput(e: Event) {
    const val = (e.target as HTMLInputElement).value
    newTagValue.value = val
    if (tagSuggestTimer) clearTimeout(tagSuggestTimer)
    tagSuggestTimer = setTimeout(() => fetchTagSuggestions(val), 200)
  }

  function selectSuggestion(tag: string) {
    newTagValue.value = tag
    showTagSuggestions.value = false
    tagSuggestions.value = []
    // Auto-commit the selected tag
    const row = filesSource.value.find((f: any) => f.id === editingId.value)
    if (row) commitNewTag(row)
  }

  function onTagKeydown(e: KeyboardEvent, row: any) {
    if (!showTagSuggestions.value) {
      if (e.key === 'Enter') commitNewTag(row)
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      selectedSuggestionIdx.value = Math.min(
        selectedSuggestionIdx.value + 1,
        tagSuggestions.value.length - 1,
      )
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      selectedSuggestionIdx.value = Math.max(selectedSuggestionIdx.value - 1, -1)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (selectedSuggestionIdx.value >= 0) {
        selectSuggestion(tagSuggestions.value[selectedSuggestionIdx.value])
      } else {
        showTagSuggestions.value = false
        commitNewTag(row)
      }
    } else if (e.key === 'Escape') {
      showTagSuggestions.value = false
    }
  }

  return {
    editingId,
    newTagValue,
    tagInputRef,
    tagSuggestions,
    showTagSuggestions,
    selectedSuggestionIdx,
    startAddTag,
    scheduleBlurCommit,
    commitNewTag,
    removeTag,
    onTagInput,
    selectSuggestion,
    onTagKeydown,
  }
}
