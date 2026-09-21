<template>
  <!--
    结构是计划 Task 17 Step 4 给定的**契约**：四个 `data-testid` 与 `class="search-cancel-btn"`
    由 Task 18 的 e2e 按名定位，一个字都不能改（`sftp-search-chip` / `-chip-scanned` /
    `-chip-matched` / `search-cancel-btn`）。

    `v-if` 挂的是 `store.chipRun`（「哪一条 run 该被报出来」的口径住在 store 里，理由见那里）：
    有任一条件在跑就非空，所以它与计划原文的 `v-if="store.isRunning"` 等价，而模板里的
    `run.matches` 永远不必在 null 上取属性。

    只在 running 时出现：搜索一结束 chip 就消失，所以「结束后不可见」是设计性质而非缺陷
    （Task 18 Step 5 会显式断言 `toBeHidden()`）。
  -->
  <div v-if="run" class="asc" data-testid="sftp-search-chip" role="status" aria-live="polite">
    <router-link class="asc-go" :to="{ name: 'SftpSearch' }" title="回到搜索页查看完整结果">
      <span class="asc-title">SFTP 搜索进行中</span>
    </router-link>
    <span class="asc-metric" data-testid="sftp-search-chip-scanned" :title="stageHint">
      {{ scannedText }}
    </span>
    <span class="asc-sep" aria-hidden="true">·</span>
    <!-- 命中数：store 只在 `match` 事件上 push，chipRun 为真时该 run 必未被摘要化
         （`compactHistory` 从 i=1 起跳过 running 条目，而 running 的那条要么仍是 activeRun、
         要么正因为是历史条目才被判 running）——所以直接读数组长度是可信的 -->
    <span class="asc-metric" data-testid="sftp-search-chip-matched" title="命中条数">
      {{ run.matches.length }}
    </span>
    <el-button
      class="search-cancel-btn"
      data-testid="search-cancel-btn"
      :icon="CircleClose"
      size="small"
      circle
      aria-label="取消搜索"
      @click="onCancel"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * App 级常驻 chip（计划 Task 17 Step 4 / spec §1.2「结果与运行状态跨页面驻留」）。
 *
 * 挂在 `layouts/MainLayout.vue` 的 Topbar 之下、内容区之上 —— **不是** `SftpBrowser.vue`
 * 内部：只有挂在所有业务页面共用的那层布局上，切到数据管理页/仪表板时它才还在，
 * 「搜索在跑」这件事才看得见。它自己不持有任何状态，全部读 `useSftpSearchStore`
 * （流的所有权在 store，组件卸载不会中断它，见 store 顶部注释）。
 */
import { computed } from 'vue'
import { CircleClose } from '@element-plus/icons-vue'
import { useSftpSearchStore } from '../../stores/sftpSearch'

const store = useSftpSearchStore()

/** 全部判据住在 store：这里只取「该报出来的那条 run」，组件不自己拼条件 */
const run = computed(() => store.chipRun)

/**
 * 取消**这一条**（显式带 id）：`cancel()` 无参取消的是 activeRun，而 chip 显示的
 * 可能是用户从历史里切走之后仍在跑的那条 —— 不带 id 就会取消到一条已结束的运行上，
 * `cancel()` 对非 running 直接 return，表现是「点了没反应」。
 */
function onCancel(): void {
  const r = run.value
  if (r) store.cancel(r.id)
}

const scannedText = computed(() => `已扫描 ${run.value?.progress?.files_scanned ?? 0} 个文件`)
const stageHint = computed(() => {
  const r = run.value
  if (!r) return ''
  const p = r.progress
  return `阶段 ${p?.stage ?? 'listing'} · 候选 ${r.candidateCount} · 用时 ${
    (p?.elapsed_s ?? 0).toFixed(1)}s`
})
</script>

<style scoped>
.asc {
  display: flex;
  align-items: center;
  gap: var(--p-space-2);
  padding: var(--p-space-2) var(--p-space-6);
  background: color-mix(in srgb, var(--brand) 12%, var(--bg-2));
  border-bottom: 1px solid var(--border-2);
  font-size: var(--p-fs-dense);
  color: var(--text-2);
}
.asc-title { font-weight: var(--p-fw-semibold); color: var(--text); }
.asc-go { text-decoration: none; }
.asc-go:hover .asc-title { color: var(--brand); }
.asc-metric { font-variant-numeric: tabular-nums; }
.asc-sep { color: var(--text-3); }
.search-cancel-btn {
  margin-left: auto;
  color: var(--text-2);
  border-color: var(--border-2);
}
.search-cancel-btn:hover { color: var(--error); border-color: var(--error); }
</style>
