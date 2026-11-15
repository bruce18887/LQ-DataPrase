<template>
  <div class="user-management">
    <UserKpiChips
      :total="kpi.total"
      :active="kpi.active"
      :locked="kpi.locked"
      :admins="kpi.admins"
    />

    <AdminPageToolbar>
      <template #right>
        <el-button type="primary" @click="openCreate">新增账号</el-button>
      </template>
    </AdminPageToolbar>

    <el-card class="table-card">
      <el-table :data="users" stripe>
        <el-table-column prop="username" label="用户名" min-width="120" />
        <el-table-column prop="display_name" label="显示名" min-width="120" />
        <el-table-column label="角色" width="120">
          <template #default="{ row }">
            <span class="role-cell">
              <el-icon class="role-icon"><component :is="roleIcon(row.role)" /></el-icon>
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
        <!-- 操作列下限 340 的来源（2026-11-10 按**已装的 element-plus 2.14.0** 的 dist CSS 实测算出，
             与视口无关；下面几个常数是版本相关的实现细节，升级 EP 后这段要重量一次，别当定律）。
             数值一律写成散文而不是声明形状 —— 源码级字号守门（e2e/global/fonts.spec.ts:155）只放过
             行首是注释的写法，模板注释的续行照样会被它扫到，写成 CSS 声明就是在给自己造红。
             最宽形态是**锁定行**：五枚 small 按钮同时出现（编辑 / 禁用或启用 / 重置密码 / 解锁 / 删除）。
             .el-button--small 的内距 5px 与 11px、字号 12px，加 CJK 字宽 12px ⇒ 单枚 48/48/72/48/48，
             合计 264；相邻按钮的外距 12px × 4 = 48；单元格内距 12px × 2 = 24 ⇒ 总计 336px。
             340 是盖过 336 的第一个整十值；往下退到 330 就不够了 —— .cell 允许折行，
             最后一枚按钮会被折到第二行（按钮自身不折，因为它 white-space 是 nowrap）。 -->
        <el-table-column label="操作" min-width="340">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click="openEdit(row)">
              编辑
            </el-button>
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

    <UserFormDialog
      v-model="formVisible"
      :mode="formMode"
      :user="editing"
      :saving="saving"
      @submit="onFormSubmit"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Stamp, UserFilled } from '@element-plus/icons-vue'

import api from '../../api'
import { collectAllPages } from '../../utils/paging'
import { useAuthStore } from '../../stores/auth'
import { roleLabel } from '../../utils/roleLabel'
import AdminPageToolbar from './components/AdminPageToolbar.vue'
import UserKpiChips from './components/UserKpiChips.vue'
import UserFormDialog from './components/UserFormDialog.vue'
import type { UserFormPayload } from './components/userFormTypes'

interface User {
  id: number
  username: string
  email: string
  display_name: string
  role: string
  is_active: boolean
  date_joined: string
  last_login: string | null
  lockout_until: string | null
}

const users = ref<User[]>([])
const formVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const editing = ref<User | null>(null)
const saving = ref(false)
const auth = useAuthStore()

/**
 * 本行是不是当前登录账号。禁用/删除自己会把自己锁在门外：
 * 登录端点对停用账号直接 403、SimpleJWT 也立刻吊销 token，只能直连数据库恢复。
 * 后端 UserManagementViewSet._guard_lockout 是权威守卫（这里只是不让点）。
 * 硬刷新后 auth.user 可能为 null（本页不自拉 profile），此时按钮回落成可点，
 * 由后端 400 + toast 兜住。
 */
function isSelf(user: User): boolean {
  return user.id === auth.user?.id
}

const kpi = computed(() => ({
  total: users.value.length,
  active: users.value.filter((u) => u.is_active && !isLocked(u)).length,
  locked: users.value.filter((u) => isLocked(u)).length,
  admins: users.value.filter((u) => u.role === 'administrator').length,
}))

function isLocked(user: User): boolean {
  if (!user.lockout_until) return false
  return new Date(user.lockout_until) > new Date()
}

function roleIcon(role: string) {
  return role === 'administrator' ? Stamp : UserFilled
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
 * 不可达，而 kpi 的四个数全按 `users` 统计 ⇒ 数字静默失真。跟着 `next` 取完；
 * 50 页护栏只为防坏响应自指成死循环，正常账号规模远不到。
 */
async function loadUsers() {
  try {
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

function openCreate() {
  editing.value = null
  formMode.value = 'create'
  formVisible.value = true
}

function openEdit(user: User) {
  editing.value = user
  formMode.value = 'edit'
  formVisible.value = true
}

async function onFormSubmit(payload: UserFormPayload) {
  saving.value = true
  try {
    if (payload.mode === 'edit' && editing.value) {
      await api.put(`/auth/users/${editing.value.id}/`, {
        display_name: payload.display_name,
        email: payload.email,
        role: payload.role,
      })
      ElMessage.success('账号已更新')
      const self = isSelf(editing.value)
      formVisible.value = false
      loadUsers()
      // 改的是登录账号自己时补拉一次 profile：降级成功后 Pinia 的 user.role 还停在旧值
      // （stores/auth.ts:35 读内存态），不补拉侧栏会按管理员继续渲染。fetchProfile 失败会先
      // logout 再抛，而账号已存好，所以就地吞掉。刻意不写 e2e 判据：降级种子唯一 admin 会塌池。
      if (self) await auth.fetchProfile().catch(() => undefined)
    } else if (payload.mode === 'create') {
      await api.post('/auth/users/', {
        username: payload.username,
        password: payload.password,
        role: payload.role,
      })
      ElMessage.success('用户已添加')
      formVisible.value = false
      loadUsers()
    }
  } catch {
    // 守卫失败与网络错误由拦截器弹文案，列表保持原样
  } finally {
    saving.value = false
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
  // 旧实现发的是硬编码 '123456'（6 位），而后端 AdminResetPasswordSerializer.new_password
  // 是 min_length=8 ⇒「重置密码」按钮从来没成功过一次。改成管理员当场输入新密码，
  // 长度门槛与后端同值：本页 inputPattern /^.{8,}$/ 的 8 == serializers.py:205 的 8
  // （强度校验另见 :208-212，前端不复制它，弱密码由后端 400 兜住）。
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
    ElMessage.success(`已重置 ${user.username} 的密码，请告知其登录后修改`)
    loadUsers()
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

:deep(.el-button) {
  border-radius: 8px;
}
</style>
