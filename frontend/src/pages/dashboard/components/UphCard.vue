<template>
  <el-card :shadow="embedded ? 'never' : 'hover'" class="uph-card" :class="{ 'uph-card--embedded': embedded }">
    <!-- embedded（批次 Bin 分布卡内嵌）：外层分区标题已由父级 divider 提供，不再重复渲染卡片头 -->
    <template #header>
      <div v-if="!embedded" class="uph-header">
        <span>⚡ UPH 效率分析</span>
        <el-tag v-if="data" size="small" :type="sourceTag.type">
          {{ sourceTag.label }}
        </el-tag>
      </div>
    </template>
    <div v-loading="loading" element-loading-text="计算UPH...">
      <div v-if="error" class="uph-empty">
        <el-empty description="暂无UPH数据" :image-size="60" />
      </div>
      <div v-else-if="data" class="uph-body">
        <!-- 核心指标 -->
        <el-row :gutter="16">
          <el-col :span="8">
            <div class="uph-metric uph-metric-primary">
              <div class="uph-metric-label">
                UPH
                <el-tooltip placement="top" :width="340">
                  <template #content>
                    <div class="uph-helper">
                      <div class="uph-helper__title">UPH ＝ 每小时产出单元数</div>
                      <div class="uph-helper__formula">UPH ＝ 测试总数量 ÷ 总耗时 × 3600</div>
                      <div v-if="data?.site_count" class="uph-helper__formula">
                        总耗时 ＝ 各单元测试时间之和 ÷ {{ data.site_count }}（并行站点模型）
                      </div>
                      <div v-if="helperSourceText" class="uph-helper__source">
                        {{ helperSourceText }}
                      </div>
                    </div>
                  </template>
                  <el-icon class="uph-metric-label__help"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <div class="uph-metric-value">{{ data.uph.toLocaleString() }}</div>
              <div class="uph-metric-unit">Units/Hour</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="uph-metric">
              <div class="uph-metric-label">平均测试时间</div>
              <div class="uph-metric-value">{{ data.avg_test_time.toFixed(4) }}</div>
              <div class="uph-metric-unit">秒</div>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="uph-metric">
              <div class="uph-metric-label">总耗时</div>
              <div class="uph-metric-value">{{ formatTime(data.total_time_seconds) }}</div>
              <div class="uph-metric-unit">({{ data.total_tested.toLocaleString() }} units)</div>
            </div>
          </el-col>
        </el-row>

        <!-- 各站点 UPH 明细（如果有） -->
        <div v-if="data.by_site && data.by_site.length > 0" style="margin-top: 16px">
          <el-divider style="margin: 8px 0">
            <span style="font-size: 12px">各站点 UPH 明细</span>
          </el-divider>
          <el-row :gutter="12">
            <el-col
              v-for="site in data.by_site"
              :key="site.site"
              :xs="12"
              :sm="8"
              :md="6"
              style="margin-bottom: 8px"
            >
              <div class="uph-site-card">
                <span class="uph-site-label">Site {{ site.site }}</span>
                <span class="uph-site-value">{{ site.uph.toLocaleString() }}</span>
                <span class="uph-site-tested">({{ site.tested }} units)</span>
              </div>
            </el-col>
          </el-row>
        </div>

        <!-- 警告信息 -->
        <div v-if="data.warnings && data.warnings.length > 0" style="margin-top: 12px">
          <el-alert
            v-for="(w, i) in data.warnings"
            :key="i"
            :title="w"
            type="warning"
            :closable="false"
            show-icon
            style="margin-bottom: 6px"
          />
        </div>

        <!-- 站点数 -->
        <div class="uph-footer">
          <span>并行站点数: <b>{{ data.site_count }}</b></span>
        </div>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { QuestionFilled } from '@element-plus/icons-vue'
import { analysisApi } from '../../../api/analysis'

interface UphSiteData {
  site: string
  tested: number
  uph: number
}

interface UphData {
  uph: number
  avg_test_time: number
  total_tested: number
  total_time_seconds: number
  source: string
  by_site: UphSiteData[]
  site_count: number
  warnings: string[]
}

