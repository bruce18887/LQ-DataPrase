<!-- frontend/src/pages/analysis/components/Site3DChart.vue
     3D 站点柱阵的薄壳：容器 + useChart(canvas) + 两种降级 + 图下提示条。
     业务计算全在 composables/site3dOption.ts（纯函数，由 T2 钉），这里不写算法。 -->
<template>
  <div class="site3d-chart">
    <el-alert
      v-if="!webglAvailable"
      class="site3d-alert"
      type="warning"
      show-icon
      :closable="false"
      title="当前环境不支持 WebGL，无法显示 3D 站点柱阵；同屏直方图不受影响"
    />
    <el-alert
      v-else-if="!hasSites"
      class="site3d-alert"
      type="info"
      show-icon
      :closable="false"
      title="该文件没有 Site 列，无法进行站点统计"
    />
    <template v-else>
      <div
        ref="chartRef"
        class="site3d-canvas"
        data-site3d-canvas
        role="img"
        :aria-label="`3D 站点柱阵：${siteCount} 个 Site × ${binCount} 个 bin，占比对全站测试次数`"
      />
      <p class="site3d-hint">规格限（LSL/USL）不在 3D 图中绘制，请看同屏直方图</p>
    </template>
  </div>
</template>

<script lang="ts">
/**
 * 模块级一次性探测（不进 setup：每个实例都探一次 = 每勾选一次就建一张 canvas）。
 * 探不到就**不建图**、只出提示——用户 2026-11-04 拍板不做「退化成 2D 分组柱」的
 * 第二条渲染路径，两条路径的口径/主题/tooltip 都要各维护一份，维护成本高于它的价值。
 */
function detectWebGL(): boolean {
  try {
    const c = document.createElement('canvas')
    return !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    return false
  }
}
const webglProbe = detectWebGL()
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
// 副作用式注册：echarts-gl 只有被 import 进来才会把 bar3D/grid3D 注册到同一个 echarts
// 实例上。**少了这一行，option 里写 `type: 'bar3D'` 会静默画不出任何东西**（容器在、
// canvas 在、系列不存在）。必须是**静态**副作用导入：实测 `import('echarts-gl')`/
// `await import('echarts-gl')` 这种动态形态会被 vue-tsc 判 TS7016（该包无 .d.ts，
// 动态导入要推返回值类型），而静态 `import 'x'` 不消费绑定所以干净。
// 本组件自身已经是 defineAsyncComponent 的异步块 ⇒ 这行天然落在同一异步 chunk 里，
// 冷启动入口不会加载它（spec §2「冷启动字节不变」）。
import 'echarts-gl'
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import {
  applyDefaultView,
  applyView,
  buildSite3DOption,
  defaultSite3DView,
  type Site3DTheme,
} from '../composables/site3dOption'
import { isSameSite3DView, readLiveView, type Site3DView } from '../composables/site3dView'
import {
  getCachedChartState,
  isMemoryEnabled,
  loadChartMemory,
  saveChartState,
} from '../../../composables/useChartMemory'
import type { OutlierMode } from '../composables/histogramBins'

const props = defineProps<{
  /** histogram 响应的单参数结果（与 HistogramChart 同一份 histResult） */
  result: any
  param: string
  outlierHandling: OutlierMode
  rangeType: string
  /** 面板头图标每点一次 +1：复位走 props-down，不靠 defineExpose（异步组件下 ref 层数不确定） */
  resetEpoch: number
}>()

// 模块级探测结果的 setup 别名（模板只认 setup 绑定；探测本体见上方普通 <script> 块）
const webglAvailable = webglProbe

const { colors, isDark, grid3DTheme } = useEChartsTheme()

const hasSites = computed(() => Object.keys(props.result?.site_histograms ?? {}).length > 0)
const binCount = computed(() => props.result?.bin_centers?.length ?? 0)
const siteCount = computed(() => Object.keys(props.result?.site_histograms ?? {}).length)

/**
 * 当前机位（specs/2026-11-05 §4）：同步读账号记忆缓存；没有就等 loadChartMemory 迟到补。
 * 记忆关闭（用户主动关）时不读不写，等价于「始终默认机位」。
 */
const currentView = ref<Site3DView | null>(
  isMemoryEnabled() === false ? null : (getCachedChartState()?.site3dView ?? null),
)
// 首帧是否已带账号视角：有就不必再被迟到加载「补」一次
const hadCachedView = currentView.value !== null
// 用户（含复位）是否已定过视角：迟到加载不许覆盖刚调好的机位
let viewDecided = false
// 是否有尚未落库的用户改动：没动过的默认机位不许在切页/卸载时当成改动写账号
let userTouched = false

function buildOption() {
  // 重渲染（切参数/切主题/keep-alive 恢复）**之前**先把真实相机读回来，直接带进新
  // option —— 不依赖 reset 事件或任何时序。读不到（实例尚未创建）才用 currentView。
  const live = readLiveView(chartInstance.value)
  // 同步回退值：实例被重建时 buildOption 读不到 live，不能拿过期机位把用户拉回去。
  // （这不等于「用户已定过视角」——迟到加载的守卫用的是显式标记。）
  if (live) currentView.value = live
  const theme: Site3DTheme = { isDark: isDark.value, colors: colors.value, grid3D: grid3DTheme.value }
  // null（无 Site 列 / 空网格）不该走到这里：模板那两条 v-if 已经把容器挡住了
  return buildSite3DOption(props.result, theme, {
    mode: props.outlierHandling,
    rangeType: props.rangeType,
    param: props.param,
    view: live ?? currentView.value ?? undefined,
  }) ?? {}
}

