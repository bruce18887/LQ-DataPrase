<template>
  <div>
    <el-empty v-if="files.length === 0" description="请先在数据管理页面上传数据文件" />

    <!-- 每个 tab 各自选文件、各自筛数据：页头不再有全局文件选择 -->
    <el-tabs v-else v-model="activeTab" type="border-card">
      <!-- ========== 单参数分析 tab ========== -->
      <el-tab-pane label="&#128202; 单文件分析" name="single-param">
        <SingleParamTab :files="files" />
      </el-tab-pane>

      <!-- ========== 晶圆图 tab ========== -->
      <el-tab-pane label="&#128309; 晶圆图" name="wafer" lazy>
        <WaferMapPanel :files="files" />
      </el-tab-pane>

      <!-- ========== 多文件分析 tab ========== -->
      <el-tab-pane label="&#128200; 多文件分析" name="multi-file" lazy>
        <MultiFileTab :files="files" />
      </el-tab-pane>

      <!-- ========== 相关性工具 tab ========== -->
      <el-tab-pane label="&#128279; 相关性对比" name="correlation-tools" lazy>
        <CorrelationToolsTab :files="files" :active="activeTab === 'correlation-tools'" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
/**
 * 数据分析页装配层。
 *
 * 页面本身只负责两件事：拉一份文件列表给 4 个 tab，以及记住当前 tab。
 * 文件选择 / 参数列表 / 数据筛选 / 异常值处理全部在 tab 内部各持一份
 * （`stores/analysisTabs.ts`），互不影响 —— 旧结构里页头那一份
 * `selectedFileId` 会让任一 tab 改选择时静默换掉其他 tab 的数据源。
 */
import { ref, onActivated, watch } from 'vue'
import { datafilesApi } from '../../api/datafiles'
import { useAnalysisStore } from '../../stores/analysis'
import SingleParamTab from './components/SingleParamTab.vue'
import WaferMapPanel from './components/WaferMapPanel.vue'
import MultiFileTab from './components/MultiFileTab.vue'
import CorrelationToolsTab from './components/CorrelationToolsTab.vue'

const analysisStore = useAnalysisStore()

const files = ref<any[]>([])
const activeTab = ref(analysisStore.activeTab)

// 「进入即拉」只挂 onActivated（同 `DataManagement.vue` 的口径）：本页被
// `MainLayout.vue:12` 的 `<keep-alive :max="10">` 缓存，首次进入 mounted 与 activated
// **都**触发 —— 旧写法 `onMounted(loadFiles)` 加上 activated 里那一次，
// 一次导航发两条 `/files/options/`。刻意不再 onMounted。
onActivated(async () => {
  // keep-alive 回来时文件列表可能已变（数据管理页新增/删除）：重新拉一次，
  // 各 tab 的 useTabFileParams 会据此校验自己已选文件的有效性
  await loadFiles()
  // 仪表板「测试项总览」跳转可能在本页缓存期间改过 store，需回读
  activeTab.value = analysisStore.activeTab
})

async function loadFiles() {
  try {
    // 下拉只需要标量列：走轻量 options 端点（不算 stage/data_date、不 join owner），
    // 避免 page_size=9999 的全量列表序列化开销。include_error 保持旧下拉的可见范围。
    const { data } = await datafilesApi.getOptions({ include_error: 1 })
    files.value = Array.isArray(data) ? data : data.results || []
  } catch {
    // silently fail
  }
}

watch(activeTab, (val) => { analysisStore.activeTab = val })
</script>

<style scoped>
/* sticky 顶栏（AnalysisTabLayout 的 .toolbar）要以 .content-area 为滚动祖先：
   EP 的 .el-tabs__content 默认 overflow:hidden 会把 sticky 困在 tab 内容盒里、
   相对页面滚动失效。放开后顶栏才能在滚到下方时贴住视口顶部。 */
:deep(.el-tabs__content) {
  overflow: visible;
}

:deep(.el-tabs--border-card) {
  background-color: var(--bg-2);
  border: 1px solid var(--border-2);
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.06);
}

:deep(.el-tabs--border-card > .el-tabs__header) {
  background-color: var(--bg-3);
  border-bottom: 1px solid var(--border-2);
}

:deep(.el-tabs--border-card > .el-tabs__header .el-tabs__item) {
  color: var(--text-2);
  border-right: 1px solid var(--border-2);
}

:deep(.el-tabs--border-card > .el-tabs__header .el-tabs__item.is-active) {
  background-color: var(--bg-2);
  color: var(--brand);
  font-weight: 600;
}

:deep(.el-tabs--border-card > .el-tabs__header .el-tabs__item:hover) {
  color: var(--brand);
}

:deep(.el-empty) {
  --el-empty-description-color: var(--text-2);
}
</style>
