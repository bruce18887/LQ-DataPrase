/**
 * 会话级子集面板（spec D4：独立于 ChartDock，不进账号记忆）。
 * 模块单例仿 useChartDock；切文件清空（R5），换账号由 auth 复位调
 * resetSubsetPanels()。切参数**不清空**（2026-11-12 子集跟进计划的显式例外）：
 * 首次加载成功把 value_range 选区固化成 serials（fixateSelection 消费响应
 * selection_serials），切参数时 serials 面板对新参数重查；后端没回 serials 的
 * value_range 面板冻结在原参数原结果。请求体构造是纯函数 buildSubsetRequest（T2 承载）。
 */
import { ref, reactive, watch, effectScope } from 'vue'
import api from '../../../api'
import { formatError } from '../../../utils/error'
import { useSingleTabStore } from '../../../stores/analysisTabs'
import { buildSubsetRequest, fixateSelection, type ChartSelection } from './selectionGeometry'

export interface SubsetPanel {
  id: number
  param: string
  selection: ChartSelection
  result: any | null
  loading: boolean
  error: string | null
  /** 内部字段：load 代际号，切参数连发时丢弃过期响应（createPanel 初始 0） */
  epoch: number
}

function create() {
  const panels = ref<SubsetPanel[]>([])
  let nextId = 1
  const store = useSingleTabStore()

  async function load(panel: SubsetPanel) {
    // 代际号：切参数会对同一面板连发 load，过期响应不得覆盖新结果；
    // loading 由最新一次 load 接管（旧的 finally 不得提前收起骨架）
    const myEpoch = ++panel.epoch
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
      if (panel.epoch !== myEpoch) return  // 过期响应丢弃
      // api 拦截器返回完整 AxiosResponse（.data 解包在 useAsyncData 里做，
      // 这里直连 api.post，须自取 resp.data；响应体形如 { results: { [param]: {...} } }）
      panel.result = resp.data?.results?.[panel.param] ?? null
      if (!panel.result) panel.error = '选区内无有效数值数据'
      // 首次加载成功：value_range 固化为 serials（后端回传命中行序列号），
      // 之后切参数以 serials 对新参数重查；无回传则保持 value_range（冻结）
      panel.selection = fixateSelection(panel.selection, resp.data)
    } catch (e) {
      if (panel.epoch !== myEpoch) return
      panel.error = formatError(e, '子集数据加载失败')
    } finally {
      if (panel.epoch === myEpoch) panel.loading = false
    }
  }

  function createPanel(selection: ChartSelection) {
    if (!store.fileId || !store.selectedParam) return
    // reactive：load 里就地改 loading/result/error 必须经响应式代理才触发 UI
    const panel = reactive<SubsetPanel>({
      id: nextId++, param: store.selectedParam, selection,
      result: null, loading: true, error: null, epoch: 0,
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

  // detached scope：单例 watch 不能绑在首个调用组件的作用域上——登出/401 卸载
  // MainLayout 会停掉它，而单例不重建、resetSubsetPanels 只清不重臂 ⇒ 重新登录后
  // 切文件不再清面板、切参数不再跟随重查（R5 泄漏）。effectScope(true) 脱离组件作用域常驻。
  const scope = effectScope(true)
  scope.run(() => {
    // 切文件清空（R5）；换账号由 resetSubsetPanels 显式清
    watch(() => store.fileId, clearAll)
    // 切参数不清空（本计划显式例外）：serials 面板跟随新参数重查，
    // value_range 面板（后端没回 serials）跳过 → 冻结在原参数原结果
    watch(() => store.selectedParam, (p) => {
      if (!p) return
      for (const panel of panels.value) {
        if (panel.selection.kind !== 'serials') continue
        panel.param = p
        void load(panel)
      }
    })
  })

  return { panels, create: createPanel, remove, clearAll, retry }
}

let singleton: ReturnType<typeof create> | null = null

export function useSubsetPanels() {
  if (!singleton) singleton = create()
  return singleton
}

/** 登出/登入（stores/auth.ts）调用：不赌 fileId 一定变，显式清空。 */
export function resetSubsetPanels() { singleton?.clearAll() }
