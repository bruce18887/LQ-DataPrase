// frontend/test/unit/slotPaths.spec.ts
// 钉住两件事：① 无 slot 时 auth/config/downloads 仍在 e2e 目录下（历史形态），
// 但 **dataDir 落 `test/e2e-data`** —— 串行跑的库/媒体/临时区绝不写仓库根 `media/`；
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
  dataDir: path.join(__dirname, '..', '..', '..', 'test', 'e2e-data'),
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
  it('DATA_DIR 落 test/e2e-data（不再写仓库根 media/）', () => {
    expect(path.resolve(p.dataDir)).toBe(path.resolve(LEGACY.dataDir))
    // 下面两条不依赖本机绝对路径，专门钉「形状」：数据根必须是仓库根下的 test/e2e-data。
    expect(path.relative(path.resolve(PROJECT_ROOT), path.resolve(p.dataDir))).toBe(
      path.join('test', 'e2e-data'),
    )
    expect(path.basename(p.dataDir)).toBe('e2e-data')
    expect(path.basename(path.dirname(p.dataDir))).toBe('test')
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
