<template>
  <el-card :class="['search-criteria', { 'is-collapsed': collapsed }]" shadow="never">
    <template #header>
      <div class="sc-head">
        <div class="sc-head-title">
          <el-icon :size="18"><Search /></el-icon>
          <span>搜索条件</span>
        </div>
        <!-- 收起态的摘要**并进卡头这一行**：另起一行等于收起只省下表单的高度，
             那一行本身还在。标题左、动作右，中间这条空带正好放条件摘要。 -->
        <SearchCriteriaSummary
          v-if="collapsed"
          :spec="modelValue"
          class="sc-head-summary"
          data-testid="sftp-search-criteria-summary"
          @expand="collapsed = false"
        />
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
          <!-- 收起只压高度、不动条件值（表单 v-show 不卸载），摘要行替它说话 -->
          <el-button
            size="small"
            text
            bg
            :icon="collapsed ? ArrowDown : ArrowUp"
            data-testid="sftp-search-criteria-toggle"
            @click="collapsed = !collapsed"
          >{{ collapsed ? '展开条件' : '收起条件' }}</el-button>
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

    <el-form v-show="!collapsed" class="sc-form" label-width="86px" label-position="left" @submit.prevent>
      <!-- ---------------- 范围 ---------------- -->
      <div class="sc-group-title sc-span">范围</div>
      <!-- sc-span 的判据只有一条：这一格里装的是长绝对路径，压进一栏就会一直换行 -->
      <el-form-item class="sc-span" label="搜索目录">
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
          </div>
          <el-input
            v-model="rootDraft"
            class="sc-root-input"
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
          </div>
          <el-input
            v-model="pruneDraft"
            data-testid="sftp-search-prune"
            placeholder="fnmatch 目录名，如 *backup*（回车加一条）"
            @keyup.enter="addPrune()"
            @blur="addPrune()"
          />
        </div>
      </el-form-item>

      <!-- ---------------- 过滤 ---------------- -->
      <div class="sc-group-title sc-span">过滤</div>
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
      <div class="sc-group-title sc-span">命中</div>
      <el-form-item label="匹配模式">
        <el-radio-group v-model="mode" data-testid="sftp-search-mode">
          <el-radio value="name">文件名</el-radio>
          <el-radio value="content">内容含</el-radio>
          <el-radio value="column">列名</el-radio>
        </el-radio-group>
      </el-form-item>

      <!-- sc-cell：输入框和「这一档怎么匹配」的提示必须同格，提示是那个字段的说明，
           独立成跨行的一格会在网格里飘到别的字段底下去。 -->
      <div class="sc-cell">
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
            placeholder="精确列名，或 *BV*2* 这类通配"
          />
        </el-form-item>
        <p v-if="mode === 'content'" class="sc-note">{{ CONTENT_ENGINE_NOTE }}</p>
        <p v-if="mode === 'column'" class="sc-note" data-testid="sftp-search-column-note">
          {{ COLUMN_MATCH_NOTE }}
        </p>
      </div>

      <!-- 匹配方式/区分大小写只被 scan_file 消费：列名档走 match_headers（精确或 fnmatch），
           文件名档走 name_pattern 的 fnmatch，两者都不消费这两个值。 -->
      <el-form-item v-if="mode === 'content'" label="匹配方式">
        <div class="sc-inline sc-inline--wrap">
          <el-radio-group v-model="matching" data-testid="sftp-search-matching">
            <el-radio value="substring">子串</el-radio>
            <el-radio value="whole_word">整词</el-radio>
            <el-radio value="fuzzy">模糊</el-radio>
          </el-radio-group>
          <el-checkbox v-model="caseSensitive">区分大小写</el-checkbox>
        </div>
      </el-form-item>

      <!-- one_per_folder 放命中区显眼位置，不藏进「高级」（spec §3.13）；说明文字保留可见，
           收进 tooltip 就等于把「这一档改变的是命中集合」这件事藏起来。 -->
      <div class="sc-flag sc-span">
        <el-switch v-model="onePerFolder" data-testid="sftp-search-one-per-folder" />
        <strong>每目录只取一个</strong>
        <span>全递归时这才是「哪些文件夹里有这个测试项」的开关：每个目录最多贡献一个命中，扫描量除以每目录文件数。</span>
      </div>

      <!-- ---------------- 高级（默认收起） ---------------- -->
      <el-collapse class="sc-adv sc-span">
        <el-collapse-item title="高级：并发、超时与各上限（留空即用后端默认值）" name="advanced">
          <div class="sc-adv-grid">
          <el-form-item label="并发数">
            <el-input v-model="workers" data-testid="sftp-search-workers" class="sc-num" type="number" :min="1" :max="8" placeholder="默认 4，上限 8" />
          </el-form-item>
          <el-form-item label="超时(秒)">
            <el-input v-model="timeout" data-testid="sftp-search-timeout" class="sc-num" type="number" :min="30" :max="3600" placeholder="默认 600，30–3600" />
          </el-form-item>
          <!-- engine.select_engine 对 mode !== 'content' 恒返回 client，
               所以这个开关在「文件名」「列名」两档不改变任何结果，就不摆出来误导。 -->
          <el-form-item v-if="mode === 'content'" label="服务端加速">
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
          </div>
        </el-collapse-item>
      </el-collapse>

      <div v-if="blockReason" class="sc-block sc-span">{{ blockReason }}</div>
    </el-form>
  </el-card>
