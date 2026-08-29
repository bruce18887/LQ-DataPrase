<template>
  <el-card shadow="never" class="section-card collapsible-section">
    <template #header>
      <button type="button" class="cs-header" :aria-expanded="open" @click="toggle">
        <span class="cs-title">{{ title }}</span>
        <span class="cs-extra" @click.stop>
          <slot name="header-extra" />
        </span>
        <span class="cs-toggle">{{ open ? '收起 ▲' : '展开 ▼' }}</span>
      </button>
    </template>
    <!-- v-if 而非 v-show：折叠时子图表容器尺寸为 0，
         initEchartsWhenReady 等待超时（5s）后不再初始化；
         重挂载可让子组件在容器可见时重新初始化 -->
    <div v-if="open" class="cs-body">
      <slot />
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = withDefaults(
  defineProps<{
    title: string
    defaultOpen?: boolean
  }>(),
  { defaultOpen: false },
)

const emit = defineEmits<{
  toggle: [open: boolean]
}>()

const open = ref(props.defaultOpen)

function toggle() {
  open.value = !open.value
  emit('toggle', open.value)
}
</script>

<style scoped>
.section-card {
  margin-bottom: 16px;
  border-radius: 8px;
}

.cs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.cs-header:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
  border-radius: 4px;
}

.cs-title {
  font-weight: 600;
  font-size: 15px;
  color: var(--text);
}

.cs-extra {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.cs-extra:empty { display: none; }
.cs-extra + .cs-toggle { margin-left: 12px; }

.cs-toggle {
  font-size: 13px;
  color: var(--text-2);
  user-select: none;
}

.cs-toggle:hover {
  color: var(--brand);
}
</style>
