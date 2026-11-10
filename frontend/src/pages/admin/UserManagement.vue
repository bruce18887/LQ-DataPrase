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

    <el-dialog
      v-model="editVisible"
      title="编辑账号"
      width="460px"
      :close-on-click-modal="false"
      append-to-body
      class="user-edit-dialog"
    >
      <el-form
        ref="editFormRef"
        :model="editForm"
        :rules="editRules"
        label-width="72px"
        @submit.prevent="saveEdit"
      >
        <el-form-item label="用户名" data-testid="edit-username">
          <el-input :model-value="editing?.username" disabled />
        </el-form-item>
        <el-form-item label="显示名" data-testid="edit-display-name">
          <el-input v-model="editForm.display_name" maxlength="150" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email" data-testid="edit-email">
          <el-input v-model="editForm.email" placeholder="可留空" />
        </el-form-item>
        <el-form-item label="角色" data-testid="edit-role">
          <el-select v-model="editForm.role">
            <el-option label="用户" value="user" />
            <el-option label="管理员" value="administrator" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

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
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import api from '../../api'
import { collectAllPages } from '../../utils/paging'
import { useAuthStore } from '../../stores/auth'
// 角色标签的唯一语义来源是 utils/roleLabel（§7.3 兜底理由写在那份文件的注释里）；
// 这里只做委托，别在本文件再写一份 roleLabel。roleIcon 只此一份，留在本地。
import { roleLabel } from '../../utils/roleLabel'

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
const newUser = ref({ username: '', password: '', role: 'user' })
const editVisible = ref(false)
const editing = ref<User | null>(null)
const saving = ref(false)
const editForm = ref({ display_name: '', email: '', role: 'user' })
const editFormRef = ref<FormInstance>()
/**
 * 与 AccountDialog 的 `profileRules` 同一条规则、同一段文案（那份在
 * `components/layout/AccountDialog.vue:155-157`）：两个弹窗都能改 email，措辞不许分叉。
 * 只管格式，**不**加 required —— 邮箱列是 `CharField(blank=True)`，留空合法（async-validator 的
 * type 校验对「空值且非 required」直接放行）。display_name 不设规则：后端对它没有任何约束
 * （blank=True、无校验器），前端编一条只会凭空造出「后端收、前端拒」的第二套判据。
 */
const editRules: FormRules = {
  email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
}
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
  // 兜底也吃掉迁移 0012 未跑到的机器上残留的第三种角色（见 2026-11-05-account-role-audit-design.md §7.3）
  return '👤'
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
  // 后端 apps/accounts/serializers.py:61-65 就是 UserCreateSerializer 的
  // password = CharField(write_only=True, min_length=8)（类声明在 :60）：不前置检查，
  // 短密码要绕一圈网络、被后端 400 挡回来才显示（文案见同处 :64 的 error_messages）。
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

function openEdit(user: User) {
  editing.value = user
  // 直接取值，不写 `?? ''`：interface User 把这两列声明成非空 string（本文件 :185-186），后端
  // 侧它们是 `CharField(blank=True)`（display_name 见 apps/accounts/models.py:43，email 来自
  // Django 的 AbstractUser），NOT NULL ⇒ 库里只有空串没有 NULL（2026-11-10 只读现量：dev 与
  // e2e 夹具两份库各 3 行，`sum(col is null)` 全 0、typeof 全 'text'）。
  editForm.value = { display_name: user.display_name, email: user.email, role: user.role }
  // 弹窗不销毁重建（没有 destroy-on-close），上一次校验失败的红字会留在 DOM 里，故开一次清一次
  // —— 与 AccountDialog 的 initForms 同法（:195）。
  editFormRef.value?.clearValidate()
  editVisible.value = true
}

async function saveEdit() {
  const user = editing.value
  if (!user) return
  // 前置校验：形状照 AccountDialog 的 saveProfile（:205-206）。validate() 不过会 reject，
  // `.catch(() => false)` 把它折成布尔。少这一步，填错的邮箱要绕一圈网络才由拦截器弹出后端文案。
  const valid = await editFormRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    // PUT 是整份替换语义的例外：后端 update() 强制 partial=True
    // （apps/accounts/views.py:478-491），所以只发这三字段不会把 is_active 冲洗掉。
    await api.put(`/auth/users/${user.id}/`, {
      display_name: editForm.value.display_name.trim(),
      email: editForm.value.email.trim(),
      role: editForm.value.role,
    })
    ElMessage.success('账号已更新')
    editVisible.value = false
    loadUsers()
    // 改的就是登录账号自己时补拉一次 profile。为什么现在才需要：`_guard_lockout` 只拦「拆掉最后
    // 一个启用的管理员」，种子里 admin 是唯一的 ⇒ 自我降级原本必被拒；本批的编辑弹窗让「先把别人
    // 提成第二个管理员、再给自己降级」成为通路，而降级成功后 Pinia 的 user.role/isAdmin 还停在旧值
    // （stores/auth.ts:35 读的是内存态）⇒ 侧边栏与菜单继续按管理员渲染，直到刷新才收敛。
    // fetchProfile 失败会先 logout() 再抛（stores/auth.ts:63-73），而账号此刻已经存好了，所以就地
    // 吞掉：不能让成功路径反过来吃一条错误 toast。auth.user 为 null（硬刷新后本页不自拉 profile，
    // 见上面 isSelf 的注释）时 isSelf 恒假 —— 那种形态下 isAdmin 本来就是 false，没有陈旧可清。
    // 刻意**不写 e2e 判据**：跑通它要把种子里唯一的 admin 降级掉，之后每条 spec 的 afterAll 登录
    // 与整个池的种子态都会塌（本批已知的未覆盖分支）。
    if (isSelf(user)) await auth.fetchProfile().catch(() => undefined)
  } catch {
    // 守卫失败（例如拆掉最后一个管理员）由拦截器弹文案，列表保持原样
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
  // 旧实现发的是硬编码 '123456'（6 位），而后端 apps/accounts/serializers.py:203-206 的
  // AdminResetPasswordSerializer.new_password 是 min_length=8 ⇒ 「重置密码」这个按钮从来没
  // 成功过一次。改成管理员当场输入新密码，长度门槛与后端同值：本页 inputPattern /^.{8,}$/
  // 的 8 == serializers.py:205 的 8（强度校验另见 :208-212 的 validate_password_or_raise，
  // 前端不复制它，弱密码由后端 400 兜住）。自助改密是另一个 Serializer：
  // PasswordChangeSerializer :184-191，同样 8。
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
    // 后端重置会同时清锁定；刷新表格让「锁定用户」KPI 与行状态立即收敛。
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
