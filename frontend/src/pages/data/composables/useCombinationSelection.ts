import { ref, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { combinationsApi } from '../../../api/combinations'
import { datafilesApi } from '../../../api/datafiles'
import type { DataCombination } from '../../../types'

export interface CombinationImportPayload {
  combinationId: number
  batchNo?: string
}

interface CombinationSelectionOptions {
  selectedIds: Ref<number[]>
  onFilterChange: () => void
  onAssigned: () => void | Promise<void>
}

/** 文件列表的组合选项、服务端筛选与批量归组状态。 */
export function useCombinationSelection({
  selectedIds,
  onFilterChange,
  onAssigned,
}: CombinationSelectionOptions) {
  const combinations = ref<DataCombination[]>([])
  const combinationFilter = ref<number | null>(null)
  const importDialogVisible = ref(false)

  async function loadCombinations() {
    try {
      const { data } = await combinationsApi.list()
      combinations.value = Array.isArray(data) ? data : []
    } catch {
      combinations.value = []
    }
  }

  function onCombinationFilterChange(value: number | null) {
    combinationFilter.value = value
    onFilterChange()
  }

  async function openImportDialog() {
    if (selectedIds.value.length === 0) {
      ElMessage.warning('请先勾选要归组的文件')
      return
    }
    importDialogVisible.value = true
    await loadCombinations()
  }

  async function assignCombination(payload: CombinationImportPayload) {
    if (selectedIds.value.length === 0) return
    try {
      await datafilesApi.assignCombination({
        fileIds: [...selectedIds.value],
        combinationId: payload.combinationId,
        ...(payload.batchNo !== undefined ? { batchNo: payload.batchNo } : {}),
      })
      importDialogVisible.value = false
      ElMessage.success(`已将 ${selectedIds.value.length} 个文件加入组合`)
      await onAssigned()
    } catch {
      // 请求失败由 axios 统一管线提示；保留弹窗与选择，便于重试。
    }
  }

  return {
    combinations,
    combinationFilter,
    importDialogVisible,
    loadCombinations,
    onCombinationFilterChange,
    openImportDialog,
    assignCombination,
  }
}
