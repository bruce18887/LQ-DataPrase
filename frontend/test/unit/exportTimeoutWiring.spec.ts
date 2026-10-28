import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * T2：「导出超时 / SFTP 下载超时」两个设置项是否真的接到了请求上。
 *
 * 判的是接线而不是钳位算法（clampExportTimeoutSec 自己的边界由 exportTimeout 那侧的
 * 断言管）：这几条 blob 导出与单文件下载以前不带任何 timeout，于是走 api/index.ts 的
 * 30 秒默认值 —— 用户把上限调到 600 秒也不生效，表现是「大文件导到一半自己断了」。
 * 设置生效链路是本项目反复踩过的类目（见 docs/tasks/todo.md 的系统设置整改），
 * 所以这里用一个假 axios 实例把最终 config 抓出来直接断言。
 */

// vi.mock 的 factory 会被提升到文件最顶，所以 spy 必须走 vi.hoisted，
// 否则 factory 里引用的 `post` 还没初始化（报 "Cannot access before initialization"）。
const { post, get } = vi.hoisted(() => ({
  post: vi.fn(async () => ({ data: {}, headers: {} })),
  get: vi.fn(async () => ({ data: {}, headers: {} })),
}))

vi.mock('../../src/api/index', () => ({
  default: { post, get, put: vi.fn(), delete: vi.fn(), defaults: { baseURL: '/api/v1' } },
}))
vi.mock('../../src/utils/exportTimeout', () => ({
  getExportTimeoutMs: async () => 123_456,
}))
vi.mock('../../src/utils/sftpTimeout', () => ({
  getSftpTimeoutSec: async () => 777,
}))

import { batchApi } from '../../src/api/batch'
import { buyoffApi } from '../../src/api/buyoff'
import { gageApi } from '../../src/api/gage'
import { weightApi } from '../../src/api/weight'
import { sftpApi } from '../../src/api/sftp'

/** 取最后一次 post 的第三参（axios config） */
function lastConfig(): Record<string, unknown> {
  const calls = post.mock.calls
  return (calls[calls.length - 1] as unknown[])[2] as Record<string, unknown>
}

describe('超时设置接到请求 config', () => {
  beforeEach(() => post.mockClear())

  it('批报表 generate_report 带 export_timeout（而不是走 30s 默认值）', async () => {
    await batchApi.generateReport([1, 2])
    expect(lastConfig()).toMatchObject({ responseType: 'blob', timeout: 123_456 })
  })

  it('Buyoff 表单生成带同一份超时', async () => {
    await buyoffApi.generateForm([1])
    expect(lastConfig()).toMatchObject({ responseType: 'blob', timeout: 123_456 })
  })

  it('Gage 汇总保留 silent 并带超时', async () => {
    await gageApi.generateSummary([{ file_id: 1, site: 1 }])
    expect(lastConfig()).toMatchObject({ responseType: 'blob', silent: true, timeout: 123_456 })
  })

  it('权重 xlsx 导出带超时（这条此前恒 30s）', async () => {
    await weightApi.export({
      filename: 'w.csv', text: 'x', visible_group_indexes: [0],
      show_mean: true, palette: [], mean_color: '#000',
    })
    expect(lastConfig()).toMatchObject({ responseType: 'blob', silent: true, timeout: 123_456 })
  })

  it('SFTP 单文件下载走 sftp_download_timeout（秒 → 毫秒）', async () => {
    await sftpApi.download('/remote/a.datalog')
    expect(lastConfig()).toMatchObject({ timeout: 777_000 })
  })

  it('对照组：不带超时的普通查询不会被这条判据误伤（list_batches 无 config）', async () => {
    await batchApi.listBatches()
    const calls = get.mock.calls
    expect((calls[calls.length - 1] as unknown[])[1]).toBeUndefined()
  })
})
