import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8')

/** 整行注释不参与判定：兜底理由与历史说明要能写在注释里。 */
const codeOf = (text: string): string =>
  text.split('\n').filter((l) => !/^\s*(\/\/|\/\*|\*|<!--)/.test(l)).join('\n')

const CHIPS = '../../src/pages/admin/components/UserKpiChips.vue'

describe('UserKpiChips：四个 chip、四个 EP 图标、零 emoji', () => {
  it('四个标签与四个 EP 图标都在', () => {
    const code = read(CHIPS)
    for (const label of ['总用户', '活跃', '锁定', '管理员']) {
      expect(code, `chip 少了「${label}」`).toContain(`label: '${label}'`)
    }
    for (const icon of ['UserFilled', 'CircleCheck', 'Lock', 'Stamp']) {
      expect(code, `chip 少了图标 ${icon}`).toContain(icon)
    }
  })

  it('代码行里没有 emoji（旧 KPI 的 👥✅🛡️ 不许复活）', () => {
    const code = codeOf(read(CHIPS))
    expect(code, 'KPI chip 里又出现了 emoji').not.toMatch(
      /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u,
    )
  })
})
