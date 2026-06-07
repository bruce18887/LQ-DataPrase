<template>
  <el-card shadow="hover" class="uph-card">
    <template #header>
      <div class="uph-header">
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
              <div class="uph-metric-label">UPH</div>
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
}>(), {
  fileId: null,
  uphData: null,
})

const loading = ref(false)
const error = ref(false)
const data = ref<UphData | null>(null)

// Source-aware tag: column=自动检测, batch=批次汇总, otherwise 手动输入
const sourceTag = computed<{ type: 'success' | 'primary' | 'warning'; label: string }>(() => {
  const source = data.value?.source
  if (source === 'column') return { type: 'success', label: '自动检测' }
  if (source === 'batch') return { type: 'primary', label: '批次汇总' }
  return { type: 'warning', label: '手动输入' }
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
  background: var(--bg-secondary, #f8f9fa);
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
  background: var(--bg-secondary, #f0f4ff);
  border: 1px solid var(--border-default, #e4e7ed);
}

.uph-site-label {
  font-size: 11px;
  color: var(--text-secondary, #666);
}

.uph-site-value {
  font-size: 20px;
  font-weight: bold;
  color: var(--text-primary, #333);
}

.uph-site-tested {
  font-size: 10px;
  color: var(--text-tertiary, #999);
}

.uph-footer {
  margin-top: 12px;
  text-align: right;
  font-size: 13px;
  color: var(--text-secondary, #666);
}
</style>
