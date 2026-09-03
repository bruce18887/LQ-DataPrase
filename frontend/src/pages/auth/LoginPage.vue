<template>
  <GridBackground>
    <div class="login-container">
      <div class="login-card">
        <!-- Logo 区域 -->
        <div class="logo-section">
          <el-icon :size="64" class="logo-icon">
            <TrendCharts />
          </el-icon>
        </div>

        <!-- 品牌标题 -->
        <h1 class="login-title">LQ-DataPrase</h1>
        <p class="login-subtitle">ATE 数据分析平台</p>

        <!-- 登录表单 -->
        <el-form ref="formRef" :model="form" :rules="rules" label-width="80px" @submit.prevent="handleLogin">
          <el-form-item prop="username" label="用户名" required>
            <el-input
              v-model="form.username"
              placeholder="请输入用户名"
              size="large"
              name="username"
              autocomplete="username"
              class="login-input"
            />
          </el-form-item>
          <el-form-item prop="password" label="密码" required>
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              size="large"
              name="password"
              autocomplete="current-password"
              show-password
              class="login-input"
            />
          </el-form-item>
          <el-form-item>
            <el-button
              type="primary"
              size="large"
              :loading="loading"
              native-type="submit"
              class="login-button"
            >
              <span v-if="!loading">登 录</span>
              <span v-else>登录中…</span>
            </el-button>
          </el-form-item>
        </el-form>

        <!-- 错误提示 -->
        <transition name="fade">
          <p
            v-if="error"
            class="error-msg"
            :class="`error-msg--${errorCategory}`"
            aria-live="polite"
          >
            {{ error }}
            <span
              v-if="errorHint"
              class="error-hint"
              data-testid="login-error-hint"
            >{{ errorHint }}</span>
          </p>
        </transition>
      </div>
    </div>
  </GridBackground>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import { TrendCharts } from '@element-plus/icons-vue'
import GridBackground from '../../components/common/GridBackground.vue'
import { parseLoginError, type LoginFailureCategory } from '../../api/auth'
import type { FormInstance } from 'element-plus'

const router = useRouter()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
// 不再预填真实凭据：渲染层打进安装包后可被反编译读出，等于把管理员
// 口令随产品分发（后端 bootstrap 仍会建 admin）。开发态如需免输入，在
// frontend/.env.development.local 里写 VITE_DEV_LOGIN_USER / VITE_DEV_LOGIN_PASS；
// import.meta.env.DEV 分支在生产构建中被 tree-shake 掉，不会泄露。
// e2e 不受影响：helpers/auth.ts 的 uiLogin 用 fill() 覆盖式输入。
const form = reactive({
  username: import.meta.env.DEV ? (import.meta.env.VITE_DEV_LOGIN_USER ?? '') : '',
  password: import.meta.env.DEV ? (import.meta.env.VITE_DEV_LOGIN_PASS ?? '') : '',
})
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}
const loading = ref(false)
const error = ref('')
const errorCategory = ref<LoginFailureCategory>('unknown')
const errorHint = ref('')

const remainingAttempts = ref<number | null>(null)
const retryAfterMinutes = ref<number | null>(null)

async function handleLogin() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  error.value = ''
  errorHint.value = ''
  errorCategory.value = 'unknown'
  remainingAttempts.value = null
  retryAfterMinutes.value = null
  try {
    await auth.login(form.username, form.password)
    router.push('/dashboard')
  } catch (e: unknown) {
    const info = parseLoginError(e)
    error.value = info.message
    errorCategory.value = info.category
    // Secondary hint: countdown info that the user actually needs.
    if (info.category === 'invalid_credentials' && info.remaining_attempts != null) {
      errorHint.value = `（还剩 ${info.remaining_attempts} 次尝试机会）`
      remainingAttempts.value = info.remaining_attempts
    } else if (info.category === 'account_locked' && info.retry_after_minutes != null) {
      errorHint.value = `（请在 ${info.retry_after_minutes} 分钟后重试）`
      retryAfterMinutes.value = info.retry_after_minutes
    } else if (info.category === 'account_disabled') {
      errorHint.value = '（请联系系统管理员重新启用账号）'
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
/* 登录容器 */
.login-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 20px;
}

/* 登录卡片（指南 §10.4：--card 底 + --border + 圆角 12 + --shadow-lg，旧霓虹发光已移除） */
.login-card {
  width: 100%;
  max-width: 400px;
  padding: 48px 40px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow-lg);
  position: relative;
  z-index: 1;
}

