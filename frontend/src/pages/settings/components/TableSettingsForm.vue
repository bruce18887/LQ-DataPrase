<template>
  <el-form :model="settings" label-width="160px">
    <el-form-item label="默认每页行数">
      <el-select v-model="settings.page_size">
        <el-option :value="50" label="50" />
        <el-option :value="100" label="100" />
        <el-option :value="200" label="200" />
        <el-option :value="500" label="500" />
      </el-select>
    </el-form-item>

    <el-form-item label="表格高度">
      <el-select v-model="settings.table_height">
        <el-option :value="500" label="500" />
        <el-option :value="600" label="600" />
        <el-option :value="700" label="700" />
        <el-option :value="800" label="800" />
        <el-option :value="900" label="900" />
        <el-option :value="1000" label="1000" />
      </el-select>
    </el-form-item>

    <el-form-item label="表头字号">
      <el-slider
        v-model="settings.aggrid_header_font_size"
        :min="8"
        :max="18"
        :step="1"
        show-input
      />
    </el-form-item>
  </el-form>
</template>

<script setup lang="ts">
import type { SettingsData } from '../../../types'

defineProps<{ settings: SettingsData }>()
</script>
