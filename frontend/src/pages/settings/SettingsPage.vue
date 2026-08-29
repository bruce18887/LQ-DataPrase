<template>
  <div class="settings-page">
    <h2>⚙️ 系统设置</h2>

    <el-tabs v-model="activeTab" tab-position="left" class="settings-tabs">
      <el-tab-pane name="display" label="📊 显示设置">
        <ChartSettingsForm :settings="settings" />
      </el-tab-pane>
      <el-tab-pane name="table" label="📋 表格设置">
        <TableSettingsForm :settings="settings" />
      </el-tab-pane>
      <el-tab-pane name="cpk" label="📐 CPK 阈值">
        <CpkSettingsForm :settings="settings" />
      </el-tab-pane>
      <el-tab-pane name="export" label="📄 导出模板">
        <ExportTimeoutSettings v-model:timeout="settings.export_timeout" />
        <ExportTemplateSettings v-model:templates="settings.export_filename_templates" />
      </el-tab-pane>
      <el-tab-pane name="sftp" label="🔌 SFTP 设置">
        <SftpTimeoutSettings v-model:timeout="settings.sftp_download_timeout" />
      </el-tab-pane>
      <el-tab-pane name="paths" label="📁 存储路径">
        <SystemPathsSettings />
      </el-tab-pane>
      <el-tab-pane name="recent" label="🕐 最近文件">
        <RecentFilesSettings
          :recent-files="recentFiles"
          :max-recent-files="settings.max_recent_files"
          @update:max-recent-files="settings.max_recent_files = $event"
        />
      </el-tab-pane>
    </el-tabs>

    <div class="settings-actions">
      <el-button type="primary" size="large" @click="saveSettings">
        💾 保存设置
      </el-button>
      <el-button size="large" @click="resetDefaults">
        🔄 恢复默认
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { authApi } from '../../api/auth'
import { ElMessage, ElMessageBox } from 'element-plus'
import { setChartRenderer } from '../../utils/echarts-theme'
import type { ExportTypeKey, SettingsData } from '../../types'
import { EXPORT_TEMPLATE_META, EXPORT_TEMPLATE_KEYS } from '../../constants/export-templates'
import ChartSettingsForm from './components/ChartSettingsForm.vue'
import TableSettingsForm from './components/TableSettingsForm.vue'
import CpkSettingsForm from './components/CpkSettingsForm.vue'
import SystemPathsSettings from './components/SystemPathsSettings.vue'
import RecentFilesSettings from './components/RecentFilesSettings.vue'
import ExportTemplateSettings from './components/ExportTemplateSettings.vue'
import ExportTimeoutSettings from './components/ExportTimeoutSettings.vue'
import SftpTimeoutSettings from './components/SftpTimeoutSettings.vue'
import { setExportTimeoutSec } from '../../utils/exportTimeout'
import { setSftpTimeoutSec } from '../../utils/sftpTimeout'
import { setFilenameWrapCache } from '../../utils/filenameWrap'
import { DEFAULT_HIDDEN_COLUMNS } from '../../constants/hidden-columns'

function defaultTemplates(): Record<ExportTypeKey, string> {
  const result = {} as Record<ExportTypeKey, string>
  EXPORT_TEMPLATE_KEYS.forEach((key) => {
    result[key] = EXPORT_TEMPLATE_META[key].default
  })
  return result
}

const defaults: SettingsData = {
  page_size: 100,
  chart_height: 500,
  table_height: 700,
  chart_dpi: 150,
  cpk_a_threshold: 1.67,
  cpk_b_threshold: 1.33,
  cpk_c_threshold: 1.0,
  chart_engine: 'echarts',
  chart_renderer: 'svg' as const,
  aggrid_header_font_size: 11,
  recent_files: [],
  max_recent_files: 10,
  histogram_label_offset: 4,
  export_filename_templates: defaultTemplates(),
  export_timeout: 600,
  sftp_download_timeout: 600,
  default_hidden_columns: [...DEFAULT_HIDDEN_COLUMNS],
  filename_wrap: true,
}

const activeTab = ref('display')
const settings = ref<SettingsData>({ ...defaults })

const recentFiles = ref<Array<{ id: number; name: string; accessed_at: string }>>([])

