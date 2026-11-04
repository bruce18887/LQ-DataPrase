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
import { computed, watch } from 'vue'
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
import { applyDefaultView, buildSite3DOption, type Site3DTheme } from '../composables/site3dOption'
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

function buildOption() {
  const theme: Site3DTheme = { isDark: isDark.value, colors: colors.value, grid3D: grid3DTheme.value }
  // 模板的两条 v-if 只挡「无 WebGL」与「无 Site 列」。空网格（bin_centers 为空）线上
  // 不可达——后端只要有 result 就发 26 个中心；真发生的话 buildSite3DOption 会返回 null，
  // 这里回退 {}，结果是空 canvas 而不是崩溃（与 HistogramChart 的 binCenters 空守卫同族）。
  return buildSite3DOption(props.result, theme, {
    mode: props.outlierHandling,
    rangeType: props.rangeType,
    param: props.param,
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

// 合并式复位：只写 grid3D.viewControl，不动 series（notMerge 会把柱数据一起换掉）。
// 视角常量单一来源在 site3dOption.ts（T2 ⑧ 钉住初始机位与复位同源）。
watch(() => props.resetEpoch, () => applyDefaultView(chartInstance.value))
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
