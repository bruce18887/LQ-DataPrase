<template>
  <el-card class="search-criteria" shadow="never">
    <template #header>
      <div class="sc-head">
        <div class="sc-head-title">
          <el-icon :size="18"><Search /></el-icon>
          <span>搜索条件</span>
        </div>
        <div class="sc-head-actions">
          <el-select
            v-model="presetId"
            data-testid="sftp-search-preset-select"
            class="sc-preset-select"
            placeholder="载入预设"
            size="small"
            clearable
            @change="onPresetPick"
          >
            <el-option v-for="p in presets" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <el-tooltip content="删除所选预设" placement="top">
            <el-button
              data-testid="sftp-search-preset-delete"
              class="sc-icon-btn"
              :icon="Delete"
              size="small"
              circle
              :disabled="presetId === null"
              aria-label="删除预设"
              @click="onDeletePreset"
            />
          </el-tooltip>
          <el-input
            v-model="presetName"
            data-testid="sftp-search-preset-name"
            class="sc-preset-name"
            placeholder="预设名"
            size="small"
            :maxlength="PRESET_NAME_MAX"
          />
          <el-button data-testid="sftp-search-preset-save" size="small" :disabled="!presetName.trim()" @click="onSavePreset">
            存为预设
          </el-button>
          <el-tooltip :content="canRun ? blockReason || '开始搜索' : '上一次搜索还在收尾，稍候即可'" placement="top">
            <el-button
              type="primary"
              data-testid="sftp-search-run"
              :icon="Search"
              :disabled="!runEnabled"
              @click="onRun"
            >搜索</el-button>
          </el-tooltip>
        </div>
      </div>
    </template>

    <el-form label-width="86px" label-position="left" @submit.prevent>
      <!-- ---------------- 范围 ---------------- -->
      <div class="sc-group-title">范围</div>
      <el-form-item label="搜索目录">
        <div class="sc-roots">
          <div class="sc-tags">
            <el-tag
              v-for="(r, i) in roots"
              :key="`${r}-${i}`"
              class="sc-tag"
              size="large"
              closable
              @close="removeRoot(i)"
            >{{ r }}</el-tag>
            <span v-if="!roots.length" class="sc-empty">还没有目录，回车或点「使用当前目录」</span>
          </div>
          <div class="sc-inline">
            <el-input
              v-model="rootDraft"
              data-testid="sftp-search-roots"
              :prefix-icon="FolderOpened"
              placeholder="绝对路径，回车添加（最多 20 条）"
              @keyup.enter="addRoot()"
              @blur="addRoot()"
            />
            <el-tooltip content="取面包屑当前所在的目录" placement="top">
              <el-button :icon="Aim" :disabled="!currentDirUsable" @click="useCurrentDir">使用当前目录</el-button>
            </el-tooltip>
          </div>
        </div>
      </el-form-item>

      <el-form-item label="递归深度">
        <div class="sc-inline">
          <el-radio-group v-model="depth" data-testid="sftp-search-depth">
            <el-radio value="self">仅当前层</el-radio>
            <el-radio value="children">含下一层</el-radio>
            <el-radio value="all">全部递归</el-radio>
            <el-radio value="custom">自定义</el-radio>
          </el-radio-group>
          <!-- 只有「自定义」才露数字框（spec §3.13 的四选一） -->
          <el-input
            v-if="depth === 'custom'"
            v-model="maxDepth"
            data-testid="sftp-search-max-depth"
            class="sc-num"
            type="number"
            :min="1"
            :max="HARD_MAX_DEPTH"
            placeholder="层数"
          />
        </div>
      </el-form-item>

      <el-form-item label="跳过目录">
        <div class="sc-roots">
          <div class="sc-tags">
            <el-tag
              v-for="(p, i) in pruneDirs"
              :key="`${p}-${i}`"
              class="sc-tag"
              type="info"
              size="large"
              closable
              @close="removePrune(i)"
            >{{ p }}</el-tag>
            <span v-if="!pruneDirs.length" class="sc-empty">不跳过任何目录</span>
          </div>
          <el-input
            v-model="pruneDraft"
            data-testid="sftp-search-prune"
            placeholder="fnmatch 目录名，如 *backup*、*_old（回车加一条）"
            @keyup.enter="addPrune()"
            @blur="addPrune()"
          />
        </div>
      </el-form-item>

      <!-- ---------------- 过滤 ---------------- -->
      <div class="sc-group-title">过滤</div>
      <el-form-item label="名称模式">
        <el-input
          v-model="namePattern"
          data-testid="sftp-search-pattern"
          placeholder="fnmatch，如 *RT*.csv（留空不限）"
          clearable
        />
      </el-form-item>
      <el-form-item label="修改时间">
        <div class="sc-inline">
          <!-- 时间值走 YYYY-MM-DDTHH:mm（后端 _DATE_FORMATS 认这一式，本地时间语义）。
               `data-testid` 只能挂在外层 span：EP 的 date-picker 把未识别属性并进 tooltip 后
               整个丢掉（渲染走查实测挂组件上 getByTestId 命中 0）。e2e 写法：
               `getByTestId('sftp-search-time-from').locator('input').fill('2026-09-01 00:00:00')`
               ——填的是**显示格式**，提交值才转成上面那个式；两个面板都常驻 DOM，断言要限定
               可见的那个，面板按钮文案是英文 Now/OK（EP 默认 locale）。 -->
          <span class="sc-date" data-testid="sftp-search-time-from">
            <el-date-picker
              v-model="timeFrom"
              id="sftp-search-time-from"
              type="datetime"
              placeholder="起"
              value-format="YYYY-MM-DDTHH:mm"
            />
          </span>
          <span class="sc-date" data-testid="sftp-search-time-to">
            <el-date-picker
              v-model="timeTo"
              id="sftp-search-time-to"
              type="datetime"
              placeholder="止"
              value-format="YYYY-MM-DDTHH:mm"
            />
          </span>
        </div>
      </el-form-item>
      <el-form-item label="文件类型">
        <el-checkbox v-model="dataFilesOnly">仅数据文件（排除 <code>Sum_*.csv</code> 汇总）</el-checkbox>
      </el-form-item>

      <!-- ---------------- 命中 ---------------- -->
      <div class="sc-group-title">命中</div>
      <el-form-item label="匹配模式">
        <el-radio-group v-model="mode" data-testid="sftp-search-mode">
          <el-radio value="name">文件名</el-radio>
          <el-radio value="content">内容含</el-radio>
          <el-radio value="column">列名</el-radio>
        </el-radio-group>
      </el-form-item>

      <el-form-item v-if="mode === 'content'" label="关键词">
        <el-input
          v-model="term"
          data-testid="sftp-search-term"
          :maxlength="MAX_TERM_LEN"
          show-word-limit
          clearable
          placeholder="要搜的测试项 / 文本"
        />
      </el-form-item>
      <el-form-item v-if="mode === 'column'" label="列名">
        <el-input
          v-model="columnName"
          data-testid="sftp-search-column"
          :maxlength="MAX_TERM_LEN"
          clearable
          placeholder="表头里的列名，如 ShadowReg2"
        />
      </el-form-item>

      <el-form-item v-if="mode !== 'name'" label="匹配方式">
        <div class="sc-inline sc-inline--wrap">
          <el-radio-group v-model="matching" data-testid="sftp-search-matching">
            <el-radio value="substring">子串</el-radio>
            <el-radio value="whole_word">整词</el-radio>
            <el-radio value="fuzzy">模糊</el-radio>
          </el-radio-group>
          <el-checkbox v-model="caseSensitive">区分大小写</el-checkbox>
        </div>
      </el-form-item>
      <div v-if="mode !== 'name'" class="sc-note">
        模糊匹配、以及含中文等非 ASCII 字符的关键词必然走客户端引擎：服务端 grep 给不出同一个
        结果集（会静默漏 GBK 文件）。整词不在其列 —— 关键词是纯 ASCII 时它照样能走服务端加速。
      </div>

      <!-- one_per_folder 放命中区显眼位置，不藏进「高级」（spec §3.13） -->
      <div class="sc-flag">
        <el-switch v-model="onePerFolder" data-testid="sftp-search-one-per-folder" />
        <div class="sc-flag-text">
          <strong>每目录只取一个</strong>
          <span>全递归时这才是「哪些文件夹里有这个测试项」的开关：勾上后每个目录最多贡献一个命中，扫描量除以每目录文件数。</span>
        </div>
      </div>

      <!-- ---------------- 高级（默认收起） ---------------- -->
      <el-collapse class="sc-adv">
        <el-collapse-item title="高级：并发、超时与各上限（留空即用后端默认值）" name="advanced">
          <el-form-item label="并发数">
            <el-input v-model="workers" data-testid="sftp-search-workers" class="sc-num" type="number" :min="1" :max="8" placeholder="默认 4，上限 8" />
          </el-form-item>
          <el-form-item label="超时(秒)">
            <el-input v-model="timeout" data-testid="sftp-search-timeout" class="sc-num" type="number" :min="30" :max="3600" placeholder="默认 600，30–3600" />
          </el-form-item>
          <el-form-item label="服务端加速">
            <div class="sc-inline">
              <el-switch v-model="allowServerGrep" data-testid="sftp-search-server-grep" />
              <span class="sc-inline-hint">允许服务器上有 grep 时用它加速（结果不等价的查询会自动回落客户端）</span>
            </div>
          </el-form-item>
          <el-form-item label="仅列候选">
            <div class="sc-inline">
              <el-switch v-model="stopAfterListing" data-testid="sftp-search-stop-after-listing" />
              <span class="sc-inline-hint">只列目录不下内容，用来先看范围对不对</span>
            </div>
          </el-form-item>
          <el-form-item label="条目上限">
            <el-input v-model="maxEntries" data-testid="sftp-search-max-entries" class="sc-num" type="number" :min="1" placeholder="默认 200000" />
          </el-form-item>
          <el-form-item label="候选上限">
            <el-input v-model="maxCandidates" data-testid="sftp-search-max-candidates" class="sc-num" type="number" :min="1" placeholder="默认 5000" />
          </el-form-item>
          <el-form-item label="命中上限">
            <el-input v-model="maxMatches" data-testid="sftp-search-max-matches" class="sc-num" type="number" :min="1" placeholder="默认 2000" />
          </el-form-item>
          <el-form-item v-if="mode === 'content'" label="每文件命中">
            <div class="sc-inline">
              <el-checkbox v-model="firstHitPerFile">只取第一条</el-checkbox>
              <el-input v-model="matchesPerFile" data-testid="sftp-search-matches-per-file" class="sc-num" type="number" :min="1" :max="20" placeholder="默认 1，上限 20" :disabled="firstHitPerFile" />
            </div>
          </el-form-item>
          <el-form-item v-if="mode === 'column'" label="取值行数">
            <el-input v-model="columnRows" data-testid="sftp-search-column-rows" class="sc-num" type="number" :min="1" :max="50" placeholder="默认 10，上限 50" />
          </el-form-item>
        </el-collapse-item>
      </el-collapse>

      <div v-if="blockReason" class="sc-block">{{ blockReason }}</div>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
