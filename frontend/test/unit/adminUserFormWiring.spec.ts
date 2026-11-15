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

const DIALOG = '../../src/pages/admin/components/UserFormDialog.vue'
const TYPES = '../../src/pages/admin/components/userFormTypes.ts'

describe('UserFormDialog：edit-* 不挪窝，create-* 独立，载荷按 mode 分叉', () => {
  it('三个静态 edit-* testid 挂在 el-form-item 上', () => {
    const code = read(DIALOG)
    for (const id of ['edit-username', 'edit-display-name', 'edit-email']) {
      expect(code, `${id} 不在 el-form-item 上`).toMatch(
        new RegExp(`<el-form-item[^>]*data-testid="${id}"`),
      )
    }
  })

  it('角色那一格的 testid 按 mode 分叉，edit-role 与 create-role 都在源码里', () => {
    const code = read(DIALOG)
    expect(code).toMatch(
      /<el-form-item[\s\S]{0,200}:data-testid="mode === 'edit' \? 'edit-role' : 'create-role'"/,
    )
    expect(code).toMatch(/data-testid="create-username"/)
    expect(code).toMatch(/data-testid="create-password"/)
  })

  it('角色下拉只此一处，两个选项与后端 choices 同集合', () => {
    const code = read(DIALOG)
    expect(code).toMatch(/<el-select v-model="form\.role">/)
    expect(code).toContain('<el-option label="用户" value="user" />')
    expect(code).toContain('<el-option label="管理员" value="administrator" />')
  })

  it('载荷类型是判别联合：create 不带 email，edit 不带 username/password', () => {
    const code = read(TYPES)
    expect(code).toMatch(/mode: 'create';\s*username: string;\s*password: string;\s*role: string/)
    expect(code).toMatch(/mode: 'edit';\s*display_name: string;\s*email: string;\s*role: string/)
  })
})
