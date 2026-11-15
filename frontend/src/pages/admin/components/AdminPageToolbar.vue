<template>
  <div class="admin-page-toolbar">
    <div v-if="$slots.left" class="admin-page-toolbar__left">
      <slot name="left" />
    </div>
    <div v-if="$slots.right" class="admin-page-toolbar__right">
      <slot name="right" />
    </div>
  </div>
</template>

<style scoped>
.admin-page-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--p-space-3);
  padding: var(--p-space-2) var(--p-space-3);
  margin-bottom: var(--p-space-3);
  background: var(--bg-3);
  border: 1px solid var(--border-2);
  border-radius: 8px;
}

.admin-page-toolbar__left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--p-space-3);
  flex: 1 1 auto;
  min-width: 0;
}

.admin-page-toolbar__right {
  display: flex;
  align-items: center;
  gap: var(--p-space-2);
  flex: 0 0 auto;
  margin-left: auto;
}

/* 宽度语言与 pages/sftp/components/SearchCriteria.vue:504/542 同源：
   flex-basis 给「还能呼吸」的宽度，min-width 允许被压短但不许压成一条缝。 */
.admin-page-toolbar :deep(.admin-filter-input) {
  flex: 1 1 260px;
  min-width: 180px;
}

.admin-page-toolbar :deep(.admin-filter-select) {
  width: 160px;
}

.admin-page-toolbar :deep(.admin-filter-date) {
  width: 190px;
}
</style>
