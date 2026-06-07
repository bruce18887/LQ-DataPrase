import axios, { AxiosError, type AxiosRequestConfig } from 'axios'

import { authApi } from './auth'
import { useAuthStore } from '../stores/auth'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  paramsSerializer: {
    indexes: null,
  },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ---------------------------------------------------------------------------
// 401 -> refresh -> retry pipeline
// ---------------------------------------------------------------------------
// `refreshPromise` is the single in-flight call to /auth/refresh/ for the
// current burst of 401s. Every concurrent 401 awaits the same promise,
// gets the new access token, and retries. Without this, three parallel
// 401s would fire three refreshes and burn through the rotated refresh
// tokens (ROTATE_REFRESH_TOKENS=True blacklists the previous one).
let refreshPromise: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) return refreshPromise

  const refresh = localStorage.getItem('refresh_token')
  if (!refresh) return null

  refreshPromise = (async () => {
    try {
      const resp = await authApi.refresh(refresh)
      const data = resp.data
      if (!data?.access) return null
      const newRefresh = data.refresh ?? refresh
      // Keep Pinia store in sync (interceptor may run before any store
      // action is dispatched, so touching refs here is the only way).
      const auth = useAuthStore()
      auth.setTokens(data.access, newRefresh)
      return data.access
    } catch {
      return null
    } finally {
      // Always release the slot so the next 401 burst (after the next
      // 30-min expiry) can refresh again.
      refreshPromise = null
    }
  })()
  return refreshPromise
}

function isAuthEndpoint(url?: string): boolean {
  return !!url && url.includes('/auth/')
}

function forceLogout() {
  // The store's logout() posts /auth/logout/, which would itself be
  // intercepted and (because we have no valid refresh token) bounce
  // through this same path. Drop tokens directly + redirect instead.
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  // Avoid the redirect loop if we are already on /login (e.g. user
  // submits bad credentials from the login page).
  if (!window.location.pathname.startsWith('/login')) {
    window.location.href = '/login'
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const status = error.response?.status
    const originalRequest = error.config as
      | (AxiosRequestConfig & { _retry?: boolean })
      | undefined

    if (status !== 401) {
      return Promise.reject(error)
    }

    // The refresh endpoint is the *only* request that is allowed to
    // bubble a 401 out without retrying — otherwise we'd recurse
    // forever. Also bail if the original request was already retried
    // (avoid infinite loops on a permanently bad access token) or
    // there's no refresh token to begin with.
    if (
      !originalRequest
      || originalRequest._retry
      || isAuthEndpoint(originalRequest.url)
      || !localStorage.getItem('refresh_token')
    ) {
      forceLogout()
      return Promise.reject(error)
    }

    const newAccess = await refreshAccessToken()
    if (!newAccess) {
      forceLogout()
      return Promise.reject(error)
    }

    // Stamp the retry flag and replay the request with the fresh token.
    originalRequest._retry = true
    originalRequest.headers = {
      ...(originalRequest.headers ?? {}),
      Authorization: `Bearer ${newAccess}`,
    }
    return api(originalRequest)
  }
)

export default api
