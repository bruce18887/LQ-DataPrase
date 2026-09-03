<template>
  <!-- UPH 紧凑明细行（指南 §11.1/§2.5.3，取代大格区块卡）：
       平均测试时间 / 总耗时 / 并行站点数 / 各站点独立小格 / 来源标签 / 警告 / 公式（? 悬停）。
       embedded（批次 Bin 分布卡内嵌）：不渲染卡片壳，标题由父级分区提供。 -->
  <div class="uph-card" :class="{ 'uph-card--embedded': embedded }">
    <template v-if="!embedded">
      <div class="uph-shell">
        <div class="uph-head">
          <h3>⚡ UPH 效率明细</h3>
          <span class="uph-head-desc">紧凑信息带：核心数字在总览条，明细/公式/来源/警告在此</span>
        </div>
        <div class="uph-body">
          <UphDetail
            :data="data"
            :loading="loading"
            :error="error"
            :source-tag="sourceTag"
          />
        </div>
      </div>
    </template>
    <UphDetail
      v-else
      :data="data"
      :loading="loading"
      :error="error"
      :source-tag="sourceTag"
    />
  </div>
</template>

<script lang="ts">
import { defineComponent, h, ref, computed, watch, type PropType } from 'vue'
import { QuestionFilled } from '@element-plus/icons-vue'
import { ElTooltip, ElIcon, ElEmpty } from 'element-plus'
import { analysisApi } from '../../../api/analysis'
import type { UphData } from '../../../types'

/** 紧凑明细行内容（单文件卡内与批次 embedded 共用） */
const UphDetail = defineComponent({
  name: 'UphDetail',
  props: {
    data: { type: Object as PropType<UphData | null>, default: null },
    loading: { type: Boolean, default: false },
    error: { type: Boolean, default: false },
    sourceTag: {
      type: Object as PropType<{ tone: 'success' | 'brand' | 'warn' | 'neutral'; label: string }>,
      required: true,
    },
  },
  setup(props) {
    function formatTime(seconds: number): string {
      if (seconds < 60) return `${seconds.toFixed(1)}s`
      if (seconds < 3600) return `${(seconds / 60).toFixed(1)}min`
      const h = Math.floor(seconds / 3600)
      const m = Math.round((seconds % 3600) / 60)
      return `${h}h ${m}m`
    }

    return () => {
      if (props.error) {
        return h('div', { class: 'uph-empty' }, [h(ElEmpty, { description: '暂无UPH数据', imageSize: 60 })])
      }
      const data = props.data
      if (!data) {
        return h('div', { class: 'uph-empty' }, props.loading ? '计算UPH...' : '')
      }
      // 后端 NaN → JSON null（R4②）：这几个字段运行时可能是 null，而此处是
      // render 函数内直接 .toFixed() / .toLocaleString()——null 会抛 TypeError，
      // 那是**不可恢复的渲染崩溃**（整块白屏），不是「显示不好看」。
      const num = (v: unknown, digits: number) =>
        typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : 'N/A'
      const int = (v: unknown) =>
        typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString() : 'N/A'
      const totalText = typeof data.total_time_seconds === 'number' && Number.isFinite(data.total_time_seconds)
        ? formatTime(data.total_time_seconds)
        : 'N/A'
      const nodes: any[] = [
        h('span', {}, ['平均测试时间 ', h('b', {}, num(data.avg_test_time, 4)), ' 秒']),
        h('span', {}, ['总耗时 ', h('b', {}, totalText), `（${int(data.total_tested)} units）`]),
        h('span', {}, ['并行站点数 ', h('b', {}, int(data.site_count))]),
        h('span', {}, [
          '数据来源 ',
          h('span', { class: `uph-src uph-src--${props.sourceTag.tone}` }, props.sourceTag.label),
        ]),
      ]
      for (const w of data.warnings || []) {
        nodes.push(h('span', { class: 'uph-warn' }, `⚠ ${w}`))
      }
      if (data.by_site && data.by_site.length > 0) {
        nodes.push(h('span', {}, '各站点 UPH'))
        nodes.push(
          h('span', { class: 'site-uph-wrap' },
            data.by_site.map((site) =>
              h('span', { class: 'site-uph', key: site.site }, [
                h('b', {}, `S${site.site}`),
                ` ${site.uph.toLocaleString()}`,
              ])
            )
          )
        )
      }
      // 公式说明（? 悬停；e2e 既有断言选择器 .uph-metric-label__help 保持）
      nodes.push(
        h('span', { class: 'uph-formula' }, [
          'UPH = 测试总数量 ÷ 总耗时 × 3600',
          h(ElTooltip, { placement: 'top', width: 340 }, {
            content: () => h('div', { class: 'uph-helper' }, [
              h('div', { class: 'uph-helper__title', style: { fontWeight: 600, marginBottom: '4px' } }, 'UPH ＝ 每小时产出单元数'),
              h('div', { class: 'uph-helper__formula', style: { lineHeight: 1.7 } }, 'UPH ＝ 测试总数量 ÷ 总耗时 × 3600'),
              data.site_count
                ? h('div', { class: 'uph-helper__formula', style: { lineHeight: 1.7 } }, `总耗时 ＝ 各单元测试时间之和 ÷ ${data.site_count}（并行站点模型）`)
                : null,
            ]),
            default: () => h(ElIcon, { class: 'uph-metric-label__help' }, () => h(QuestionFilled)),
          }),
        ])
      )
      return h('div', { class: 'uph-detail' }, nodes)
    }
  },
})
</script>

