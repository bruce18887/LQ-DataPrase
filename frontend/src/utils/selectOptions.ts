/**
 * 大列表下拉（`el-select-v2`）的选项准备：过滤 → 排序 → 映射。
 *
 * 大列表下拉真正共享的是 `toOptions`（`:options` 必须是对象数组）；`filterByKeyword` /
 * `sortPrefixFirst` 拆成独立导出是为了能单测。
 * 消费者（2026-11-21 现数，`grep -rn "utils/selectOptions" frontend/src`）：
 * `toOptions` = CorrelationToolsTab（X/Y）+ DataBrowserToolbar（固定列）+ useSelectFilter 共 3 处；
 * `filterByKeyword` = useSelectFilter 1 处 + 本文件 `buildSelectView` 1 处（后者被 ParamSelector 消费）
 * ⇒ 改它经 `useSelectFilter` 牵到 TestColumn / Serial / Export、经 `buildSelectView` 牵到 ParamSelector，共 4 个下拉；
 * `sortPrefixFirst` 无外部直调（仅 `buildSelectView` 内用）；`buildSelectView` = ParamSelector 1 处；
 * `highlightSegments` = ParamSelector + FileSelect（刀五b）共 2 处。
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
 * 泛型 `T` 是为了**保住返回类型的元素类型**：`SerialSelector` 把返回值直接喂给 `clamp()`
 * 与 `emit('update:modelValue', …: number[])`，非泛型签名（返回 `Array<string | number>`）
 * 在那两处都要重新断言一次，等于把复用换成本地转型。判据在
 * `test/unit/selectOptions.spec.ts`（`const nums: number[] = filterByKeyword(…)` 那一行，
 * 由 `npm run build` 的 `vue-tsc -b` 检查，vitest 本身不看类型）。
 *
 * 空关键词返回**入参本身**（同一引用、零拷贝）—— 与 `sortPrefixFirst` 相反，后者总是
 * 返回新数组：`Array.prototype.sort` 原地改，不拷贝就会把调用方传进来的 `props.params` 排坏。
 * 这个不对称是有意的，两条判据分别用 `toBe` / `not.toBe` 钉住，别"顺手统一"。
 */
export function filterByKeyword<T extends string | number>(items: T[], keyword: string): T[] {
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
 * 顺序是「过滤 → 排序 → 映射」，**没有截断步骤**。历史上这里截断到 300 —— 那是**已经不存在
 * 于树里**的旧 `DROPDOWN_RENDER_CAP`（非虚拟化 `el-select` 时代防冻结用的，本批迁
 * `el-select-v2` 时连同定义一起删除，`constants/dropdown.ts` 整个文件已删），不是当下的约束：
 * 找回那个数等于把用户报的「只能看前 300 项」放回来。
 * 排序必须留在映射之前：`el-select-v2` 按数组顺序渲染，映射后再排要重建对象。
 */
export function buildSelectView(
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
