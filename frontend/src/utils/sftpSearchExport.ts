/**
 * SFTP 搜索结果的 CSV 序列化（计划 Task 16 Step 4 / spec §3.1 末段、§3.13）。
 *
 * 三条规矩各挡一个真实故障，少一条就是「导出文件比表格还难用」：
 * 1. **RFC 4180 转义**：含 `"` `,` CR/LF 的字段整体加引号、内部引号翻倍。
 *    远程路径里带逗号是真事（`RT_1,rev2.csv`）、命中片段里带引号也是真事，
 *    漏转义会把一行劈成两列，用户在 Excel 里看到的就是错位数据。
 * 2. **UTF-8 BOM**：Excel 双击打开 .csv 时按本地代码页猜编码，没有 BOM
 *    中文测试项名一律乱码。BOM 只加在**落盘那一次**（`exportSearchResults`），
 *    不进 `buildCsv` —— 后者管的是「行」，编码是「写文件」这件事的职责。
 * 3. **mtime 导出 epoch 秒原值**：格式化串既带逗号又有本地时区歧义，
 *    而导出的用途正是在 Excel 里排序/筛选，数字原值直接可算。
 *
 * 列集合随 `mode` 变，**与结果表所见的列一致**（不导出用户看不见的列）。
 *
 * 文件名由前端拼 `sftp_search_<mode>_<YYYYMMDD_HHmmss>.csv`，**不套**后端
 * `apps/common/export_naming.py` 的模板 —— 与项目其它导出**有意不一致**（spec §3.1）：
 * 那套模板要后端渲染，而搜索结果的整份数据已经在前端手里，为拼个名字再发一次请求不值。
 */
import { downloadBlob } from './download'
import type { CandidateItem, MatchItem, SearchMode } from '../api/sftpSearch'

/** 结果行：`name` 档只有候选（后端 `runner.py` 在 mode=name 时不产生命中），其余两档是命中行 */
export type SearchResultRow = CandidateItem | MatchItem

/** 无 BOM 则 Excel 打开中文乱码 */
const BOM = '\uFEFF'

function cell(v: unknown): string {
  const s = v === null || v === undefined ? '' : String(v)
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s   // RFC 4180
}

// 列集合随 mode 变，与结果表所见一致 —— 不该导出看不见的列
const COLUMNS: Record<SearchMode, Array<[key: string, label: string]>> = {
  name:    [['name', '名称'], ['path', '完整路径'], ['size', '字节'],
            ['mtime', '修改时间(epoch秒)']],
  content: [['name', '名称'], ['path', '完整路径'], ['size', '字节'],
            ['mtime', '修改时间(epoch秒)'], ['line', '命中行'], ['snippet', '命中内容'],
            ['test_file', 'TestFile'], ['start_time', 'StartTime'],
            ['pts_modify_time', 'PtsModifyTime']],
  column:  [['name', '名称'], ['path', '完整路径'], ['column_name', '列名'],
            ['values', '值'], ['test_file', 'TestFile'], ['start_time', 'StartTime']],
}

export function buildCsv(rows: SearchResultRow[], mode: SearchMode): string {
  const cols = COLUMNS[mode]
  const lines = [cols.map(([, label]) => cell(label)).join(',')]
  for (const row of rows) {
    lines.push(cols.map(([key]) => {
      const v = (row as unknown as Record<string, unknown>)[key]
      return cell(Array.isArray(v) ? v.join(' | ') : v)   // values 并成一格
    }).join(','))
  }
  return lines.join('\r\n') + '\r\n'
}

/** `sftp_search_column_20260920_141530.csv` —— 本地时间，与用户看到的时刻一致。 */
export function buildSearchExportName(mode: SearchMode, at: Date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0')
  const stamp = `${at.getFullYear()}${p(at.getMonth() + 1)}${p(at.getDate())}`
    + `_${p(at.getHours())}${p(at.getMinutes())}${p(at.getSeconds())}`
  return `sftp_search_${mode}_${stamp}.csv`
}

/** 序列化 + BOM + 交给 `downloadBlob` 落盘。name 省略时按 mode 与当前时间拼名。 */
export function exportSearchResults(
  rows: SearchResultRow[],
  mode: SearchMode,
  name: string = buildSearchExportName(mode),
): void {
  downloadBlob(new Blob([BOM + buildCsv(rows, mode)],
    { type: 'text/csv;charset=utf-8' }),
    name.endsWith('.csv') ? name : `${name}.csv`)
}
