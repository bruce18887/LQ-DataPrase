<!-- frontend/src/pages/settings/components/AnalysisLayoutSettings.vue
     单文件分析图表布局记忆（显示设置 tab）：总开关（随「保存设置」持久化）
     + 恢复默认布局（立即清空账号与本机状态，不依赖保存按钮）。 -->
<template>
  <el-form label-width="160px" class="chart-memory-settings">
    <el-form-item label="图表布局记忆">
      <el-switch v-model="settings.analysis_chart_memory" data-testid="chart-memory-switch" />
      <span class="chart-memory-settings__hint">记住单文件分析的图表布局与勾选（跟随账号，换设备不丢）</span>
    </el-form-item>
    <el-form-item label=" ">
      <el-button data-testid="chart-memory-reset" @click="onResetLayout">恢复默认布局</el-button>
      <span class="chart-memory-settings__hint">清除账号与本机保存的布局和勾选，下次进入分析页生效</span>
    </el-form-item>
  </el-form>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import type { SettingsData } from '../../../types'
import { clearChartMemoryState } from '../../../composables/useChartMemory'

defineProps<{ settings: SettingsData }>()

async function onResetLayout() {
  const ok = await clearChartMemoryState()
  if (ok) ElMessage.success('已恢复默认布局，下次进入分析页生效')
  else ElMessage.error('恢复失败，请稍后重试')
}
</script>

<style scoped>
.chart-memory-settings { margin-top: 8px; }
.chart-memory-settings__hint {
  margin-left: 12px;
  font-size: 12px;
  color: var(--text-2);
}
</style>
