<template>
  <!-- 整行是个按钮：收起态下点开它 = 展开条件。做成按钮而不是「随便哪都能点」，
       是为了键盘能 Tab 到、且屏幕阅读器念得出「这是一次展开操作」。 -->
  <button
    type="button"
    class="scs"
    :aria-expanded="false"
    aria-label="展开搜索条件"
    data-testid="sftp-search-criteria-summary"
    @click="emit('expand')"
  >
    <span v-for="c in chips" :key="c.k" class="scs-chip" :class="`scs-chip--${c.k}`" :title="c.v">
      <em v-if="c.t">{{ c.t }}</em>{{ c.v }}
    </span>
  </button>
</template>

<script setup lang="ts">
/**
 * 搜索条件的**收起态摘要**（2026-09-25 版式重做）。渲染在条件卡卡头那一行的中间空带上，
 * 位置由父组件决定，本组件只负责「一行讲清这次搜的是什么」。
 *
 * 存在的理由只有一条：条件卡收起后不能变成「看不见条件」——那等于把用户刚设的东西
 * 藏进一个按钮背后。所以这一行要能独立回答「这次搜的是哪儿、搜什么、按哪档」，
 * 用户不必展开就能判断要不要展开。
 *
 * 只写不猜：这里读的全是 `spec`（页面持有的那份真值），组件本身无状态、无请求。
 * 空值一律不上行（宁缺毋滥），高级区只列**用户显式改过**的那几项 —— 留空的字段
 * 用的是后端默认值，写出来就是在谎报。
 */
import { computed } from 'vue'
import type { SearchSpec } from '../../../api/sftpSearch'

const props = defineProps<{ spec: SearchSpec }>()
const emit = defineEmits<{ expand: [] }>()

const DEPTH_LABEL: Record<string, string> = {
  self: '仅当前层', children: '含下一层', all: '全部递归', custom: '自定义',
}
const MODE_LABEL: Record<string, string> = { name: '文件名', content: '内容含', column: '列名' }
const MATCHING_LABEL: Record<string, string> = { substring: '子串', whole_word: '整词', fuzzy: '模糊' }

/** 高级区各字段的上行标签（值非空才显示） */
const ADV_LABEL: [keyof SearchSpec, string][] = [
  ['workers', '并发'], ['timeout', '超时'], ['max_entries', '条目上限'],
  ['max_candidates', '候选上限'], ['max_matches', '命中上限'],
  ['matches_per_file', '每文件命中'], ['column_rows', '取值行数'],
]

interface Chip { k: string; t?: string; v: string }

const chips = computed<Chip[]>(() => {
  const s = props.spec
  const out: Chip[] = []

  const roots = s.roots ?? []
  if (roots.length) {
    out.push({
      k: 'roots',
      t: roots.length > 1 ? `${roots.length} 个目录 ` : '目录 ',
      v: roots.join('、'),
    })
  }
  const depth = s.depth ?? 'all'
  out.push({
    k: 'depth',
    v: depth === 'custom' ? `自定义 ${s.max_depth ?? '?'} 层` : DEPTH_LABEL[depth],
  })
  if ((s.prune_dirs ?? []).length) out.push({ k: 'prune', v: `跳过 ${s.prune_dirs!.length} 项` })
  if (s.name_pattern) out.push({ k: 'plain', t: '名称 ', v: s.name_pattern })
  if (s.modified_after || s.modified_before) {
    out.push({ k: 'plain', t: '时间 ', v: `${s.modified_after ?? '—'} ~ ${s.modified_before ?? '—'}` })
  }
  if (s.data_files_only === false) out.push({ k: 'plain', v: '含 Sum 汇总文件' })

  const mode = s.mode ?? 'name'
  const term = mode === 'content' ? s.term : mode === 'column' ? s.column_name : ''
  out.push({ k: 'mode', t: `${MODE_LABEL[mode]} `, v: term || '（未填）' })
  if (mode === 'content') {
    out.push({ k: 'plain', v: `${MATCHING_LABEL[s.matching ?? 'substring']}${s.case_sensitive ? ' · 区分大小写' : ''}` })
  }
  if (s.one_per_folder) out.push({ k: 'plain', v: '每目录只取一个' })
  if (mode === 'content' && s.first_hit_per_file === false) out.push({ k: 'plain', v: '每文件多条命中' })
  if (mode === 'content' && s.allow_server_grep === false) out.push({ k: 'plain', v: '不用服务端 grep' })
  if (s.stop_after_listing) out.push({ k: 'plain', v: '仅列候选' })
  for (const [key, label] of ADV_LABEL) {
    const raw = s[key]
    if (raw !== null && raw !== undefined) out.push({ k: 'plain', t: `${label} `, v: String(raw) })
  }
  return out
})
</script>

<style scoped>
.scs {
  display: flex; align-items: center; gap: var(--p-space-2);
  width: 100%; min-width: 0; padding: var(--p-space-1) 0;
  border: 0; background: none; color: inherit; font: inherit; text-align: left;
  cursor: pointer;
}

.scs-chip {
  display: inline-flex; align-items: center; max-width: 34%;
  padding: 2px var(--p-space-2);
  border: 1px solid var(--border-2); border-radius: var(--p-radius-sm);
  background: var(--bg-2);
  font-size: var(--p-fs-micro); color: var(--text-2);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.scs-chip em { margin-right: 4px; font-style: normal; color: var(--text-3); }
/* 目录与匹配档是「一眼要看到的那两件」：实色边框区分，不靠颜色深浅
   （tint 到不了 3:1，状态得靠边框承载 —— 见 token 对比度实测口径） */
.scs-chip--roots { border-color: var(--brand); color: var(--text); max-width: 46%; }
.scs-chip--mode { border-color: var(--brand); background: var(--bg-3); color: var(--text); }
</style>
