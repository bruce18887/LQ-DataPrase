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

    // 应用到document根元素
    document.documentElement.setAttribute('data-theme', newTheme)
    document.documentElement.style.colorScheme = newTheme === 'night' ? 'dark' : 'light'

    // 更新 meta theme-color (移动端浏览器 Chrome 颜色)
    const meta = document.getElementById('theme-color-meta')
    if (meta) {
      meta.setAttribute('content', newTheme === 'night' ? '#1a1a2e' : '#fafbfc')
    }

    // 同时添加class以便兼容
    if (newTheme === 'night') {
      document.documentElement.classList.add('theme-night')
      document.documentElement.classList.remove('theme-light')
    } else {
      document.documentElement.classList.add('theme-light')
      document.documentElement.classList.remove('theme-night')
    }
  }, { immediate: true })

  return {
    currentTheme,
    toggleTheme,
    setTheme
  }
})