/**
 * 搜索条件表单（计划 Task 15 Step 2 / spec §3.13）：范围 → 过滤 → 命中 → 高级，四段同序。
 *
 * 状态归属：表单值**不住在这里**，`modelValue` 由页面持有，每次改动 emit 一份新对象回去
 * （不原地改 props、也不另存副本，否则「预设回填」与「用户改动」互相看不见）；预设的增删查
 * 同样只 emit，HTTP 在页面侧；`canRun` 是页面把 store 的 `canStart` 传下来的。
 *
 * 数值字段一律 `el-input[type=number]` 而非 `el-input-number`：后者的 fallthrough 属性落在
 * 组件根 div，`data-testid` 挂上去后 e2e 的 `fill()` 会打在非编辑元素上；而 `el-input` 是
 * `inheritAttrs:false` + 把属性绑进内层 `<input>`（先例 `ColumnHeaderFilter.vue:57` 配
 * `file-list-sort-filter.spec.ts:157`）。唯一例外 `el-date-picker` 见模板里那段注释。
 *
 * 钳位由后端 `apps/sftp/search/contracts.py` 负责（超界夹住并出一条 `notice`，钳位码只告知、
 * 不进 `limits_hit`）；下面的 MAX_*
 * 只是抄同名常量用于「输入时就拦住」，留空的数值字段一律发 `null` = 用后端默认值。
 *
 * e2e 契约钩子（Task 18 按名定位，勿改，均带 `sftp-search-` 前缀）：roots / depth / prune /
 * pattern / time-from / time-to / mode / term / matching / one-per-folder / workers /
 * timeout / run / preset-select / preset-save。本组件另附计划未要求的：-preset-name /
 * -preset-delete / -column / -max-depth / -server-grep / -stop-after-listing /
 * -max-{entries,candidates,matches} / -matches-per-file / -column-rows。
 */
