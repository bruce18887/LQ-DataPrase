import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8')

const SHELL = '../../src/pages/admin/components/AdminPageToolbar.vue'

describe('AdminPageToolbar：两页共用的壳', () => {
  it('左右两个命名 slot 都在，且空槽不渲染包裹层', () => {
    const code = read(SHELL)
    expect(code).toContain('<slot name="left" />')
    expect(code).toContain('<slot name="right" />')
    expect(code).toMatch(/v-if="\$slots\.left"/)
    expect(code).toMatch(/v-if="\$slots\.right"/)
  })

  it('宽度语言与 SearchCriteria 同源：输入可压到 180、下拉 160、日期 190', () => {
    const code = read(SHELL)
    expect(code).toMatch(/\.admin-filter-input[^}]*min-width:\s*180px/s)
    expect(code).toMatch(/\.admin-filter-select[^}]*width:\s*160px/s)
    expect(code).toMatch(/\.admin-filter-date[^}]*width:\s*190px/s)
  })

  it('只吃语义 token，不写死颜色/字号（双主题的前提）', () => {
    const code = read(SHELL)
    expect(code).toContain('var(--bg-3)')
    expect(code).toContain('var(--border-2)')
    expect(code).not.toMatch(/(?:^|[^\w-])font-size:\s*\d+(?:\.\d+)?px/m)
    expect(code).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
  })
})

const AUDIT = '../../src/pages/admin/AuditLogPage.vue'

const codeOf = (text: string): string =>
  text.split('\n').filter((l) => !/^\s*(\/\/|\/\*|\*|<!--)/.test(l)).join('\n')

describe('审计页接线：testid 不挪窝、宽度类真绑上', () => {
  it('四个 data-testid 仍挂在 el-form-item 上，不挪到控件上', () => {
    const code = codeOf(read(AUDIT))
    for (const id of ['audit-event', 'audit-username', 'audit-date-from', 'audit-date-to']) {
      expect(code, `${id} 不在 el-form-item 上`).toMatch(
        new RegExp(`<el-form-item[^>]*data-testid="${id}"`),
      )
      expect(code, `${id} 被挪到了控件上`).not.toMatch(
        new RegExp(`<(?:el-input|el-select|el-date-picker)[^>]*data-testid="${id}"`),
      )
    }
  })

  it('五颗筛选控件真的带上了宽度类', () => {
    const code = read(AUDIT)
    expect(code).toMatch(/<el-select[^>]*class="admin-filter-select"/)
    expect(code).toMatch(/<el-input[^>]*class="admin-filter-input"/)
    expect(code.match(/<el-date-picker[^>]*class="admin-filter-date"/g) ?? []).toHaveLength(2)
  })

  it('工具栏走壳的左右两个命名槽：重置在左、查询在右', () => {
    const code = read(AUDIT)
    expect(code).toContain('<AdminPageToolbar>')
    const left = code.slice(code.indexOf('<template #left>'), code.indexOf('</template>', code.indexOf('<template #left>')))
    const right = code.slice(code.indexOf('<template #right>'))
    expect(left, '重置没有留在左槽').toContain('重置')
    expect(right, '查询没有落在右槽').toContain('查询')
  })
})
