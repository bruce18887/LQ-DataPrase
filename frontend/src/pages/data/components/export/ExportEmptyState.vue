<template>
  <div class="export-empty">
    <div class="empty-icon">📥</div>
    <div class="empty-title">选择文件后即可导出参数分布图</div>
    <div class="empty-desc">请先在上方「当前文件」选择器里选择一个数据文件，再配置参数与图表。</div>
  </div>
</template>

<style scoped>
.export-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px dashed var(--border-muted);
  border-radius: 12px;
}

.empty-icon {
  font-size: 40px;
  margin-bottom: 12px;
  opacity: 0.6;
}

.empty-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.empty-desc {
  font-size: 13px;
  max-width: 420px;
  line-height: 1.6;
}
</style>
