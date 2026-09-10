<template>
  <div ref="chartRef" class="chart-container" />
</template>

<script setup lang="ts">
/**
 * 多文件箱线图对比（占位）。
 *
 * Task 3 只落地组件与挂载点：数据契约按 multi_lot 响应里每个 lot 的
 * q1 / median / q3 / mean / std / cpk 字段绘制，fileNames 提供图例名。
 * 真正的 ECharts 渲染在 Task 4 实现。
 */
const props = defineProps<{ lotData: any; fileNames: Record<number, string> }>()
</script>

<style scoped>
.chart-container {
  width: 100%;
  height: 100%;
  min-height: 200px;
}
</style>
