import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '../api/auth'
import { resetExportTimeoutCache } from '../utils/exportTimeout'
import { resetSftpTimeoutCache } from '../utils/sftpTimeout'
import type { User } from '../types'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('access_token'))
  const refreshToken = ref<string | null>(localStorage.getItem('refresh_token'))
  const user = ref<User | null>(null)

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.role === 'administrator')

  async function login(username: string, password: string) {
    resetExportTimeoutCache()
    resetSftpTimeoutCache()
    const { data } = await authApi.login(username, password)
    token.value = data.token
    refreshToken.value = data.refresh
    localStorage.setItem('access_token', data.token)
    localStorage.setItem('refresh_token', data.refresh)
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
    localStorage.setItem('access_token', accessToken)
    localStorage.setItem('refresh_token', newRefreshToken)
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
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    resetExportTimeoutCache()
    resetSftpTimeoutCache()
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
