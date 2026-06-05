import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../pages/auth/LoginPage.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    component: () => import('../layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/dashboard' },
      // 数据操作
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('../pages/dashboard/DashboardPage.vue'),
        meta: { title: '仪表板' },
      },
      {
        path: 'data',
        name: 'DataManagement',
        component: () => import('../pages/data/DataManagement.vue'),
        meta: { title: '数据管理' },
      },
      {
        path: 'sftp',
        name: 'SftpBrowser',
        component: () => import('../pages/sftp/SftpBrowser.vue'),
        meta: { title: 'SFTP 浏览器' },
      },
      {
        path: 'analysis',
        name: 'Analysis',
        component: () => import('../pages/analysis/AnalysisPage.vue'),
        meta: { title: '数据分析' },
      },
      {
        path: 'batch',
        redirect: '/dashboard',
      },
      // 系统管理
      {
        path: 'admin/users',
        name: 'UserManagement',
        component: () => import('../pages/admin/UserManagement.vue'),
        meta: { title: '用户管理' },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('../pages/settings/SettingsPage.vue'),
        meta: { title: '系统设置' },
      },
      {
        path: 'roadmap',
        name: 'Roadmap',
        component: () => import('../pages/roadmap/RoadmapPage.vue'),
        meta: { title: '功能路线图' },
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isLoggedIn) {
    next('/login')
  } else if (to.path === '/login' && auth.isLoggedIn) {
    next('/dashboard')
  } else {
    next()
  }
})

export default router
