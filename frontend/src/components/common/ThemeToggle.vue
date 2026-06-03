<template>
  <button class="theme-toggle" @click="toggleTheme" :title="toggleTitle" :aria-label="toggleTitle">
    <transition name="icon-fade" mode="out-in">
      <el-icon :size="20" :key="currentTheme" aria-hidden="true">
        <Sunny v-if="currentTheme === 'light'" />
        <Moon v-else />
      </el-icon>
    </transition>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Sunny, Moon } from '@element-plus/icons-vue'
import { useThemeStore } from '../../stores/theme'

const themeStore = useThemeStore()

const currentTheme = computed(() => themeStore.currentTheme)

const toggleTitle = computed(() =>
  currentTheme.value === 'light' ? '切换到夜晚模式' : '切换到浅色模式'
)

const toggleTheme = () => {
  themeStore.toggleTheme()
}
</script>

<style scoped>
.theme-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 8px;
  background: var(--bg-tertiary);
  color: var(--text-primary);
  cursor: pointer;
  transition: background-color 0.3s ease, color 0.3s ease, transform 0.3s ease, box-shadow 0.3s ease;
  position: relative;
  overflow: hidden;
}

.theme-toggle::before {
  content: '';
  position: absolute;
  inset: 0;
  background: var(--brand-primary);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.theme-toggle:hover {
  background: var(--brand-primary);
  color: var(--text-inverse);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.theme-toggle:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: 2px;
}

.theme-toggle:active {
  transform: translateY(0);
}

/* 图标淡入淡出动画 */
@media (prefers-reduced-motion: reduce) {
  .icon-fade-enter-active,
  .icon-fade-leave-active { transition: none; }
  .icon-fade-enter-from,
  .icon-fade-leave-to { opacity: 0; transform: none; }
}
.icon-fade-enter-active,
.icon-fade-leave-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}

.icon-fade-enter-from {
  opacity: 0;
  transform: rotate(-180deg) scale(0.5);
}

.icon-fade-leave-to {
  opacity: 0;
  transform: rotate(180deg) scale(0.5);
}

/* 夜晚主题特殊效果 */
:root[data-theme="night"] .theme-toggle,
:root.theme-night .theme-toggle {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
}

:root[data-theme="night"] .theme-toggle:hover,
:root.theme-night .theme-toggle:hover {
  background: var(--brand-primary);
  border-color: var(--brand-primary);
  box-shadow: 0 0 20px rgba(249, 168, 37, 0.4);
}
</style>
