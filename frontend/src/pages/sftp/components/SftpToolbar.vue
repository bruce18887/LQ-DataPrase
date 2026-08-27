<template>
  <el-card class="toolbar-card" shadow="never" :body-style="{ padding: '12px 20px' }">
    <el-row align="middle">
      <el-col :span="12">
        <div class="breadcrumb-wrap">
          <el-button size="small" circle @click="emit('navigate', parentPath)" class="back-btn">
            <el-icon><ArrowUp /></el-icon>
          </el-button>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item @click="emit('navigate', '/')">
              <el-icon><HomeFilled /></el-icon>
            </el-breadcrumb-item>
            <el-breadcrumb-item
              v-for="(seg, i) in pathSegments"
              :key="i"
              @click="emit('navigate', seg.path)"
            >
              {{ seg.name }}
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>
      </el-col>
      <el-col :span="12" class="toolbar-controls">
        <!-- 文件名浏览过滤：默认仅 CSV，可切换显示全部类型 -->
        <el-select
          :model-value="fileType"
          @update:model-value="emit('update:fileType', $event)"
          size="small"
          class="type-filter"
          :data-testid="'sftp-type-filter'"
          aria-label="文件类型过滤"
        >
          <el-option label="仅 CSV" value="csv" />
          <el-option label="全部文件" value="all" />
        </el-select>
        <!-- 下载超时（秒）：自由设定，持久化到用户设置 -->
        <div class="timeout-control" title="单文件/批量下载超时时间（秒），30-3600">
          <span class="timeout-label">超时</span>
          <el-input-number
            :model-value="timeoutSec"
            @update:model-value="emit('update:timeoutSec', $event as number)"
            :min="30"
            :max="3600"
            :step="30"
            size="small"
            controls-position="right"
            class="timeout-input"
            :data-testid="'sftp-timeout-input'"
          />
          <span class="timeout-unit">秒</span>
        </div>
        <el-input
          :model-value="searchQuery"
          @update:model-value="emit('update:searchQuery', $event)"
          placeholder="搜索文件..."
          size="small"
          clearable
          style="width: 200px; margin-right: 12px"
          :prefix-icon="Search"
        />
        <el-button size="small" type="danger" plain @click="emit('disconnect')">
          <el-icon><CircleClose /></el-icon> 断开
        </el-button>
      </el-col>
    </el-row>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ArrowUp, HomeFilled, Search, CircleClose } from '@element-plus/icons-vue'

const props = defineProps<{
  currentPath: string
  searchQuery: string
  /** 文件名浏览过滤：'csv' = 仅显示 CSV（默认），'all' = 显示所有类型 */
  fileType: 'csv' | 'all'
  /** 下载超时（秒），30-3600 */
  timeoutSec: number
}>()

const emit = defineEmits<{
  'update:searchQuery': [value: string]
  'update:fileType': [value: 'csv' | 'all']
  'update:timeoutSec': [value: number]
  navigate: [path: string]
  disconnect: []
}>()

const pathSegments = computed(() => {
  const segs = props.currentPath.split('/').filter(Boolean)
  let path = ''
  return segs.map(s => { path += '/' + s; return { name: s, path } })
})

const parentPath = computed(() => {
  const segs = props.currentPath.split('/').filter(Boolean)
  if (segs.length === 0) return '/'
  segs.pop()
  return '/' + segs.join('/')
})
</script>

<style scoped>
.toolbar-card { border-radius: 8px; margin-bottom: 8px; }
.breadcrumb-wrap { display: flex; align-items: center; gap: 8px; }
.back-btn { margin-right: 4px; }
.toolbar-controls {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
.type-filter { width: 110px; }
.timeout-control {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}
.timeout-input { width: 100px; }
.timeout-unit { font-size: 12px; color: var(--text-secondary); }
</style>
