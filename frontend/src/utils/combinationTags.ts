export function managedTagsFor(
  combinationName: string | null | undefined,
  batchNo: string | undefined,
): string[] {
  if (!combinationName) return []
  const tags = [combinationName]
  if (batchNo) tags.push(`${combinationName} / ${batchNo}`)
  return tags
}

export function mergeDisplayTags(manual: string[], managed: string[]): string[] {
  const result: string[] = []
  const seen = new Set<string>()
  for (const tag of [...manual, ...managed]) {
    const key = tag.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    result.push(tag)
  }
  return result
}