@media (prefers-reduced-motion: reduce) {
  .logo-icon {
    animation: none;
  }
}

/* Logo 区域 */
.logo-section {
  display: flex;
  justify-content: center;
  margin-bottom: 24px;
}

.logo-icon {
  color: var(--brand);
}

/* 品牌标题（渐变文字裁切，基调 A） */
.login-title {
  text-align: center;
  font-size: 32px;
  font-weight: 800;
  background: var(--grad-brand);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  margin: 0 0 8px;
  letter-spacing: 2px;
}

.login-subtitle {
  text-align: center;
  color: var(--text-2);
  margin: 0 0 40px;
  font-size: 14px;
  letter-spacing: 1px;
}

/* 表单样式覆盖 */
:deep(.el-form-item) {
  margin-bottom: 24px;
  align-items: center;
}

:deep(.el-form-item__label) {
  display: flex;
  align-items: center;
  height: 40px;
  line-height: 1.2;
  color: var(--text);
}

:deep(.el-form-item__error) {
  color: var(--error);
  font-size: 12px;
}

/* 输入框（指南 §10.3：--bg 底 + --border-2 + 品牌焦点环） */
:deep(.login-input .el-input__wrapper) {
  background-color: var(--bg);
  border: 1px solid var(--border-2);
  border-radius: 8px;
  box-shadow: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

:deep(.login-input .el-input__wrapper:hover) {
  border-color: var(--brand);
}

:deep(.login-input .el-input__wrapper.is-focus) {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--focus-ring);
}

:deep(.login-input .el-input__inner) {
  color: var(--text);
  font-size: 14px;
}

:deep(.login-input .el-input__inner::placeholder) {
  color: var(--text-3);
}

/* 主按钮（指南 §10.2：品牌渐变 + X 抬升悬停） */
:deep(.login-button) {
  width: 100%;
  height: 44px;
  background: var(--grad-brand);
  border: none;
  border-radius: 8px;
  color: var(--on-brand);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 2px;
  box-shadow: var(--shadow-sm);
  transition: box-shadow 0.12s ease, transform 0.12s ease;
}

:deep(.login-button:hover) {
  transform: translateY(-1px);
  box-shadow: var(--shadow-md);
}

:deep(.login-button:active) {
  transform: translateY(0);
}

:deep(.login-button.is-loading) {
  opacity: 0.8;
}

/* 加载动画 */
:deep(.login-button .el-icon.is-loading) {
  animation: rotating 2s linear infinite;
}

@keyframes rotating {
  0% {
    transform: rotate(0deg);
  }
  100% {
    transform: rotate(360deg);
  }
}

/* 错误提示 */
.error-msg {
  color: var(--error);
  text-align: center;
  margin-top: 16px;
  font-size: 13px;
  padding: 12px;
  background: color-mix(in srgb, var(--error) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--error) 30%, transparent);
  border-radius: 8px;
  line-height: 1.6;
}

@media (prefers-reduced-motion: no-preference) {
  .error-msg {
    animation: shake 0.5s ease;
  }
}

.error-hint {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  opacity: 0.85;
}
/* Network / timeout: amber, not red */
.error-msg--timeout,
.error-msg--network_error {
  color: var(--warn);
  background: color-mix(in srgb, var(--warn) 8%, transparent);
  border-color: color-mix(in srgb, var(--warn) 30%, transparent);
}
/* Disabled / locked */
.error-msg--account_disabled,
.error-msg--account_locked {
  color: var(--error-2);
  background: color-mix(in srgb, var(--error) 8%, transparent);
  border-color: color-mix(in srgb, var(--error) 40%, transparent);
}
/* Server error */
.error-msg--server_error {
  color: var(--warn);
  background: color-mix(in srgb, var(--warn) 8%, transparent);
  border-color: color-mix(in srgb, var(--warn) 30%, transparent);
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-10px); }
  75% { transform: translateX(10px); }
}

/* 淡入淡出过渡 */
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from, .fade-leave-to {
  opacity: 0;
}

/* 响应式设计 */
@media (max-width: 480px) {
  .login-card {
    padding: 32px 24px;
  }

  .login-title {
    font-size: 28px;
  }

  .logo-icon {
    font-size: 48px;
  }
}
</style>