</template>

<script setup lang="ts">
/**
 * 搜索条件表单（计划 Task 15 Step 2 / spec §3.13）：范围 → 过滤 → 命中 → 高级，四段同序。
 *
 * **版式（2026-09-25 重做）**：`el-form` 本体是一张 CSS grid，栏数由可用宽度自己决定
 * （`auto-fill minmax(420px,1fr)`），跨整行只有一个判据「这一格装长绝对路径」。改版前是
 * 定宽单列，1440 与 1280 下高度一模一样（实测 805px > 一页预算 796px）。卡头可收起成一行
 * 摘要（`SearchCriteriaSummary`，渲染在卡头那条空带上，收起后整张卡 71px）。
 * 版式的承重断言在 `e2e/sftp/search-layout.spec.ts`，改样式前先读它的三条口径。
 *
 * 状态归属：表单值**不住在这里**，`modelValue` 由页面持有，每次改动 emit 一份新对象回去
 * （不原地改 props、也不另存副本，否则「预设回填」与「用户改动」互相看不见）；预设的增删查
 * 同样只 emit，HTTP 在页面侧；`canRun` 是页面把 store 的 `canStart` 传下来的。
 * 字段级的 getter/setter 在 `useSearchSpecFields.ts`（本文件的 600 行上限装不下两份）。
 *
 * 数值字段一律 `el-input[type=number]` 而非 `el-input-number`：后者的 fallthrough 属性落在
 * 组件根 div，`data-testid` 挂上去后 e2e 的 `fill()` 会打在非编辑元素上；而 `el-input` 是
 * `inheritAttrs:false` + 把属性绑进内层 `<input>`（先例 `ColumnHeaderFilter.vue:57` 配
 * `file-list-sort-filter.spec.ts:157`）。唯一例外 `el-date-picker` 见模板里那段注释。
 *
 * 钳位由后端 `apps/sftp/search/contracts.py` 负责（超界夹住并出一条 `notice`，钳位码只告知、
 * 不进 `limits_hit`）；`MAX_*` / `HARD_MAX_DEPTH` 只是抄同名常量用于「输入时就拦住」，
 * 留空的数值字段一律发 `null` = 用后端默认值。
 *
 * e2e 契约钩子（Task 18 按名定位，勿改，均带 `sftp-search-` 前缀）：roots / depth / prune /
 * pattern / time-from / time-to / mode / term / matching / one-per-folder / workers /
 * timeout / run / preset-select / preset-save。本组件另附计划未要求的：-preset-name /
 * -preset-delete / -column / -max-depth / -server-grep / -stop-after-listing /
 * -max-{entries,candidates,matches} / -matches-per-file / -column-rows /
 * -criteria-toggle / -criteria-summary（后两个挂在摘要子组件的根元素上）。
 */