async function loadSettings() {
  try {
    const { data } = await authApi.getSettings()
    const merged = { ...defaults }
    if (data && typeof data === 'object') {
      Object.keys(defaults).forEach((key) => {
        if (key in data) {
          ;(merged as Record<string, unknown>)[key] = data[key]
        }
      })
    }
    // 导出文件名模板逐 key 合并：后端返回的完整表缺 key 时补默认
    const remoteTemplates = (data as Record<string, unknown>)?.export_filename_templates
    if (remoteTemplates && typeof remoteTemplates === 'object') {
      const mergedTemplates = { ...defaultTemplates() }
      EXPORT_TEMPLATE_KEYS.forEach((key) => {
        const v = (remoteTemplates as Record<string, unknown>)[key]
        if (typeof v === 'string') mergedTemplates[key] = v
      })
      merged.export_filename_templates = mergedTemplates
    }
    settings.value = merged as SettingsData
    setChartRenderer(merged.chart_renderer as 'svg' | 'canvas')
    recentFiles.value = Array.isArray(data?.recent_files) ? data.recent_files : []
    // 导出超时同步到模块缓存，使导出调用点无需访问本页即可使用最新值
    setExportTimeoutSec(merged.export_timeout)
    // SFTP 下载超时同步到模块缓存（SFTP 浏览器读取此值）
    setSftpTimeoutSec(merged.sftp_download_timeout)
  } catch {
    // silently fall back to defaults
  }
}

async function saveSettings() {
  try {
    const payload: Record<string, unknown> = {
      ...settings.value,
      recent_files: recentFiles.value,
    }
    await authApi.updateSettings(payload)
    setChartRenderer(settings.value.chart_renderer)
    setExportTimeoutSec(settings.value.export_timeout)
    setSftpTimeoutSec(settings.value.sftp_download_timeout)
    setFilenameWrapCache(settings.value.filename_wrap)
    ElMessage.success('设置已保存')
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  }
}

async function resetDefaults() {
  try {
    await ElMessageBox.confirm(
      '确定恢复所有设置为默认值吗？',
      '恢复默认',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
    settings.value = { ...defaults }
    recentFiles.value = []
    ElMessage.success('已恢复默认设置（请点击保存以持久化）')
  } catch {
    // cancelled
  }
}

onMounted(() => {
  loadSettings()
})
</script>

<style scoped>
.settings-page h2 {
  margin-bottom: 20px;
  color: var(--text);
}

.settings-tabs {
  background-color: var(--bg-2);
  border: 1px solid var(--border-2);
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.06);
}

:deep(.el-tabs__header) {
  background-color: var(--bg-3);
  border-right: 1px solid var(--border-2);
  border-bottom: none;
}

:deep(.el-tabs__item) {
  color: var(--text-2);
  justify-content: flex-start;
}

:deep(.el-tabs__item.is-active) {
  color: var(--brand);
}

:deep(.el-tabs__active-bar) {
  background-color: var(--brand);
}

:deep(.el-tabs__content) {
  padding: 20px 24px;
}

.settings-actions {
  display: flex;
  gap: 16px;
  margin-top: 24px;
  margin-bottom: 40px;
}

:deep(.el-form-item__label) {
  color: var(--text);
}

:deep(.el-input__wrapper) {
  background-color: var(--bg);
  border-radius: 8px;
  box-shadow: 0 0 0 1px var(--border-2) inset;
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--brand) inset;
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--brand) inset;
}

:deep(.el-input__inner) {
  color: var(--text);
}

:deep(.el-input__inner::placeholder) {
  color: var(--text-2);
}

:deep(.el-table) {
  --el-table-bg-color: var(--bg-2);
  --el-table-tr-bg-color: var(--bg-2);
  --el-table-header-bg-color: var(--bg-3);
  --el-table-border-color: var(--border-2);
  --el-table-text-color: var(--text);
  --el-table-header-text-color: var(--text);
}

:deep(.el-table__empty-text) {
  color: var(--text-2);
}

:deep(.el-slider__runway) {
  background-color: var(--bg-3);
}

:deep(.el-slider__bar) {
  background-color: var(--brand);
}

:deep(.el-slider__button) {
  border-color: var(--brand);
}

:deep(.el-input-number) {
  --el-input-number-border-color: var(--border-2);
}

:deep(.el-input-number .el-input__wrapper) {
  background-color: var(--bg);
}

:deep(.el-select .el-input__wrapper) {
  background-color: var(--bg);
}

:deep(.el-radio__input.is-checked .el-radio__inner) {
  background-color: var(--brand);
  border-color: var(--brand);
}

:deep(.el-radio__label) {
  color: var(--text);
}

:deep(.el-empty__description) {
  color: var(--text-2);
}
</style>
