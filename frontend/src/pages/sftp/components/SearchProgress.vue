<template>
  <el-card class="search-progress" shadow="never">
    <div class="sp-row">
      <div class="sp-col">
        <el-tooltip :content="statusHint" placement="top">
          <span class="sp-badge" :class="`sp-badge--${status}`" data-testid="sftp-search-status">{{ status }}</span>
        </el-tooltip>
        <span class="sp-stage">{{ stageText }}</span>
        <el-tooltip :content="engineHint" placement="top" :disabled="!engineReason">
          <span class="sp-engine">引擎 <span data-testid="sftp-search-engine">{{ engineText }}</span></span>
        </el-tooltip>
        <span v-if="workersActual" class="sp-meta">并发 {{ workersActual }}</span>
      </div>
      <div class="sp-col sp-col--end">
        <span class="sp-counts">{{ countsText }}</span>
        <el-tooltip v-if="running" content="取消搜索" placement="top">
          <el-button
            class="search-cancel-btn"
            data-testid="search-cancel-btn"
            :icon="CircleClose"
            size="small"
            circle
            aria-label="取消搜索"
            @click="emit('cancel')"
          />
        </el-tooltip>
      </div>
    </div>

    <!-- 态二：有分母（scanning 档 = 候选数）→ 百分比 -->
    <el-progress
      v-if="running && percent !== null"
      class="sp-bar"
      :percentage="percent"
      :stroke-width="10"
      :format="(p: number) => `${p}%`"
    />
    <!-- 态一：无分母（listing 阶段与 grep 档全程）→ 不定档流光带 + 纯计数 -->
    <div v-else-if="running" class="sp-band" role="progressbar" :aria-label="stageText">
      <span class="sp-band-glide" />
    </div>
    <!-- 态三：stage done / 已收尾 → 只留上面那一行摘要 -->

    <!-- partial 黄条：常驻、不可关闭（spec §3.13 四条硬约束之一）。
         判据是 `notice.incomplete`（= 后端 events.INCOMPLETE_CODES），**不是**「收到过任何
         告知」：换引擎/少并发那几个码只影响快慢，染成黄色就是谎报结果不完整。
         文案逐字用后端送来的 `message`（前端不维护第二份码表）。 -->
    <el-alert
      v-if="incompleteLines.length"
      class="sp-alert"
      type="warning"
      :closable="false"
      show-icon
      title="结果不完整：已触达上限"
      data-testid="sftp-search-truncated"
    >
      <!-- data-code 只给 e2e 定位「说的是哪一条上限」用，用户看得见的是那句中文 -->
      <p v-for="n in incompleteLines" :key="n.code" class="sp-alert-line" :data-code="n.code">
        {{ n.message }}
      </p>
      <p class="sp-alert-line">真实结果可能更多，请缩小范围或放宽上限后重搜。</p>
    </el-alert>

    <!-- 中性告知：钳位 + 「只影响快慢」的降级（incomplete=false）。同样来自 notice，
         同样不可关（关掉就等于把「这次是哪档跑的」藏回去）。 -->
    <div
      v-if="neutralLines.length"
      class="sp-notices"
      data-testid="sftp-search-notices"
      role="note"
    >
      <span v-for="n in neutralLines" :key="n.code" class="sp-notice" :data-code="n.code">
        {{ n.message }}
      </span>
    </div>
  </el-card>
</template>

