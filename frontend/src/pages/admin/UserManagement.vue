<template>
  <div class="user-management">
    <div class="kpi-grid">
      <div class="kpi-card kpi-card--blue">
        <div class="kpi-card__icon">👥</div>
        <div class="kpi-card__info">
          <div class="kpi-card__label">总用户数</div>
          <div class="kpi-card__value">{{ kpi.total }}</div>
        </div>
      </div>
      <div class="kpi-card kpi-card--green">
        <div class="kpi-card__icon">✅</div>
        <div class="kpi-card__info">
          <div class="kpi-card__label">活跃用户</div>
          <div class="kpi-card__value">{{ kpi.active }}</div>
        </div>
      </div>
      <div class="kpi-card kpi-card--orange">
        <div class="kpi-card__icon">🔒</div>
        <div class="kpi-card__info">
          <div class="kpi-card__label">锁定用户</div>
          <div class="kpi-card__value">{{ kpi.locked }}</div>
        </div>
      </div>
      <div class="kpi-card kpi-card--purple">
        <div class="kpi-card__icon">🛡️</div>
        <div class="kpi-card__info">
          <div class="kpi-card__label">管理员</div>
          <div class="kpi-card__value">{{ kpi.admins }}</div>
        </div>
      </div>
    </div>

    <el-card class="table-card">
      <el-table :data="users" stripe>
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column prop="display_name" label="显示名" min-width="120" />
        <el-table-column label="角色" width="120">
          <template #default="{ row }">
            <span class="role-cell">
              <span class="role-icon">{{ roleIcon(row.role) }}</span>
              {{ roleLabel(row.role) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <span class="status-cell">
              <span class="status-dot" :class="'status-dot--' + statusClass(row)"></span>
              {{ statusLabel(row) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">
            {{ formatDate(row.date_joined) }}
          </template>
        </el-table-column>
        <el-table-column label="最后登录" width="170">
          <template #default="{ row }">
            {{ formatDate(row.last_login) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="240">
          <template #default="{ row }">
            <el-button
              size="small"
              :disabled="isSelf(row)"
              :title="isSelf(row) ? '不能禁用或删除自己的账号' : undefined"
              @click="toggleUser(row)"
            >
              {{ row.is_active ? '禁用' : '启用' }}
            </el-button>
            <el-button size="small" type="warning" @click="resetPassword(row)">
              重置密码
            </el-button>
            <el-button
              v-if="isLocked(row)"
              size="small"
              type="primary"
              @click="unlockUser(row)"
            >
              解锁
            </el-button>
            <el-button
              size="small"
              type="danger"
              :disabled="isSelf(row)"
              :title="isSelf(row) ? '不能禁用或删除自己的账号' : undefined"
              @click="deleteUser(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-divider />
    <h3>➕ 添加用户</h3>
    <el-card>
      <el-form :model="newUser" inline @submit.prevent="addUser">
        <el-form-item label="用户名">
          <el-input v-model="newUser.username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="newUser.password" type="password" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="newUser.role">
            <el-option label="用户" value="user" />
            <el-option label="管理员" value="administrator" />
            <el-option label="查看者" value="viewer" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">添加</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../../api'
import { collectAllPages } from '../../utils/paging'
import { useAuthStore } from '../../stores/auth'

interface User {
  id: number
  username: string
  display_name: string
  role: string
  is_active: boolean
  date_joined: string
  last_login: string | null
  lockout_until: string | null
}

const users = ref<User[]>([])
const newUser = ref({ username: '', password: '', role: 'user' })
const auth = useAuthStore()

/**
 * 本行是不是当前登录账号。禁用/删除自己会把自己锁在门外：登录端点对
 * 停用账号直接 403、SimpleJWT 也立刻吊销 token，只能直连数据库恢复。
 * 后端 UserManagementViewSet._guard_lockout 是权威守卫（这里只是不让点）。
 * 注意硬刷新后 auth.user 可能为 null（本页不自拉 profile），此时按钮回落
 * 成可点，由后端 400 + toast 兜住。
 */
function isSelf(user: User): boolean {
  return user.id === auth.user?.id
}

const kpi = computed(() => {
  return {
    total: users.value.length,
    active: users.value.filter((u) => u.is_active && !isLocked(u)).length,
    locked: users.value.filter((u) => isLocked(u)).length,
    admins: users.value.filter((u) => u.role === 'administrator').length,
  }
})

function isLocked(user: User): boolean {
  if (!user.lockout_until) return false
  return new Date(user.lockout_until) > new Date()
}

function roleIcon(role: string): string {
  if (role === 'administrator') return '🛡️'
  if (role === 'viewer') return '👁️'
  return '👤'
}

function roleLabel(role: string): string {
  if (role === 'administrator') return '管理员'
  if (role === 'viewer') return '查看者'
  return '用户'
}

function statusClass(user: User): string {
  if (isLocked(user)) return 'locked'
  if (!user.is_active) return 'disabled'
  return 'active'
}

function statusLabel(user: User): string {
  if (isLocked(user)) return 'locked'
  if (!user.is_active) return 'disabled'
  return 'active'
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * 分页取全。DRF 默认 PAGE_SIZE=20（config/settings/base.py:214-215，本 ViewSet 未覆写
 * pagination_class），而本页**没有翻页控件**：只读第一页的话，第 21 个用户起在页面上
 * 不可达，而下面 kpi 的 total/active/locked/admins 全按 `users` 统计 ⇒ 数字静默失真。
 * 跟着 `next` 取完；50 页护栏只为防坏响应自指成死循环，正常账号规模远不到。
 */
async function loadUsers() {
  try {
    // 判据内核与三种响应形态的单测在 utils/paging.ts（T2，秒级、不开浏览器）
    const { rows, truncated } = await collectAllPages<User>(
      async (url) => (await api.get(url)).data,
      '/auth/users/',
    )
    users.value = rows
    if (truncated) {
      ElMessage.warning(`用户多于 ${rows.length} 条，本次只取到前若干页，统计可能偏小`)
    }
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出（utils/error.ts formatError）
  }
}

async function addUser() {
  // 后端 apps/accounts/serializers.py:60 是 password = CharField(min_length=8)：
  // 不前置检查，短密码要跑到后端被 400 再弹一句英文 detail。
  if (newUser.value.password.length < 8) {
    ElMessage.warning('密码至少 8 位')
    return
  }
  try {
    await api.post('/auth/users/', newUser.value)
    ElMessage.success('用户已添加')
    newUser.value = { username: '', password: '', role: 'user' }
    loadUsers()
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  }
}

async function toggleUser(user: User) {
  try {
    await api.put(`/auth/users/${user.id}/`, { is_active: !user.is_active })
    ElMessage.success('状态已更新')
    loadUsers()
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  }
}

async function resetPassword(user: User) {
  // 旧实现发的是硬编码 '123456'（6 位），而后端 apps/accounts/views.py:300 对
  // len<8 一律 400 ⇒ 「重置密码」这个按钮从来没成功过一次。改成管理员当场输入新密码，
  // 长度门槛与后端同值（views.py:300 与 serializers.py:173 都是 8）。
  let value: string
  try {
    ({ value } = await ElMessageBox.prompt(
      `为 ${user.username} 设置新密码（至少 8 位）`,
      '重置密码',
      {
        confirmButtonText: '重置',
        cancelButtonText: '取消',
        inputPattern: /^.{8,}$/,
        inputErrorMessage: '密码至少 8 位',
      },
    ))
  } catch {
    return // 取消：prompt 关闭时 reject 'cancel'
  }
  try {
    await api.post(`/auth/users/${user.id}/reset_password/`, { new_password: value })
    ElMessage.success(`已重置 ${user.username} 的密码`)
  } catch {
    // 真实错误 toast 由拦截器弹出
  }
}

async function unlockUser(user: User) {
  try {
    await api.post(`/auth/users/${user.id}/unlock/`)
    ElMessage.success('账户已解锁')
    loadUsers()
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  }
}

async function deleteUser(user: User) {
  try {
    await ElMessageBox.confirm(`确定删除用户 ${user.username}？`, '确认')
    await api.delete(`/auth/users/${user.id}/`)
    ElMessage.success('已删除')
    loadUsers()
  } catch {
    // ElMessageBox.confirm 取消会 reject "cancel"；真实错误 toast 由拦截器弹出
  }
}

onMounted(loadUsers)
</script>

<style scoped>
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.kpi-card {
  border-radius: 12px;
  padding: 20px;
  background: var(--card);
  border: 1px solid var(--border);
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.25s ease, border-color 0.25s ease;
}

.kpi-card:hover {
  box-shadow: var(--shadow-md);
}

/* 语义色柔和底（指南 §10.1 V1 语言），双主题自动适配，无页面级覆盖 */
.kpi-card--blue {
  background: color-mix(in srgb, var(--brand) 10%, var(--card));
}
.kpi-card--blue .kpi-card__icon { color: var(--brand); }

.kpi-card--green {
  background: color-mix(in srgb, var(--success) 10%, var(--card));
}
.kpi-card--green .kpi-card__icon { color: var(--success); }

.kpi-card--orange {
  background: color-mix(in srgb, var(--warn) 10%, var(--card));
}
.kpi-card--orange .kpi-card__icon { color: var(--warn); }

.kpi-card--purple {
  background: color-mix(in srgb, var(--info) 10%, var(--card));
}
.kpi-card--purple .kpi-card__icon { color: var(--info); }

.kpi-card__icon {
  font-size: 36px; /* @type-scale-one-off 装饰图标，非 UI 文本，不进九档 */
  flex-shrink: 0;
}

.kpi-card__label {
  font-size: var(--p-fs-small);
  color: var(--text-2);
  margin-bottom: 4px;
}

.kpi-card__value {
  font-size: var(--p-fs-headline);
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  color: var(--text);
}

.table-card {
  margin-bottom: 16px;
  border-radius: 8px;
}

.table-card :deep(.el-card__body) {
  padding: 0;
}

.role-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.role-icon {
  font-size: var(--p-fs-title);
}

.status-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.status-dot--active {
  background-color: var(--success);
}

.status-dot--locked {
  background-color: var(--error);
}

.status-dot--disabled {
  background-color: var(--text-3);
}

:deep(.el-card) {
  background-color: var(--bg-2);
  border: 1px solid var(--border-2);
  border-radius: 8px;
}

:deep(.el-table) {
  --el-table-bg-color: var(--bg-2);
  --el-table-tr-bg-color: var(--bg-2);
  --el-table-header-bg-color: var(--bg-3);
  --el-table-border-color: var(--border-2);
  --el-table-text-color: var(--text);
  --el-table-row-hover-bg-color: var(--bg-3);
}

:deep(.el-input__wrapper) {
  background-color: var(--bg);
  border-radius: 8px;
  box-shadow: 0 0 0 1px var(--border-2) inset;
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--brand) inset;
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--brand) inset;
}

:deep(.el-select .el-input__wrapper) {
  background-color: var(--bg);
}

:deep(.el-button) {
  border-radius: 8px;
}

:deep(.el-divider) {
  border-color: var(--border-2);
}

@media (max-width: 900px) {
  .kpi-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 500px) {
  .kpi-grid {
    grid-template-columns: 1fr;
  }
}
</style>
