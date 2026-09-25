import { computed } from 'vue'
import type { SearchDepth, SearchMatching, SearchMode, SearchSpec } from '../../../api/sftpSearch'

/**
 * 搜索条件表单的**字段绑定层**（从 `SearchCriteria.vue` 拆出，为满足项目 600 行上限，
 * 也为了让「表单值 ↔ spec」这件事只有一处实现）。
 *
 * 规则只有一条：**值不住在这里**。每个字段的 getter 读 `props.modelValue`、setter 发一份
 * 合并后的新 spec 给 `patch` —— 所以父组件持有的那份 `SearchSpec` 永远是唯一真相，
 * 「预设整体回填」与「用户逐字段改动」才能互相看见（各自存一份副本就会打架）。
 *
 * 数值字段统一走字符串：`el-input[type=number]` 的空串 `v-model` 会写成 `''`，而契约要的是
 * `null`（= 用后端默认值）。留空发 `null`、非数发 `null`，钳位仍由后端 `contracts.parse_spec`
 * 负责（超界夹住并出一条 notice）。
 *
 * 下面的上限常量与 `apps/sftp/search/contracts.py` 同名值同源（前端拿不到 Python，抄的只是
 * 「拦住输入」这一层）。后端加键或改上限时，这里要一起改 —— 键名对齐由
 * `tasks/_sftp_search_keycheck.py` 双向核对。
 */
export const MAX_ROOTS = 20
export const HARD_MAX_DEPTH = 64
export const MAX_TERM_LEN = 200
export const PRESET_NAME_MAX = 80

type NumKey = 'max_depth' | 'column_rows' | 'matches_per_file' | 'workers' | 'timeout'
  | 'max_entries' | 'max_candidates' | 'max_matches'

type PatchFn = (part: Record<string, unknown>) => void

export function useSearchSpecFields(getSpec: () => SearchSpec, patch: PatchFn) {
  const text = (key: 'name_pattern' | 'term' | 'column_name') =>
    computed<string>({
      get: () => getSpec()[key] ?? '',
      set: v => patch({ [key]: v }),
    })

  const flag = (key: 'data_files_only' | 'case_sensitive' | 'one_per_folder'
    | 'first_hit_per_file' | 'allow_server_grep' | 'stop_after_listing', fallback: boolean) =>
    computed<boolean>({
      get: () => getSpec()[key] ?? fallback,
      set: v => patch({ [key]: v }),
    })

  /** 数值框：空串与非数都归一成 `null`（后端把 null 读成「用契约默认值」） */
  const num = (key: NumKey) => computed<string>({
    get: () => {
      const raw = getSpec()[key]
      return raw === undefined || raw === null ? '' : String(raw)
    },
    set: raw => {
      const value = String(raw ?? '').trim()
      const parsed = Number(value)
      patch({ [key]: value !== '' && Number.isFinite(parsed) ? parsed : null })
    },
  })

  return {
    roots: computed(() => getSpec().roots ?? []),
    pruneDirs: computed(() => getSpec().prune_dirs ?? []),
    mode: computed<SearchMode>({
      get: () => getSpec().mode ?? 'name',
      set: v => patch({ mode: v }),
    }),
    depth: computed<SearchDepth>({
      get: () => getSpec().depth ?? 'all',
      set: v => patch({ depth: v }),
    }),
    matching: computed<SearchMatching>({
      get: () => getSpec().matching ?? 'substring',
      set: v => patch({ matching: v }),
    }),
    namePattern: text('name_pattern'),
    term: text('term'),
    columnName: text('column_name'),
    timeFrom: computed<string | null>({
      get: () => getSpec().modified_after ?? null,
      set: v => patch({ modified_after: v }),
    }),
    timeTo: computed<string | null>({
      get: () => getSpec().modified_before ?? null,
      set: v => patch({ modified_before: v }),
    }),
    dataFilesOnly: flag('data_files_only', true),
    caseSensitive: flag('case_sensitive', false),
    onePerFolder: flag('one_per_folder', false),
    firstHitPerFile: flag('first_hit_per_file', true),
    allowServerGrep: flag('allow_server_grep', true),
    stopAfterListing: flag('stop_after_listing', false),
    maxDepth: num('max_depth'),
    workers: num('workers'),
    timeout: num('timeout'),
    maxEntries: num('max_entries'),
    maxCandidates: num('max_candidates'),
    maxMatches: num('max_matches'),
    matchesPerFile: num('matches_per_file'),
    columnRows: num('column_rows'),
  }
}