<script setup lang="ts">
/**
 * 搜索进度（计划 Task 15 Step 1 / spec §3.8「进度分母按阶段变」）—— **三态**：
 * 1. `total === null` → 不定档：CSS 流光带 + 纯计数（listing 阶段与 grep 档全程走这里，
 *    因为那一档压根没有可信分母）；
 * 2. `total` 为数字 → `el-progress` 百分比（scanning 档，分母 = 候选数）；
 * 3. 收尾（`stage === 'done'` 或状态已不是 running）→ 收成上面那一行摘要。
 *
 * 为什么不复用 `SftpDownloadProgress.vue`：那个组件的 `mode` 契约是 `file|dir` 两种
 * **百分比**语义，塞不进「无分母」这一态；它的取消按钮 class `.dl-cancel-btn` 还有既有
 * e2e 依赖。混用等于同时改坏两个组件（spec §3.8 末注已记这个决定）。
 *
 * 状态本身**不住在这里**：全部由调用方从 `useSftpSearchStore` 的 activeRun 取好再传进来
 * （流的所有权在 store，组件只是个渲染面），本组件不持有任何运行状态。
 *
 * e2e 契约钩子（Task 18 按名定位，勿改）：`sftp-search-status`（文本恒为 store 的五个
 * 英文状态值之一，中文文案走 tooltip）、`sftp-search-engine`（恒为 `client` / `grep`）、
 * `search-cancel-btn`（与 chip 上那个同名不同实例，两处都要在）、
 * `sftp-search-truncated`（黄条）/ `sftp-search-notices`（中性告知），两者内部的
 * `[data-code]` 用来钉「说的是哪一条上限」——码名只在属性里，用户读到的一直是中文。
 *
 * 提示文案不在这里写：`run.notices`（后端 `notice` 事件）带中文 `message` 与 `incomplete`
 * 旗标，组件只负责分两行渲染（spec §3.8「引擎回落必须进 notice，不能让人猜这次是哪档跑的」）。
 */
import { computed } from 'vue'
import { CircleClose } from '@element-plus/icons-vue'
import type { SearchEngine, SearchNotice } from '../../../api/sftpSearch'
import type { SearchRunStatus } from '../../../stores/sftpSearch'

const props = withDefaults(defineProps<{
  stage: string
  status: SearchRunStatus
  done: number
  /** `null` = 不定档（态一） */
  total: number | null
  elapsedS: number
  matched: number
  candidates: number
  engine?: SearchEngine | null
  /** `hello.engine_reason`：为什么是这一档，tooltip 给全文 */
  engineReason?: string
  workersActual?: number
  /**
   * 本次运行收到的全部告知（`notice` 事件原样收在 store 的 `run.notices` 里）。
   * 黄条与中性行都由它算：文案取后端 `message`，`incomplete` 旗标取后端
   * `events.INCOMPLETE_CODES` —— 这个组件里没有任何一份码名表。
   */
  notices?: SearchNotice[]
}>(), {
  engine: null,
  engineReason: '',
  workersActual: 0,
  notices: () => [],
})

const emit = defineEmits<{ (e: 'cancel'): void }>()

const running = computed(() => props.status === 'running')

/** 百分比：只在有正分母时才算；`total` 为 0/NaN 一律退回不定档（不显示 0% 假进度） */
const percent = computed<number | null>(() => {
  const total = props.total
  if (total === null || !Number.isFinite(total) || total <= 0) return null
  const done = Number.isFinite(props.done) ? props.done : 0
  return Math.max(0, Math.min(100, Math.round((done / total) * 100)))
})

const STAGE_TEXT: Record<string, string> = {
  listing: '列目录中', scanning: '扫描中', done: '已结束',
}
const stageText = computed(() => STAGE_TEXT[props.stage] ?? props.stage)

const STATUS_HINT: Record<SearchRunStatus, string> = {
  running: '搜索进行中', done: '已完成', partial: '已完成，但结果被上限截断',
  cancelled: '已取消', error: '搜索失败或流意外中断',
}
const statusHint = computed(() => STATUS_HINT[props.status] ?? props.status)

const engineText = computed(() => props.engine ?? 'pending')
const engineHint = computed(() => props.engineReason || '引擎尚未确定')

const elapsedText = computed(() =>
  (Number.isFinite(props.elapsedS) ? props.elapsedS : 0).toFixed(1))

/** grep 档没有候选阶段（spec §3.8：它只有命中流），所以计数里不摆候选 */
const countsText = computed(() => {
  const scanned = props.stage === 'listing' ? '已列出' : '已扫描'
  const parts = [`${scanned} ${props.done}`]
  if (props.engine !== 'grep') parts.push(`候选 ${props.candidates}`)
  parts.push(`命中 ${props.matched}`, `${elapsedText.value}s`)
  return parts.join(' · ')
})

