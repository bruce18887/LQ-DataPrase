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
