/**
 * 大列表下拉（`el-select-v2`）的选项准备：过滤 → 排序 → 映射。
 *
 * 为什么必须有这份文件：`el-select-v2` 的 `filter-method` 在 2.14.0 里**退化成纯回调**
 * （`useSelect.mjs:114-132` 判到 filterMethod 合法后让 `isValidOption` 恒 true ⇒
 * `filteredOptions` = 全量 `props.options`），组件自己不过滤。所以过滤必须由调用方算好
 * 塞进 `:options`。而 `:options` 的元素必须是对象（`useProps.mjs:25-28` 走
 * `lodash.get(option,'label'|'value')`），喂 `string[]` 是静默空白行。
 *
 * 高亮片段**不在这里算**：它由组件在 v2 的 `#default` 逐条渲染器里按需调用
 * `highlightSegments`（虚拟窗口每帧只渲染约 8 行）。若在准备 options 时就给每一项建
 * segments，等于把性能批 d1146dd 治掉的「1,702 项每次击键建 1,702 份」原样放回来
 * —— `test/unit/selectOptions.spec.ts` 里那条反向探针就是拦这个的。
 */

export interface SelectOption {
  value: string | number
  label: string
}

export interface ParamSegment {
  text: string
  mark: boolean
}

/** 映射成 `el-select-v2` 要求的 `{value,label}` 形状 */
export function toOptions(items: Array<string | number>): SelectOption[] {
  return items.map((value) => ({ value, label: String(value) }))
}

/** 大小写不敏感子串匹配（关键词与条目都在函数内归一化）；空关键词返回原集合 */
export function filterByKeyword(items: string[], keyword: string): string[] {
  const q = keyword.trim().toLowerCase()
  if (!q) return items
  return items.filter((it) => it.toLowerCase().includes(q))
}

/** 前缀匹配优先，其余按 localeCompare。关键词在函数内归一化；返回新数组，不改入参。 */
export function sortPrefixFirst(items: string[], keyword: string): string[] {
  const q = keyword.trim().toLowerCase()
  return [...items].sort((a, b) => {
    const aStarts = a.toLowerCase().startsWith(q)
    const bStarts = b.toLowerCase().startsWith(q)
    if (aStarts && !bStarts) return -1
    if (!aStarts && bStarts) return 1
    return a.localeCompare(b)
  })
}

/**
 * 高亮分段：返回 {text, mark} 片段列表。
 *
 * 不走 v-html：参数名来自上传文件的列头（用户可控输入），旧实现对 text 未转义，
 * 列名含 `<img src=x onerror=...>` 即成存储型 XSS，普通 `<`/`&` 也会被当标签/实体
 * 吞掉导致下拉显示错乱。大小写不敏感子串匹配与旧 `gi` 正则高亮等价，
 * 且无正则元字符转义问题。（本段说明从 ParamSelector.vue:145-149 原样搬来，
 * 搬动原因是 Serial/TestColumn/Export 三处也需要同一条判据的注释锚点。）
 */
export function highlightSegments(text: string, query: string): ParamSegment[] {
  if (!query) return [{ text, mark: false }]
  const lower = text.toLowerCase()
  const q = query.toLowerCase()
  const segments: ParamSegment[] = []
  let i = 0
  while (i < text.length) {
    const idx = lower.indexOf(q, i)
    if (idx === -1) {
      segments.push({ text: text.slice(i), mark: false })
      break
    }
    if (idx > i) segments.push({ text: text.slice(i, idx), mark: false })
    segments.push({ text: text.slice(idx, idx + q.length), mark: true })
    i = idx + q.length
  }
  return segments
}

/**
 * 参数下拉的完整视图：`options` 交给 `:options`，`total` 交给 footer 计数。
 *
 * 顺序是「过滤 → 排序 → 映射」，**没有截断步骤**（截断是旧 DROPDOWN_RENDER_CAP 的做法，
 * 本批删除）。排序必须留在映射之前：`el-select-v2` 按数组顺序渲染，映射后再排要重建对象。
 */
export function buildParamOptions(
  params: string[],
  query: string,
): { options: SelectOption[]; total: number } {
  const kw = query.trim().toLowerCase()
  const matched = filterByKeyword(params, kw)
  const ordered = kw ? sortPrefixFirst(matched, kw) : matched
  return { options: toOptions(ordered), total: matched.length }
}
