<template>
  <el-form :model="settings" label-width="160px">
    <el-form-item label="ECharts 渲染器">
      <el-radio-group v-model="settings.chart_renderer">
        <el-radio value="svg">SVG（推荐 · 无损缩放 · 支持 CSS 操控）</el-radio>
        <el-radio value="canvas">Canvas（大数据量时性能更好）</el-radio>
      </el-radio-group>
    </el-form-item>

    <el-form-item label="图表 DPI">
      <el-input-number
        v-model="settings.chart_dpi"
        :min="72"
        :max="600"
        :step="1"
      />
      <div class="form-hint">
        导出图表（数据分析页「批量图表」导出的 Excel / PPT 内嵌直方图）的像素密度，
        不影响页面显示。默认 100 已按 Excel 嵌入尺寸调优；调大会显著增大导出体积。
      </div>
    </el-form-item>
  </el-form>
</template>

<script setup lang="ts">
import type { SettingsData } from '../../../types'

defineProps<{ settings: SettingsData }>()
</script>

<style scoped>
/* 与 TableSettingsForm.vue 的 .form-hint 同款：只用主题 token，明暗两套自动跟随 */
.form-hint {
  margin-left: 10px;
  font-size: var(--p-fs-dense);
  color: var(--text-3);
  line-height: 1.6;
}
</style>
