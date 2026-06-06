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
          <el-form-item label="密码" required>
            <el-input v-model="conn.password" type="password" show-password :prefix-icon="Lock" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item class="form-actions">
        <el-button type="primary" native-type="submit" :loading="connecting" size="large">
          <el-icon><Link /></el-icon> 连接
        </el-button>
        <el-button @click="saveCurrentConfig" :disabled="!conn.host" size="large">
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
          :key="config.name"
          class="config-item"
          shadow="hover"
          :body-style="{ padding: '16px' }"
        >
          <div class="config-header">
            <el-icon :size="20" color="#409EFF"><OfficeBuilding /></el-icon>
            <span class="config-name">{{ config.name }}</span>
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
            <el-button type="danger" size="small" plain @click="deleteConfig(config.name)" aria-label="删除配置">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </el-card>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  Connection, Monitor, User, Lock, Link, Star, Collection,
  OfficeBuilding, Switch, Delete,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { sftpApi } from '../../../api/sftp'

export interface SftpConfig {
  name: string
  host: string
  port: number
  username: string
  password: string
}

const emit = defineEmits<{
  connected: []
}>()

const conn = ref({ host: '', port: 22, username: '', password: '' })
const connecting = ref(false)
const savedConfigs = ref<SftpConfig[]>([])

onMounted(() => {
  loadSavedConfigs()
})

function loadSavedConfigs() {
  try {
    const data = localStorage.getItem('sftp_configs')
    if (data) savedConfigs.value = JSON.parse(data)
  } catch {
    savedConfigs.value = []
  }
}

function saveConfigs() {
  localStorage.setItem('sftp_configs', JSON.stringify(savedConfigs.value))
}

function saveCurrentConfig() {
  if (!conn.value.host) return
  const name = prompt('配置名称:', conn.value.host)
  if (!name) return
  const existing = savedConfigs.value.findIndex(c => c.name === name)
  const config: SftpConfig = { name, ...conn.value }
  if (existing >= 0) savedConfigs.value[existing] = config
  else savedConfigs.value.push(config)
  saveConfigs()
  ElMessage.success('配置已保存')
}

function loadConfig(config: SftpConfig) {
  conn.value = { ...config }
}

function deleteConfig(name: string) {
  savedConfigs.value = savedConfigs.value.filter(c => c.name !== name)
  saveConfigs()
  ElMessage.success('配置已删除')
}

async function doConnect() {
  connecting.value = true
  try {
    await sftpApi.connect(conn.value.host, conn.value.port, conn.value.username, conn.value.password)
    ElMessage.success('已连接')
    emit('connected')
  } catch { ElMessage.error('连接失败') }
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
.config-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.config-name { font-weight: 600; font-size: 15px; color: var(--text-primary); }
.config-info { margin-bottom: 12px; }
.config-row { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-secondary); margin-bottom: 4px; }
.config-actions { display: flex; gap: 8px; }
</style>
