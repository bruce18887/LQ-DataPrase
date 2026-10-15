// frontend/test/unit/slotPaths.spec.ts
// 钉住两件事：① 无 slot 时路径与历史上逐字相同（改造不许改变非 slot 行为面）；
// ② 有 slot 清单时四类路径全部改指 slot 目录，且缺字段就硬失败而不是回落。
import { describe, expect, it } from 'vitest'
import os from 'node:os'
import path from 'node:path'
import { slotPaths, type SlotManifest } from '../../e2e/helpers/slot'
import { PROJECT_ROOT } from '../../e2e/fixtures/test-data'

const LEGACY = {
  systemConfigFile: path.join(os.tmpdir(), 'lqdp-e2e-system-config.json'),
  authDir: path.join(__dirname, '..', '..', 'e2e', '.auth'),
  downloadsDir: path.join(__dirname, '..', '..', 'e2e', '.downloads'),
  dataDir: path.resolve(__dirname, '..', '..', '..'),
}

const manifest = (root: string): SlotManifest => ({
  index: 3, backendPort: 8103, frontendPort: 3103,
  dataDir: root, tempDir: path.join(root, 'temp'),
  dbPath: path.join(root, 'db.sqlite3'), mediaDir: path.join(root, 'media'),
  systemConfigFile: path.join(root, 'system-config.json'), slotFile: path.join(root, 'slot.json'),
  authDir: path.join(root, '.auth'), downloadsDir: path.join(root, '.downloads'),
  blobDir: path.join(root, 'blob'), jsonOut: path.join(root, 'results.json'),
  logFile: path.join(root, 'run.log'), templateDbPath: 'x', templateMediaDir: 'y',
  redisDb: 15, secretKey: 'k',
})

describe('无 slot：逐字等于今天 test-data.ts 里的写法', () => {
  const p = slotPaths(null)

  it('config 文件仍指 lqdp-e2e-system-config.json', () => {
    expect(p.systemConfigFile).toBe(LEGACY.systemConfigFile)
    expect(path.basename(p.systemConfigFile)).toBe('lqdp-e2e-system-config.json')
  })
  it('.auth / .downloads 仍在 e2e 目录下，loginState 文件名不变', () => {
    expect(p.authDir).toBe(LEGACY.authDir)
    expect(p.adminState).toBe(path.join(LEGACY.authDir, 'admin.json'))
    expect(p.userState).toBe(path.join(LEGACY.authDir, 'user.json'))
    expect(p.downloadDir).toBe(LEGACY.downloadsDir)
    expect(path.basename(p.downloadDir)).toBe('.downloads')
  })
  it('DATA_DIR 回落仓库根（两处 media 硬编码用例靠它）', () => {
    expect(path.resolve(p.dataDir)).toBe(path.resolve(PROJECT_ROOT))
  })
})

describe('有 slot：四类路径全部改指 slot 目录', () => {
  const root = path.join('C:', 'lqdp-e2e', 'slots', 'r1', 'slot3')
  const p = slotPaths(manifest(root))

  it('config/auth/downloads/dataDir 全在 slot 根下', () => {
    expect(p.systemConfigFile).toBe(path.join(root, 'system-config.json'))
    expect(p.adminState).toBe(path.join(root, '.auth', 'admin.json'))
    expect(p.userState).toBe(path.join(root, '.auth', 'user.json'))
    expect(p.downloadDir).toBe(path.join(root, '.downloads'))
    expect(p.dataDir).toBe(root)
  })
  it('端口也来自清单，供 playwright.config 覆盖 baseURL 用', () => {
    expect(p.frontendOrigin).toBe('http://localhost:3103')
    expect(p.backendPort).toBe(8103)
    expect(p.frontendPort).toBe(3103)
  })
  it('缺承重字段就抛，绝不静默回落共享目录', () => {
    const broken = { ...manifest(root), authDir: '' } as SlotManifest
    expect(() => slotPaths(broken)).toThrow(/slot\.json 缺字段/)
    expect(() => slotPaths({ ...manifest(root), dataDir: undefined } as unknown as SlotManifest)).toThrow(/slot\.json 缺字段/)
  })
})
