<template>
  <div class="settings-page">
    <h2>⚙️ 系统设置</h2>

    <el-card class="settings-section">
      <template #header>
        <span class="section-title">📊 图表与显示</span>
      </template>
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
    </el-card>

    <el-card class="settings-section">
      <template #header>
        <span class="section-title">📋 表格设置</span>
      </template>
      <el-form :model="settings" label-width="160px">
        <el-form-item label="默认每页行数">
          <el-select v-model="settings.page_size">
            <el-option :value="50" label="50" />
            <el-option :value="100" label="100" />
            <el-option :value="200" label="200" />
            <el-option :value="500" label="500" />
          </el-select>
        </el-form-item>

        <el-form-item label="表格高度">
          <el-select v-model="settings.table_height">
            <el-option :value="500" label="500" />
            <el-option :value="600" label="600" />
            <el-option :value="700" label="700" />
            <el-option :value="800" label="800" />
            <el-option :value="900" label="900" />
            <el-option :value="1000" label="1000" />
          </el-select>
        </el-form-item>

        <el-form-item label="表头字号">
          <el-slider
            v-model="settings.aggrid_header_font_size"
            :min="8"
            :max="18"
            :step="1"
            show-input
          />
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="settings-section">
      <template #header>
        <span class="section-title">📐 CPK 阈值设置</span>
      </template>
      <el-form :model="settings" label-width="160px">
        <el-form-item label="CPK A 级阈值">
          <el-input-number
            v-model="settings.cpk_a_threshold"
            :min="1"
            :max="3"
            :step="0.01"
            :precision="2"
            @change="onCpkAChanged"
          />
          <span class="threshold-hint">≥ {{ settings.cpk_a_threshold }} 为 A 级（优）</span>
        </el-form-item>

        <el-form-item label="CPK B 级阈值">
          <el-input-number
            v-model="settings.cpk_b_threshold"
            :min="0.5"
            :max="settings.cpk_a_threshold - 0.01"
            :step="0.01"
            :precision="2"
            @change="onCpkBChanged"
          />
          <span class="threshold-hint">≥ {{ settings.cpk_b_threshold }} 且 &lt; {{ settings.cpk_a_threshold }} 为 B 级</span>
        </el-form-item>

        <el-form-item label="CPK C 级阈值">
          <el-input-number
            v-model="settings.cpk_c_threshold"
            :min="0"
            :max="settings.cpk_b_threshold - 0.01"
            :step="0.01"
            :precision="2"
          />
          <span class="threshold-hint">≥ {{ settings.cpk_c_threshold }} 且 &lt; {{ settings.cpk_b_threshold }} 为 C 级</span>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="settings-section">
      <template #header>
        <span class="section-title">📁 最近文件列表</span>
      </template>
      <div v-if="recentFiles.length > 0" class="recent-files">
        <div class="recent-files__header">
          <span>最多保留</span>
          <el-input-number
            v-model="settings.max_recent_files"
            :min="1"
            :max="50"
            :step="1"
            size="small"
            style="margin-left: 8px; width: 120px"
          />
          <span>个最近文件</span>
        </div>
        <el-table :data="recentFiles" stripe size="small">
          <el-table-column label="序号" type="index" width="60" />
          <el-table-column prop="id" label="文件 ID" width="100" />
          <el-table-column prop="name" label="文件名" min-width="200" />
          <el-table-column label="访问时间" width="170">
            <template #default="{ row }">
              {{ formatDate(row.accessed_at) }}
            </template>
          </el-table-column>
        </el-table>
      </div>
      <el-empty v-else description="暂无最近文件" />
    </el-card>

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

interface SettingsData {
  page_size: number
  chart_height: number
  table_height: number
  chart_dpi: number
  cpk_a_threshold: number
  cpk_b_threshold: number
  cpk_c_threshold: number
  chart_engine: string
  chart_renderer: 'svg' | 'canvas'
  aggrid_header_font_size: number
  recent_files: Array<{ id: number; name: string; accessed_at: string }>
  max_recent_files: number
  histogram_label_offset: number
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
}

