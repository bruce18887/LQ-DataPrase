<template>
  <div class="settings-page">
    <el-tabs v-model="activeTab" tab-position="left" class="settings-tabs">
      <el-tab-pane name="display" label="📊 显示设置">
        <ChartSettingsForm :settings="settings" />
        <AnalysisLayoutSettings :settings="settings" />
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
      <el-tab-pane name="connection" label="🔗 连接">
        <ConnectionSettings />
      </el-tab-pane>
      <el-tab-pane name="paths" label="📁 存储路径">
        <SystemPathsSettings />
      </el-tab-pane>
    </el-tabs>

    <div class="settings-actions">
      <!-- 脏追踪（Task 6b）：没有改动就不发 PUT，按钮同时置灰。
           disabled 视觉走 Element Plus 自己的 --el-button-disabled-*（本仓 light/night
           两块都定义了 --el-color-primary-light-5/7，见 styles/element-plus-theme.css:35-38
           与 :189-192），提示文案复用已主题化的 .text-secondary ⇒ 不加一行 CSS。 -->
      <el-button type="primary" size="large" :disabled="!hasChanges" @click="saveSettings">
        💾 保存设置
      </el-button>
      <el-button size="large" @click="resetDefaults">
        🔄 恢复默认
      </el-button>
      <span v-if="!hasChanges" class="text-secondary">没有需要保存的改动</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { setChartRenderer } from '../../utils/echarts-theme'
import { useUserSettingsStore } from '../../stores/userSettings'
import type { UserSettings } from '../../stores/userSettings'
import type { ExportTypeKey, SettingsData } from '../../types'
import { EXPORT_TEMPLATE_META, EXPORT_TEMPLATE_KEYS } from '../../constants/export-templates'
import ChartSettingsForm from './components/ChartSettingsForm.vue'
import AnalysisLayoutSettings from './components/AnalysisLayoutSettings.vue'
import { clearChartMemoryState, setChartMemoryEnabled } from '../../composables/useChartMemory'
import TableSettingsForm from './components/TableSettingsForm.vue'
import CpkSettingsForm from './components/CpkSettingsForm.vue'
import SystemPathsSettings from './components/SystemPathsSettings.vue'
import ConnectionSettings from './components/ConnectionSettings.vue'
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
  chart_dpi: 100,
  cpk_a_threshold: 1.67,
  cpk_b_threshold: 1.33,
  cpk_c_threshold: 1.0,
  chart_renderer: 'svg' as const,
  export_filename_templates: defaultTemplates(),
  export_timeout: 600,
  sftp_download_timeout: 600,
  default_hidden_columns: [...DEFAULT_HIDDEN_COLUMNS],
  filename_wrap: true,
  analysis_chart_memory: true,
}

const activeTab = ref('display')
// 必须深拷贝：defaults 里的 export_filename_templates / default_hidden_columns 是嵌套对象与
// 数组，浅 spread 会让 settings 与模块级 defaults **共享同一个内层对象**（下面 :108 的 loaded
// 早就用 snapshot() 防同一件事，只是这三处漏了）。
const settings = ref<SettingsData>(snapshot(defaults))
const store = useUserSettingsStore()

/**
 * 载入时的快照。`saveSettings` 只 PUT 与它不同的键（脏追踪）—— 今天生产实测一次会话
 * 32 次整对象 PUT（`defaults` 的 12 个键全量 spread），改后一次点击只发真正改过的那几个。
 * 必须是**深拷贝**：各子表单是就地改 `settings` 对象的属性（含数组/对象键），
 * 与 merged 共享引用的话「改动」会被同时写进快照，脏判定就永远不成立。
 *
 * ⚠ 也必须是 **ref**（2026-10-23 收口评审 D 项）：`dirtyKeys` 是个 computed，它只跟踪
 * 读到的响应式来源。这里原先写 `let loaded: SettingsData = {...defaults}` —— 普通变量
 * 不进依赖表 ⇒ `saveSettings` 成功后那句 `loaded = snapshot(...)` 重赋值**不会**让
 * computed 失效：脏键列表停在保存前那一份，按钮继续可用、「没有需要保存的改动」永不出现、
 * 再点一次就把同一批键再 PUT 一遍（载荷本身仍正确，坏的是判定）。`snapshot()` 是函数声明、
 * 已提升，所以在下面定义之前就能用。
 */
