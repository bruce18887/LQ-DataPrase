<template>
  <div class="user-management">
    <h2>👥 用户管理</h2>

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
            <el-button size="small" @click="toggleUser(row)">
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
            <el-button size="small" type="danger" @click="deleteUser(row)">
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

async function loadUsers() {
  try {
    const { data } = await api.get('/auth/users/')
    users.value = Array.isArray(data) ? data : data.results || []
  } catch {
    ElMessage.error('加载用户失败')
  }
}

async function addUser() {
  try {
    await api.post('/auth/users/', newUser.value)
    ElMessage.success('用户已添加')
    newUser.value = { username: '', password: '', role: 'user' }
    loadUsers()
  } catch {
    ElMessage.error('添加失败')
  }
}

async function toggleUser(user: User) {
  try {
    await api.put(`/auth/users/${user.id}/`, { is_active: !user.is_active })
    ElMessage.success('状态已更新')
    loadUsers()
  } catch {
    ElMessage.error('操作失败')
  }
}

async function resetPassword(user: User) {
  try {
    await ElMessageBox.confirm(
      `确定将用户 ${user.username} 的密码重置为 123456 吗？`,
      '确认重置密码',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
    await api.post(`/auth/users/${user.id}/reset_password/`, {
      new_password: '123456',
    })
    ElMessage.success('密码已重置')
  } catch {
    // cancelled or error
  }
}

async function unlockUser(user: User) {
  try {
    await api.post(`/auth/users/${user.id}/unlock/`)
    ElMessage.success('账户已解锁')
    loadUsers()
  } catch {
    ElMessage.error('解锁失败')
  }
}

async function deleteUser(user: User) {
  try {
    await ElMessageBox.confirm(`确定删除用户 ${user.username}？`, '确认')
    await api.delete(`/auth/users/${user.id}/`)
    ElMessage.success('已删除')
    loadUsers()
  } catch {
    // user cancelled or error
  }
}

onMounted(loadUsers)
</script>

<style scoped>
.user-management h2 {
  margin-bottom: 20px;
  color: var(--text-primary);
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.kpi-card {
  border-radius: 8px;
  padding: 20px;
  color: var(--text-inverse);
  display: flex;
  align-items: center;
  gap: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.06);
  transition: box-shadow 0.3s ease, border-color 0.3s ease;
}

.kpi-card:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12), 0 2px 6px rgba(0, 0, 0, 0.08);
  transform: translateY(-2px);
}

.kpi-card--blue {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
}

.kpi-card--green {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
}

.kpi-card--orange {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
}

.kpi-card--purple {
  background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
}

.kpi-card__icon {
  font-size: 36px;
  flex-shrink: 0;
}

.kpi-card__label {
  font-size: 14px;
  opacity: 0.9;
  margin-bottom: 4px;
}

.kpi-card__value {
  font-size: 32px;
  font-weight: 700;
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
  font-size: 18px;
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
  background-color: var(--color-success);
}

.status-dot--locked {
  background-color: var(--color-error);
}

.status-dot--disabled {
  background-color: var(--text-tertiary);
}

:deep(.el-card) {
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
}

:deep(.el-table) {
  --el-table-bg-color: var(--bg-secondary);
  --el-table-tr-bg-color: var(--bg-secondary);
  --el-table-header-bg-color: var(--bg-tertiary);
  --el-table-border-color: var(--border-default);
  --el-table-text-color: var(--text-primary);
  --el-table-row-hover-bg-color: var(--bg-tertiary);
}

:deep(.el-input__wrapper) {
  background-color: var(--bg-primary);
  border-radius: 8px;
  box-shadow: 0 0 0 1px var(--border-default) inset;
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--brand-primary) inset;
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--brand-primary) inset;
}

:deep(.el-select .el-input__wrapper) {
  background-color: var(--bg-primary);
}

:deep(.el-button) {
  border-radius: 8px;
}

:deep(.el-divider) {
  border-color: var(--border-default);
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
