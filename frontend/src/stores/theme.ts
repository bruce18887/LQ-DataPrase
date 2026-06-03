import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export type Theme = 'light' | 'night'

export const useThemeStore = defineStore('theme', () => {
  // 从localStorage读取保存的主题，默认为浅色
  const currentTheme = ref<Theme>((localStorage.getItem('theme') as Theme) || 'light')

  // 切换主题
  function toggleTheme() {
    currentTheme.value = currentTheme.value === 'light' ? 'night' : 'light'
  }

  // 设置指定主题
  function setTheme(theme: Theme) {
    currentTheme.value = theme
  }

  // 监听主题变化，应用到DOM和localStorage
  watch(currentTheme, (newTheme) => {
    // 保存到localStorage
    localStorage.setItem('theme', newTheme)

    document.documentElement.setAttribute('data-theme', newTheme)

    if (newTheme === 'night') {
      document.documentElement.classList.add('theme-night')
      document.documentElement.classList.remove('theme-light')
    } else {
      document.documentElement.classList.add('theme-light')
      document.documentElement.classList.remove('theme-night')
    }

    const meta = document.getElementById('theme-color-meta')
    if (meta) {
      meta.setAttribute('content', newTheme === 'night' ? '#1a1a2e' : '#fafbfc')
    }
  }, { immediate: true })

  return {
    currentTheme,
    toggleTheme,
    setTheme
  }
})
