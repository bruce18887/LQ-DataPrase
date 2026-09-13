<template>
  <div class="analysis-tab-layout">
    <!-- 顶部工具栏：sticky 冻结在滚动容器顶部（文件选择 + 参数选择/其它主控件） -->
    <div v-if="$slots.toolbar" class="toolbar dp-analysis-toolbar">
      <slot name="toolbar" />
    </div>

    <!-- 次级工具栏：随内容滚动（数据筛选行等） -->
    <div v-if="$slots['toolbar-2']" class="toolbar-2 dp-analysis-toolbar">
      <slot name="toolbar-2" />
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

/* 冻结顶栏：滚动看图表时文件选择/参数选择始终可见。
   前提是祖先链无 overflow:hidden（.el-tabs__content 的默认值由 AnalysisPage 放开）——
   .dp-analysis-toolbar 自带不透明底 + 边框，滚过的内容不会透出。 */
.toolbar {
  position: sticky;
  top: 0;
  z-index: 30;
}

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
