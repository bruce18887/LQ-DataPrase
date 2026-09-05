/**
 * 分析页「按 tab 独立」的状态袋（2026-09-05 设计）。
 *
 * 数据分析页的 4 个 tab 各自选文件、各自筛数据：单文件分析选 A 文件、晶圆图选
 * B 文件、相关性对比选 C 文件、多文件分析选一组文件，四者互不影响。因此状态不
 * 能再是一份全局 `selectedFileId` + 一组全局开关（旧结构下任一 tab 改选择，
 * 其余 tab 的数据源与参数列表会被静默换掉）。
 *
 * 每个 tab 一个 store，字段由同一个工厂产出 —— `reset()` 复用工厂重跑，初始值
 * 只有一处定义，不会与 reset 名单漂移（lessons R5：持久化选择在上下文切换时
 * 必须显式重置）。
 *
 * 控件归属按后端生效矩阵取严（docs/specs/2026-09-02-analysis-data-controls-design.md §2）：
 *  - 晶圆图不吃任何筛选（`wafer_map` 不读这些字段，`data_only_bin1` 还会把
 *    fail die 全抹掉），所以它的状态袋里根本没有开关字段；
 *  - 多文件图表不消费前端裁剪口径，故只有「敏感度」（低 CPK 判定阈值），
 *    没有 `outlierHandling`。
 */
import { defineStore } from 'pinia'
import { ref, watch, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

/** 异常值处理模式：`exclude` 是后端与图表保留的口径，UI 目前只暴露 clip/off */
export type OutlierMode = 'clip' | 'exclude' | 'off'

/** 状态袋工厂 + 与其字段永不分叉的 reset */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function useStateBag<T extends Record<string, Ref<any>>>(make: () => T) {
  const bag = make()
  function reset() {
    const fresh = make()
    for (const key of Object.keys(fresh) as (keyof T)[]) {
      bag[key].value = fresh[key].value
    }
  }
  return { bag, reset }
}

/** 数据筛选 5 开关 + 异常值处理 + 敏感度（单文件 / 相关性两 tab 同构） */
function createFilterState() {
  return {
    ignoreNoLimit: ref(false),
    // 两个筛选测试项（参数列表），一个筛选数据行（仅 Bin1）
    ignoreNoTestValue: ref(false),
    dataOnlyBin1: ref(false),
    onlyFailTestItem: ref(false),
    onlyLowCpk: ref(false),
    outlierHandling: ref<OutlierMode>('off'),
    iqrMultiplier: ref(1.5),
  }
}

/** 同上但不含 `outlierHandling`：多文件图表不消费前端裁剪口径 */
function createFilterStateWithoutOutlier() {
  const { outlierHandling, ...rest } = createFilterState()
  void outlierHandling
  return rest
}

/** 「选择 + 参数列表 + 请求态」——文件与参数列表都是每 tab 各一份 */
function createSingleState() {
  return {
    fileId: ref<number | null>(null),
    params: ref<string[]>([]),
    selectedParam: ref(''),
    loading: ref(false),
    // 图表显示配置（仅单文件 tab 消费；数据管理页的导出面板读同一份口径）
    chartMode: ref('distribution'),
    chartConfig: ref<string[]>(['limit', 's6', 'kde']),
    rangeType: ref('RDL'),
    barWidthPercent: ref(20),
    // 柱体重合 0-100（barGap 负值）：重合越高柱组越窄、柱宽上限越高
    barOverlapPercent: ref(5),
    customLow: ref<number | null>(null),
    customHigh: ref<number | null>(null),
    ...createFilterState(),
  }
}

export const useSingleTabStore = defineStore('analysisTabSingle', () => {
  const { bag, reset } = useStateBag(createSingleState)
  return { ...bag, reset }
})

function createWaferState() {
  return {
    fileId: ref<number | null>(null),
    params: ref<string[]>([]),
    loading: ref(false),
    // 判定参数是可选的（默认「无」），留在面板本地；不进 store 就不会被
    // 误当成本 tab 的「当前参数」而参与自动回退首项
  }
}

export const useWaferTabStore = defineStore('analysisTabWafer', () => {
  const { bag, reset } = useStateBag(createWaferState)
  return { ...bag, reset }
})

function createCorrelationState() {
  return {
    fileId: ref<number | null>(null),
    params: ref<string[]>([]),
    loading: ref(false),
    ...createFilterState(),
  }
}

export const useCorrelationTabStore = defineStore('analysisTabCorrelation', () => {
  const { bag, reset } = useStateBag(createCorrelationState)
  return { ...bag, reset }
})

/**
 * 多文件分析：文件是数组（最少 2 个），图例名与柱宽各自一套，
 * 与单文件 tab 的开关互不影响（2026-08-20 起就是独立字段，此处收进自己的 store）。
 */
function createMultiState() {
  return {
    fileIds: ref<number[]>([]),
    selectedParam: ref(''),
    fileNames: ref<Record<number, string>>({}),
    chartConfig: ref<string[]>(['limit']),
    barWidthPercent: ref(20),
    rangeType: ref('RDL'),
    // 加载态由 useMultiFile 自己拿（multi_lot 一条请求同时回列表与分布）
    ...createFilterStateWithoutOutlier(),
  }
}

export const useMultiTabStore = defineStore('analysisTabMulti', () => {
  const { bag, reset } = useStateBag(createMultiState)
  const route = useRoute()
  const router = useRouter()

  // 多选状态同步到 URL query（刷新/分享链接可恢复），300ms 防抖
  function syncToQuery() {
    if (syncTimer) clearTimeout(syncTimer)
    syncTimer = setTimeout(() => {
      const q: Record<string, string> = {}
      const fileIds = bag.fileIds.value
      const selectedParam = bag.selectedParam.value
      const rangeType = bag.rangeType.value
      if (fileIds.length >= 2) q.mf_ids = fileIds.join(',')
      if (selectedParam) q.mf_param = selectedParam
      if (rangeType && rangeType !== 'RDL') q.mf_range = rangeType
      router.replace({ query: { ...route.query, ...q } })
    }, 300)
  }

  let syncTimer: ReturnType<typeof setTimeout> | null = null
  watch([bag.fileIds, bag.selectedParam, bag.rangeType], syncToQuery)

  function initFromQuery() {
    const q = route.query
    if (q.mf_ids) {
      const ids = String(q.mf_ids).split(',').map(Number).filter((n) => !isNaN(n))
      if (ids.length >= 2) bag.fileIds.value = ids
    }
    if (q.mf_param) bag.selectedParam.value = String(q.mf_param)
    if (q.mf_range) bag.rangeType.value = String(q.mf_range)
  }

  return { ...bag, reset, initFromQuery, syncToQuery }
})
