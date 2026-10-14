<template>
  <header class="topbar">
    <!-- 左侧：页面身份。单一真相是 route.meta（此前这里另有一份按路径段翻译的 routeLabels，
         与 meta.title 已经漂过：面包屑把 /sftp/search 译成「高级搜索」）。
         契约：[data-testid=page-identity] 的文本 = 当前页名，用例只认它、不认结构。 -->
    <div class="topbar-left">
      <div class="page-identity">
        <span v-if="identity.icon" class="identity-badge" aria-hidden="true">
          <el-icon :size="16"><component :is="identity.icon" /></el-icon>
        </span>
        <div class="identity-text">
          <h1 class="identity-name" data-testid="page-identity">{{ identity.name }}</h1>
          <span v-if="identity.sub.length" class="identity-sub">
            <template v-for="(part, i) in identity.sub" :key="part.label">
              <span v-if="i > 0" class="sub-sep" aria-hidden="true">›</span>
              <router-link v-if="part.to" :to="part.to" class="sub-link">{{ part.label }}</router-link>
              <span v-else>{{ part.label }}</span>
            </template>
          </span>
        </div>
      </div>
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

/** 页面身份 = route.meta：名 + 徽章图标 + 副行（上级 › 说明）。上级与说明都可缺省。 */
const identity = computed(() => {
  const sub: Array<{ label: string; to?: string }> = []
  if (route.meta.parent) sub.push({ ...route.meta.parent })
  if (route.meta.desc) sub.push({ label: route.meta.desc })
  return { name: route.meta.title ?? '', icon: route.meta.icon, sub }
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
  background-color: var(--bg-2);
  border-bottom: 1px solid var(--border-2);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  gap: 24px;
}

/* 左侧：页面身份块 */
.topbar-left {
  flex: 1;
  min-width: 0;
}

.page-identity {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

/* 徽章底 = 徽标主变体（guide §10.1：品牌色 tint + 同色描边），图标用品牌色的 EP 矢量图标
   而非 emoji —— 与侧栏菜单同一批组件，认页面靠同一个形，不依赖系统 emoji 字体。 */
.identity-badge {
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: var(--p-radius-md);
  color: var(--brand);
  background: color-mix(in srgb, var(--brand) 14%, transparent);
  border: 1px solid color-mix(in srgb, var(--brand) 30%, transparent);
}

.identity-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.identity-name {
  font-size: var(--p-fs-lead);
  font-weight: var(--font-bold);
  line-height: 1.2;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.identity-sub {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--p-fs-micro);
  line-height: 1.2;
  /* 不用 --text-3：light 档它是 #9ca3af，压在 --bg-2 上实测 2.31:1，11px 说明文字根本读不动
     （与 DataFilterSection 的 sensitivity-hint 同一条坑）。纯 --text-2 是 4.39，仍差 AA 小字线
     0.11 —— 再朝 --text 压 22%：light 到 4.5+，night 因 --text 是白而自动变亮，两档同源不写死色。 */
  color: color-mix(in srgb, var(--text-2) 78%, var(--text));
  white-space: nowrap;
  overflow: hidden;
}

.sub-link {
  /* 跟随副行色，避免两处各写一份对比度取值 */
  color: inherit;
  text-decoration: none;
  transition: color 0.2s ease;
}

.sub-link:hover {
  color: var(--brand);
}

.sub-link:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
  border-radius: var(--p-radius-xs);
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
  --el-input-bg-color: var(--bg);
  --el-input-border-color: var(--border-2);
  --el-input-hover-border-color: var(--brand);
  --el-input-focus-border-color: var(--brand);
  --el-input-text-color: var(--text);
  --el-input-placeholder-color: var(--text-2);
}

:deep(.el-input__wrapper) {
  background-color: var(--bg);
  border-radius: 8px;
  box-shadow: none;
  transition: background-color 0.2s ease, box-shadow 0.2s ease;
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--brand);
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--brand), 0 0 8px rgba(37, 99, 235, 0.2);
}

/* 版本徽章 */
.version-badge {
  padding: 3px 10px;
  border-radius: 999px;
  font-size: var(--p-fs-dense);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--text-2);
  background: var(--bg-3);
  border: 1px solid var(--border-2);
  cursor: pointer;
  transition: color 0.2s ease, border-color 0.2s ease;
}

.version-badge:hover {
  color: var(--brand);
  border-color: var(--brand);
}

.version-badge:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
}

/* 通知图标 */
.notification-badge {
  line-height: 1;
}

:deep(.el-badge__content) {
  background-color: var(--error);
  border: none;
}

.icon-btn {
  color: var(--text-2);
  transition: color 0.2s ease, background-color 0.2s ease;
}

.icon-btn:hover {
  color: var(--brand);
  background-color: var(--bg-3);
}

.icon-btn:focus-visible {
  outline: 2px solid var(--brand);
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
  background-color: var(--bg-3);
}

.user-menu:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
}

.user-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: var(--brand);
  border-radius: 50%;
  color: #fff;
}

.user-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.user-name {
  font-size: var(--p-fs-small);
  font-weight: 600;
  color: var(--text);
  line-height: 1;
}

.user-role {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  line-height: 1;
}

.dropdown-icon {
  color: var(--text-2);
  font-size: var(--p-fs-dense);
  transition: transform 0.2s ease;
}

.user-menu:hover .dropdown-icon {
  color: var(--brand);
}

/* 下拉菜单样式 */
:deep(.el-dropdown-menu) {
  background-color: var(--bg-2);
  border: 1px solid var(--border-2);
  box-shadow: var(--shadow-lg);
}

:deep(.el-dropdown-menu__item) {
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 8px;
}

:deep(.el-dropdown-menu__item:hover) {
  background-color: var(--bg-3);
  color: var(--brand);
}

:deep(.el-dropdown-menu__item .el-icon) {
  font-size: var(--p-fs-lead);
}

@media (prefers-reduced-motion: reduce) {
  .topbar *,
  .dropdown-icon,
  .user-menu {
    transition: none !important;
  }
}
</style>
