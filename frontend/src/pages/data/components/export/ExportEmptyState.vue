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
  color: var(--text-2);
  background: var(--bg-2);
  border: 1px dashed var(--border);
  border-radius: 12px;
}

.empty-icon {
  font-size: 40px; /* @type-scale-one-off 空状态装饰图标 */
  margin-bottom: 12px;
  opacity: 0.6;
}

.empty-title {
  font-size: var(--p-fs-base);
  font-weight: 600;
  color: var(--text);
  margin-bottom: 6px;
}

.empty-desc {
  font-size: var(--p-fs-small);
  max-width: 420px;
  line-height: 1.6;
}
</style>