const props = withDefaults(defineProps<{
  fileId?: number | null
  /** Direct UPH data — when provided, skips API fetch (batch mode) */
  uphData?: UphData | null
  /** 内嵌模式（批次 Bin 分布卡内）：去掉卡片头与悬浮阴影，标题由父级分区提供 */
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
const sourceTag = computed<{ type: 'success' | 'primary' | 'warning'; label: string }>(() => {
  const source = data.value?.source
  if (source === 'batch') return { type: 'primary', label: '批次汇总' }
  if (source && source.startsWith('manual')) return { type: 'warning', label: '手动输入' }
  if (source && source !== 'unavailable') return { type: 'success', label: '自动检测' }
  return { type: 'warning', label: '无测试时间' }
})

/** helper 里「测试时间来源」说明行：按后端 source 字段区分手动/自动/批次 */
const helperSourceText = computed(() => {
  const source = data.value?.source ?? ''
  if (source === 'batch') return '测试时间来源：批次汇总数据'
  if (source.startsWith('manual')) {
    const sec = source.replace(/^manual\s*\(?/, '').replace(/s?\)?$/, '')
    return `测试时间来源：手动输入每单元测试时间 ${sec}s`
  }
  if (source && source !== 'unavailable') {
    return `测试时间来源：自动检测 ${source} 列（元数据单位 ms 时已换算为秒）`
  }
  return '测试时间可自动检测（Test_Time 等列）或手动输入'
})

function formatTime(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}min`
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  return `${h}h ${m}m`
}

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

// When uphData is provided directly (batch mode), use it
watch(() => props.uphData, (val) => {
  if (val) {
    data.value = val
    error.value = false
  }
}, { immediate: true })

// When fileId changes (single-file mode), fetch from API
watch(() => props.fileId, () => {
  if (props.fileId) fetchUph()
}, { immediate: true })
</script>

<style scoped>
.uph-card {
  border-radius: 8px;
}

/* embedded：el-card 对已声明的 #header 插槽仍会渲染空头部容器（$slots.header 恒真），
   必须用 CSS 隐藏，否则残留一条带 padding/下边框的空头带 */
.uph-card--embedded :deep(.el-card__header) {
  display: none;
}

.uph-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  font-size: 15px;
}

.uph-empty {
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.uph-body {
  min-height: 120px;
}

/* Core metrics */
.uph-metric {
  text-align: center;
  padding: 12px 8px;
  border-radius: 8px;
  background: var(--bg-2, #f8f9fa);
}

.uph-metric-primary {
  background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 100%);
  color: #fff;
}

.uph-metric-label {
  font-size: 12px;
  opacity: 0.85;
  margin-bottom: 4px;
}

.uph-metric-label__help {
  margin-left: 2px;
  vertical-align: -2px;
  cursor: help;
  opacity: 0.85;
}

.uph-helper__title {
  font-weight: 600;
  margin-bottom: 4px;
}

.uph-helper__formula {
  line-height: 1.7;
}

.uph-helper__source {
  margin-top: 6px;
  font-size: 12px;
  opacity: 0.85;
}

.uph-metric-value {
  font-size: 28px;
  font-weight: bold;
  line-height: 1.2;
}

.uph-metric-unit {
  font-size: 11px;
  opacity: 0.7;
  margin-top: 2px;
}

/* Per-site cards */
.uph-site-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 10px;
  border-radius: 6px;
  background: var(--bg-2, #f0f4ff);
  border: 1px solid var(--border-2, #e4e7ed);
}

.uph-site-label {
  font-size: 11px;
  color: var(--text-2, #666);
}

.uph-site-value {
  font-size: 20px;
  font-weight: bold;
  color: var(--text, #333);
}

.uph-site-tested {
  font-size: 10px;
  color: var(--text-3, #999);
}

.uph-footer {
  margin-top: 12px;
  text-align: right;
  font-size: 13px;
  color: var(--text-2, #666);
}
</style>
