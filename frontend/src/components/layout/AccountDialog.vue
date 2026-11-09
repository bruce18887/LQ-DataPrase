<template>
  <el-dialog
    v-model="visible"
    title="个人资料"
    width="520px"
    :close-on-click-modal="false"
    append-to-body
    class="account-dialog"
  >
    <div data-testid="account-dialog">
      <section class="account-section">
        <h3 class="account-section__title">基本信息</h3>
        <el-form
          ref="profileFormRef"
          :model="profileForm"
          :rules="profileRules"
          label-width="90px"
          @submit.prevent="saveProfile"
        >
          <el-form-item label="用户名">
            <el-input :model-value="auth.user?.username ?? ''" disabled />
          </el-form-item>
          <el-form-item label="角色">
            <el-input :model-value="roleLabel(auth.user?.role)" disabled />
          </el-form-item>
          <el-form-item label="显示名" prop="display_name">
            <el-input
              v-model="profileForm.display_name"
              maxlength="150"
              placeholder="显示在右上角的名称"
              data-testid="account-display-name"
            />
          </el-form-item>
          <el-form-item label="邮箱" prop="email">
            <el-input
              v-model="profileForm.email"
              placeholder="用于联系与识别账号"
              autocomplete="email"
              data-testid="account-email"
            />
          </el-form-item>
          <el-form-item>
            <el-button
              type="primary"
              native-type="submit"
              :loading="savingProfile"
              data-testid="account-save-profile"
            >
              保存资料
            </el-button>
          </el-form-item>
        </el-form>
      </section>

      <el-divider />

      <section class="account-section">
        <h3 class="account-section__title">修改密码</h3>
        <p class="account-hint">
          修改成功后当前登录会立即失效，需要使用新密码重新登录。
          管理员重置的临时密码也在这里修改。
        </p>
        <el-form
          ref="passwordFormRef"
          :model="passwordForm"
          :rules="passwordRules"
          label-width="90px"
          @submit.prevent="changePassword"
        >
          <el-form-item label="当前密码" prop="old_password">
            <el-input
              v-model="passwordForm.old_password"
              type="password"
              show-password
              autocomplete="current-password"
              data-testid="account-old-password"
            />
          </el-form-item>
          <el-form-item label="新密码" prop="new_password">
            <el-input
              v-model="passwordForm.new_password"
              type="password"
              show-password
              autocomplete="new-password"
              data-testid="account-new-password"
            />
          </el-form-item>
          <el-form-item label="确认新密码" prop="confirm_password">
            <el-input
              v-model="passwordForm.confirm_password"
              type="password"
              show-password
              autocomplete="new-password"
              data-testid="account-confirm-password"
            />
          </el-form-item>
          <el-form-item>
            <el-button
              type="warning"
              native-type="submit"
              :loading="changingPassword"
              data-testid="account-change-password"
            >
              修改密码
            </el-button>
          </el-form-item>
        </el-form>
      </section>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { authApi } from '../../api/auth'
import { useAuthStore } from '../../stores/auth'
// 角色标签的唯一语义来源是 utils/roleLabel（§7.3 兜底理由写在那份文件的注释里）；
// 这里只做委托，别在本文件再写一份 roleLabel。
import { roleLabel } from '../../utils/roleLabel'

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
}>()

const auth = useAuthStore()
const router = useRouter()

const visible = computed({
  get: () => props.visible,
  set: (value) => emit('update:visible', value),
})

const profileFormRef = ref<FormInstance>()
const passwordFormRef = ref<FormInstance>()
const savingProfile = ref(false)
const changingPassword = ref(false)

const profileForm = reactive({
  display_name: '',
  email: '',
})

const passwordForm = reactive({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

const profileRules: FormRules = {
  email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
}

function validateConfirm(
  _rule: unknown,
  value: string,
  callback: (error?: Error) => void,
) {
  if (value !== passwordForm.new_password) {
    callback(new Error('两次输入的新密码不一致'))
    return
  }
  callback()
}

const passwordRules: FormRules = {
  old_password: [
    { required: true, message: '请输入当前密码', trigger: 'blur' },
  ],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, message: '密码至少 8 位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    { validator: validateConfirm, trigger: 'blur' },
  ],
}

function resetPasswordForm() {
  passwordForm.old_password = ''
  passwordForm.new_password = ''
  passwordForm.confirm_password = ''
  passwordFormRef.value?.clearValidate()
}

function initForms() {
  profileForm.display_name = auth.user?.display_name ?? ''
  profileForm.email = auth.user?.email ?? ''
  profileFormRef.value?.clearValidate()
  resetPasswordForm()
}

watch(visible, (open) => {
  if (open) initForms()
  else resetPasswordForm()
})

async function saveProfile() {
  const valid = await profileFormRef.value?.validate().catch(() => false)
  if (!valid) return

  savingProfile.value = true
  try {
    await authApi.updateProfile({
      display_name: profileForm.display_name.trim(),
      email: profileForm.email.trim(),
    })
    await auth.fetchProfile()
    ElMessage.success('资料已保存')
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  } finally {
    savingProfile.value = false
  }
}

async function changePassword() {
  const valid = await passwordFormRef.value?.validate().catch(() => false)
  if (!valid) return

  changingPassword.value = true
  try {
    await authApi.changePassword({
      old_password: passwordForm.old_password,
      new_password: passwordForm.new_password,
      confirm_password: passwordForm.confirm_password,
    })
    ElMessage.success('密码已修改，请使用新密码重新登录')
    visible.value = false
    auth.clearSession()
    router.push('/login')
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  } finally {
    changingPassword.value = false
  }
}
</script>

<style scoped>
.account-section__title {
  margin: 0 0 16px;
  font-size: var(--p-fs-title);
  font-weight: 700;
  color: var(--text);
}

.account-hint {
  margin: -8px 0 16px;
  color: var(--text-2);
  font-size: var(--p-fs-dense);
  line-height: 1.6;
}

:deep(.el-divider) {
  border-color: var(--border-2);
}
</style>