import { computed, ref } from 'vue'
import { Aim, Delete, FolderOpened, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { SearchDepth, SearchMatching, SearchMode, SearchPresetItem, SearchSpec } from '../../../api/sftpSearch'

/** 与 `contracts.py` 同名常量同源（前端拿不到 Python，抄的是「拦住输入」这一层） */
const MAX_ROOTS = 20
const HARD_MAX_DEPTH = 64
const MAX_TERM_LEN = 200
const PRESET_NAME_MAX = 80

const props = withDefaults(defineProps<{
  modelValue: SearchSpec
  /** 面包屑当前路径：给「使用当前目录」用；空串（未连接/未加载）即禁用该按钮 */
  currentPath?: string
  presets?: SearchPresetItem[]
  /** 页面把 store 的 `canStart`（并发 + 取消冷却）传下来，判据只在 store 说一次 */
  canRun?: boolean
}>(), {
  currentPath: '',
  presets: () => [],
  canRun: true,
})

const emit = defineEmits<{
  'update:modelValue': [SearchSpec]
  run: []
  'save-preset': [string]
  'delete-preset': [number]
}>()

function patch(part: Record<string, unknown>): void {
  emit('update:modelValue', { ...props.modelValue, ...part } as SearchSpec)
}

// ------------------------------------------------------------------ 字段绑定

const roots = computed(() => props.modelValue.roots ?? [])
const pruneDirs = computed(() => props.modelValue.prune_dirs ?? [])
const mode = computed<SearchMode>({
  get: () => props.modelValue.mode ?? 'name',
  set: v => patch({ mode: v }),
})
const depth = computed<SearchDepth>({
  get: () => props.modelValue.depth ?? 'all',
  set: v => patch({ depth: v }),
})
const matching = computed<SearchMatching>({
  get: () => props.modelValue.matching ?? 'substring',
  set: v => patch({ matching: v }),
})
const namePattern = computed<string>({
  get: () => props.modelValue.name_pattern ?? '',
  set: v => patch({ name_pattern: v }),
})
const term = computed<string>({
  get: () => props.modelValue.term ?? '',
  set: v => patch({ term: v }),
})
const columnName = computed<string>({
  get: () => props.modelValue.column_name ?? '',
  set: v => patch({ column_name: v }),
})
const timeFrom = computed<string | null>({
  get: () => props.modelValue.modified_after ?? null,
  set: v => patch({ modified_after: v }),
})
const timeTo = computed<string | null>({
  get: () => props.modelValue.modified_before ?? null,
  set: v => patch({ modified_before: v }),
})
const dataFilesOnly = computed<boolean>({
  get: () => props.modelValue.data_files_only ?? true,
  set: v => patch({ data_files_only: v }),
})
const caseSensitive = computed<boolean>({
  get: () => props.modelValue.case_sensitive ?? false,
  set: v => patch({ case_sensitive: v }),
})
const onePerFolder = computed<boolean>({
  get: () => props.modelValue.one_per_folder ?? false,
  set: v => patch({ one_per_folder: v }),
})
const firstHitPerFile = computed<boolean>({
  get: () => props.modelValue.first_hit_per_file ?? true,
  set: v => patch({ first_hit_per_file: v }),
})
const allowServerGrep = computed<boolean>({
  get: () => props.modelValue.allow_server_grep ?? true,
  set: v => patch({ allow_server_grep: v }),
})
const stopAfterListing = computed<boolean>({
  get: () => props.modelValue.stop_after_listing ?? false,
  set: v => patch({ stop_after_listing: v }),
})

/** 数值输入统一走字符串：空 = 发 `null`（后端 `_get` 把 null 当「用契约默认值」） */
type NumKey = 'max_depth' | 'column_rows' | 'matches_per_file' | 'workers' | 'timeout'
  | 'max_entries' | 'max_candidates' | 'max_matches'

function num(key: NumKey) {
  return computed<string>({
    get: () => {
      const raw = props.modelValue[key]
      return raw === undefined || raw === null ? '' : String(raw)
    },
    set: raw => {
      const text = String(raw ?? '').trim()
      const parsed = Number(text)
      patch({ [key]: text !== '' && Number.isFinite(parsed) ? parsed : null })
    },
  })
}
const maxDepth = num('max_depth')
const workers = num('workers')
const timeout = num('timeout')
const maxEntries = num('max_entries')
const maxCandidates = num('max_candidates')
const maxMatches = num('max_matches')
const matchesPerFile = num('matches_per_file')
const columnRows = num('column_rows')

// ------------------------------------------------------------------ 标签式输入

const rootDraft = ref('')
const pruneDraft = ref('')

/** 去重追加；`cap` 只对 roots 有意义（`MAX_ROOTS` 与后端同名常量），prune_dirs 后端不设限 */
function withTag(list: string[], text: string, cap = Infinity): string[] | null {
  const value = text.trim()
  if (!value || list.includes(value)) return null
  if (list.length >= cap) {
    ElMessage.warning(`搜索目录最多 ${cap} 条，多余的已忽略`)
    return null
  }
  return [...list, value]
}

function addRoot(): void {
  const next = withTag(roots.value, rootDraft.value, MAX_ROOTS)
  rootDraft.value = ''
  if (next) patch({ roots: next })
}
function removeRoot(index: number): void {
  patch({ roots: roots.value.filter((_, i) => i !== index) })
}
function addPrune(): void {
  const next = withTag(pruneDirs.value, pruneDraft.value)
  pruneDraft.value = ''
  if (next) patch({ prune_dirs: next })
}
function removePrune(index: number): void {
  patch({ prune_dirs: pruneDirs.value.filter((_, i) => i !== index) })
}

const currentDirUsable = computed(() => {
  const path = props.currentPath.trim()
  return path !== '' && !roots.value.includes(path)
})
function useCurrentDir(): void {
  const path = props.currentPath.trim()
  rootDraft.value = ''
  if (path) patch({ roots: [...roots.value, path] })
}

// ------------------------------------------------------------------ 校验与提交

/** 草稿也算数：填了路径没回车时按钮就该可点（回车/失焦/点搜索三条路都会收录它） */
const pendingRootList = computed(() => {
  const draft = rootDraft.value.trim()
  return draft && !roots.value.includes(draft) ? [...roots.value, draft] : roots.value
})
const blockReason = computed(() => {
  if (!pendingRootList.value.length) return '请至少添加一个搜索目录'
  if (pendingRootList.value.length > MAX_ROOTS) return `搜索目录最多 ${MAX_ROOTS} 条`
  // 后端对非绝对路径含 `..` 段直接 400（`contracts._normalise_roots`），先在前端拦住
  if (pendingRootList.value.some(r => !r.startsWith('/') || r.split('/').includes('..'))) {
    return '搜索目录必须是绝对路径，且不能含 .. 段'
  }
  if (mode.value === 'content' && !term.value.trim()) return '内容搜索需要填写关键词'
  if (mode.value === 'column' && !columnName.value.trim()) return '列匹配需要填写列名'
  return ''
})
const runEnabled = computed(() => props.canRun && blockReason.value === '')

function onRun(): void {
  // 先把没回车/没失焦的草稿并进这一份 spec 再判定：同一拍里 `props.modelValue` 还是旧的
  // （父组件的 ref 已更新，但要等下一次渲染才回流到 props），只读 props 会漏掉刚写的那条。
  const spec: SearchSpec = {
    ...props.modelValue,
    roots: pendingRootList.value,
    prune_dirs: withTag(pruneDirs.value, pruneDraft.value) ?? pruneDirs.value,
  }
  if (blockReason.value || !props.canRun) return
  rootDraft.value = ''
  pruneDraft.value = ''
  emit('update:modelValue', spec)
  emit('run')
}

// ------------------------------------------------------------------ 预设

const presetId = ref<number | null>(null)
const presetName = ref('')

function onPresetPick(id: number | null): void {
  const hit = props.presets.find(p => p.id === id)
  if (!hit) return
  rootDraft.value = ''
  pruneDraft.value = ''
  // 整体替换而不是 merge：预设里没写的字段就该回到默认，留着上一次的改动是第三种真相
  emit('update:modelValue', { ...hit.spec })
}
function onSavePreset(): void {
  const name = presetName.value.trim()
  if (!name) return
  addRoot()
  addPrune()
  presetName.value = ''
  emit('save-preset', name)
}
function onDeletePreset(): void {
  if (presetId.value === null) return
  emit('delete-preset', presetId.value)
  presetId.value = null
}
</script>

<style scoped>
.search-criteria { border-radius: var(--p-radius-md); border-left: 4px solid var(--brand); }
.search-criteria :deep(.el-card__body) { padding: var(--p-space-3) var(--p-space-5) var(--p-space-2); }

.sc-head { display: flex; align-items: center; justify-content: space-between; gap: var(--p-space-3); flex-wrap: wrap; }
.sc-head-title { display: flex; align-items: center; gap: var(--p-space-2); font-weight: var(--p-fw-semibold); font-size: var(--p-fs-base); color: var(--text); }
.sc-head-actions { display: flex; align-items: center; gap: var(--p-space-2); flex-wrap: wrap; }
.sc-preset-select { width: 140px; }
.sc-preset-name { width: 130px; }
.sc-icon-btn { color: var(--text-2); border-color: var(--border-2); }
.sc-icon-btn:hover { color: var(--error); border-color: var(--error); }

.sc-group-title {
  margin: var(--p-space-2) 0 var(--p-space-3);
  padding-bottom: var(--p-space-1);
  border-bottom: 1px solid var(--border);
  font-size: var(--p-fs-small);
  font-weight: var(--p-fw-semibold);
  color: var(--brand);
}

.sc-roots { display: flex; flex-direction: column; gap: var(--p-space-2); width: 100%; }
.sc-tags { display: flex; align-items: center; gap: var(--p-space-1); flex-wrap: wrap; min-height: 28px; }
.sc-tag { max-width: 100%; }
.sc-tag :deep(.el-tag__content) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sc-empty { font-size: var(--p-fs-micro); color: var(--text-3); }
.sc-inline { display: flex; align-items: center; gap: var(--p-space-2); flex-wrap: wrap; width: 100%; }
.sc-inline--wrap { align-items: center; }
.sc-inline-hint { font-size: var(--p-fs-micro); color: var(--text-2); }
.sc-num { width: 180px; }
.sc-date { display: inline-flex; }
.sc-date :deep(.el-date-editor) { width: 190px; }

.sc-note {
  margin: 0 0 var(--p-space-3) 86px;
  font-size: var(--p-fs-micro);
  color: var(--text-2);
}

/* 「每目录只取一个」显眼花在命中区：品牌左边框 + 说明文字 */
.sc-flag {
  display: flex;
  align-items: flex-start;
  gap: var(--p-space-3);
  margin: var(--p-space-2) 0 var(--p-space-3) 86px;
  padding: var(--p-space-3);
  border: 1px solid var(--border-2);
  border-left: 3px solid var(--brand);
  border-radius: var(--p-radius-sm);
  background: var(--bg-2);
}
.sc-flag-text { display: flex; flex-direction: column; gap: 2px; }
.sc-flag-text strong { font-size: var(--p-fs-small); color: var(--text); }
.sc-flag-text span { font-size: var(--p-fs-micro); color: var(--text-2); line-height: var(--leading-normal); }

.sc-adv { margin-top: var(--p-space-2); border-top: 1px solid var(--border); }
.sc-adv :deep(.el-collapse-item__header) { font-size: var(--p-fs-small); color: var(--text-2); }
.sc-adv :deep(.el-collapse-item__wrap) { border-top: none; }
.sc-adv :deep(.el-form-item) { margin-bottom: var(--p-space-2); }

.sc-block { margin-left: 86px; font-size: var(--p-fs-micro); color: var(--error); }
code { font-family: var(--font-mono); font-size: var(--p-fs-micro); }
</style>
