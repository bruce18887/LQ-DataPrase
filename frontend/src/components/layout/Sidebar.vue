<template>
  <aside class="sidebar" :class="{ collapsed: isCollapsed }">
    <!-- Logo 区域 -->
    <div class="logo-section">
      <div class="logo-icon">
        <el-icon :size="28" aria-hidden="true"><TrendCharts /></el-icon>
      </div>
      <transition name="fade">
        <div v-show="!isCollapsed" class="logo-text">
          <span class="logo-title">DataPhrase</span>
          <span class="logo-subtitle">ATE数据分析平台</span>
        </div>
      </transition>
    </div>

    <!-- 导航菜单 -->
    <nav class="nav-menu">
      <template v-for="(item, index) in menuItems" :key="item.path">
        <!-- 分组分隔线 -->
        <div
          v-if="item.groupStart && index > 0"
          class="menu-divider"
          :class="{ 'divider-collapsed': isCollapsed }"
        >
          <div class="divider-line"></div>
          <transition name="fade">
            <span v-show="!isCollapsed" class="divider-label">{{ item.groupLabel }}</span>
          </transition>
        </div>

        <router-link
          :to="item.path"
          class="menu-item"
          :class="{ active: isActive(item.path), hidden: item.requiresAdmin && !isAdmin }"
        >
          <div class="menu-item-content">
            <div class="menu-icon" aria-hidden="true">
              <component :is="item.icon" />
            </div>
            <transition name="fade">
              <span v-show="!isCollapsed" class="menu-label">{{ item.label }}</span>
            </transition>
          </div>
          <div v-if="isActive(item.path)" class="active-indicator" aria-hidden="true"></div>
        </router-link>
      </template>
    </nav>

    <!-- 折叠按钮 -->
    <button class="collapse-btn" @click="toggleCollapse" aria-label="折叠侧边栏">
      <el-icon :size="18" aria-hidden="true">
        <DArrowLeft v-if="!isCollapsed" />
        <DArrowRight v-else />
      </el-icon>
    </button>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import {
  Odometer,
  Folder,
  TrendCharts,
  Setting,
  Connection,
  User,
  DArrowLeft,
  DArrowRight,
} from '@element-plus/icons-vue'

const route = useRoute()
const authStore = useAuthStore()

const isCollapsed = ref(false)

const isAdmin = computed(() => authStore.user?.role === 'administrator')

const menuItems = [
  // 数据操作
  { path: '/dashboard', label: '仪表板', icon: Odometer, requiresAdmin: false, groupStart: true, groupLabel: '数据操作' },
  { path: '/data', label: '数据管理', icon: Folder, requiresAdmin: false },
  { path: '/analysis', label: '数据分析', icon: TrendCharts, requiresAdmin: false },
  { path: '/sftp', label: 'SFTP浏览器', icon: Connection, requiresAdmin: false },
  // 系统管理
  { path: '/admin/users', label: '用户管理', icon: User, requiresAdmin: true, groupStart: true, groupLabel: '系统管理' },
  { path: '/settings', label: '系统设置', icon: Setting, requiresAdmin: false },
]

const isActive = (path: string) => {
  return route.path === path || route.path.startsWith(path + '/')
}

const toggleCollapse = () => {
  isCollapsed.value = !isCollapsed.value
}
</script>

<style scoped>
.sidebar {
  width: 240px;
  height: 100vh;
  background-color: var(--bg-secondary);
  display: flex;
  flex-direction: column;
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
  border-right: 1px solid var(--border-default);
}

.sidebar.collapsed {
  width: 64px;
}

/* Logo 区域 */
.logo-section {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 16px;
  border-bottom: 1px solid var(--border-default);
  min-height: 76px;
}

.logo-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  background: var(--brand-primary);
  border-radius: 8px;
  color: #fff;
  flex-shrink: 0;
}

.logo-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow: hidden;
}

.logo-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.5px;
  white-space: nowrap;
}

.logo-subtitle {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}

/* 导航菜单 */
.nav-menu {
  flex: 1;
  padding: 12px 8px;
  overflow-y: auto;
  overflow-x: hidden;
}

.nav-menu::-webkit-scrollbar {
  width: 4px;
}

.nav-menu::-webkit-scrollbar-thumb {
  background: var(--border-default);
  border-radius: 2px;
}

.menu-item {
  position: relative;
  margin-bottom: 4px;
  cursor: pointer;
  border-radius: 8px;
  transition: background-color 0.2s ease, color 0.2s ease;
  display: block;
  text-decoration: none;
  color: inherit;
}

.menu-item.hidden {
  display: none;
}

.menu-item:hover {
  background-color: var(--bg-tertiary);
}

.menu-item:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: -2px;
}

.menu-item.active {
  background-color: rgba(37, 99, 235, 0.1);
}

.menu-item-content {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 12px;
  position: relative;
}

.menu-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  color: var(--text-secondary);
  transition: color 0.2s ease;
  flex-shrink: 0;
  font-size: 20px;
}

.menu-item:hover .menu-icon,
.menu-item.active .menu-icon {
  color: var(--brand-primary);
}

.menu-label {
  font-size: 14px;
  color: var(--text-primary);
  font-weight: 500;
  white-space: nowrap;
  transition: color 0.2s ease;
}

.menu-item.active .menu-label {
  color: var(--brand-primary);
}

/* 激活指示器 */
.active-indicator {
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 20px;
  background: var(--brand-primary);
  border-radius: 0 2px 2px 0;
  box-shadow: 0 0 8px rgba(37, 99, 235, 0.4), 0 0 16px rgba(37, 99, 235, 0.2);
}

/* 折叠按钮 */
.collapse-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 48px;
  width: 100%;
  cursor: pointer;
  color: var(--text-secondary);
  transition: background-color 0.2s ease, color 0.2s ease;
  border: none;
  border-top: 1px solid var(--border-default);
  background: none;
  font: inherit;
}

.collapse-btn:hover {
  background-color: var(--bg-tertiary);
  color: var(--brand-primary);
}

.collapse-btn:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: -2px;
}

/* 过渡动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* 分组分隔线 */
.menu-divider {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 12px 6px;
  user-select: none;
}

.menu-divider.divider-collapsed {
  justify-content: center;
  padding: 12px 0 6px;
}

.divider-line {
  flex: 1;
  height: 1px;
  background: var(--border-default);
}

.divider-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  white-space: nowrap;
  flex-shrink: 0;
}

.menu-divider.divider-collapsed .divider-line {
  width: 20px;
  flex: 0;
}

/* 折叠状态下的样式调整 */
.sidebar.collapsed .menu-item-content {
  justify-content: center;
  padding: 12px 0;
}

.sidebar.collapsed .active-indicator {
  left: 0;
  width: 3px;
}
</style>
