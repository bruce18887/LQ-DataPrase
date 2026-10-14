<template>
  <GridBackground>
    <div class="connect-container" data-test="connect-page">
      <div class="connect-card">
        <div class="logo-section">
          <el-icon :size="56" class="logo-icon"><Connection /></el-icon>
        </div>
        <h1 class="connect-title">选择这台机器的连接方式</h1>
        <p class="connect-subtitle">
          {{ cfg.firstRun ? '首次运行 · 决定以后连哪个后端' : '当前连接设置' }}
        </p>

        <el-alert
          v-if="showUnreachableBanner"
          class="banner"
          type="error"
          :closable="false"
          show-icon
          title="上次配置的服务器连不上"
          :description="`地址 ${cfg.serverUrl} 无响应。可以先重试，或改回「本机模式」马上开始工作。`"
        />

        <el-radio-group v-model="mode" class="mode-group">
          <el-radio value="local" data-test="mode-local">
            本机模式
            <span class="mode-desc">在这台电脑上内嵌运行分析后端，数据存在本机</span>
          </el-radio>
          <el-radio value="remote" data-test="mode-remote">
            连接服务器
            <span class="mode-desc">界面仍在这个窗口里，数据与算力都在局域网的服务器上</span>
          </el-radio>
        </el-radio-group>

        <div v-if="mode === 'remote'" class="url-section">
          <el-input
            v-model="serverUrl"
            size="large"
            placeholder="http://10.0.0.9:8000"
            clearable
            data-test="server-url"
            @keyup.enter="handleSave"
          />
          <p v-if="error" class="form-error" data-test="connect-error">{{ error }}</p>
          <p v-else class="form-hint">
            填服务器给的完整地址（含 http:// 与端口）。填错不会弄坏东西 —— 连不上时会回到这一页。
          </p>
        </div>

        <el-alert
          class="banner"
          type="warning"
          :closable="false"
          show-icon
          title="两边历史不互通"
          description="从「本机模式」改到「连接服务器」后，本机积累的分析历史与批报告留在本机、不会带到服务器；服务器端从空库开始。反向切换同理。"
        />

        <div class="actions">
          <el-button
            size="large"
            type="primary"
            :loading="saving"
            :disabled="!bridgeAvailable"
            data-test="save-restart"
            @click="handleSave"
          >
            {{ cfg.firstRun ? '开始使用' : '保存并重启' }}
          </el-button>
          <el-button v-if="!cfg.firstRun" size="large" :disabled="saving" @click="loadConfig">
            放弃修改
          </el-button>
        </div>

        <p v-if="!bridgeAvailable" class="form-hint">
          这一页需要桌面客户端：浏览器里请直接访问服务器地址，或在电脑上运行 LQ-DataPrase。
        </p>
      </div>
    </div>
  </GridBackground>
</template>

<script setup lang="ts">
/**
 * 首次运行的「连哪个后端」选择页（#\/connect）。
 *
 * 为什么做成前端路由而不是 Electron 原生对话框：判据与校验只该有一份（都在
 * `electron/client-config.ts`，有 T2 单测），这里只搬运字符串；同时前端路由天然
 * 继承设计系统的 CSS token，dark/light 两套主题不用另写一遍。
 *
 * 为什么首启**不先起本机后端**再问：那样做的话，用户选了服务器，本机那份库也已经
 * 被建好了 —— 等于替他做了一个他没做的决定。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Connection } from '@element-plus/icons-vue'
import GridBackground from '../../components/common/GridBackground.vue'

type Mode = 'local' | 'remote'

interface ConfigView {
  mode: Mode
  serverUrl: string
  reachable: boolean | null
  firstRun: boolean
}

const DEFAULT_VIEW: ConfigView = { mode: 'local', serverUrl: '', reachable: null, firstRun: true }

const cfg = ref<ConfigView>({ ...DEFAULT_VIEW })
const mode = ref<Mode>('local')
const serverUrl = ref('')
const error = ref('')
const saving = ref(false)

const bridgeAvailable = computed(() => typeof window !== 'undefined' && !!window.electronAPI)
const showUnreachableBanner = computed(
  () => cfg.value.mode === 'remote' && cfg.value.reachable === false,
)

async function loadConfig(): Promise<void> {
  if (!window.electronAPI) return
  const view = (await window.electronAPI.getClientConfig()) as ConfigView
  cfg.value = view
  mode.value = view.mode
  serverUrl.value = view.serverUrl
  error.value = ''
}

async function handleSave(): Promise<void> {
  error.value = ''
  if (!window.electronAPI) {
    error.value = '浏览器形态无法切换连接方式，请直接访问服务器地址。'
    return
  }
  if (mode.value === 'remote' && !serverUrl.value.trim()) {
    error.value = '请填写服务器地址，例如 http://10.0.0.9:8000'
    return
  }

  saving.value = true
  try {
    const result = await window.electronAPI.setClientConfig({
      mode: mode.value,
      serverUrl: serverUrl.value.trim(),
    })
    if (!result.ok) {
      // 校验原因由主进程给出（那里是唯一一处判据），这里直接显示，不在前端再校验一遍
      error.value = result.error ?? '保存失败'
      return
    }
    // **两种情况都必须重启**：首启时主进程刻意没有 spawn 本机后端（见 planStartup），
    // 若不重启，用户选完「本机模式」会停在这个页面上面对一个根本不存在的后端。
    ElMessage.success(cfg.value.firstRun ? '已按所选方式保存，正在启动' : '已保存，正在重启以切换后端')
    await window.electronAPI.restartApp()
  } finally {
    saving.value = false
  }
}

onMounted(loadConfig)
</script>

<style scoped>
.connect-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.connect-card {
  width: 100%;
  max-width: 520px;
  padding: 32px 28px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow-lg);
}

.logo-section {
  display: flex;
  justify-content: center;
}

.logo-icon {
  color: var(--brand);
}

.connect-title {
  margin: 12px 0 4px;
  text-align: center;
  font-size: var(--p-fs-hero);
  color: var(--text);
}

.connect-subtitle {
  margin: 0 0 16px;
  text-align: center;
  font-size: var(--p-fs-base);
  color: var(--text-2);
}

.banner {
  margin-bottom: 16px;
}

.mode-group {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 16px;
  width: 100%;
}

.mode-group :deep(.el-radio) {
  height: auto;
  align-items: flex-start;
  white-space: normal;
  width: 100%;
}

.mode-desc {
  display: block;
  margin-top: 2px;
  font-size: var(--p-fs-dense);
  color: var(--text-2);
}

.url-section {
  margin-bottom: 16px;
}

.form-error {
  margin: 6px 0 0;
  color: var(--error);
  font-size: var(--p-fs-dense);
}

.form-hint {
  margin: 6px 0 0;
  color: var(--text-2);
  font-size: var(--p-fs-dense);
  line-height: 1.5;
}

.actions {
  display: flex;
  gap: 12px;
  margin-top: 8px;
}
</style>
