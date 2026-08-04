<template>
  <header class="topbar">
    <!-- 左侧：面包屑导航 -->
    <div class="topbar-left">
      <el-breadcrumb separator="/">
        <el-breadcrumb-item v-for="item in breadcrumbs" :key="item.path" :to="item.path">
          {{ item.label }}
        </el-breadcrumb-item>
      </el-breadcrumb>
    </div>

    <!-- 右侧：搜索、通知、主题切换、用户菜单 -->
    <div class="topbar-right">
      <!-- 搜索框（开发中） -->
      <div class="search-box">
        <el-input
          v-model="searchQuery"
          placeholder="搜索（开发中）"
          :prefix-icon="Search"
          size="small"
          disabled
          autocomplete="off"
          aria-label="搜索功能（开发中）"
        />
      </div>

      <!-- 主题切换 -->
      <ThemeToggle />

      <!-- 版本徽章：点击打开「关于」对话框 -->
      <button
        class="version-badge"
        type="button"
        title="点击查看版本信息"
        aria-label="版本 v{{ APP_VERSION }}，点击查看详情"
        @click="openAbout"
      >
        v{{ APP_VERSION }}
      </button>

      <!-- 通知图标 -->
      <el-badge :value="notificationCount" :hidden="notificationCount === 0" class="notification-badge">
        <el-button text circle class="icon-btn" aria-label="通知">
          <el-icon :size="18" aria-hidden="true"><Bell /></el-icon>
        </el-button>
      </el-badge>

      <!-- 用户菜单 -->
      <el-dropdown trigger="click" @command="handleCommand" @visible-change="onDropdownVisibleChange">
        <button class="user-menu" aria-haspopup="true" :aria-expanded="dropdownVisible">
          <div class="user-avatar">
            <el-icon :size="18" aria-hidden="true"><User /></el-icon>
          </div>
          <div class="user-info">
            <span class="user-name">{{ displayName }}</span>
            <span class="user-role">{{ roleLabel }}</span>
          </div>
          <el-icon class="dropdown-icon" aria-hidden="true"><ArrowDown /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="profile">
              <el-icon><User /></el-icon>
              <span>个人资料</span>
            </el-dropdown-item>
            <el-dropdown-item command="settings">
              <el-icon><Setting /></el-icon>
              <span>设置</span>
            </el-dropdown-item>
            <el-dropdown-item divided command="logout">
              <el-icon><SwitchButton /></el-icon>
              <span>退出登录</span>
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import { Search, Bell, User, ArrowDown, Setting, SwitchButton } from '@element-plus/icons-vue'
import ThemeToggle from '../common/ThemeToggle.vue'
import { useAboutDialog } from '../../composables/useAboutDialog'
import { APP_VERSION } from '../../utils/version'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { open: openAbout } = useAboutDialog()

const searchQuery = ref('')
const notificationCount = ref(0)
const dropdownVisible = ref(false)

const onDropdownVisibleChange = (visible: boolean) => {
  dropdownVisible.value = visible
}

const displayName = computed(() => {
  return authStore.user?.display_name || authStore.user?.username || '用户'
})

const roleLabel = computed(() => {
  const role = authStore.user?.role
  if (role === 'administrator') return '管理员'
  if (role === 'viewer') return '查看者'
  return '用户'
})

const breadcrumbs = computed(() => {
  const items: Array<{ path: string; label: string }> = []
  const pathSegments = route.path.split('/').filter(Boolean)

  // 路由标题映射
  const routeLabels: Record<string, string> = {
    dashboard: '仪表板',
    data: '数据管理',
    analysis: '数据分析',
    settings: '系统设置',
    batch: '批次报表',
    sftp: 'SFTP浏览器',
    admin: '管理',
    users: '用户管理',
  }

  let currentPath = ''
  pathSegments.forEach((segment) => {
    currentPath += `/${segment}`
    items.push({
      path: currentPath,
      label: routeLabels[segment] || segment,
    })
  })

  return items
})

