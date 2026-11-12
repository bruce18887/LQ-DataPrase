<script setup lang="ts">
import { ref, computed } from 'vue'
import MockFrame from './MockFrame.vue'
import { UM_SEED } from '../data'
import { toast, dialog } from '../useUi'
const users = ref(UM_SEED.map(u => ({ ...u })))
const q = ref('')
const emit = defineEmits<{ audit: [ev: string, op: string, tg: string, d: string] }>()
const vis = computed(() => users.value.filter(u => !q.value || (u.u + u.disp).toLowerCase().includes(q.value.toLowerCase())))
const kpi = computed(() => [users.value.length, users.value.filter(u => u.active).length, users.value.filter(u => u.locked).length, users.value.filter(u => u.role === 'administrator').length])
function audit(ev: string, tg: string, d: string) { emit('audit', ev, 'admin', tg, d) }
function edit(u: typeof users.value[number]) {
  dialog('编辑账号 · ' + u.u, `<p>显示名与角色在真实应用对话框中修改；此处演示直接切换角色。</p>`, [
    { label: '取消' },
    { label: '切换角色', cls: 'pri', fn: () => { u.role = u.role === 'user' ? 'administrator' : 'user'; audit('更新账号', u.u, 'role=' + u.role); toast('账号已更新（演示）') } },
  ])
}
function toggle(u: typeof users.value[number]) {
  u.active = !u.active
  audit('更新账号', u.u, 'active=' + u.active)
  toast(u.u + (u.active ? ' 已启用' : ' 已禁用'), u.active ? '' : 'warn')
}
function unlock(u: typeof users.value[number]) {
  u.locked = false; u.active = true
  audit('账号解锁', u.u, '限流计数清零')
  toast(u.u + ' 已解锁（演示）')
}
function del(u: typeof users.value[number]) {
  dialog('删除账号', `<p>删除 <b>${u.u}</b>？真实应用中不可逆。</p>`, [
    { label: '取消' },
    { label: '删除', cls: 'danger', fn: () => {
      const i = users.value.indexOf(u)
      users.value.splice(i, 1)
      audit('删除账号', u.u, '—')
      toast('已删除 ' + u.u, 'warn', { label: '撤销', fn: () => users.value.splice(i, 0, u) })
    } },
  ])
}
function create() {
  dialog('创建账号', '<p>用户名 / 显示名 / 角色三项；此处演示创建一个合成账号。</p>', [
    { label: '取消' },
    { label: '创建', cls: 'pri', fn: () => {
      const u = 'demo_wang'
      users.value.push({ u, disp: '王五', role: 'user', active: true, locked: false, cr: '2026-11-12 11:02', last: '—', self: false })
      audit('创建账号', u, 'role=user')
      toast('账号已创建（演示）')
    } },
  ])
}
</script>

<template>
  <MockFrame title="用户管理">
    <div class="m-strip">
      <div class="sc"><div class="v">{{ kpi[0] }}</div><div class="l">总用户</div></div>
      <div class="sc"><div class="v">{{ kpi[1] }}</div><div class="l">活跃</div></div>
      <div class="sc"><div class="v">{{ kpi[2] }}</div><div class="l">锁定</div></div>
      <div class="sc"><div class="v">{{ kpi[3] }}</div><div class="l">管理员</div></div>
    </div>
    <div class="m-toolbar">
      <input v-model="q" class="m-input" placeholder="搜索用户名 / 显示名" style="width:200px">
      <span class="grow"></span>
      <button class="m-btn pri" @click="create">创建账号</button>
    </div>
    <div class="m-table-wrap">
      <table class="m-table">
        <thead><tr><th>用户名</th><th>显示名</th><th>角色</th><th>状态</th><th>创建时间</th><th>最后登录</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="u in vis" :key="u.u">
            <td><b>{{ u.u }}</b> <span v-if="u.self" class="tag info">当前</span></td>
            <td>{{ u.disp }}</td>
            <td><span class="tag" :class="u.role === 'administrator' ? 'warn' : 'mut'">{{ u.role === 'administrator' ? '管理员' : '用户' }}</span></td>
            <td><span v-if="u.locked" class="tag err">锁定</span><span v-else-if="u.active" class="tag ok">active</span><span v-else class="tag mut">禁用</span></td>
            <td class="num">{{ u.cr }}</td><td class="num">{{ u.last }}</td>
            <td style="white-space:nowrap">
              <button class="m-btn" style="padding:2px 8px" :disabled="u.self" :title="u.self ? '不能操作自己' : ''" @click="edit(u)">编辑</button>
              <button class="m-btn" style="padding:2px 8px" :disabled="u.self" @click="toggle(u)">{{ u.active ? '禁用' : '启用' }}</button>
              <button class="m-btn" style="padding:2px 8px" :disabled="u.self" @click="audit('管理员重置密码', u.u, '—'); toast('已生成重置密码流程（演示）· 审计留痕')">重置密码</button>
              <button v-if="u.locked" class="m-btn" style="padding:2px 8px" :disabled="u.self" @click="unlock(u)">解锁</button>
              <button class="m-btn danger" style="padding:2px 8px" :disabled="u.self" @click="del(u)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="m-foot">角色仅 user / administrator；不能对自己执行禁用 / 删除等操作（admin 行操作列置灰）。操作会写入下方审计复刻。</div>
  </MockFrame>
</template>