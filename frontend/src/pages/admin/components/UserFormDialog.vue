<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'

import type { UserFormPayload, UserFormUser } from './userFormTypes'

const props = defineProps<{
  modelValue: boolean
  mode: 'create' | 'edit'
  user: UserFormUser | null
  saving: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  submit: [payload: UserFormPayload]
}>()

const formRef = ref<FormInstance>()
const form = reactive({ username: '', password: '', display_name: '', email: '', role: 'user' })

/**
 * 与 AccountDialog 的 profileRules 同一条规则、同一段文案：两个弹窗都能改 email，措辞不许分叉。
 * 只管格式，不加 required —— 邮箱列 blank=True，留空合法；display_name 后端零约束，前端不造第二套判据。
 */
const editRules: FormRules = {
  email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
}
const createRules: FormRules = {}

const title = computed(() => (props.mode === 'edit' ? '编辑账号' : '新增账号'))

function reset() {
  form.username = props.mode === 'edit' ? (props.user?.username ?? '') : ''
  form.password = ''
  form.display_name = props.mode === 'edit' ? (props.user?.display_name ?? '') : ''
  form.email = props.mode === 'edit' ? (props.user?.email ?? '') : ''
  form.role = props.mode === 'edit' ? (props.user?.role ?? 'user') : 'user'
  formRef.value?.clearValidate()
}

watch(
  () => [props.modelValue, props.user] as const,
  ([visible]) => {
    if (visible) reset()
  },
  { flush: 'post' },
)

function close() {
  emit('update:modelValue', false)
}

async function submit() {
  if (props.mode === 'edit') {
    const valid = await formRef.value?.validate().catch(() => false)
    if (!valid) return
    emit('submit', {
      mode: 'edit',
      display_name: form.display_name.trim(),
      email: form.email.trim(),
      role: form.role,
    })
    return
  }
  if (form.password.length < 8) {
    ElMessage.warning('密码至少 8 位')
    return
  }
  emit('submit', {
    mode: 'create',
    username: form.username,
    password: form.password,
    role: form.role,
  })
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="460px"
    :close-on-click-modal="false"
    append-to-body
    class="user-form-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form
      ref="formRef"
      :model="form"
      :rules="mode === 'edit' ? editRules : createRules"
      label-width="72px"
      @submit.prevent="submit"
    >
      <el-form-item v-if="mode === 'edit'" label="用户名" data-testid="edit-username">
        <el-input :model-value="user?.username" disabled />
      </el-form-item>
      <el-form-item v-else label="用户名" data-testid="create-username">
        <el-input v-model="form.username" />
      </el-form-item>
      <el-form-item v-if="mode === 'create'" label="密码" data-testid="create-password">
        <el-input v-model="form.password" type="password" />
      </el-form-item>
      <el-form-item v-if="mode === 'edit'" label="显示名" data-testid="edit-display-name">
        <el-input v-model="form.display_name" maxlength="150" />
      </el-form-item>
      <el-form-item v-if="mode === 'edit'" label="邮箱" prop="email" data-testid="edit-email">
        <el-input v-model="form.email" placeholder="可留空" />
      </el-form-item>
      <el-form-item
        label="角色"
        :data-testid="mode === 'edit' ? 'edit-role' : 'create-role'"
      >
        <el-select v-model="form.role">
          <el-option label="用户" value="user" />
          <el-option label="管理员" value="administrator" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">
        {{ mode === 'edit' ? '保存' : '创建' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
/* 页面在批3b 把对话框拆成子组件后，原页面 scoped 的 input/footer 规则够不到 teleport 后的 DOM；
 * 这里按原值接手，light 下的底色/描边与页面其余控件一致，night 由全局主题层 !important 覆盖。 */
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
