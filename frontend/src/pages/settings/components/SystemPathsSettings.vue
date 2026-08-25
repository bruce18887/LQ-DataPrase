<template>
  <div class="system-paths">
    <el-alert
      v-if="restartPending"
      title="路径已修改，重启应用后生效"
      type="warning"
      show-icon
      :closable="true"
      @close="restartPending = false"
      class="paths-alert"
    />

    <el-descriptions :column="1" border class="paths-descriptions">
      <el-descriptions-item label="数据目录">
        <template v-if="paths.editable">
          <div class="path-edit-row">
            <el-input
              v-model="draftDataDir"
              placeholder="存放数据库与上传数据（修改后需重启生效）"
              class="path-input"
            />
            <el-button :icon="FolderIcon" @click="pickDir('data_dir')">选择目录</el-button>
          </div>
        </template>
        <span v-else class="path-value">{{ paths.data_dir }}</span>
        <el-tag v-if="paths.configured.data_dir === null" size="small" type="info" effect="plain" class="path-default-tag">默认值</el-tag>
      </el-descriptions-item>

      <el-descriptions-item label="临时文件目录">
        <template v-if="paths.editable">
          <div class="path-edit-row">
            <el-input
              v-model="draftTempDir"
              placeholder="存放导出与图表缓存文件（修改后需重启生效）"
              class="path-input"
            />
            <el-button :icon="FolderIcon" @click="pickDir('temp_dir')">选择目录</el-button>
          </div>
        </template>
        <span v-else class="path-value">{{ paths.temp_dir }}</span>
        <el-tag v-if="paths.configured.temp_dir === null" size="small" type="info" effect="plain" class="path-default-tag">默认值</el-tag>
      </el-descriptions-item>

      <el-descriptions-item label="数据库文件">
        <span class="path-value">{{ paths.db_path }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="上传数据目录">
        <span class="path-value">{{ paths.media_path }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="配置文件">
        <span class="path-value">{{ paths.config_file }}</span>
      </el-descriptions-item>
    </el-descriptions>

    <div v-if="paths.editable" class="paths-actions">
      <el-button type="primary" :loading="saving" @click="savePaths">
        💾 保存路径
      </el-button>
      <span class="paths-hint">修改路径后需重启应用生效；数据库与上传数据将迁移到新数据目录</span>
    </div>
    <p v-else class="paths-hint">仅管理员可修改存储路径</p>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Folder } from '@element-plus/icons-vue'
import { systemApi, type SystemPaths } from '../../../api/system'

const FolderIcon = Folder

const paths = ref<SystemPaths>({
  data_dir: '',
  db_path: '',
  media_path: '',
  temp_dir: '',
  config_file: '',
  configured: { data_dir: null, temp_dir: null },
  editable: false,
  restart_required: false,
})
const draftDataDir = ref('')
const draftTempDir = ref('')
const saving = ref(false)
const restartPending = ref(false)

async function loadPaths() {
  try {
    const { data } = await systemApi.getPaths()
    paths.value = data
    draftDataDir.value = data.data_dir
    draftTempDir.value = data.temp_dir
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  }
}

async function pickDir(key: 'data_dir' | 'temp_dir') {
  if (!window.electronAPI) return
  const dir = await window.electronAPI.openDirectoryDialog()
  if (dir) {
    if (key === 'data_dir') draftDataDir.value = dir
    else draftTempDir.value = dir
  }
}

async function savePaths() {
  saving.value = true
  try {
    const { data } = await systemApi.updatePaths({
      data_dir: draftDataDir.value.trim() || null,
      temp_dir: draftTempDir.value.trim() || null,
    })
    paths.value = data
    ElMessage.success('路径已保存')
    if (data.restart_required) {
      restartPending.value = true
      promptRestart()
    }
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  } finally {
    saving.value = false
  }
}

async function promptRestart() {
  try {
    await ElMessageBox.confirm(
      '路径修改需重启应用后生效，是否立即重启？',
      '重启应用',
      { confirmButtonText: '🔁 立即重启', cancelButtonText: '稍后再说', type: 'warning' }
    )
    if (window.electronAPI) {
      await window.electronAPI.restartApp()
    } else {
      ElMessage.info('请手动重启应用后生效')
    }
  } catch {
    // 用户选择稍后再说
  }
}

onMounted(loadPaths)
</script>

<style scoped>
.paths-alert {
  margin-bottom: 16px;
}

.paths-descriptions {
  margin-bottom: 16px;
}

.path-value {
  color: var(--text-primary);
  word-break: break-all;
}

.path-edit-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.path-input {
  flex: 1;
}

.path-default-tag {
  margin-left: 8px;
  vertical-align: middle;
}

.paths-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.paths-hint {
  font-size: 13px;
  color: var(--text-secondary);
}

:deep(.el-descriptions) {
  --el-descriptions-table-border: var(--border-default);
}

:deep(.el-descriptions__label) {
  color: var(--text-primary);
  background-color: var(--bg-tertiary);
  width: 140px;
}

:deep(.el-descriptions__content) {
  color: var(--text-primary);
  background-color: var(--bg-secondary);
}

:deep(.el-descriptions__cell) {
  border-color: var(--border-default);
}
</style>
