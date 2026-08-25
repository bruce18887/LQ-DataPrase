<template>
  <div class="buyoff-form-page">
    <!-- 标题区 -->
    <header class="tab-header">
      <div class="tab-title-group">
        <span class="tab-title-icon" aria-hidden="true">📝</span>
        <h3 class="tab-title">Buyoff Form 生成</h3>
      </div>
      <p class="tab-subtitle">为每个文件分配 FT / QA1 / QA2 角色，生成对比分析报表</p>
    </header>

    <!-- 角色分配 -->
    <section class="section-card">
      <div class="card-header">
        <div class="card-title-group">
          <span class="card-icon" aria-hidden="true">🎭</span>
          <span class="card-title">角色分配</span>
        </div>
      </div>
      <div class="card-body">
        <el-row :gutter="16">
          <el-col :span="8" v-for="role in roles" :key="role.key" class="role-col">
            <div class="role-item">
              <div class="role-label">{{ role.label }}</div>
              <FileSelect
                v-model="roleAssignments[role.key]"
                :files="availableFiles(role.key)"
                placeholder="选择文件"
                clearable
                show-meta
                aria-label="选择角色用户"
                class="role-select"
              />
            </div>
          </el-col>
        </el-row>
      </div>
    </section>

    <!-- 分析结果 -->
    <section v-if="analysisResult" class="section-card">
      <div class="card-header">
        <div class="card-title-group">
          <span class="card-icon" aria-hidden="true">📊</span>
          <span class="card-title">测试项分析</span>
        </div>
      </div>
      <div class="card-body">
        <el-descriptions :column="3" border>
          <el-descriptions-item label="共同测试项">
            <el-tag type="success">{{ analysisResult.common_count }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="部分共有项">
            <el-tag type="warning">{{ partialCount }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="独有测试项">
            <el-tag type="info">{{ uniqueCount }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="文件数">{{ analysisResult.file_count }}</el-descriptions-item>
        </el-descriptions>

        <!-- 共同测试项列表 -->
        <div v-if="analysisResult.common_items?.length" class="items-section">
          <div class="section-title">共同测试项 ({{ analysisResult.common_items.length }})</div>
          <div class="item-tags">
            <el-tag
              v-for="item in analysisResult.common_items.slice(0, 20)"
              :key="item"
              size="small"
              class="item-tag"
            >
              {{ item }}
            </el-tag>
            <span v-if="analysisResult.common_items.length > 20" class="more-text">
              +{{ analysisResult.common_items.length - 20 }} 更多…
            </span>
          </div>
        </div>

        <!-- 文件特有测试项 -->
        <div v-if="fileSpecificItems.length" class="items-section">
          <div class="section-title">文件特有测试项</div>
          <el-collapse>
            <el-collapse-item
              v-for="item in fileSpecificItems"
              :key="item.filename"
              :title="`${item.filename} (${item.items.length})`"
            >
              <div class="item-tags">
                <el-tag
                  v-for="param in item.items.slice(0, 15)"
                  :key="param"
                  size="small"
                  type="info"
                  class="item-tag"
                >
                  {{ param }}
                </el-tag>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>
    </section>

    <!-- 操作区 -->
    <div class="action-bar">
      <div class="action-options">
        <el-checkbox v-model="onlyBin1">只选择 Bin1 数据</el-checkbox>
      </div>
      <div class="action-buttons">
        <el-button
          :loading="loading"
          :disabled="assignedFileIds.length < 2"
          @click="analyze"
        >
          🔍 分析共同测试项
        </el-button>
        <el-button
          type="primary"
          :loading="loading"
          :disabled="assignedFileIds.length < 2"
          @click="generate"
        >
          📥 生成 Buyoff Form
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { buyoffApi } from '../../api/buyoff'
import { downloadBlob, extractFilenameFromContentDisposition } from '../../utils/download'
import type { DataFile } from '../../types'
import FileSelect from '../../components/common/FileSelect.vue'

interface AnalysisResult {
  common_items: string[]
  common_count: number
  file_specific: Record<string, string[]>
  file_count: number
}

interface Props {
  /** 文件列表（由 DataManagement 维护刷新后传入，组件不自行拉取） */
  files: DataFile[]
}

const props = withDefaults(defineProps<Props>(), { files: () => [] })

const roleAssignments = ref<Record<string, number | null>>({
  FT: null,
  QA1: null,
  QA2: null,
})
const onlyBin1 = ref(false)
const loading = ref(false)
const analysisResult = ref<AnalysisResult | null>(null)

const roles = [
  { key: 'FT', label: 'FT (工厂测试)' },
  { key: 'QA1', label: 'QA1 (质量检测1)' },
  { key: 'QA2', label: 'QA2 (质量检测2)' },
]

// 数据库文件被删除后自动清理已失效的角色分配（keep-alive 下组件常驻，
// 文件列表由父级刷新，这里负责把已不在列表中的 id 置空）
watch(() => props.files, (list) => {
  const ids = new Set(list.map(f => f.id))
  for (const key of Object.keys(roleAssignments.value)) {
    const id = roleAssignments.value[key]
    if (id !== null && !ids.has(id)) {
      roleAssignments.value[key] = null
    }
  }
})

const assignedFileIds = computed(() => {
  return Object.values(roleAssignments.value).filter((id): id is number => id !== null)
})

const partialCount = computed(() => {
  if (!analysisResult.value?.file_specific) return 0
  return Object.values(analysisResult.value.file_specific).reduce((sum, items) => sum + items.length, 0)
})

const uniqueCount = computed(() => {
  return partialCount.value
})

const fileSpecificItems = computed(() => {
  if (!analysisResult.value?.file_specific) return []
  return Object.entries(analysisResult.value.file_specific).map(([filename, items]) => ({
    filename,
    items,
  }))
})

/**
 * 当前角色可选文件：排除其它角色已占用；当前角色已选文件即使被其它角色
 * 占用也并回 options（否则 el-select 对不在 options 中的值显示裸 id 数字）。
 */
function availableFiles(currentRole: string) {
  const usedIds = new Set<number>()
  for (const [role, id] of Object.entries(roleAssignments.value)) {
    if (role !== currentRole && id !== null) {
      usedIds.add(id)
    }
  }
  const own = roleAssignments.value[currentRole]
  if (own != null) usedIds.delete(own)
  return props.files.filter(f => !usedIds.has(f.id))
}

async function analyze() {
  if (assignedFileIds.value.length < 2) {
    ElMessage.warning('请至少分配 2 个文件')
    return
  }
  loading.value = true
  try {
    const { data } = await buyoffApi.identifyCommonItems(assignedFileIds.value)
    analysisResult.value = data as AnalysisResult
    ElMessage.success(`找到 ${data.common_count} 个共同测试项`)
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  } finally {
    loading.value = false
  }
}

async function generate() {
  if (assignedFileIds.value.length < 2) {
    ElMessage.warning('请至少分配 2 个文件')
    return
  }
  loading.value = true
  try {
    const resp = await buyoffApi.generateForm(assignedFileIds.value, onlyBin1.value, roleAssignments.value)
    const fname = extractFilenameFromContentDisposition(
      (resp.headers as Record<string, string>)?.['content-disposition'],
    ) ?? 'Buyoff_Form.xlsx'
    downloadBlob(resp.data as Blob, fname)
    ElMessage.success('Buyoff Form 已下载')
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* ================================================================
   容器
   ================================================================ */
.buyoff-form-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ================================================================
   Tab 标题区（与 DataManagement 的 page-header 风格一致）
   ================================================================ */
.tab-header {
  position: relative;
  padding: 16px 20px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-left: 3px solid var(--brand-primary);
  border-radius: 10px;
  box-shadow: var(--shadow-sm);
}

.tab-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.tab-title-icon {
  font-size: 18px;
  line-height: 1;
}

.tab-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.01em;
  background: linear-gradient(135deg, var(--brand-primary) 0%, var(--color-info) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.tab-subtitle {
  margin: 0;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.5;
}

/* ================================================================
   Section Card（与 ExportToolsTab / FileCorrelationSection 一致）
   ================================================================ */
.section-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border-muted);
}

.card-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-icon {
  font-size: 16px;
  line-height: 1;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.card-body {
  padding: 16px 20px;
}

/* ================================================================
   角色分配
   ================================================================ */
.role-col {
  margin-bottom: 12px;
}

.role-item {
  background: var(--bg-primary);
  border: 1px solid var(--border-muted);
  border-radius: 10px;
  padding: 12px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.role-item:hover {
  border-color: var(--brand-primary);
  box-shadow: var(--shadow-indigo-focus);
}

.role-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--brand-primary);
  margin-bottom: 8px;
}

.role-select {
  width: 100%;
}

/* ================================================================
   测试项分析块
   ================================================================ */
.items-section {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px dashed var(--border-muted);
}

.items-section:first-child {
  border-top: none;
  padding-top: 0;
  margin-top: 8px;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 10px;
  padding-left: 8px;
  border-left: 3px solid var(--brand-primary);
  line-height: 1.2;
}

.item-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.item-tag {
  margin: 0;
}

.more-text {
  font-size: 12px;
  color: var(--text-secondary);
  padding: 0 4px;
}

/* ================================================================
   操作区
   ================================================================ */
.action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 20px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 10px;
  box-shadow: var(--shadow-sm);
  flex-wrap: wrap;
}

.action-options {
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
}

.action-buttons {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

/* ================================================================
   Element Plus 主题适配
   ================================================================ */
:deep(.el-descriptions) {
  --el-descriptions-item-bordered-label-background: var(--bg-tertiary);
}

:deep(.el-descriptions__label) {
  color: var(--text-primary);
  font-weight: 600;
}

:deep(.el-descriptions__content) {
  color: var(--text-primary);
}

:deep(.el-collapse) {
  border-top: 1px solid var(--border-muted);
  border-bottom: 1px solid var(--border-muted);
}

:deep(.el-collapse-item__header) {
  background-color: var(--bg-secondary);
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-muted);
}

:deep(.el-collapse-item__wrap) {
  background-color: var(--bg-primary);
  border-bottom: 1px solid var(--border-muted);
}

:deep(.el-checkbox) {
  --el-checkbox-checked-bg-color: var(--brand-primary);
  --el-checkbox-checked-input-border-color: var(--brand-primary);
  --el-checkbox-checked-icon-color: var(--text-inverse);
}

:deep(.el-button) {
  border-radius: 8px;
}
</style>
