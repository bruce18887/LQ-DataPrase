import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '../api/auth'
import { useUserSettingsStore } from './userSettings'
import { resetChartMemoryCache } from '../composables/useChartMemory'
import { resetChartDockMemoryState } from '../pages/analysis/composables/useChartDock'
import { safeGetItem, safeSetItem, safeRemoveItem } from '../utils/safeStorage'
import type { User } from '../types'

/**
 * 账号级 /auth/settings/ 缓存的失效点（登录与登出各一次）。
 * - store.reset() 覆盖**所有**账号设置本身（四个 scalar + analysis_chart_* + 网格读的
 *   page_size/default_hidden_columns）——自 Task 6a 起由 stores/userSettings.ts 唯一持有，
 *   6b 起网格与 useChartMemory 也不再各自缓存，没有第二份设置可清。
 * - resetChartMemoryCache() 清的是 useChartMemory **自己的运行时态**（不是设置）：
 *   analysis_chart_memory 的三态 memoryEnabled、800ms 防抖窗口里待冲刷的 latest + timer、
 *   以及 loadChartMemory 的结果 memo loadPromise（useChartMemory.ts:38-42,152-160）。
 *   这三样 store 管不到，摘掉这次调用就给图表记忆留一个 SPA 内跨账号串值的窗口，故保留。
 * - resetChartDockMemoryState() 与本项无关：纯 localStorage 会话态，从不请求
 *   /auth/settings/（pages/analysis/composables/useChartDock.ts:337），保持原样。
 */
function resetUserSettingsCaches(): void {
  useUserSettingsStore().reset()
  resetChartMemoryCache()
  resetChartDockMemoryState()
}

export const useAuthStore = defineStore('auth', () => {
  // safeGetItem 替代裸 localStorage.getItem：Electron 磁盘满/权限异常时不白屏
  const token = ref<string | null>(safeGetItem('access_token'))
  const refreshToken = ref<string | null>(safeGetItem('refresh_token'))
  const user = ref<User | null>(null)

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.role === 'administrator')

  async function login(username: string, password: string) {
    resetUserSettingsCaches()
    const { data } = await authApi.login(username, password)
    token.value = data.token
    refreshToken.value = data.refresh
    safeSetItem('access_token', data.token)
    safeSetItem('refresh_token', data.refresh)
    const { data: profile } = await authApi.getProfile()
    user.value = profile
  }

  /**
   * Replace both tokens at once. Used by the axios 401 interceptor
   * after a successful /auth/refresh/ call so the in-memory refs and
   * localStorage stay in sync without going through login() again.
   */
  function setTokens(accessToken: string, newRefreshToken: string) {
    token.value = accessToken
    refreshToken.value = newRefreshToken
    safeSetItem('access_token', accessToken)
    safeSetItem('refresh_token', newRefreshToken)
  }

  // Restore the in-memory profile after a hard refresh: the token persists in
  // localStorage (so isLoggedIn stays true), but `user` does not, which would
  // otherwise leave the UI showing the "用户" fallback and isAdmin=false.
  async function fetchProfile() {
    if (!token.value) return
    try {
      const { data: profile } = await authApi.getProfile()
      user.value = profile
    } catch (err) {
      // Token expired / invalid → drop the stale session.
      logout()
      throw err
    }
  }

  /**
   * 仅清空会话（内存态 + localStorage），不发起 /auth/logout/ 请求。
   * 供 axios 401 拦截器的 forceLogout 使用：此前只清 localStorage 不清
   * store，导致 isLoggedIn 仍为 true，路由守卫把 /login 弹回 dashboard，
   * dashboard 的请求再次 401 → 无限跳转循环。
   */
  function clearSession() {
    token.value = null
    refreshToken.value = null
    user.value = null
    safeRemoveItem('access_token')
    safeRemoveItem('refresh_token')
    resetUserSettingsCaches()
  }

  function logout() {
    if (refreshToken.value) {
      authApi.logout(refreshToken.value).catch(() => {
        // silently ignore logout errors
      })
    }
    clearSession()
  }

  return { token, refreshToken, user, isLoggedIn, isAdmin, login, logout, clearSession, fetchProfile, setTokens }
})
