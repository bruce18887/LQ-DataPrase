<template>
  <el-form :model="settings" label-width="160px">
    <el-form-item label="CPK A 级阈值">
      <el-input-number
        v-model="settings.cpk_a_threshold"
        :min="1" :max="3" :step="0.01" :precision="2"
        aria-describedby="cpk-a-hint"
        @change="onCpkAChanged"
      />
      <span id="cpk-a-hint" class="threshold-hint">≥ {{ settings.cpk_a_threshold }} 为 A 级（优）</span>
    </el-form-item>

    <el-form-item label="CPK B 级阈值">
      <el-input-number
        v-model="settings.cpk_b_threshold"
        :min="0.5" :max="settings.cpk_a_threshold - 0.01"
        :step="0.01" :precision="2"
        aria-describedby="cpk-b-hint"
        @change="onCpkBChanged"
      />
      <span id="cpk-b-hint" class="threshold-hint">≥ {{ settings.cpk_b_threshold }} 且 &lt; {{ settings.cpk_a_threshold }} 为 B 级</span>
    </el-form-item>

    <el-form-item label="CPK C 级阈值">
      <el-input-number
        v-model="settings.cpk_c_threshold"
        :min="0" :max="settings.cpk_b_threshold - 0.01"
        :step="0.01" :precision="2"
        aria-describedby="cpk-c-hint"
      />
      <span id="cpk-c-hint" class="threshold-hint">≥ {{ settings.cpk_c_threshold }} 且 &lt; {{ settings.cpk_b_threshold }} 为 C 级</span>
    </el-form-item>
  </el-form>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import type { SettingsData } from '../../../types'

const props = defineProps<{ settings: SettingsData }>()

function onCpkAChanged() {
  if (props.settings.cpk_b_threshold >= props.settings.cpk_a_threshold) {
    props.settings.cpk_b_threshold = parseFloat((props.settings.cpk_a_threshold - 0.34).toFixed(2))
    ElMessage.warning('CPK B 已自动调整为低于 CPK A')
  }
  if (props.settings.cpk_c_threshold >= props.settings.cpk_b_threshold) {
    props.settings.cpk_c_threshold = parseFloat((props.settings.cpk_b_threshold - 0.33).toFixed(2))
    ElMessage.warning('CPK C 已自动调整为低于 CPK B')
  }
}

function onCpkBChanged() {
  if (props.settings.cpk_b_threshold >= props.settings.cpk_a_threshold) {
    props.settings.cpk_b_threshold = parseFloat((props.settings.cpk_a_threshold - 0.01).toFixed(2))
    ElMessage.warning('CPK B 不能高于 CPK A，已自动调整')
  }
  if (props.settings.cpk_c_threshold >= props.settings.cpk_b_threshold) {
    props.settings.cpk_c_threshold = parseFloat((props.settings.cpk_b_threshold - 0.01).toFixed(2))
    ElMessage.warning('CPK C 已自动调整为低于 CPK B')
  }
  if (props.settings.cpk_c_threshold < 0) {
    props.settings.cpk_c_threshold = 0
  }
}
</script>

<style scoped>
.threshold-hint {
  margin-left: 12px;
  font-size: 13px;
  color: var(--text-secondary);
}
</style>
