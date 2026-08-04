<template>
  <el-card class="connect-card" shadow="hover">
    <template #header>
      <div class="card-header">
        <el-icon :size="18"><Connection /></el-icon>
        <span>连接配置</span>
      </div>
    </template>

    <el-form :model="conn" label-width="90px" @submit.prevent="doConnect" class="connect-form">
      <el-row :gutter="20">
        <el-col :span="8">
          <el-form-item label="主机" required>
            <el-input v-model="conn.host" placeholder="例如: 192.168.1.1" :prefix-icon="Monitor" clearable />
          </el-form-item>
        </el-col>
        <el-col :span="4">
          <el-form-item label="端口">
            <el-input-number v-model="conn.port" :min="1" :max="65535" style="width: 100%" />
          </el-form-item>
        </el-col>
        <el-col :span="6">
          <el-form-item label="用户名" required>
            <el-input v-model="conn.username" :prefix-icon="User" clearable />
          </el-form-item>
        </el-col>
        <el-col :span="6">
          <el-form-item label="密码">
            <el-input
              v-model="conn.password"
              type="password"
              show-password
              :prefix-icon="Lock"
              :placeholder="activeConfig?.has_password ? '已保存，留空则用已存密码' : ''"
            />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item class="form-actions">
        <el-button type="primary" native-type="submit" :loading="connecting" size="large">
          <el-icon><Link /></el-icon> 连接
        </el-button>
        <el-button @click="openSaveDialog" :disabled="!conn.host || !conn.username" size="large">
          <el-icon><Star /></el-icon> 保存配置
        </el-button>
      </el-form-item>
    </el-form>

    <!-- Saved Configs -->
    <div v-if="savedConfigs.length > 0" class="saved-configs">
      <el-divider>
        <el-icon><Collection /></el-icon> 已保存配置
      </el-divider>
      <div class="config-grid">
        <el-card
          v-for="config in savedConfigs"
          :key="config.id"
          class="config-item"
          :class="{ 'config-active': activeConfig?.id === config.id }"
          shadow="hover"
          :body-style="{ padding: '16px' }"
        >
          <div class="config-header">
            <el-icon :size="20"><OfficeBuilding /></el-icon>
            <span class="config-name">{{ config.name }}</span>
            <el-tag v-if="config.has_password" size="small" type="success" effect="plain" class="pw-tag">
              <el-icon><Lock /></el-icon> 已保存密码
            </el-tag>
          </div>
          <div class="config-info">
            <div class="config-row">
              <el-icon :size="14"><Monitor /></el-icon>
              <span>{{ config.host }}:{{ config.port }}</span>
            </div>
            <div class="config-row">
              <el-icon :size="14"><User /></el-icon>
              <span>{{ config.username }}</span>
            </div>
          </div>
          <div class="config-actions">
            <el-button type="primary" size="small" @click="loadConfig(config)">
              <el-icon><Switch /></el-icon> 加载
            </el-button>
            <el-button type="danger" size="small" plain @click="deleteConfig(config)" aria-label="删除配置">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </el-card>
      </div>
    </div>

    <!-- Save Config Name Dialog -->
    <el-dialog v-model="saveDialogVisible" title="保存配置" width="420px" append-to-body>
      <el-form @submit.prevent="confirmSave">
        <el-form-item label="配置名称" label-width="80px" :error="nameError">
          <el-input
            v-model="configName"
            placeholder="请输入配置名称"
            maxlength="50"
            clearable
            @input="nameError = ''"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="saveDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="confirmSave">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  Connection, Monitor, User, Lock, Link, Star, Collection,
  OfficeBuilding, Switch, Delete,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { sftpApi, type SftpConfigItem } from '../../../api/sftp'

const emit = defineEmits<{
  connected: []
}>()

const conn = ref({ host: '', port: 22, username: '', password: '' })
const connecting = ref(false)
const savedConfigs = ref<SftpConfigItem[]>([])
// The saved config currently loaded into the form (if any). When set and the
// password field is left empty, we connect by config_name so the stored
// password stays server-side and never enters the browser.
const activeConfig = ref<SftpConfigItem | null>(null)