import { computed, ref } from 'vue'
import { Aim, ArrowDown, ArrowUp, Delete, FolderOpened, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { SearchPresetItem, SearchSpec } from '../../../api/sftpSearch'
import { COLUMN_MATCH_NOTE, CONTENT_ENGINE_NOTE } from './searchHints'
import SearchCriteriaSummary from './SearchCriteriaSummary.vue'
// 字段绑定层与那几个「与 contracts.py 同名」的上限常量一起住在 composable 里：
// 本组件的 600 行上限装不下两份，而「表单值 ↔ spec」这件事也只该有一处实现。
import {
  HARD_MAX_DEPTH, MAX_ROOTS, MAX_TERM_LEN, PRESET_NAME_MAX, useSearchSpecFields,
} from './useSearchSpecFields'

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

/**
 * 收起态：表单 `v-show` 掉而不是卸载 —— 条件值本来就住在页面持有的 `spec` 上，
 * 但目录/跳过目录的**草稿**（还没回车的输入）住在这里，卸载会把它们擦掉。
 * 只在组件实例活着的时候成立，刷新即回到展开（与搜索结果的驻留口径一致）。
 */
const collapsed = ref(false)

function patch(part: Record<string, unknown>): void {
  emit('update:modelValue', { ...props.modelValue, ...part } as SearchSpec)
}

// ------------------------------------------------------------------ 字段绑定
// getter 读 props.modelValue、setter 发一份合并后的新 spec —— 真相只有页面那一份，
// 所以「预设整体回填」和「用户逐字段改」才看得见彼此（值在这里再存一份副本就会打架）。
const {
  roots, pruneDirs, mode, depth, matching, namePattern, term, columnName, timeFrom, timeTo,
  dataFilesOnly, caseSensitive, onePerFolder, firstHitPerFile, allowServerGrep,
  stopAfterListing, maxDepth, workers, timeout, maxEntries, maxCandidates, maxMatches,
  matchesPerFile, columnRows,
} = useSearchSpecFields(() => props.modelValue, patch)

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
/* 收起态整张卡只剩卡头那一行：摘要已经并进卡头，卡体没有内容了，
   但 el-card 的 body 还在 —— 不关掉它，收起就白收（它还占那份内边距）。
   表单本身是 v-show 掉的（草稿在组件里，卸载会擦掉），这里关的是容器。 */
.search-criteria.is-collapsed :deep(.el-card__body) { display: none; }

.sc-head { display: flex; align-items: center; justify-content: space-between; gap: var(--p-space-3); flex-wrap: wrap; }
.sc-head-title { display: flex; align-items: center; gap: var(--p-space-2); font-weight: var(--p-fw-semibold); font-size: var(--p-fs-base); color: var(--text); }
/* 摘要吃卡头中间那条空带；`min-width:0` 才允许它被压短（否则 chips 会把卡头顶宽） */
.sc-head-summary { flex: 1 1 200px; min-width: 0; }
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

/* 表单是一张网格：栏数由可用宽度自己决定（420px 是「一个字段 + 86px 标签」还呼吸得下的
   下限），所以 1440 两栏、超宽屏三栏、窄窗自动回一栏，不需要按视口写断点 —— 视口断点会
   把侧边栏宽度算错，而侧边栏可折叠。跨整行只有一个判据：这一格装长绝对路径。 */
.sc-form {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 0 var(--p-space-6);
  align-items: start;
}
/* EP 默认 18px 行距是给「一行一字段」的长表单留呼吸；网格里行与行已经同宽并排，
   段落感由三节标题与分隔线承担，18px 就纯浪费高度（8 行 × 6px = 48px）。 */
.sc-form :deep(.el-form-item) { margin-bottom: var(--p-space-3); }
.sc-span { grid-column: 1 / -1; }
/* 420px 下限在超宽屏会铺出 5 栏以上，条件表单铺那么宽只会读成一条横线 */
@media (min-width: 2200px) {
  .sc-form { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

/* 一个输入框 + 属于它的那句提示，占网格里的一个格 */
.sc-cell { display: flex; flex-direction: column; min-width: 0; }

.sc-roots { display: flex; align-items: center; gap: var(--p-space-2); flex-wrap: wrap; width: 100%; }
.sc-root-input { flex: 1 1 260px; min-width: 180px; }
.sc-tags { display: flex; align-items: center; gap: var(--p-space-1); flex-wrap: wrap; min-width: 0; }
.sc-tag { max-width: 100%; }
.sc-tag :deep(.el-tag__content) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sc-inline { display: flex; align-items: center; gap: var(--p-space-2); flex-wrap: wrap; width: 100%; }
.sc-inline--wrap { align-items: center; }
.sc-inline-hint { font-size: var(--p-fs-micro); color: var(--text-2); }
.sc-num { width: 180px; }
.sc-date { display: inline-flex; }
.sc-date :deep(.el-date-editor) { width: 190px; }

.sc-note {
  margin: 0 0 var(--p-space-2) 86px;
  font-size: var(--p-fs-micro);
  line-height: var(--leading-normal);
  color: var(--text-2);
}

/* 「每目录只取一个」显花在命中区：品牌左边框 + 一句话说明。
   86px 缩进是让开关与上面的输入框左对齐（它跨整行，不缩进会顶到标签列外面）。 */
.sc-flag {
  display: flex;
  align-items: center;
  gap: var(--p-space-3);
  margin: var(--p-space-1) 0 var(--p-space-3) 86px;
  padding-left: var(--p-space-3);
  border-left: 3px solid var(--brand);
}
.sc-flag strong { flex: none; font-size: var(--p-fs-small); color: var(--text); }
.sc-flag > span { font-size: var(--p-fs-micro); color: var(--text-2); line-height: var(--leading-normal); }

.sc-adv { margin-top: var(--p-space-2); border-top: 1px solid var(--border); }
.sc-adv :deep(.el-collapse-item__header) { font-size: var(--p-fs-small); color: var(--text-2); }
.sc-adv :deep(.el-collapse-item__wrap) { border-top: none; }
.sc-adv :deep(.el-form-item) { margin-bottom: var(--p-space-2); }
/* 高级区全是 180px 的数字框，横着排才不浪费折叠体那点宽度 */
.sc-adv-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 0 var(--p-space-5); }

.sc-block { margin-left: 86px; font-size: var(--p-fs-micro); color: var(--error); }
code { font-family: var(--font-mono); font-size: var(--p-fs-micro); }
</style>
