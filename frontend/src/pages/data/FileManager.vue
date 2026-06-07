<template>
  <div>
    <el-upload
      drag
      :http-request="handleUpload"
      accept=".csv,.txt,.dat,.zip,.7z,.rar"
      :show-file-list="false"
      multiple
    >
      <el-icon :size="48"><UploadFilled /></el-icon>
      <div class="upload-text">拖拽文件到此处 或 <em>点击上传</em></div>
      <div class="upload-hint">支持多文件上传，ZIP/7z/RAR 压缩包会自动解压</div>
    </el-upload>
    <el-progress
      v-if="uploadProgress > 0 && uploadProgress < 100"
      :percentage="uploadProgress"
      style="margin-top: 8px"
    />
    <el-divider />

    <!-- Unregistered batch directories (from SFTP downloads) -->
    <template v-if="unregisteredDirs.length > 0">
      <div class="section-label">📂 SFTP 下载目录（未导入）</div>
      <div v-for="dir in unregisteredDirs" :key="dir.name" class="batch-group unregistered">
        <div class="batch-header">
          <span class="batch-name">📁 {{ dir.name }}</span>
          <span class="batch-count">{{ dir.file_count }} 个文件</span>
          <span class="batch-size">{{ formatSize(dir.total_size) }}</span>
          <div style="flex:1" />
          <el-button size="small" type="success" @click="importDir(dir)" :loading="importingDir === dir.name">
            <el-icon><Upload /></el-icon> 导入
          </el-button>
          <el-button size="small" type="danger" plain @click="deleteDir(dir)">
            <el-icon><Delete /></el-icon> 删除
          </el-button>
        </div>
      </div>
    </template>

    <!-- Batch files grouped (registered) -->
    <template v-if="batchGroups.length > 0">
      <div class="section-label">📦 已导入批次</div>
      <div v-for="group in batchGroups" :key="group.name" class="batch-group">
        <div class="batch-header">
          <span class="batch-name">📦 {{ group.name }}</span>
          <span class="batch-count">{{ group.files.length }} 个文件</span>
          <div style="flex:1" />
          <el-button size="small" type="danger" plain @click="deleteBatch(group)">
            <el-icon><Delete /></el-icon> 删除批次
          </el-button>
        </div>
        <el-row :gutter="12">
          <el-col :span="8" v-for="f in group.files" :key="f.id">
            <el-card shadow="hover" :class="{ 'active-file': f.id === activeFileId }">
              <div style="font-weight:bold; color: var(--text-primary)">{{ f.filename }}</div>
              <div style="color: var(--text-secondary); font-size:12px; margin:4px 0">
                {{ f.format_type }} | {{ f.row_count }}行×{{ f.col_count }}列
              </div>
              <div style="color: var(--text-secondary); font-size:12px" v-if="f.program_name" class="program-name">{{ f.program_name }}</div>
              <el-row :gutter="8" style="margin-top:8px">
                <el-col :span="16">
                  <el-button size="small" type="primary" @click="emit('file-selected', f.id)" style="width: 100%">
                    {{ f.id === activeFileId ? '✓ 当前文件' : '浏览数据' }}
                  </el-button>
                </el-col>
                <el-col :span="8">
                  <el-button size="small" type="danger" @click="deleteFile(f)" aria-label="删除文件">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </el-col>
              </el-row>
            </el-card>
          </el-col>
        </el-row>
      </div>
    </template>

    <!-- Single files -->
    <template v-if="singleFiles.length > 0">
      <div class="section-label" v-if="batchGroups.length > 0 || unregisteredDirs.length > 0">📁 单文件</div>
      <el-row :gutter="16">
        <el-col :span="8" v-for="f in singleFiles" :key="f.id">
          <el-card shadow="hover" :class="{ 'active-file': f.id === activeFileId }">
            <div style="font-weight:bold; color: var(--text-primary)">{{ f.filename }}</div>
            <div style="color: var(--text-secondary); font-size:12px; margin:4px 0">
              {{ f.format_type }} | {{ f.row_count }}行×{{ f.col_count }}列
            </div>
            <div style="color: var(--text-secondary); font-size:12px" v-if="f.program_name" class="program-name">{{ f.program_name }}</div>
            <el-row :gutter="8" style="margin-top:8px">
              <el-col :span="16">
                <el-button size="small" type="primary" @click="emit('file-selected', f.id)" style="width: 100%">
                  {{ f.id === activeFileId ? '✓ 当前文件' : '浏览数据' }}
                </el-button>
              </el-col>
              <el-col :span="8">
                <el-button size="small" type="danger" @click="deleteFile(f)" aria-label="删除文件">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </el-col>
            </el-row>
          </el-card>
        </el-col>
      </el-row>
    </template>

    <el-empty v-if="files.length === 0 && unregisteredDirs.length === 0" description="暂无文件" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { UploadFilled, Delete, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { datafilesApi, type BatchDirInfo } from '../../api/datafiles'
import { useFilesStore } from '../../stores/files'
import type { DataFile } from '../../types'

const props = defineProps<{ activeFileId?: number }>()
const emit = defineEmits<{ 'file-selected': [id: number] }>()

const files = ref<DataFile[]>([])
const uploadProgress = ref(0)
const batchDirs = ref<BatchDirInfo[]>([])
const importingDir = ref('')
const filesStore = useFilesStore()

// Sync batchDirs when files change externally (e.g. SFTP auto-import)
watch(() => filesStore.filesVersion, () => {
  loadFiles()
  loadBatchDirs()
})

const singleFiles = computed(() => files.value.filter(f => f.file_type !== 'batch'))

const unregisteredDirs = computed(() => batchDirs.value.filter(d => !d.registered))

const batchGroups = computed(() => {
  const batches = files.value.filter(f => f.file_type === 'batch' && f.batch_name)
  const groups = new Map<string, DataFile[]>()
  for (const f of batches) {
    const key = f.batch_name || 'unknown'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(f)
  }
  return Array.from(groups.entries()).map(([name, files]) => ({ name, files }))
})

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}