/**
 * 两条提示行按后端那个 `incomplete` 旗标分家：`true` → 常驻黄条（结果集不完整），
 * `false` → 中性一行（钳位、换引擎、少并发：用户的输入被完整执行了，只是慢）。
 * 判据住在 `events.py`，这里连一个码名都不出现 —— 见 props 上那段注释。
 */
const incompleteLines = computed(() => props.notices.filter(n => n.incomplete))
const neutralLines = computed(() => props.notices.filter(n => !n.incomplete))

</script>

<style scoped>
.search-progress {
  border-radius: var(--p-radius-md);
  margin-bottom: var(--p-space-2);
  border-left: 4px solid var(--brand);
}
.search-progress :deep(.el-card__body) { padding: 12px 20px; }
.sp-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--p-space-3);
  flex-wrap: wrap;
}
.sp-col { display: flex; align-items: center; gap: var(--p-space-2); flex-wrap: wrap; }
.sp-col--end { justify-content: flex-end; }

/* 徽章：彩底 + 同色文字（与 Badge.vue 同源写法），文本恒为英文状态值 */
.sp-badge {
  padding: 2px 8px;
  border-radius: var(--p-radius-sm);
  font-size: var(--p-fs-micro);
  font-weight: var(--p-fw-bold);
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.sp-badge--running { background: color-mix(in srgb, var(--brand) 13%, transparent); color: var(--brand); }
.sp-badge--done { background: color-mix(in srgb, var(--success) 13%, transparent); color: var(--success); }
.sp-badge--partial { background: color-mix(in srgb, var(--warn) 15%, transparent); color: var(--warn); }
.sp-badge--cancelled { background: color-mix(in srgb, var(--text-2) 12%, transparent); color: var(--text-2); }
.sp-badge--error { background: color-mix(in srgb, var(--error) 13%, transparent); color: var(--error); }

.sp-stage { font-weight: var(--p-fw-semibold); font-size: var(--p-fs-base); color: var(--text); }
.sp-engine, .sp-meta { font-size: var(--p-fs-small); color: var(--text-2); }
.sp-engine [data-testid="sftp-search-engine"] { font-variant-numeric: tabular-nums; color: var(--text-2); }
.sp-counts { font-size: var(--p-fs-small); color: var(--text-2); font-variant-numeric: tabular-nums; }

/* 态一：不定档流光带（纯 CSS，无字面色） */
.sp-band {
  position: relative;
  overflow: hidden;
  height: 6px;
  margin-top: var(--p-space-3);
  border-radius: var(--p-radius-full);
  background: var(--bg-3);
}
.sp-band-glide {
  position: absolute;
  inset: 0;
  width: 36%;
  border-radius: inherit;
  background: linear-gradient(90deg, transparent, var(--brand), transparent);
  animation: sp-sweep 1.3s ease-in-out infinite;
}
@keyframes sp-sweep {
  from { transform: translateX(-110%); }
  to { transform: translateX(300%); }
}
@media (prefers-reduced-motion: reduce) {
  .sp-band-glide { animation: none; width: 100%; opacity: 0.5; }
}

.sp-bar { margin-top: var(--p-space-3); }
.sp-alert { margin-top: var(--p-space-3); }
/* 黄条里的每一行是一条上限（后端文案），行距压到最小以免把进度挤下去 */
.sp-alert-line { margin: 0; font-size: var(--p-fs-small); }
.sp-alert-line + .sp-alert-line { margin-top: 2px; }

/* 中性告知：与黄条同一份 notice，只是 incomplete=false，所以用 --info 描边而非警告色。
   全部语义 token，dark/light 两套都跟着 design-tokens 走。 */
.sp-notices {
  margin-top: var(--p-space-3);
  padding: var(--p-space-2) var(--p-space-3);
  border: 1px solid var(--border-2); border-left: 3px solid var(--info);
  border-radius: var(--p-radius-sm); background: var(--bg-2);
  display: flex; flex-direction: column; gap: 2px;
}
.sp-notice { font-size: var(--p-fs-micro); color: var(--text-2); }
.search-cancel-btn { color: var(--text-2); border-color: var(--border-2); }
.search-cancel-btn:hover { color: var(--error); border-color: var(--error); }
</style>