<script setup lang="ts">
const props = withDefaults(defineProps<{
  fileId?: number | null
  /** Direct UPH data — when provided, skips API fetch (batch mode) */
  uphData?: UphData | null
  /** 内嵌模式（批次 Bin 分布卡内）：去掉卡片壳，标题由父级分区提供 */
  embedded?: boolean
}>(), {
  fileId: null,
  uphData: null,
  embedded: false,
})

const loading = ref(false)
const error = ref(false)
const data = ref<UphData | null>(null)

// Source-aware tag: batch=批次汇总, manual*=手动输入, 其余非空=自动检测列
// （后端实际取值 'Test_Time (ms→s)' / 'Test_Time' / 'manual (1.2s)' / 'unavailable' / 'batch'，
//   此前只认 'column' 导致单文件自动检测被误标成「手动输入」）
const sourceTag = computed<{ tone: 'success' | 'brand' | 'warn' | 'neutral'; label: string }>(() => {
  const source = data.value?.source
  if (source === 'batch') return { tone: 'brand', label: '批次汇总' }
  if (source && source.startsWith('manual')) return { tone: 'warn', label: '手动输入' }
  if (source && source !== 'unavailable') return { tone: 'success', label: `自动检测 ${source}` }
  return { tone: 'neutral', label: '无测试时间' }
})

async function fetchUph() {
  if (!props.fileId) {
    error.value = true
    data.value = null
    return
  }
  loading.value = true
  error.value = false
  data.value = null
  try {
    const resp = await analysisApi.getUph(props.fileId)
    data.value = resp.data as UphData
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

// When uphData is provided directly (batch mode / 页面统一下传), use it
watch(() => props.uphData, (val) => {
  if (val) {
    data.value = val
    error.value = false
  }
}, { immediate: true })

// When fileId changes (single-file mode), fetch from API（uphData 优先）
watch(() => props.fileId, () => {
  if (props.fileId && !props.uphData) fetchUph()
}, { immediate: true })
</script>

<style scoped>
/* Section 卡（§10.4 定稿） */
.uph-shell {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  margin-bottom: 14px;
}
.uph-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg-2) 60%, var(--card));
}
.uph-head h3 {
  margin: 0;
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text);
}
.uph-head-desc {
  font-size: 11px;
  color: var(--text-3);
}
.uph-body {
  padding: 14px 16px;
}

/* embedded：无卡壳（父级提供分区标题） */
.uph-card--embedded :deep(.uph-detail) {
  padding: 4px 0;
}

/* UphDetail 为 plain script 内 defineComponent + h() 渲染，scoped 选择器
   无法命中其内部节点——统一 :deep()（2026-08-30 修复：各站点 UPH 挤作一团） */
.uph-card :deep(.uph-empty) {
  min-height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-3);
  font-size: 12px;
}

/* —— 紧凑信息带 —— */
.uph-card :deep(.uph-detail) {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  font-size: 12px;
  color: var(--text-2);
  align-items: center;
}
.uph-card :deep(.uph-detail b) {
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.uph-card :deep(.uph-src) {
  font-size: 11px;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 6px;
}
.uph-card :deep(.uph-src--success) {
  background: color-mix(in srgb, var(--success) 13%, transparent);
  color: var(--success);
}
.uph-card :deep(.uph-src--brand) {
  background: color-mix(in srgb, var(--brand) 13%, transparent);
  color: var(--brand);
}
.uph-card :deep(.uph-src--warn) {
  background: color-mix(in srgb, var(--warn) 13%, transparent);
  color: var(--warn);
}
.uph-card :deep(.uph-src--neutral) {
  background: color-mix(in srgb, var(--text-2) 12%, transparent);
  color: var(--text-2);
}

.uph-card :deep(.uph-warn) {
  font-size: 11.5px;
  color: var(--warn);
  font-weight: 600;
}

.uph-card :deep(.site-uph-wrap) {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 5px;
  align-items: center;
}
.uph-card :deep(.site-uph) {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  border: 1px solid var(--border-2);
  border-radius: 6px;
  padding: 1px 8px;
  font-size: 11px;
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
  background: var(--bg);
}

.uph-card :deep(.uph-formula) {
  color: var(--text-3);
  font-size: 11px;
}
.uph-card :deep(.uph-metric-label__help) {
  margin-left: 3px;
  vertical-align: -2px;
  cursor: help;
}
</style>
