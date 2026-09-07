<template>
  <div class="analysis-tab-layout">
    <!-- 顶部工具栏 -->
    <div v-if="$slots.toolbar" class="toolbar dp-analysis-toolbar">
      <slot name="toolbar" />
    </div>

    <!-- 主内容区：左侧配置面板 + 右侧图表 -->
    <el-row :gutter="12" class="main-row">
      <!-- 左侧面板 -->
      <el-col :span="leftPanelSpan" class="left-panel">
        <slot name="left-panel" />
      </el-col>

      <!-- 右侧面板 -->
      <el-col
        :span="rightPanelSpan"
        class="right-panel"
        v-loading="loading"
        element-loading-text="正在分析数据..."
      >
        <slot name="right-panel" />
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  loading?: boolean
  leftPanelSpan?: number
  rightPanelSpan?: number
}>(), {
  loading: false,
  leftPanelSpan: 6,
  rightPanelSpan: 18,
})
</script>

<style scoped>
.analysis-tab-layout {
  padding: 0;
}

/* .toolbar 盒样式来自共享 .dp-analysis-toolbar（styles/utilities.css） */

.main-row {
  margin-bottom: 16px;
}

.left-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.right-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
</style>
