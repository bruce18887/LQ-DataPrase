/**
 * `pickBoundedKeyword` 的**纯核**（无 Playwright、无 DOM，T2 可直接驱动）。
 *
 * 为什么要把判定抽出来：与 `paramListCore.ts` 同一条理由 —— 这是「造不出关键词就 throw」的
 * 带边界启发式，判定错了在浏览器里表现为「导出作业选了上千个参数」或「整条用例红在
 * throw 上」，而归因要点开 e2e 才知道；抽成纯函数后 `test/unit/boundedKeyword.spec.ts`
 * 用假名字表就能钉住三条界（扫描窗口 / 下界 2 / 上限 cap）。
 *
 * 语义（与接线侧同源，一次实现两处用）：前缀越短匹配越多（**单调不增**），所以从短往长试，
 * 第一个落进 `[2, cap]` 的前缀就是答案；匹配数已经 < 2 时后面只会更少，直接换下一个名字。
 * 参数名一律来自**响应**而不是 DOM —— 迁 `el-select-v2` 之后 DOM 里只有虚拟窗口那约 11 行，
 * 「数选项条数」与「按位置点第 i 行」都不再是合法判据形状（2026-11-13 批1 Task 8）。
 * 匹配规则这里是本地一行 `includes`，**没有**复用 src 的 `filterByKeyword`：判据要与实现
 * 异源，否则产品把过滤写坏时这条跟着一起绿。
 */

/** 只试前 N 个名字：不在上千项的全集上做全量扫描（代价是「第 N+1 个名字里藏着解」时造不出 ⇒ 红给调用方） */
export const BOUNDED_KEYWORD_SCAN_NAMES = 12

/** 匹配数下界：1 项的「全选匹配」等于「选中一项」，测不到全选那条分支 */
export const BOUNDED_KEYWORD_MIN_MATCHES = 2

/** 忽略大小写的子串命中数（与产品 `filterByKeyword` 同一口径、不同实现） */
export function countKeywordMatches(all: string[], kw: string): number {
  const needle = kw.toLowerCase()
  return all.filter((p) => p.toLowerCase().includes(needle)).length
}

/** 造不出「≥2 且有界」的关键词时返回 null，由调用方决定红还是 skip（导出族的纪律是**红**） */
export function pickBoundedKeyword(all: string[], cap: number): { kw: string; count: number } | null {
  for (const name of all.slice(0, BOUNDED_KEYWORD_SCAN_NAMES)) {
    for (let len = 1; len <= name.length; len++) {
      const kw = name.slice(0, len).toLowerCase()
      const count = countKeywordMatches(all, kw)
      if (count >= BOUNDED_KEYWORD_MIN_MATCHES && count <= cap) return { kw, count }
      if (count < BOUNDED_KEYWORD_MIN_MATCHES) break
    }
  }
  return null
}
