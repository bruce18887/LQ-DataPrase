<template>
  <div class="view-file-tabs" role="tablist" aria-label="查看数据文件标签页">
    <button
      v-for="(t, i) in tabs"
      :key="t.id"
      type="button"
      role="tab"
      :aria-selected="t.id === activeId"
      :class="['vf-tab', { 'is-active': t.id === activeId }]"
      :title="t.label || '未选择文件'"
      @click="emit('activate', t.id)"
    >
      <span class="vf-tab__idx">{{ i + 1 }}</span>
      <span class="vf-tab__name">{{ t.label || '未选择文件' }}</span>
      <span
        v-if="tabs.length > 1"
        class="vf-tab__close"
        :aria-label="'关闭标签页 ' + (t.label || '未选择文件')"
        @click.stop="emit('close', t.id)"
      >
        &times;
      </span>
    </button>

    <button
      type="button"
      class="vf-tab vf-tab--add"
      :disabled="tabs.length >= max"
      :title="tabs.length >= max ? `最多同时打开 ${max} 个文件` : '在新标签页查看文件'"
      @click="emit('add')"
    >
      +
    </button>
  </div>
</template>

<script setup lang="ts">
/** 一个标签页 = 一份独立的表格实例（各自的筛选、固定列、滚动位置） */
export interface ViewFileTab {
  id: number
  fileId: number | null
  /** 文件名，由父级按 fileId 反查；null 文件（空白页）时为空串 */
  label: string
  /** 首次被激活过才挂载表格实例：没看过的标签不该发请求 */
  everActive: boolean
}

defineProps<{
  tabs: ViewFileTab[]
  activeId: number
  max: number
}>()

const emit = defineEmits<{
  activate: [number]
  close: [number]
  add: []
}>()
</script>

<style scoped>
.view-file-tabs {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.vf-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 260px;
  padding: 4px 10px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-2);
  font-size: var(--p-fs-dense);
  font-family: inherit;
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease, background-color 0.15s ease;
}

.vf-tab:hover {
  color: var(--text);
  border-color: var(--border-2);
}

.vf-tab.is-active {
  background: var(--bg-3);
  border-color: var(--brand);
  color: var(--text);
  font-weight: 600;
}

.vf-tab__idx {
  flex-shrink: 0;
  min-width: 14px;
  color: var(--text-3);
  font-size: var(--p-fs-micro);
  font-weight: 700;
}

.vf-tab.is-active .vf-tab__idx {
  color: var(--brand);
}

/* 文件名中间省略：两端都可能有区分度（前缀是料号、后缀是日期时间戳） */
.vf-tab__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.vf-tab__close {
  flex-shrink: 0;
  padding: 0 2px;
  border-radius: 4px;
  color: var(--text-3);
  font-size: var(--p-fs-base);
  line-height: 1;
}

.vf-tab__close:hover {
  color: var(--error);
}

.vf-tab--add {
  max-width: none;
  padding: 4px 12px;
  font-weight: 700;
}

.vf-tab--add:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}
</style>
