/**
 * 大列表下拉（`el-select-v2`）的选项准备：过滤 → 排序 → 映射。
 *
 * 四个下拉真正共享的是 `toOptions`（`:options` 必须是对象数组）；`filterByKeyword` /
 * `sortPrefixFirst` 拆成独立导出是为了能单测，目前唯一消费者是 `buildParamOptions`，
 * 改它们不会同时影响四个下拉。
 *
 * 为什么必须有这份文件：`el-select-v2` 的 `filter-method` 在 2.14.0 里**退化成纯回调**
 * （`select-v2/src/useSelect.mjs:114-132` 判到 filterMethod 合法后让 `isValidOption` 恒 true ⇒
 * `filteredOptions` = 全量 `props.options`），组件自己不过滤。所以过滤必须由调用方算好
 * 塞进 `:options`。而 `:options` 的元素必须是对象（`select-v2/src/useProps.mjs:25-28` 走
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

export interface HighlightSegment {
  text: string
  mark: boolean
}

/** 映射成 `el-select-v2` 要求的 `{value,label}` 形状 */
export function toOptions(items: Array<string | number>): SelectOption[] {
  return items.map((value) => ({ value, label: String(value) }))
}

/**
 * 大小写不敏感子串匹配（关键词与条目都在函数内归一化）。
 *
 * 入参收 `string | number`：序列号下拉（`SerialSelector`）的候选是 `number[]`，而
 * `toOptions` 本来就收数字 —— 这三个函数口径必须一致，否则第二个消费者就得本地重写一份。
 *
 * 空关键词返回**入参本身**（同一引用、零拷贝）—— 与 `sortPrefixFirst` 相反，后者总是
 * 返回新数组：`Array.prototype.sort` 原地改，不拷贝就会把调用方传进来的 `props.params` 排坏。
 * 这个不对称是有意的，两条判据分别用 `toBe` / `not.toBe` 钉住，别"顺手统一"。
 */
export function filterByKeyword(
  items: Array<string | number>,
  keyword: string,
): Array<string | number> {
  const q = keyword.trim().toLowerCase()
  if (!q) return items
  return items.filter((it) => String(it).toLowerCase().includes(q))
}

/** 前缀匹配优先，其余按 localeCompare。关键词在函数内归一化；返回新数组，不改入参。 */
export function sortPrefixFirst(
  items: Array<string | number>,
  keyword: string,
): Array<string | number> {
  const q = keyword.trim().toLowerCase()
  return [...items].sort((a, b) => {
    const aStarts = String(a).toLowerCase().startsWith(q)
    const bStarts = String(b).toLowerCase().startsWith(q)
    if (aStarts && !bStarts) return -1
    if (!aStarts && bStarts) return 1
    return String(a).localeCompare(String(b))
  })
}

/**
 * 把 `text` 按关键词切成 {text, mark} 片段列表，供消费方逐段渲染。
 *
 * **消费方必须把 `text` 当文本节点渲染（`{{ }}` 插值），禁止 `v-html`**：参数名来自上传
 * 文件的列头（用户可控输入），旧实现对 text 未转义，列名含 `<img src=x onerror=...>` 即成
 * 存储型 XSS。本函数只保证返回的文本无损，**拦不住**消费方用 v-html —— 判据是
 * `test/unit/selectOptions.spec.ts` 里那条 XSS 反向探针 + 源码侧的 template 审查。
 *
 * 大小写不敏感子串匹配，与旧 `gi` 正则高亮等价且无正则元字符转义问题。
 * 锚点：修复本体见 ParamSelector 的 highlightSegments 历史实现与提交 d1146dd。
 */
export function highlightSegments(text: string, query: string): HighlightSegment[] {
  const q = query.trim().toLowerCase()
  if (!q) return [{ text, mark: false }]
  if (!text) return [{ text, mark: false }]
  const lower = text.toLowerCase()
  const segments: HighlightSegment[] = []
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
  // 归一化只做一次（判「有没有关键词」用），两个 callee 各自还会再归一化一遍 ——
  // 它们必须能独立被单测，不能假定调用方已经洗过。
  const kw = query.trim().toLowerCase()
  const matched = filterByKeyword(params, query)
  // 无关键词时**不排序**：那一支返回 filterByKeyword 的原引用，列表顺序 = 文件列顺序。
  // 去掉这个三元，用户没搜任何东西也会看到一次整体重排（localeCompare 结果）。
  const ordered = kw ? sortPrefixFirst(matched, query) : matched
  return { options: toOptions(ordered), total: matched.length }
}