const loaded = ref<SettingsData>(snapshot(defaults))

/** 值比较：基本类型比身份，数组/对象比 JSON（同一形状来源固定，顺序差异只会多 PUT 一个键，不会漏） */
function sameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true
  try {
    return JSON.stringify(a) === JSON.stringify(b)
  } catch {
    return false
  }
}

const dirtyKeys = computed<(keyof SettingsData)[]>(() =>
  (Object.keys(defaults) as (keyof SettingsData)[]).filter(
    (k) => !sameValue(settings.value[k], loaded.value[k]),
  ),
)
const hasChanges = computed(() => dirtyKeys.value.length > 0)

function snapshot(v: SettingsData): SettingsData {
  return JSON.parse(JSON.stringify(v)) as SettingsData
}

async function loadSettings() {
  // Task 6b：不再自己 GET。store.ensure() 的单飞通常已被路由守卫的
  // ensureChartRenderer() 用掉（⇒ 本页 0 请求）；守卫那次失败时 raw=null，
  // 下面按 defaults 兜底，与今天 catch 分支同形（失败即默认值，不重试）。
  await store.ensure()
  const data = store.raw
  const merged = snapshot(defaults)
  if (data && typeof data === 'object') {
    Object.keys(defaults).forEach((key) => {
      if (key in data) {
        ;(merged as unknown as Record<string, unknown>)[key] = data[key]
      }
    })
  }
  // 导出文件名模板逐 key 合并：后端返回的完整表缺 key 时补默认
  const remoteTemplates = (data as Record<string, unknown> | null)?.export_filename_templates
  if (remoteTemplates && typeof remoteTemplates === 'object') {
    const mergedTemplates = { ...defaultTemplates() }
    EXPORT_TEMPLATE_KEYS.forEach((key) => {
      const v = (remoteTemplates as Record<string, unknown>)[key]
      if (typeof v === 'string') mergedTemplates[key] = v
    })
    merged.export_filename_templates = mergedTemplates
  }
  settings.value = merged as SettingsData
  loaded.value = snapshot(merged)
  setChartRenderer(merged.chart_renderer as 'svg' | 'canvas')
  // 导出超时同步到模块缓存，使导出调用点无需访问本页即可使用最新值
  setExportTimeoutSec(merged.export_timeout)
  // SFTP 下载超时同步到模块缓存（SFTP 浏览器读取此值）
  setSftpTimeoutSec(merged.sftp_download_timeout)
}

async function saveSettings() {
  const dirty = dirtyKeys.value
  if (dirty.length === 0) return // 无改动：不发 PUT（按钮此时已置灰，这里是第二道闸）
  const payload = {} as Record<string, unknown>
  dirty.forEach((k) => { payload[k] = settings.value[k] })
  try {
    await store.save(payload as UserSettings)
    // PUT 的响应就是全量（apps/accounts/views.py:218-225），store.save 已把它写进 raw
    // 并记为已取过 ⇒ 保存后不会再补一次 GET（R24 0b）。
    // 响应写回脏基线：这一步**必须**让 `dirtyKeys` 失效（loaded 是 ref 才做得到，见其声明处）
    loaded.value = snapshot(settings.value)
    setChartRenderer(settings.value.chart_renderer)
    setExportTimeoutSec(settings.value.export_timeout)
    setSftpTimeoutSec(settings.value.sftp_download_timeout)
    setFilenameWrapCache(settings.value.filename_wrap)
    if (settings.value.analysis_chart_memory) {
      // 会话内「关→开」：立即恢复同步；账号布局套用下次进入分析页生效
      setChartMemoryEnabled(true)
    } else {
      // 关 = 完全不记忆：保存为关时一并清空已存状态（账号 + 本机）并断写本会话
      await clearChartMemoryState({ disableMemory: true })
    }
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
    // 同 :92：浅 spread 会把 defaults 的内层对象直接交给 settings，此后每敲一次
    // 输入框都在改写模块级 defaults ⇒「恢复默认」不再恢复真默认。
    settings.value = snapshot(defaults)
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