async function handleUpload(options: { file: File }) {
  uploadProgress.value = 0
  try {
    await datafilesApi.upload(options.file, (pct: number) => {
      uploadProgress.value = pct
    })
    ElMessage.success(`${options.file.name} 上传成功`)
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch {
    ElMessage.error(`${options.file.name} 上传失败`)
  } finally {
    uploadProgress.value = 0
  }
}

async function loadFiles() {
  try {
    const { data } = await datafilesApi.list()
    files.value = Array.isArray(data) ? data : (data.results ?? [])
  } catch {
    // silently ignore fetch errors
  }
}

async function loadBatchDirs() {
  try {
    const { data } = await datafilesApi.listBatchDirs()
    batchDirs.value = Array.isArray(data) ? data : []
  } catch {
    // silently ignore
  }
}

async function importDir(dir: BatchDirInfo) {
  importingDir.value = dir.name
  try {
    await datafilesApi.importBatchDir(dir.name)
    ElMessage.success(`批次 "${dir.name}" 已导入`)
    await Promise.all([loadFiles(), loadBatchDirs()])
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '导入失败')
  } finally {
    importingDir.value = ''
  }
}

async function deleteDir(dir: BatchDirInfo) {
  try {
    await ElMessageBox.confirm(
      `确定删除目录 "${dir.name}" 及其 ${dir.file_count} 个文件吗？此操作不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await datafilesApi.deleteBatchDir(dir.name)
    ElMessage.success(`目录 "${dir.name}" 已删除`)
    await Promise.all([loadFiles(), loadBatchDirs()])
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.response?.data?.error || '删除失败')
    }
  }
}

async function deleteFile(file: DataFile) {
  try {
    await ElMessageBox.confirm(
      `确定删除文件 "${file.filename}" 吗？此操作不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await datafilesApi.remove(file.id)
    ElMessage.success('文件已删除')
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

async function deleteBatch(group: { name: string; files: DataFile[] }) {
  try {
    await ElMessageBox.confirm(
      `确定删除批次 "${group.name}" 及其 ${group.files.length} 个文件吗？此操作不可恢复。`,
      '确认删除批次',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    // Delete all files in the batch
    for (const f of group.files) {
      try { await datafilesApi.remove(f.id) } catch {}
    }
    ElMessage.success(`批次 "${group.name}" 已删除`)
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

onMounted(() => {
  loadFiles()
  loadBatchDirs()
})
</script>

<style scoped>
.upload-text {
  font-size: 14px;
  color: var(--text-secondary);
  margin-top: 8px;
}
.upload-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 4px;
}
.active-file {
  border: 2px solid var(--brand-primary);
}
.program-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.batch-group {
  margin-bottom: 20px;
  padding: 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 10px;
}

.batch-group.unregistered {
  border-left: 3px solid var(--color-warning);
}

.batch-size {
  font-size: 12px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.batch-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.batch-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.batch-count {
  font-size: 12px;
  color: var(--text-tertiary);
  padding: 2px 8px;
  background: var(--bg-primary);
  border-radius: 10px;
}

.section-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

:deep(.el-upload-dragger) {
  background-color: var(--bg-secondary);
  border: 2px dashed var(--border-default);
  border-radius: 8px;
}

:deep(.el-upload-dragger:hover) {
  border-color: var(--brand-primary);
}

:deep(.el-card) {
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
}

:deep(.el-card:hover) {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12), 0 2px 6px rgba(0, 0, 0, 0.08);
}
</style>
