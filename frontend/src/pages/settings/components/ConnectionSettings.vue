<template>
  <div class="conn-block">
    <el-descriptions :column="1" border class="conn-descriptions">
      <el-descriptions-item label="当前后端">
        <el-tag :type="remoteMode ? 'warning' : 'success'" size="small" effect="plain" data-test="conn-mode-tag">
          {{ remoteMode ? '远端服务器' : '本机内嵌' }}
        </el-tag>
        <span v-if="remoteMode" class="conn-url" data-test="conn-url">{{ view.serverUrl }}</span>
        <el-tag v-else size="small" type="info" effect="plain" class="conn-url">
          随应用在本机启动，端口自动分配
        </el-tag>
      </el-descriptions-item>
    </el-descriptions>

    <div v-if="bridgeAvailable" class="conn-actions">
      <el-button @click="goConnect" data-test="conn-change">更改连接方式</el-button>
      <span class="conn-hint">
        切换会重启应用：本机与远端是两个不同的后端进程，数据也各在各自的位置，无法热切换。
      </span>
    </div>
    <p v-else class="conn-hint">
      在浏览器里访问时，连接方式由你打开的地址决定，无需在此设置。
    </p>
  </div>
</template>

<script setup lang="ts">
/**
 * 设置页里的「连哪个后端」入口。
 *
 * 这里**不重复实现表单**：判据与校验只有一份，都在 `electron/client-config.ts` +
 * `pages/auth/ConnectPage.vue`。设置页只负责显示现状并把用户送到那一页 ——
 * 两处各写一遍地址校验必然漂移（lessons 2026-09-19「同一个区间的多份字面量」同一类问题）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

interface ConfigView {
  mode: 'local' | 'remote'
  serverUrl: string
  reachable: boolean | null
  firstRun: boolean
}

const view = ref<ConfigView>({ mode: 'local', serverUrl: '', reachable: null, firstRun: false })

const bridgeAvailable = computed(() => typeof window !== 'undefined' && !!window.electronAPI)
const remoteMode = computed(() => view.value.mode === 'remote')

async function load(): Promise<void> {
  if (!window.electronAPI) return
  try {
    view.value = await window.electronAPI.getClientConfig()
  } catch {
    // 读不到就维持默认显示，不阻塞设置页其余部分
  }
}

function goConnect(): void {
  router.push('/connect')
}

onMounted(load)
</script>

<style scoped>
.conn-block {
  margin-bottom: 16px;
}

.conn-descriptions {
  margin-bottom: 10px;
}

.conn-url {
  margin-left: 8px;
  font-size: var(--p-fs-dense);
  color: var(--text-2);
  word-break: break-all;
}

.conn-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.conn-hint {
  margin: 0;
  font-size: var(--p-fs-dense);
  color: var(--text-2);
  line-height: 1.5;
}
</style>
