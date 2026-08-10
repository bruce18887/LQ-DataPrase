import { execSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { PROJECT_ROOT } from '../fixtures/test-data'

/** 根目录 .venv Python（与 global-setup.ts 相同的解析方式；Windows 路径） */
function pythonBin(): string {
  return process.env.PYTHON_BIN || path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe')
}

/**
 * 用 venv Python 标准库 zipfile 构造 zip 文件（避免新增 npm 依赖）。
 * entries: [{ name: 'a.csv', content: '...' }, ...] — name 为 zip 内相对路径。
 */
export function makeZip(zipPath: string, entries: Array<{ name: string; content: string }>): void {
  const stamp = `${Date.now()}_${Math.random().toString(36).slice(2)}`
  const entriesPath = path.join(os.tmpdir(), `lqdp_zip_entries_${stamp}.json`)
  const scriptPath = path.join(os.tmpdir(), `lqdp_make_zip_${stamp}.py`)
  fs.writeFileSync(entriesPath, JSON.stringify(entries), 'utf-8')
  fs.writeFileSync(
    scriptPath,
    [
      "import json, zipfile",
      `with open(r'${entriesPath}', encoding='utf-8') as f:`,
      '    entries = json.load(f)',
      `with zipfile.ZipFile(r'${zipPath}', 'w', zipfile.ZIP_DEFLATED) as zf:`,
      "    for e in entries:",
      "        zf.writestr(e['name'], e['content'])",
    ].join('\n'),
    'utf-8',
  )
  try {
    execSync(`"${pythonBin()}" "${scriptPath}"`, { stdio: 'pipe', timeout: 30_000 })
  } finally {
    fs.rmSync(entriesPath, { force: true })
    fs.rmSync(scriptPath, { force: true })
  }
}
