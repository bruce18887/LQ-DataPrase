<template>
  <el-dialog
    v-model="visible"
    title="关于 LQ-DataPrase"
    width="360px"
    align-center
    append-to-body
    class="app-about-dialog"
  >
    <div class="about-body">
      <div class="about-title">
        <span class="about-logo">📊</span>
        <span>LQ-DataPrase</span>
      </div>
      <div class="about-sub">ATE 量产数据分析平台</div>

      <dl class="about-meta">
        <div class="about-row">
          <dt>版本</dt>
          <dd>v{{ APP_VERSION }}</dd>
        </div>
        <div class="about-row">
          <dt>构建</dt>
          <dd>{{ BUILD_COMMIT }} · {{ BUILD_DATE }}</dd>
        </div>
        <div class="about-row">
          <dt>运行环境</dt>
          <dd>{{ isElectronEnv() ? 'Electron' : '浏览器' }} · {{ getPlatformLabel() }}</dd>
        </div>
      </dl>
    </div>
    <template #footer>
      <el-button size="small" @click="close">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useAboutDialog } from '../../composables/useAboutDialog'
import { APP_VERSION, BUILD_COMMIT, BUILD_DATE, getPlatformLabel, isElectronEnv } from '../../utils/version'

const { visible, close } = useAboutDialog()

// Electron 菜单 Help → About LQ-DataPrase 打开对话框
let unsubscribe: (() => void) | null = null

onMounted(() => {
  if (window.electronAPI?.onMenuAbout) {
    unsubscribe = window.electronAPI.onMenuAbout(() => {
      visible.value = true
    })
  }
})

onUnmounted(() => {
  unsubscribe?.()
})
</script>

<style scoped>
.about-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.about-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.about-logo {
  font-size: 22px;
}

.about-sub {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.about-meta {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.about-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}

.about-row dt {
  color: var(--text-secondary);
}

.about-row dd {
  margin: 0;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
</style>
