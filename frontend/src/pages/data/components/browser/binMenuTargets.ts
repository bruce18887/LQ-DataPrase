export interface JumpTargetInput {
  failCols: string[]
  borderlineCols: string[]
  binCol: string
  displayCols: string[]
}

/**
 * 定位目标顺序：红格测试列 → 临界橙格列 → Bin。
 * 橙格只解释 fail 原因，不改 fail_cells 语义。
 */
export function orderedJumpTargets(input: JumpTargetInput): string[] {
  const red = input.failCols.filter((c) => c !== input.binCol)
  const orange = input.borderlineCols.filter(
    (c) => c !== input.binCol && !red.includes(c),
  )
  const bin = input.failCols.includes(input.binCol) ? [input.binCol] : []
  return [...red, ...orange, ...bin]
}

/** 第一个可见目标；全部被隐藏时返回 undefined（调用方退回整行 flash）。 */
export function firstVisibleJumpTarget(input: JumpTargetInput): string | undefined {
  return orderedJumpTargets(input).find((c) => input.displayCols.includes(c))
}
