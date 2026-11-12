import { defineConfig } from 'vitepress'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
// 版本单一事实源仍是 frontend/package.json（与顶栏徽标同源，check.mjs 钉住）
const pkg = JSON.parse(readFileSync(path.resolve(here, '../../../frontend/package.json'), 'utf8')) as { version: string }

export default defineConfig({
  // 三种 serving 形态都挂在 /intro/ 前缀下：vite 中间件 / Django intro 挂载 / Electron 经后端 origin。
  // file:// 双击形态已放弃（ES module 被 CORS 拦），见 spec §2。
  base: '/intro/',
  lang: 'zh-CN',
  title: 'LQ-DataPrase 产品介绍书',
  description: '把半导体测试机产出的 CSV datalog，变成良率、CPK、晶圆图与批次结论。',
  cleanUrls: true,
  lastUpdated: true,
  themeConfig: {
    nav: [
      { text: '快速上手', link: '/guide/02-quickstart' },
      { text: '功能巡礼', link: '/guide/03-dashboard' },
      { text: '常见问题', link: '/guide/10-faq' },
      { text: `v${pkg.version}`, link: '/guide/11-versions' },
    ],
    sidebar: [
      {
        text: '开始',
        items: [
          { text: '封面', link: '/' },
          { text: '01 产品概览', link: '/guide/01-overview' },
          { text: '02 快速上手', link: '/guide/02-quickstart' },
        ],
      },
      {
        text: '功能巡礼',
        items: [
          { text: '03 仪表板', link: '/guide/03-dashboard' },
          { text: '04 数据管理 · 七页签', link: '/guide/04-data' },
          { text: '05 数据分析 · 五视角', link: '/guide/05-analysis' },
          { text: '06 SFTP 浏览器与搜索', link: '/guide/06-sftp' },
          { text: '07 权重画图', link: '/guide/07-weight' },
          { text: '08 系统设置与双主题', link: '/guide/08-settings' },
          { text: '09 用户与操作审计', link: '/guide/09-admin' },
        ],
      },
      {
        text: '附录',
        items: [
          { text: '10 常见问题', link: '/guide/10-faq' },
          { text: '11 版本历程', link: '/guide/11-versions' },
          { text: '12 术语表', link: '/guide/12-glossary' },
        ],
      },
    ],
    outline: { level: [2, 3], label: '本页目录' },
    search: {
      provider: 'local',
      options: {
        translations: {
          button: { buttonText: '搜索介绍书', buttonAriaLabel: '搜索介绍书' },
          modal: {
            noResultsText: '无匹配结果',
            resetButtonTitle: '清除',
            footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' },
          },
        },
      },
    },
    docFooter: { prev: '上一页', next: '下一页' },
    lastUpdatedText: '最后更新',
    returnToTopLabel: '回到顶部',
    sidebarMenuLabel: '目录',
    darkModeSwitchLabel: '主题',
    lightModeSwitchTitle: '切换到浅色模式',
    darkModeSwitchTitle: '切换到夜间模式',
    footer: {
      message: `基于 v${pkg.version} 演示环境 · 截图均为合成数据 · 编制 2026-11-12`,
      copyright: 'LQ-DataPrase 产品介绍书 · 离线 serving 三形态分发',
    },
  },
})