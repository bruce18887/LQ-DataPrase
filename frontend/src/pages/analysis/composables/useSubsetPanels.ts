/**
 * 会话级子集面板（spec D4：独立于 ChartDock，不进账号记忆）。
 * 模块单例仿 useChartDock；切文件/切参数清空（R5），换账号由 auth 复位调
 * resetSubsetPanels()。请求体构造是纯函数 buildSubsetRequest（T2 承载）。
 */
import { ref, reactive, watch } from 'vue'
import api from '../../../api'
import { formatError } from '../../../utils/error'
import { useSingleTabStore } from '../../../stores/analysisTabs'
import { buildSubsetRequest, type ChartSelection } from './selectionGeometry'

export interface SubsetPanel {
  id: number
  param: string
  selection: ChartSelection
  result: any | null
  loading: boolean
  error: string | null
}

function create() {
  const panels = ref<SubsetPanel[]>([])
  let nextId = 1
  const store = useSingleTabStore()

  async function load(panel: SubsetPanel) {
    panel.loading = true
    panel.error = null
    try {
      const ctx = {
        fileId: store.fileId as number,
        ignoreNoLimit: store.ignoreNoLimit,
        ignoreNoTestValue: store.ignoreNoTestValue,
        dataOnlyBin1: store.dataOnlyBin1,
        onlyFailTestItem: store.onlyFailTestItem,
        onlyLowCpk: store.onlyLowCpk,
        iqrMultiplier: store.iqrMultiplier,
        chartConfig: store.chartConfig,
      }
      const resp = await api.post(
        '/analysis/histogram/',
        buildSubsetRequest(ctx, panel.param, panel.selection),
        { silent: true },
      )
      // api 拦截器返回完整 AxiosResponse（.data 解包在 useAsyncData 里做，
      // 这里直连 api.post，须自取 resp.data；响应体形如 { results: { [param]: {...} } }）
      panel.result = resp.data?.results?.[panel.param] ?? null
      if (!panel.result) panel.error = '选区内无有效数值数据'
    } catch (e) {
      panel.error = formatError(e, '子集数据加载失败')
    } finally {
      panel.loading = false
    }
  }

  function createPanel(selection: ChartSelection) {
    if (!store.fileId || !store.selectedParam) return
    // reactive：load 里就地改 loading/result/error 必须经响应式代理才触发 UI
    const panel = reactive<SubsetPanel>({
      id: nextId++, param: store.selectedParam, selection,
      result: null, loading: true, error: null,
    })
    panels.value = [...panels.value, panel]
    void load(panel)
  }

  function remove(id: number) { panels.value = panels.value.filter((p) => p.id !== id) }
  function clearAll() { panels.value = [] }
  function retry(id: number) {
    const p = panels.value.find((x) => x.id === id)
    if (p) void load(p)
  }

  watch([() => store.fileId, () => store.selectedParam], clearAll)

  return { panels, create: createPanel, remove, clearAll, retry }
}

let singleton: ReturnType<typeof create> | null = null

export function useSubsetPanels() {
  if (!singleton) singleton = create()
  return singleton
}

/** 登出/登入（stores/auth.ts）调用：不赌 fileId 一定变，显式清空。 */
export function resetSubsetPanels() { singleton?.clearAll() }