<template>
  <!-- QA 数量校验（指南 §10.8 四色横幅 + §11.3）：单行汇总（级别取最高）+
       点击展开明细（各阶段 入库数 = 测试数 对照）；无校验零占位。 -->
  <div
    v-if="checks.length"
    class="qa-banner"
    :class="`qa-banner--${tone}`"
    role="status"
    data-testid="qa-banner"
  >
    <div class="banner-head" role="button" tabindex="0" @click="open = !open" @keydown.enter="open = !open">
      <span class="b-icon">{{ tone === 'success' ? '✅' : '⚠️' }}</span>
      <span class="b-title">{{ title }}</span>
      <span class="b-toggle">{{ open ? '收起明细' : '展开明细' }} <span class="b-caret">{{ open ? '▴' : '▾' }}</span></span>
    </div>
    <ul v-if="open" class="banner-body">
      <li v-for="(c, i) in checks" :key="i">
        <b>{{ c.check }}</b> — 期望 <b>{{ c.expected }}</b> / 实际 <b>{{ c.actual }}</b>
        <span :class="isOk(c) ? 'st-ok' : 'st-warn'">{{ c.status }}</span>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  checks: { check: string; expected: string; actual: string; status: string }[]
}>()

const open = ref(false)

function isOk(c: { check: string; expected: string; actual: string; status: string }): boolean {
  return !c.status.includes('差异') && c.expected === c.actual
}

const passCount = computed(() => props.checks.filter(isOk).length)

const tone = computed<'success' | 'warning'>(() =>
  passCount.value === props.checks.length ? 'success' : 'warning'
)

const title = computed(() =>
  tone.value === 'success'
    ? `QA 数量校验 ${passCount.value}/${props.checks.length} 通过`
    : `QA 数量校验 ${passCount.value}/${props.checks.length} 通过 · ${props.checks.length - passCount.value} 项差异`
)
</script>

<style scoped>
.qa-banner {
  margin-bottom: 14px;
  border-radius: 12px;
  border: 1px solid;
}
.qa-banner--success {
  background: color-mix(in srgb, var(--success) 10%, transparent);
  border-color: color-mix(in srgb, var(--success) 40%, transparent);
}
.qa-banner--warning {
  background: color-mix(in srgb, var(--warn) 10%, transparent);
  border-color: color-mix(in srgb, var(--warn) 40%, transparent);
}

.banner-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  cursor: pointer;
}
.b-icon { font-size: 15px; }
.b-title {
  font-weight: 700;
  font-size: 13px;
}
.qa-banner--success .b-title { color: var(--success); }
.qa-banner--warning .b-title { color: var(--warn); }

.b-toggle {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-2);
  display: inline-flex;
  gap: 4px;
  align-items: center;
}

.banner-body {
  padding: 0 16px 11px 42px;
  font-size: 12px;
  color: var(--text-2);
}
.banner-body li {
  margin: 3px 0 3px 14px;
}
.banner-body li b {
  color: var(--text);
}
.st-ok { color: var(--success); font-weight: 600; }
.st-warn { color: var(--warn); font-weight: 600; }
</style>
