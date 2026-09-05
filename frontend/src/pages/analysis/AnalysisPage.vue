<template>
  <div>
    <h2>&#128200; 数据分析</h2>

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
import { ref, onMounted, onActivated, watch } from 'vue'
import api from '../../api'
import { useAnalysisStore } from '../../stores/analysis'
import SingleParamTab from './components/SingleParamTab.vue'
import WaferMapPanel from './components/WaferMapPanel.vue'
import MultiFileTab from './components/MultiFileTab.vue'
import CorrelationToolsTab from './components/CorrelationToolsTab.vue'

const analysisStore = useAnalysisStore()

const files = ref<any[]>([])
const activeTab = ref(analysisStore.activeTab)

onMounted(loadFiles)
onActivated(async () => {
  // keep-alive 回来时文件列表可能已变（数据管理页新增/删除）：重新拉一次，
  // 各 tab 的 useTabFileParams 会据此校验自己已选文件的有效性
  await loadFiles()
  // 仪表板「测试项总览」跳转可能在本页缓存期间改过 store，需回读
  activeTab.value = analysisStore.activeTab
})

async function loadFiles() {
  try {
    // 分页会静默截断文件列表（默认 PAGE_SIZE=20），下拉将选不到旧文件
    const { data } = await api.get('/files/', { params: { page_size: 9999 } })
    files.value = Array.isArray(data) ? data : data.results || []
  } catch {
    // silently fail
  }
}

watch(activeTab, (val) => { analysisStore.activeTab = val })
</script>

<style scoped>
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
