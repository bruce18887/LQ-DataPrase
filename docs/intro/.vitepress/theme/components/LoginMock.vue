<script setup lang="ts">
import { ref } from 'vue'
import MockFrame from './MockFrame.vue'
import { toast } from '../useUi'
const user = ref('')
const pass = ref('')
const msg = ref('演示：任意非空账号密码可「登录」；空密码会演示限流计数文案。')
const ok = ref<boolean | null>(null)
function go() {
  if (!user.value.trim() || !pass.value) {
    ok.value = false
    msg.value = 'reason=bad_password，remaining_attempts=4（演示限流计数）'
    toast('登录失败：审计将留痕 reason=bad_password', 'warn')
  } else {
    ok.value = true
    msg.value = '欢迎，' + user.value.trim() + '（演示）'
    toast('登录成功（演示）· 真实应用顶栏显示账号与角色')
  }
}
</script>

<template>
  <MockFrame title="登录页">
    <div style="max-width:420px;margin:0 auto">
      <div class="setrow"><span class="sl"><b>账号</b></span><input v-model="user" class="m-input" placeholder="管理员创建的账号" style="flex:1"></div>
      <div class="setrow"><span class="sl"><b>密码</b></span><input v-model="pass" type="password" class="m-input" placeholder="••••••••" style="flex:1"></div>
      <div class="m-toolbar" style="margin:12px 0 0"><button class="m-btn pri" style="flex:1;justify-content:center" @click="go">登 录</button></div>
      <div class="m-foot">
        <span v-if="ok === true" class="tag ok">登录成功</span>
        <span v-else-if="ok === false" class="tag err">登录失败</span>
        <span>{{ msg }}</span>
      </div>
    </div>
  </MockFrame>
</template>