const saveDialogVisible = ref(false)
const configName = ref('')
const nameError = ref('')
const saving = ref(false)

onMounted(() => {
  refreshConfigs()
})

async function refreshConfigs() {
  try {
    const { data } = await sftpApi.getConfigs()
    savedConfigs.value = data.configs || []
  } catch {
    savedConfigs.value = []
  }
}

function openSaveDialog() {
  if (!conn.value.host || !conn.value.username) return
  configName.value = activeConfig.value?.name || conn.value.host
  nameError.value = ''
  saveDialogVisible.value = true
}

async function confirmSave() {
  const name = configName.value.trim()
  if (!name) {
    nameError.value = '配置名称不能为空'
    return
  }
  saving.value = true
  try {
    // silent：字段校验错误在表单项内联展示（拦截器提示会与其重复）
    await sftpApi.saveConfig({
      name,
      host: conn.value.host,
      port: conn.value.port,
      username: conn.value.username,
      password: conn.value.password,
    }, { silent: true })
    saveDialogVisible.value = false
    ElMessage.success('配置已保存')
    await refreshConfigs()
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 400) {
      const data = err.response.data || {}
      const msg = data.name?.[0] || data.host?.[0] || data.detail || '配置无效'
      nameError.value = String(msg)
    }
    // 非 400 错误：拦截器统一弹出全局提示
  } finally {
    saving.value = false
  }
}

function loadConfig(config: SftpConfigItem) {
  // Populate host/port/username only — the backend never returns the password.
  conn.value = { host: config.host, port: config.port, username: config.username, password: '' }
  activeConfig.value = config
}

async function deleteConfig(config: SftpConfigItem) {
  try {
    await ElMessageBox.confirm(`确定删除配置 "${config.name}"？`, '删除配置', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await sftpApi.deleteConfig({ name: config.name })
    if (activeConfig.value?.id === config.id) activeConfig.value = null
    ElMessage.success('配置已删除')
    await refreshConfigs()
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  }
}

async function doConnect() {
  if (!conn.value.host || !conn.value.username) {
    ElMessage.warning('请输入主机地址和用户名')
    return
  }
  connecting.value = true
  try {
    // Security-preferred: when a saved config is active and the user didn't type
    // a new password, connect by config_name so the stored password is decrypted
    // server-side and never reaches the browser. Otherwise use explicit fields.
    if (activeConfig.value && !conn.value.password) {
      await sftpApi.connect({ config_name: activeConfig.value.name })
    } else {
      await sftpApi.connect({
        host: conn.value.host,
        port: conn.value.port,
        username: conn.value.username,
        password: conn.value.password,
      })
    }
    ElMessage.success('已连接')
    emit('connected')
  } catch { /* 错误 toast 由 axios 拦截器统一弹出 */ }
  finally { connecting.value = false }
}
</script>

<style scoped>
.connect-card { border-radius: 8px; margin-bottom: 20px; }
.card-header { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 15px; color: var(--text-primary); }
.connect-form { padding-top: 8px; }
.form-actions { margin-top: 8px; margin-bottom: 0; }
.form-actions :deep(.el-form-item__content) { gap: 12px; }

.saved-configs { margin-top: 16px; }
.config-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; margin-top: 16px; }
.config-item { border-radius: 8px; transition: transform 0.3s ease, box-shadow 0.3s ease; }
.config-item:hover { transform: translateY(-2px); box-shadow: var(--shadow-lg); }
.config-active { box-shadow: 0 0 0 2px var(--brand-primary) inset; }
.config-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.config-header :deep(.el-icon) { color: var(--brand-primary); }
.config-name { font-weight: 600; font-size: 15px; color: var(--text-primary); }
.pw-tag { margin-left: auto; display: inline-flex; align-items: center; gap: 4px; }
.config-info { margin-bottom: 12px; }
.config-row { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-secondary); margin-bottom: 4px; }
.config-actions { display: flex; gap: 8px; }
</style>