const handleCommand = (command: string) => {
  switch (command) {
    case 'profile':
      // 个人资料功能开发中，暂不跳转
      break
    case 'settings':
      router.push('/settings')
      break
    case 'logout':
      authStore.logout()
      router.push('/login')
      break
  }
}
</script>

<style scoped>
.topbar {
  height: 56px;
  background-color: var(--bg-secondary);
  border-bottom: 1px solid var(--border-default);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  gap: 24px;
}

/* 左侧面包屑 */
.topbar-left {
  flex: 1;
  min-width: 0;
}

:deep(.el-breadcrumb) {
  font-size: 14px;
}

:deep(.el-breadcrumb__item) {
  color: var(--text-secondary);
}

:deep(.el-breadcrumb__inner) {
  color: var(--text-secondary);
  font-weight: 500;
  transition: color 0.2s ease;
}

:deep(.el-breadcrumb__inner:hover) {
  color: var(--brand-primary);
}

:deep(.el-breadcrumb__item:last-child .el-breadcrumb__inner) {
  color: var(--text-primary);
}

:deep(.el-breadcrumb__separator) {
  color: var(--text-tertiary);
}

/* 右侧工具栏 */
.topbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

/* 搜索框 */
.search-box {
  width: 240px;
}

:deep(.el-input) {
  --el-input-bg-color: var(--bg-primary);
  --el-input-border-color: var(--border-default);
  --el-input-hover-border-color: var(--brand-primary);
  --el-input-focus-border-color: var(--brand-primary);
  --el-input-text-color: var(--text-primary);
  --el-input-placeholder-color: var(--text-secondary);
}

:deep(.el-input__wrapper) {
  background-color: var(--bg-primary);
  border-radius: 8px;
  box-shadow: none;
  transition: background-color 0.2s ease, box-shadow 0.2s ease;
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--brand-primary);
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--brand-primary), 0 0 8px rgba(37, 99, 235, 0.2);
}

/* 版本徽章 */
.version-badge {
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
  background: var(--bg-tertiary);
  border: 1px solid var(--border-default);
  cursor: pointer;
  transition: color 0.2s ease, border-color 0.2s ease;
}

.version-badge:hover {
  color: var(--brand-primary);
  border-color: var(--brand-primary);
}

.version-badge:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: 2px;
}

/* 通知图标 */
.notification-badge {
  line-height: 1;
}

:deep(.el-badge__content) {
  background-color: var(--color-error);
  border: none;
}

.icon-btn {
  color: var(--text-secondary);
  transition: color 0.2s ease, background-color 0.2s ease;
}

.icon-btn:hover {
  color: var(--brand-primary);
  background-color: var(--bg-tertiary);
}

.icon-btn:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: 2px;
  border-radius: 4px;
}

/* 用户菜单 */
.user-menu {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 0.2s ease;
  background: none;
  border: none;
  font: inherit;
  color: inherit;
}

.user-menu:hover {
  background-color: var(--bg-tertiary);
}

.user-menu:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: 2px;
}

.user-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: var(--brand-primary);
  border-radius: 50%;
  color: #fff;
}

.user-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.user-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1;
}

.user-role {
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1;
}

.dropdown-icon {
  color: var(--text-secondary);
  font-size: 12px;
  transition: transform 0.2s ease;
}

.user-menu:hover .dropdown-icon {
  color: var(--brand-primary);
}

/* 下拉菜单样式 */
:deep(.el-dropdown-menu) {
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-default);
  box-shadow: var(--shadow-lg);
}

:deep(.el-dropdown-menu__item) {
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}

:deep(.el-dropdown-menu__item:hover) {
  background-color: var(--bg-tertiary);
  color: var(--brand-primary);
}

:deep(.el-dropdown-menu__item .el-icon) {
  font-size: 16px;
}

@media (prefers-reduced-motion: reduce) {
  .topbar *,
  .dropdown-icon,
  .user-menu {
    transition: none !important;
  }
}
</style>
