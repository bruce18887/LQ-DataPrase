<template>
  <el-card class="file-list-card" shadow="never">
    <el-table
      v-loading="loading"
      :data="items"
      @row-click="(row: any) => { if (row.is_dir) emit('navigate', currentPath + '/' + row.name) }"
      @sort-change="(sort: any) => emit('sort-change', sort)"
      class="file-table"
      :header-cell-style="{ background: '#f5f7fa', fontWeight: '600', fontSize: '13px' }"
    >
      <el-table-column width="40" align="center">
        <template #default="{row}">
          <el-checkbox
            v-if="!row.is_dir && isCsv(row.name)"
            v-model="row._selected"
            @click.stop
          />
        </template>
      </el-table-column>
      <el-table-column label="名称" min-width="280" column-key="name" sortable="custom" :sort-orders="['ascending', 'descending']">
        <template #default="{row}">
          <div class="file-name-cell" :class="{ 'is-dir': row.is_dir }">
            <div class="file-icon">
              <el-icon v-if="row.is_dir" :size="22" color="#E6A23C"><Folder /></el-icon>
              <el-icon v-else :size="22" color="#409EFF"><Document /></el-icon>
            </div>
            <div class="file-info">
              <span class="file-name">{{ row.name }}</span>
              <span v-if="!row.is_dir" class="file-ext">{{ getFileExt(row.name) }}</span>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="大小" width="120" align="right" column-key="size" sortable="custom" :sort-orders="['ascending', 'descending']">
        <template #default="{row}">
          <span v-if="row.is_dir" class="dir-label">文件夹</span>
          <span v-else class="file-size">{{ formatSize(row.size) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="修改时间" width="160" align="center" column-key="mtime" sortable="custom" :sort-orders="['ascending', 'descending']">
        <template #default="{row}">
          <span class="file-time">{{ row.mtime ? formatDate(row.mtime) : '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" align="center">
        <template #default="{row}">
          <div class="action-cell">
            <el-button-group v-if="!row.is_dir">
              <el-button
                v-if="isCsv(row.name)"
                size="small"
                @click.stop="emit('download', row)"
                :loading="isDownloading(`file_${row.name}`)"
              >
                <el-icon><Download /></el-icon> 下载
              </el-button>
              <el-button
                v-if="isCsv(row.name)"
                size="small"
                type="primary"
                @click.stop="emit('download-and-parse', row)"
                :loading="isDownloading(`parse_${row.name}`)"
              >
                <el-icon><DataAnalysis /></el-icon> 解析
              </el-button>
              <el-tag v-if="!isCsv(row.name)" type="info" size="small" effect="plain">仅支持 CSV</el-tag>
            </el-button-group>
            <el-button-group v-else>
              <el-button
                size="small"
                type="warning"
                plain
                @click.stop="emit('download-directory', row.name)"
                :loading="isDownloading(`dir_${row.name}`)"
              >
                <el-icon><Download /></el-icon> 下载
              </el-button>
              <el-button size="small" type="info" plain @click.stop="emit('navigate', currentPath + '/' + row.name)">
                <el-icon><FolderOpened /></el-icon> 打开
              </el-button>
            </el-button-group>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="items.length === 0" description="暂无文件" :image-size="100">
      <template #image>
        <el-icon :size="60" color="#dcdfe6"><FolderOpened /></el-icon>
      </template>
    </el-empty>
  </el-card>
</template>

<script setup lang="ts">
import {
  Folder, Document, FolderOpened, Download, DataAnalysis,
} from '@element-plus/icons-vue'

const props = defineProps<{
  items: any[]
  currentPath: string
  downloadingRows: Set<string>
  loading?: boolean
}>()

const emit = defineEmits<{
  navigate: [path: string]
  'sort-change': [sort: { prop: string; order: string | null }]
  download: [row: any]
  'download-and-parse': [row: any]
  'download-directory': [name: string]
}>()

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}

function formatDate(timestamp: number): string {
  const d = new Date(timestamp * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function getFileExt(name: string): string {
  const ext = name.split('.').pop()
  return ext && ext !== name ? '.' + ext : ''
}

function isCsv(name: string): boolean {
  return name.toLowerCase().endsWith('.csv')
}

function isDownloading(key: string): boolean {
  return props.downloadingRows.has(key)
}
</script>

<style scoped>
.file-list-card { border-radius: 8px; margin-bottom: 12px; }
.file-table { cursor: pointer; }

.file-name-cell { display: flex; align-items: center; gap: 10px; padding: 4px 0; }
.file-icon {
  display: flex; align-items: center; justify-content: center;
  width: 36px; height: 36px; background: var(--bg-tertiary); border-radius: 8px; flex-shrink: 0;
}
.is-dir .file-icon { background: rgba(217, 119, 6, 0.1); }
.file-info { display: flex; align-items: center; gap: 6px; min-width: 0; }
.file-name {
  font-size: 14px; color: var(--text-primary); font-weight: 500;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.is-dir .file-name { color: var(--color-warning); font-weight: 600; }
.file-ext {
  font-size: 12px; color: var(--text-secondary); background: var(--bg-tertiary);
  padding: 1px 6px; border-radius: 4px; white-space: nowrap;
}
.file-size { font-size: 13px; color: var(--text-secondary); font-family: var(--font-mono); }
.file-time { font-size: 13px; color: var(--text-tertiary); }
.dir-label {
  font-size: 12px; color: var(--color-warning);
  background: rgba(217, 119, 6, 0.1); padding: 2px 8px; border-radius: 4px;
}

.action-cell { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.action-cell :deep(.el-button) { font-size: 12px; }
.action-cell :deep(.el-button .el-icon) { margin-right: 2px; }
</style>
