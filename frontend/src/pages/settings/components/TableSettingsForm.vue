<template>
  <el-form :model="settings" label-width="160px">
    <el-form-item label="文件名自动换行">
      <el-switch
        v-model="settings.filename_wrap"
        :data-testid="'filename-wrap-switch'"
      />
      <div class="form-hint">
        开启时文件名（文件列表与批次数据列表）自动换行显示完整名称，最多 3 行；关闭时单行截断（hover 查看全名）。
      </div>
    </el-form-item>

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

    <el-form-item label="默认隐藏列">
      <div class="hidden-cols">
        <div class="hidden-cols-hint">
          勾选的记录级列在「查看数据」表格与导出 Excel 中默认隐藏（导出仍保留列数据，可
          取消隐藏；ag-grid 可通过表头列菜单重新显示）。按 ATE 平台与属性归类，点击
          属性名可整组勾选/取消。仅对文件中实际存在的列生效。
        </div>
        <div class="hidden-cols-checkboxes">
          <div
            v-for="platform in platforms"
            :key="platform.name"
            class="platform-section"
            :data-platform="platform.name"
          >
            <div class="platform-title">{{ platform.name }}</div>
            <div v-for="group in platform.groups" :key="group.property" class="property-row">
              <el-checkbox
                :model-value="groupAllChecked(group.cols)"
                :indeterminate="groupSomeChecked(group.cols)"
                @change="toggleGroup(group.cols, $event)"
              >
                {{ group.property }}
              </el-checkbox>
              <div class="property-cols">
                <el-checkbox
                  v-for="col in group.cols"
                  :key="col"
                  :model-value="isChecked(col)"
                  @change="toggleOne(col, $event)"
                >
                  {{ col }}
                </el-checkbox>
              </div>
            </div>
          </div>
        </div>
      </div>
    </el-form-item>
  </el-form>
</template>

<script setup lang="ts">
import type { SettingsData } from '../../../types'
import { HIDDEN_COLUMNS_BY_PLATFORM } from '../../../constants/hidden-columns'

const props = defineProps<{ settings: SettingsData }>()

const platforms = HIDDEN_COLUMNS_BY_PLATFORM

function isChecked(col: string): boolean {
  return props.settings.default_hidden_columns.includes(col)
}

function groupAllChecked(cols: string[]): boolean {
  return cols.length > 0 && cols.every((c) => isChecked(c))
}

function groupSomeChecked(cols: string[]): boolean {
  return cols.some((c) => isChecked(c)) && !groupAllChecked(cols)
}

function toggleOne(col: string, checked: boolean) {
  const arr = [...props.settings.default_hidden_columns]
  if (checked) {
    if (!arr.includes(col)) arr.push(col)
  } else {
    const i = arr.indexOf(col)
    if (i !== -1) arr.splice(i, 1)
  }
  props.settings.default_hidden_columns = arr
}

/** 属性复选框：整组勾选/取消（解决「逐列勾选太麻烦」） */
function toggleGroup(cols: string[], checked: boolean) {
  for (const col of cols) {
    const arr = [...props.settings.default_hidden_columns]
    if (checked) {
      if (!arr.includes(col)) arr.push(col)
    } else {
      const i = arr.indexOf(col)
      if (i !== -1) arr.splice(i, 1)
    }
    props.settings.default_hidden_columns = arr
  }
}
</script>

<style scoped>
.hidden-cols {
  width: 100%;
}

.form-hint {
  margin-left: 10px;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.6;
}

.hidden-cols-hint {
  font-size: 12px;
  color: var(--text-2);
  margin-bottom: 8px;
  line-height: 1.6;
}

.hidden-cols-checkboxes {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.platform-section {
  border: 1px solid var(--border-2);
  border-radius: 8px;
  overflow: hidden;
  background: var(--bg);
}

.platform-title {
  padding: 6px 12px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  background: var(--bg-3);
  border-bottom: 1px solid var(--border-2);
}

.property-row {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 5px 12px;
  border-bottom: 1px solid var(--border);
}

.property-row:last-child {
  border-bottom: none;
}

.property-row :deep(.el-checkbox) {
  margin-right: 0;
}

.property-cols {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
}
</style>
