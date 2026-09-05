import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  useCorrelationTabStore,
  useMultiTabStore,
  useSingleTabStore,
  useWaferTabStore,
} from './analysisTabs'

/**
 * 分析页的跨 tab 状态：只剩「当前打开哪个 tab」。
 *
 * 文件选择、参数列表、数据筛选、异常值处理都按 tab 独立，收在
 * `stores/analysisTabs.ts` 的四个子 store 里（2026-09-05）——页头那份
 * 全局 `selectedFileId` 会让任一 tab 的选择静默换掉其他 tab 的数据源。
 */
export const useAnalysisStore = defineStore('analysis', () => {
  const activeTab = ref('single-param')

  /** 全量重置（含四个 tab 上下文）。目前无调用点，保留给「清空会话」类入口。 */
  function reset() {
    activeTab.value = 'single-param'
    useSingleTabStore().reset()
    useWaferTabStore().reset()
    useCorrelationTabStore().reset()
    useMultiTabStore().reset()
  }

  return {
    activeTab,
    reset,
  }
})
