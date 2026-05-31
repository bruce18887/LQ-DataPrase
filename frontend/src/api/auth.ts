import api from './index'

export const authApi = {
  login(username: string, password: string) {
    return api.post('/auth/login/', { username, password })
  },
  logout(refresh: string) {
    return api.post('/auth/logout/', { refresh })
  },
  getProfile() {
    return api.get('/auth/profile/')
  },
  updateProfile(data: Record<string, unknown>) {
    return api.put('/auth/profile/', data)
  },
  getSettings() {
    return api.get('/auth/settings/')
  },
  updateSettings(data: Record<string, unknown>) {
    return api.put('/auth/settings/', data)
  },
}
