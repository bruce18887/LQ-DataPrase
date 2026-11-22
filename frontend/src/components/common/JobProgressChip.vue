<script setup lang="ts">
/**
 * 作业进度的极简显示：一条百分比条 + 一个数字。
 *
 * 还在队列里（后端 `queue_position > 0`）时数字位换成「排队中 · 前面 N 个」：
 * 那种时候进度条恒为 0%，一直显示 0% 等于告诉用户「没动静」。
 *
 * **没有复用 `SftpDownloadProgress.vue`**，理由是语义不对而不是偷懒：那张卡的 props 是
 * `speed / eta / bytes_done / total_bytes`（字节传输），而导出作业只汇报「完成百分之几」。
 * 套上去会显示「0 B/s、ETA —」这种看着精确其实是假话的数字。
 * 同类先例见 `SearchProgress.vue` 的文件注释（它也明确不复用那张卡）。
 *
 * 样式只认 token（`--text-2 / --brand / --p-fs-*`），日/夜主题由
 * `styles/design-tokens.css` 与 `styles/element-plus-theme.css` 切换，
 * 这里不许出现写死的颜色值。
 */
import { computed } from 'vue'

import { queuePositionText } from '../../composables/jobPolling'

const props = defineProps<{
  /** 0–100。 */
  percent: number
  /** 只在作业进行中时显示；完成后立刻消失，不留下「100%」的死元素。 */
  active: boolean
  /**
   * 同 owner 里排在我前面的作业数（0 = 下一个就轮到我）。
   * 只有「还没跑起来（percent 为 0）」时才有意义：那时显示百分比等于一直说 0%。
   */
  queuePosition?: number
}>()

const shown = computed(() => props.active)
const clamped = computed(() => Math.max(0, Math.min(100, Math.round(props.percent))))
/** 排队文案；进度一动就让位给百分比（`queuePositionText` 自己把 0 收敛成 null）。 */
const queueText = computed(() => (clamped.value === 0 ? queuePositionText(props.queuePosition ?? 0) : null))
const label = computed(() => queueText.value ?? `${clamped.value}%`)
const ariaLabel = computed(() => (
  queueText.value ? `导出${queueText.value}` : `导出进行中 ${clamped.value}%`
))
</script>

<template>
  <span
    v-if="shown"
    class="job-progress"
    data-testid="job-progress"
    role="status"
    :aria-label="ariaLabel"
  >
    <el-progress
      class="job-progress__bar"
      :percentage="clamped"
      :stroke-width="6"
      :show-text="false"
    />
    <span class="job-progress__text">{{ label }}</span>
  </span>
</template>

<style scoped>
.job-progress {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 104px;
  font-size: var(--p-fs-sm, 12px);
  color: var(--text-2);
}

.job-progress__bar {
  flex: 1 1 60px;
  min-width: 60px;
}

/* el-progress 在 element-plus-theme.css 里**没有** night 覆盖（实测 grep 零命中），
   所以它的轨道/条色会退回 EP 默认的浅灰 —— night 下就是一条几乎看不见的槽。
   这里显式绑到 token 上，不去赌默认值：这类「功能全绿但夜里不可读」正是
   e2e/theme/night-visibility.spec.ts 存在的理由。 */
.job-progress__bar :deep(.el-progress-bar__outer) {
  background-color: var(--border-2);
}

.job-progress__bar :deep(.el-progress-bar__inner) {
  background-color: var(--brand);
}

.job-progress__text {
  /* 数字用等宽避免进度变化时整行左右抖动 */
  font-variant-numeric: tabular-nums;
  min-width: 34px;
  text-align: right;
  /* 排队文案比「100%」长得多：不让它折成两行把 chip 撑高 */
  white-space: nowrap;
}
</style>