const settings = ref<SettingsData>({ ...defaults })

const recentFiles = ref<Array<{ id: number; name: string; accessed_at: string }>>([])

function onCpkAChanged() {
  if (settings.value.cpk_b_threshold >= settings.value.cpk_a_threshold) {
    settings.value.cpk_b_threshold = parseFloat((settings.value.cpk_a_threshold - 0.34).toFixed(2))
  }
  if (settings.value.cpk_c_threshold >= settings.value.cpk_b_threshold) {
    settings.value.cpk_c_threshold = parseFloat((settings.value.cpk_b_threshold - 0.33).toFixed(2))
  }
}

function onCpkBChanged() {
  if (settings.value.cpk_b_threshold >= settings.value.cpk_a_threshold) {
    settings.value.cpk_b_threshold = parseFloat((settings.value.cpk_a_threshold - 0.01).toFixed(2))
  }
  if (settings.value.cpk_c_threshold >= settings.value.cpk_b_threshold) {
    settings.value.cpk_c_threshold = parseFloat((settings.value.cpk_b_threshold - 0.01).toFixed(2))
  }
  if (settings.value.cpk_c_threshold < 0) {
    settings.value.cpk_c_threshold = 0
  }
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

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
    settings.value = merged as SettingsData
    setChartRenderer(merged.chart_renderer as 'svg' | 'canvas')
    recentFiles.value = Array.isArray(data?.recent_files) ? data.recent_files : []
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
    ElMessage.success('设置已保存')
  } catch {
    ElMessage.error('保存失败')
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
  color: var(--text-primary);
}

.settings-section {
  margin-bottom: 20px;
}

.section-title {
  font-weight: 600;
  font-size: 16px;
  color: var(--text-primary);
}

.threshold-hint {
  margin-left: 12px;
  font-size: 13px;
  color: var(--text-secondary);
}

.recent-files {
  margin-bottom: 8px;
}

.recent-files__header {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  font-size: 14px;
  color: var(--text-secondary);
}

.settings-actions {
  display: flex;
  gap: 16px;
  margin-top: 24px;
  margin-bottom: 40px;
}

:deep(.el-card) {
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.06);
}

:deep(.el-card__header) {
  background-color: var(--bg-tertiary);
  border-bottom: 1px solid var(--border-default);
}

:deep(.el-form-item__label) {
  color: var(--text-primary);
}

:deep(.el-input__wrapper) {
  background-color: var(--bg-primary);
  border-radius: 8px;
  box-shadow: 0 0 0 1px var(--border-default) inset;
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--brand-primary) inset;
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--brand-primary) inset;
}

:deep(.el-input__inner) {
  color: var(--text-primary);
}

:deep(.el-input__inner::placeholder) {
  color: var(--text-secondary);
}

:deep(.el-table) {
  --el-table-bg-color: var(--bg-secondary);
  --el-table-tr-bg-color: var(--bg-secondary);
  --el-table-header-bg-color: var(--bg-tertiary);
  --el-table-border-color: var(--border-default);
  --el-table-text-color: var(--text-primary);
  --el-table-header-text-color: var(--text-primary);
}

:deep(.el-table__empty-text) {
  color: var(--text-secondary);
}

:deep(.el-slider__runway) {
  background-color: var(--bg-tertiary);
}

:deep(.el-slider__bar) {
  background-color: var(--brand-primary);
}

:deep(.el-slider__button) {
  border-color: var(--brand-primary);
}

:deep(.el-input-number) {
  --el-input-number-border-color: var(--border-default);
}

:deep(.el-input-number .el-input__wrapper) {
  background-color: var(--bg-primary);
}

:deep(.el-select .el-input__wrapper) {
  background-color: var(--bg-primary);
}

:deep(.el-radio__input.is-checked .el-radio__inner) {
  background-color: var(--brand-primary);
  border-color: var(--brand-primary);
}

:deep(.el-radio__label) {
  color: var(--text-primary);
}

:deep(.el-empty__description) {
  color: var(--text-secondary);
}
</style>
