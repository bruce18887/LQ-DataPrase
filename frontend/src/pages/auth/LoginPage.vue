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
              class="neon-input"
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
  background: var(--bg-2);
  border: 1px solid var(--brand);
  border-radius: 16px;
  box-shadow:
    0 0 20px color-mix(in srgb, var(--brand) 20%, transparent),
    0 0 40px color-mix(in srgb, var(--brand) 10%, transparent),
    inset 0 0 60px color-mix(in srgb, var(--brand) 3%, transparent);
  position: relative;
  z-index: 1;
}

@media (prefers-reduced-motion: no-preference) {
  .login-card {
    animation: cardGlow 3s ease-in-out infinite;
  }
}

@keyframes cardGlow {
  0%, 100% {
    box-shadow:
      0 0 20px color-mix(in srgb, var(--brand) 20%, transparent),
      0 0 40px color-mix(in srgb, var(--brand) 10%, transparent),
      inset 0 0 60px color-mix(in srgb, var(--brand) 3%, transparent);
  }
  50% {
    box-shadow:
      0 0 30px color-mix(in srgb, var(--brand) 30%, transparent),
      0 0 60px color-mix(in srgb, var(--brand) 15%, transparent),
      inset 0 0 80px color-mix(in srgb, var(--brand) 5%, transparent);
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
  color: var(--brand);
  filter: drop-shadow(0 0 10px color-mix(in srgb, var(--brand) 40%, transparent));
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
  color: var(--text);
  margin: 0 0 8px;
  letter-spacing: 2px;
  text-shadow: 0 0 20px color-mix(in srgb, var(--brand) 30%, transparent);
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

/* 霓虹输入框 */
:deep(.neon-input .el-input__wrapper) {
  background-color: var(--bg);
  border: 1px solid var(--border-2);
  box-shadow: none;
  transition: background-color 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
}

:deep(.neon-input .el-input__wrapper:hover) {
  border-color: var(--brand);
}

:deep(.neon-input .el-input__wrapper.is-focus) {
  border-color: var(--brand);
  box-shadow:
    0 0 10px color-mix(in srgb, var(--brand) 20%, transparent),
    0 0 20px color-mix(in srgb, var(--brand) 10%, transparent),
    inset 0 0 10px color-mix(in srgb, var(--brand) 5%, transparent);
}

:deep(.neon-input .el-input__inner) {
  color: var(--text);
  font-size: 14px;
}

:deep(.neon-input .el-input__inner::placeholder) {
  color: var(--text-3);
}

/* 霓虹按钮 */
:deep(.neon-button) {
  width: 100%;
  height: 48px;
  background: var(--brand);
  border: 1px solid var(--brand);
  border-radius: 8px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 2px;
  box-shadow: 0 0 20px color-mix(in srgb, var(--brand) 20%, transparent);
  transition: background-color 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
}

:deep(.neon-button:hover) {
  transform: translateY(-2px);
  box-shadow:
    0 0 30px color-mix(in srgb, var(--brand) 30%, transparent),
    0 4px 20px color-mix(in srgb, var(--brand) 20%, transparent);
  background: var(--brand-2);
}

:deep(.neon-button:active) {
  transform: translateY(0);
}

:deep(.neon-button.is-loading) {
  background: var(--brand);
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
