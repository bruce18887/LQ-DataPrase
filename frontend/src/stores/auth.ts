import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '../api/auth'
import type { User } from '../types'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('access_token'))
  const refreshToken = ref<string | null>(localStorage.getItem('refresh_token'))
  const user = ref<User | null>(null)

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.role === 'administrator')

  async function login(username: string, password: string) {
    const { data } = await authApi.login(username, password)
    token.value = data.token
    refreshToken.value = data.refresh
    localStorage.setItem('access_token', data.token)
    localStorage.setItem('refresh_token', data.refresh)
    const { data: profile } = await authApi.getProfile()
    user.value = profile
  }

  function logout() {
    if (refreshToken.value) {
      authApi.logout(refreshToken.value).catch(() => {
        // silently ignore logout errors
      })
    }
    token.value = null
    refreshToken.value = null
    user.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  return { token, refreshToken, user, isLoggedIn, isAdmin, login, logout }
})
