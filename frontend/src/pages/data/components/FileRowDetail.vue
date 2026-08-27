<template>
  <div class="row-detail">
    <div class="detail-row">
      <span class="detail-label">完整文件名</span>
      <span class="detail-value mono">{{ row.filename }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">行列</span>
      <span class="detail-value mono">{{ row.row_count }} × {{ row.col_count }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">测试程序</span>
      <span class="detail-value">{{ row.program_name || '—' }}</span>
    </div>
    <div class="detail-row">
      <span class="detail-label">所有标签</span>
      <div class="detail-value tag-wrap">
        <el-tag
          v-for="t in (row.tags || [])"
          :key="t"
          closable
          size="small"
          type="info"
          effect="light"
          class="file-tag"
          @close="emit('remove-tag', row, t)"
        >{{ t }}</el-tag>
        <span v-if="!row.tags || row.tags.length === 0" class="empty-text">无标签</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ row: any }>()
const emit = defineEmits<{ 'remove-tag': [row: any, tag: string] }>()
</script>

<style scoped>
.row-detail {
  padding: 12px 24px 16px 56px;
  background: var(--bg-secondary);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 6px 8px;
}
.detail-row {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  min-height: 20px;
}
.detail-label {
  flex-shrink: 0;
  width: 96px;
  font-size: 12px;
  color: var(--text-tertiary);
  padding-top: 1px;
}
.detail-value {
  flex: 1;
  font-size: 13px;
  color: var(--text-primary);
  word-break: break-all;
  line-height: 1.5;
}
.detail-value.tag-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.mono {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
}
.empty-text {
  color: var(--text-tertiary);
}
</style>
