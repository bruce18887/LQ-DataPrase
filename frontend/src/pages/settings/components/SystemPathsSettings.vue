<template>
  <div class="system-paths">
    <el-alert
      v-if="hiddenByServer"
      data-testid="paths-hidden-notice"
      title="存储路径仅管理员可见"
      type="info"
      show-icon
      :closable="false"
      class="paths-alert"
      description="这里显示的是服务器上的目录（数据、数据库文件、配置文件的位置）。服务器只把这些信息给管理员，普通账号读不到；需要确认数据位置时请联系管理员。"
    />

    <template v-else>
      <el-alert
        v-if="restartPending"
        title="路径已修改，重启应用后生效"
        type="warning"
        show-icon
        :closable="true"
        @close="restartPending = false"
        class="paths-alert"
      />

      <el-alert
        v-if="remoteMode"
        data-testid="paths-remote-notice"
        title="当前连接的是服务器，这里显示的是服务器上的路径"
        type="warning"
        show-icon
        :closable="false"
        class="paths-alert"
        description="存储目录只能在那台机器上、由运行本程序的管理员修改。在这里改动不会影响你自己的电脑，也不会影响服务器上的数据存放位置。"
      />

      <el-descriptions :column="1" border class="paths-descriptions">
        <el-descriptions-item label="数据目录">
          <template v-if="canEdit">
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
          <template v-if="canEdit">
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

      <div v-if="canEdit" class="paths-actions">
        <el-button type="primary" :loading="saving" @click="savePaths">
          💾 保存路径
        </el-button>
        <span class="paths-hint">修改路径后需重启应用生效；数据库与上传数据将迁移到新数据目录</span>
      </div>
      <p v-else-if="!remoteMode" class="paths-hint">仅管理员可修改存储路径</p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Folder } from '@element-plus/icons-vue'
import { systemApi, type SystemPaths } from '../../../api/system'
import { formatError } from '../../../utils/error'

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

/**
 * 服务器档（SYSTEM_PATHS_VISIBLE_TO_ALL=False）把 GET 也收给了管理员：
 * 这些路径描述的是那台机器的文件系统，普通账号读到的是 403。此时不显示表格，
 * 只给一句「谁去找管理员」——语义变了就要在界面上看得见，而不是悄悄空着。
 */
const hiddenByServer = ref(false)

/**
 * 连的是服务器时，本页的目录属于**服务器**磁盘：在这里改它既不影响用户本机，
 * 也不该被当成用户可改项（语义翻转贴，spec §6.6）。浏览器形态没有这个概念，保持原状。
 */
const remoteMode = ref(false)
const canEdit = computed(() => paths.value.editable && !remoteMode.value)

async function loadConnectionMode(): Promise<void> {
  if (!window.electronAPI) return
  try {
    const view = await window.electronAPI.getClientConfig()
    remoteMode.value = view.mode === 'remote'
  } catch {
    // IPC 取不到就按本机处理：宁可让用户看到原来的可编辑界面，
    // 也不要因为一次桥接失败把设置页锁死。
  }
}

async function loadPaths() {
  try {
    const { data } = await systemApi.getPaths({ silent: true })
    paths.value = data
    draftDataDir.value = data.data_dir
    draftTempDir.value = data.temp_dir
  } catch (err) {
    if ((err as AxiosError)?.response?.status === 403) {
      hiddenByServer.value = true
      return
    }
    // silent 压掉的是本请求的全局 toast；403 之外的错误仍然要让用户看见。
    ElMessage.error(formatError(err))
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

onMounted(() => {
  loadPaths()
  loadConnectionMode()
})
</script>

<style scoped>
.paths-alert {
  margin-bottom: 16px;
}

.paths-descriptions {
  margin-bottom: 16px;
}

.path-value {
  color: var(--text);
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
  font-size: var(--p-fs-small);
  color: var(--text-2);
}

:deep(.el-descriptions) {
  --el-descriptions-table-border: var(--border-2);
}

:deep(.el-descriptions__label) {
  color: var(--text);
  background-color: var(--bg-3);
  width: 140px;
}

:deep(.el-descriptions__content) {
  color: var(--text);
  background-color: var(--bg-2);
}

:deep(.el-descriptions__cell) {
  border-color: var(--border-2);
}
</style>
