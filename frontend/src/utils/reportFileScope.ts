import type { DataFile } from '../types'

export function filterReportFiles(
  files: DataFile[],
  combinationId: number | null | undefined,
): DataFile[] {
  if (combinationId == null) return files
  return files.filter(file => (file.combination_id ?? null) === combinationId)
}
