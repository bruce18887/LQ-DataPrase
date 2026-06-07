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
        <h1 class="login-title">DataPhrase</h1>
        <p class="login-subtitle">ATE 数据分析平台</p>

        <!-- 登录表单 -->
        <el-form ref="formRef" :model="form" :rules="rules" @submit.prevent="handleLogin">
          <el-form-item prop="username">
            <el-input
              v-model="form.username"
              placeholder="用户名"
              size="large"
              autocomplete="username"
              class="neon-input"
            />
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="密码"
              size="large"
              autocomplete="current-password"
              show-password
              class="neon-input"
            />
          </el-form-item>
          <el-form-item>
            <el-button
              type="primary"
              size="large"
              :loading="loading"
              native-type="submit"
              class="neon-button"
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
import { computed, ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../../stores/auth'
import { TrendCharts } from '@element-plus/icons-vue'
import GridBackground from '../../components/common/GridBackground.vue'
import { parseLoginError, type LoginFailureCategory } from '../../api/auth'
import type { FormInstance } from 'element-plus'

const router = useRouter()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const form = reactive({ username: 'admin', password: 'admin123' })
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

const errorIcon = computed(() => {
  // Exposed for future <el-icon> usage; kept as a mapping so the
  // template can stay data-driven when the design wants an icon.
  switch (errorCategory.value) {
    case 'timeout':
    case 'network_error':
      return 'Connection'
    case 'account_disabled':
      return 'Lock'
    case 'account_locked':
      return 'Timer'
    case 'user_not_found':
    case 'invalid_credentials':
      return 'WarningFilled'
    case 'server_error':
      return 'CircleClose'
    default:
      return 'WarningFilled'
  }
})

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

/* 登录卡片 - 霓虹边框效果 */
.login-card {
  width: 100%;
  max-width: 400px;
  padding: 48px 40px;
  background: var(--bg-secondary);
  border: 1px solid var(--brand-primary);
  border-radius: 16px;
  box-shadow:
    0 0 20px rgba(37, 99, 235, 0.2),
    0 0 40px rgba(37, 99, 235, 0.1),
    inset 0 0 60px rgba(37, 99, 235, 0.03);
  position: relative;
  z-index: 1;
  animation: cardGlow 3s ease-in-out infinite;
}

@keyframes cardGlow {
  0%, 100% {
    box-shadow:
      0 0 20px rgba(37, 99, 235, 0.2),
      0 0 40px rgba(37, 99, 235, 0.1),
      inset 0 0 60px rgba(37, 99, 235, 0.03);
  }
  50% {
    box-shadow:
      0 0 30px rgba(37, 99, 235, 0.3),
      0 0 60px rgba(37, 99, 235, 0.15),
      inset 0 0 80px rgba(37, 99, 235, 0.05);
  }
}

@media (prefers-reduced-motion: reduce) {
  .login-card {
    animation: none;
  }
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
  color: var(--brand-primary);
  filter: drop-shadow(0 0 10px rgba(37, 99, 235, 0.4));
  animation: logoFloat 3s ease-in-out infinite;
}

@keyframes logoFloat {
  0%, 100% {
    transform: translateY(0px);
  }
  50% {
    transform: translateY(-10px);
  }
}

/* 品牌标题 */
.login-title {
  text-align: center;
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px;
  letter-spacing: 2px;
  text-shadow: 0 0 20px rgba(37, 99, 235, 0.3);
}

.login-subtitle {
  text-align: center;
  color: var(--text-secondary);
  margin: 0 0 40px;
  font-size: 14px;
  letter-spacing: 1px;
}

/* 表单样式覆盖 */
:deep(.el-form-item) {
  margin-bottom: 24px;
}

:deep(.el-form-item__error) {
  color: #ff6b6b;
  font-size: 12px;
}

/* 霓虹输入框 */
:deep(.neon-input .el-input__wrapper) {
  background-color: var(--bg-primary);
  border: 1px solid var(--border-default);
  box-shadow: none;
  transition: background-color 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
}

:deep(.neon-input .el-input__wrapper:hover) {
  border-color: var(--brand-primary);
}

:deep(.neon-input .el-input__wrapper.is-focus) {
  border-color: var(--brand-primary);
  box-shadow:
    0 0 10px rgba(37, 99, 235, 0.2),
    0 0 20px rgba(37, 99, 235, 0.1),
    inset 0 0 10px rgba(37, 99, 235, 0.05);
}

:deep(.neon-input .el-input__inner) {
  color: var(--text-primary);
  font-size: 14px;
}

:deep(.neon-input .el-input__inner::placeholder) {
  color: var(--text-tertiary);
}

/* 霓虹按钮 */
:deep(.neon-button) {
  width: 100%;
  height: 48px;
  background: var(--brand-primary);
  border: 1px solid var(--brand-primary);
  border-radius: 8px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 2px;
  box-shadow: 0 0 20px rgba(37, 99, 235, 0.2);
  transition: background-color 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
}

:deep(.neon-button:hover) {
  transform: translateY(-2px);
  box-shadow:
    0 0 30px rgba(37, 99, 235, 0.3),
    0 4px 20px rgba(37, 99, 235, 0.2);
  background: var(--brand-primary-hover);
}

:deep(.neon-button:active) {
  transform: translateY(0);
}

:deep(.neon-button.is-loading) {
  background: var(--brand-primary);
  opacity: 0.8;
}

/* 加载动画 */
:deep(.neon-button .el-icon.is-loading) {
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
  color: #ff6b6b;
  text-align: center;
  margin-top: 16px;
  font-size: 13px;
  padding: 12px;
  background: rgba(255, 107, 107, 0.1);
  border: 1px solid rgba(255, 107, 107, 0.3);
  border-radius: 8px;
  animation: shake 0.5s ease;
  line-height: 1.6;
}
.error-hint {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  opacity: 0.85;
}
/* Network / timeout: amber, not red — "your fault" vs "server's fault" */
.error-msg--timeout,
.error-msg--network_error {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.08);
  border-color: rgba(245, 158, 11, 0.3);
}
/* Disabled / locked: keep red, more emphatic */
.error-msg--account_disabled,
.error-msg--account_locked {
  color: #ef4444;
  background: rgba(239, 68, 68, 0.08);
  border-color: rgba(239, 68, 68, 0.4);
}
/* Server error: muted grey-red, do not look like a user action issue */
.error-msg--server_error {
  color: #d97706;
  background: rgba(217, 119, 6, 0.08);
  border-color: rgba(217, 119, 6, 0.3);
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