// 渲染器恒为 canvas：gl 只吃 canvas（不传第 4 参时全局默认是 svg，会被 useChart
// 的 ensureRenderer 判成「渲染器不符」反复 dispose 重建）。主题切换不必自己挂——
// useChart 已 watch themeStore.currentTheme 重渲染。
const { chartRef, chartInstance } = useChart(
  buildOption,
  [() => props.result, () => props.outlierHandling, () => props.rangeType, () => props.param],
  'chartRef',
  () => 'canvas',
)
void chartRef // 绑模板 <div ref="chartRef">（noUnusedLocals 需要显式消费一次）

/** 读一次实时相机并落账号记忆（防抖在记忆模块内，这里只管 400ms 静置） */
let settleTimer: ReturnType<typeof setTimeout> | null = null
function flushView() {
  if (settleTimer) {
    clearTimeout(settleTimer)
    settleTimer = null
  }
  const live = readLiveView(chartInstance.value)
  if (!live) return
  const prev = currentView.value
  currentView.value = live
  if (!userTouched) return // 没动过：已加载的机位（或默认机位）不该被当成用户改动落库
  userTouched = false
  // 静置后再比一次：滚轮在事件当刻还没落到相机上，只有这里才能判出真变化
  if (prev && isSameSite3DView(prev, live)) return
  saveChartState({ site3dView: live })
}
function scheduleSettle() {
  if (settleTimer) clearTimeout(settleTimer)
  settleTimer = setTimeout(flushView, 400)
}
function onInteractionSettled() {
  const live = readLiveView(chartInstance.value)
  if (!live) return
  // 单击/tooltip 也会来 pointerup：机位没动就不算用户决定——否则会挡住迟到加载，
  // 还会把未动过的默认机位写进账号。
  if (currentView.value && isSameSite3DView(live, currentView.value)) return
  userTouched = true
  viewDecided = true
  scheduleSettle()
}
function onWheel() {
  // 滚轮只改 gl 的 `_zoomSpeed`，阻尼在后续帧才落到相机：事件当刻读不出变化，
  // 不能按「与 currentView 相等」跳过，否则单次滚轮永远不落库。
  viewDecided = true
  userTouched = true
  scheduleSettle()
}

// 容器可能被 v-if 换掉（有/无 Site、WebGL 分支），绑在 ref 上而不是 onMounted 一次
watch(
  chartRef,
  (el, old) => {
    old?.removeEventListener('pointerup', onInteractionSettled)
    old?.removeEventListener('wheel', onWheel)
    el?.addEventListener('pointerup', onInteractionSettled)
    el?.addEventListener('wheel', onWheel)
  },
  { flush: 'post' },
)

// keep-alive 切页/组件销毁：立即冲刷最后一段机位（实例此时还在，可读）
onDeactivated(flushView)
onBeforeUnmount(() => {
  chartRef.value?.removeEventListener('pointerup', onInteractionSettled)
  chartRef.value?.removeEventListener('wheel', onWheel)
  flushView()
})

// 记忆首帧没赶上（少见：进页时设置还没取到）：迟到补写一次。
// 用显式标记判「要不要补」——实时机位在重渲染时也会被读，但那不是用户的决定。
loadChartMemory().then((r) => {
  if (r.memoryEnabled === false || !r.state.site3dView) return
  if (hadCachedView || viewDecided) return
  currentView.value = r.state.site3dView
  applyView(chartInstance.value, r.state.site3dView)
}).catch(() => { /* 记忆拿不到就走默认机位 */ })

// 合并式复位：写默认机位；同时更新 currentView 与账号记忆，
// 否则下一次重渲染（切参数/切主题）会按旧视角把刚复位的图拉回去。
watch(() => props.resetEpoch, () => {
  // 防抖窗口里残留的拖拽可能落在 animateTo 中途，先取消再复位
  if (settleTimer) {
    clearTimeout(settleTimer)
    settleTimer = null
  }
  userTouched = false
  viewDecided = true
  applyDefaultView(chartInstance.value)
  currentView.value = defaultSite3DView()
  saveChartState({ site3dView: defaultSite3DView() })
})
</script>

<style scoped>
.site3d-chart {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.site3d-canvas {
  flex: 1;
  min-height: 0;
  width: 100%;
}

/* 图下信息条：与 OutlierHintBar 同一族的位置与字号，DOM 侧用 var(--token)（R7①） */
.site3d-hint {
  flex-shrink: 0;
  margin: 4px 0 0;
  padding: 4px 8px;
  font-size: var(--p-fs-dense);
  color: var(--text-3, #9ca3af);
}

.site3d-alert {
  align-self: start;
  margin: 16px;
  height: auto;
}
</style>
