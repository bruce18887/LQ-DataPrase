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

const PAGE = '../../src/pages/admin/UserManagement.vue'

describe('UserManagement：薄页——只有 chip 行、工具栏、表格与对话框', () => {
  it('三个管理页组件都接上了', () => {
    const code = read(PAGE)
    expect(code).toContain('<UserKpiChips')
    expect(code).toContain('<AdminPageToolbar>')
    expect(code).toContain('<UserFormDialog')
  })

  it('页内不再自带对话框/内联添加表单', () => {
    const code = codeOf(read(PAGE))
    expect(code).not.toContain('<el-dialog')
    expect(code).not.toContain('添加用户')
    expect(code).not.toContain('el-divider')
  })

  it('左槽留空（决策 D 归批4），右槽有「新增账号」', () => {
    const code = read(PAGE)
    expect(code).not.toContain('<template #left>')
    expect(code).toContain('<template #right>')
    expect(code).toContain('新增账号')
  })

  it('KPI 四个数逐项传给 chip 组件', () => {
    const code = read(PAGE)
    for (const prop of ['total', 'active', 'locked', 'admins']) {
      expect(code, `KPI prop ${prop} 没传给 UserKpiChips`).toContain(`:${prop}="kpi.${prop}"`)
    }
  })

  it('页面代码行零 emoji（旧 KPI 与 roleIcon 已换 EP 图标）', () => {
    const code = codeOf(read(PAGE))
    expect(code).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u)
  })

  it('页面不再自带角色下拉（唯一一个在 UserFormDialog）', () => {
    const code = codeOf(read(PAGE))
    expect(code).not.toMatch(/<el-select[^>]*v-model="[^"]*\.role"/)
  })
})

describe('B3 移交：input/footer 基线样式已由对话框接手', () => {
  it('UserFormDialog 有 input/button 深规则，UserManagement 不再有 input 深规则', () => {
    const dialog = read(DIALOG)
    expect(dialog).toMatch(/:deep\(\.el-input__wrapper\)/)
    expect(dialog).toMatch(/:deep\(\.el-button\)/)
    const page = read(PAGE)
    expect(page).not.toMatch(/:deep\(\.el-input__wrapper\)/)
    expect(page).toMatch(/:deep\(\.el-button\)/)
  })
})

const THEME = '../../src/styles/element-plus-theme.css'

describe('批次级主题收敛：select 触发区由 .el-select__wrapper 承载', () => {
  it('night 规则指向 .el-select__wrapper，死规则 .el-select .el-input__wrapper 已不存在', () => {
    const theme = codeOf(read(THEME))
    expect(theme).toMatch(/:root\[data-theme="night"\] \.el-select__wrapper/)
    expect(theme).toMatch(/\.el-select__wrapper\.is-focused/)
    expect(theme).not.toMatch(/\.el-select \.el-input__wrapper/)
    expect(codeOf(read(PAGE)), '页面里还留着死规则').not.toMatch(/\.el-select \.el-input__wrapper/)
  })
})
