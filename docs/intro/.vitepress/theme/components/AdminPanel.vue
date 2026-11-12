<script setup lang="ts">
import { ref } from 'vue'
import UsersMock from './UsersMock.vue'
import AuditMock from './AuditMock.vue'
const extra = ref<{ t: string; ev: string; op: string; tg: string; ip: string; d: string }[]>([])
function onAudit(ev: string, op: string, tg: string, d: string) {
  extra.value.unshift({ t: '2026-11-12 ' + new Date().toTimeString().slice(0, 8), ev, op, tg, ip: '127.0.0.1', d })
}
</script>

<template>
  <UsersMock @audit="onAudit" />
  <AuditMock :extra="extra" />
</template>