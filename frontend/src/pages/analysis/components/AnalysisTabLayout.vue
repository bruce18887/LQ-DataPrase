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
  /* 左栏宽度下限（2026-09-14）。el-col 的 25% 在 1920 视口 125% 缩放（→1536 CSS px）
     下只剩 307px，而栏内两张表的列宽由内容决定（实测内在宽：范围对比 275px、
     Site统计 319px）→ Gap/Unit、>Max 列在视口里直接看不到（见 table-zoom-fit.spec）。
     取 385 = 最宽表 319 + 卡片内边距 30 + 余量 36（Yield 单元格随样本量变长）。
     min-width 优先于 el-col 的内联 max-width:25%：窄视口保住下限，宽视口仍按 25% 走。 */
  min-width: 385px;
}

/* 视口窄到「左栏下限 + 图表」都放不下时改纵向堆叠（左栏整行、图表在下）。
   el-col 的内联 flex-basis/max-width 按行方向计算，纵向后必须复位。 */
@media (max-width: 1120px) {
  .main-row {
    flex-direction: column;
  }

  .left-panel,
  .right-panel {
    flex: 1 1 auto !important;
    max-width: 100% !important;
  }
}

.right-panel {
  /* el-col-18 是 flex:0 0 75%，不可收缩：左栏被 min-width 垫高后两者之和会超过行宽
     （125% 缩放下 385 + 921 = 1306 > 1228），而 .content-area 是 overflow-x:hidden，
     多出来的图表右缘会被直接裁掉。改吃剩余空间：任何缩放下左右之和恒等于行宽。 */
  flex: 1 1 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
</style>
