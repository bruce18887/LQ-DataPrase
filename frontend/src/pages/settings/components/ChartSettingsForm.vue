<template>
  <el-form :model="settings" label-width="160px">
    <el-form-item label="图表渲染引擎">
      <el-radio-group v-model="settings.chart_engine">
        <el-radio value="echarts">交互式 ECharts</el-radio>
        <el-radio value="matplotlib">静态 Matplotlib</el-radio>
      </el-radio-group>
    </el-form-item>

    <el-form-item label="ECharts 渲染器">
      <el-radio-group v-model="settings.chart_renderer">
        <el-radio value="svg">SVG（推荐 · 无损缩放 · 支持 CSS 操控）</el-radio>
        <el-radio value="canvas">Canvas（大数据量时性能更好）</el-radio>
      </el-radio-group>
    </el-form-item>

    <el-form-item label="图表高度 (px)">
      <el-slider
        v-model="settings.chart_height"
        :min="300"
        :max="800"
        :step="50"
        show-input
      />
    </el-form-item>

    <el-form-item label="图表 DPI">
      <el-input-number
        v-model="settings.chart_dpi"
        :min="72"
        :max="600"
        :step="1"
      />
    </el-form-item>

    <el-form-item label="直方图标签偏移">
      <el-input-number
        v-model="settings.histogram_label_offset"
        :min="0"
        :max="20"
        :step="1"
      />
    </el-form-item>
  </el-form>
</template>

<script setup lang="ts">
import type { SettingsData } from '../../../types'

defineProps<{ settings: SettingsData }>()
</script>
