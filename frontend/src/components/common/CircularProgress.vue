<template>
  <transition name="cp-fade">
    <div v-if="visible" class="circular-progress" :title="`加载中 ${displayPct}%`">
      <svg viewBox="0 0 100 100" class="cp-svg">
        <!-- background ring -->
        <circle cx="50" cy="50" r="42" class="cp-bg" />
        <!-- progress ring -->
        <circle
          cx="50" cy="50" r="42"
          class="cp-ring"
          :class="{ 'cp-ring--done': done }"
          :style="{ strokeDashoffset: dashOffset }"
        />
      </svg>
      <span v-if="!done" class="cp-text">{{ displayPct }}%</span>
      <span v-else class="cp-check">✓</span>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'

const CIRCUMFERENCE = 2 * Math.PI * 42 // ≈ 263.9

interface Props {
  loading: boolean
}

const props = defineProps<Props>()

const displayPct = ref(0)
const done = ref(false)
const visible = ref(false)
let _timer: ReturnType<typeof setInterval> | null = null
let _doneTimer: ReturnType<typeof setTimeout> | null = null

const dashOffset = computed(() => CIRCUMFERENCE * (1 - displayPct.value / 100))

function startProgress() {
  stopProgress()
  displayPct.value = 0
  done.value = false
  visible.value = true
  const startedAt = Date.now()

  _timer = setInterval(() => {
    const elapsed = (Date.now() - startedAt) / 1000

    if (displayPct.value < 70) {
      // Phase 1: blast to 70% in ~2s
      displayPct.value = Math.min(70, elapsed * 35)
    } else if (displayPct.value < 90) {
      // Phase 2: crawl 70→90 over ~3s (after phase 1)
      const phase2Elapsed = Math.max(0, elapsed - 2)
      displayPct.value = Math.min(90, 70 + phase2Elapsed * 6.7)
    } else if (displayPct.value < 99) {
      // Phase 3: crawl 90→99 very slowly (~5s)
      const phase3Elapsed = Math.max(0, elapsed - 5)
      displayPct.value = Math.min(99, 90 + phase3Elapsed * 1.8)
    }

    displayPct.value = Math.round(displayPct.value)
  }, 80)
}

function finishProgress() {
  if (_timer) { clearInterval(_timer); _timer = null }
  displayPct.value = 100
  done.value = true

  _doneTimer = setTimeout(() => {
    visible.value = false
    displayPct.value = 0
    done.value = false
  }, 700)
}

function stopProgress() {
  if (_timer) { clearInterval(_timer); _timer = null }
  if (_doneTimer) { clearTimeout(_doneTimer); _doneTimer = null }
}

watch(() => props.loading, (val) => {
  if (val) {
    startProgress()
  } else {
    // Only finish if we actually started (visible is true)
    if (visible.value) {
      finishProgress()
    }
  }
})
</script>

<style scoped>
.circular-progress {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  position: relative;
  flex-shrink: 0;
}
.cp-svg {
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}
.cp-bg {
  fill: none;
  stroke: #e5e7eb;
  stroke-width: 5;
}
.cp-ring {
  fill: none;
  stroke: #2563eb;
  stroke-width: 5;
  stroke-linecap: round;
  stroke-dasharray: 263.9;
  transition: stroke-dashoffset 0.25s ease;
}
.cp-ring--done {
  stroke: #059669;
}
.cp-text {
  position: absolute;
  font-size: 12px;
  font-weight: 700;
  color: #2563eb;
  user-select: none;
}
.cp-check {
  position: absolute;
  font-size: 18px;
  font-weight: 700;
  color: #059669;
  user-select: none;
}

/* ----- night theme ----- */
:root.theme-night .cp-bg {
  stroke: rgba(255,255,255,0.12);
}
:root.theme-night .cp-text {
  color: #4facfe;
}
:root.theme-night .cp-ring--done {
  stroke: #38ef7d;
}
:root.theme-night .cp-check {
  color: #38ef7d;
}

/* transition */
.cp-fade-enter-active { transition: opacity .25s ease, transform .25s ease; }
.cp-fade-leave-active { transition: opacity .2s ease; }
.cp-fade-enter-from { opacity: 0; transform: scale(0.6); }
.cp-fade-leave-to   { opacity: 0; }
</style>
