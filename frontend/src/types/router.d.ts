import type { Component } from 'vue'

/**
 * 路由 meta 是页面身份的唯一真相：顶栏身份块与 `document.title` 都从这里读。
 * 此前 Topbar 另维护了一份按路径段翻译的 `routeLabels`，两边已经漂了
 * （面包屑把 `/sftp/search` 译成「高级搜索」，而 meta 与页面自己写的是「SFTP 搜索」），
 * 那份表随身份块改造一起删除。
 */
declare module 'vue-router' {
  interface RouteMeta {
    /** 页面名：面包屑/身份块/document.title 共用 */
    title?: string
    requiresAuth?: boolean
    requiresAdmin?: boolean
    /** 身份块徽章图标，与侧栏菜单同一批 EP 图标组件（认页面靠同一个形，不靠读字） */
    icon?: Component
    /** 身份块副行的一句话说明；缺省时副行只画上级 */
    desc?: string
    /** 身份块副行的上级。省略 `to` 表示这一级不是可跳转路由（如侧栏分组名） */
    parent?: { label: string; to?: string }
  }
}
