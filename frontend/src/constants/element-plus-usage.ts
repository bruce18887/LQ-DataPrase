/**
 * Element Plus 在本项目的实际用量清单。
 *
 * 存在的理由是「按需注册」这一刀的分母：今天 main.ts 走的是整包
 * `app.use(ElementPlus)` + `element-plus/dist/index.css`（357,282 B），要换成逐件注册，
 * 必须先把「到底用了哪几件」变成一个可被机器核对的事实，而不是靠人记。
 *
 * 唯一的读者目前是 `test/unit/elementPlusUsage.spec.ts` 那条绊线（它双向钉住本清单与
 * src 真实用量：界面新引入一件而这里没加 → 红；这里多列一件没人用的 → 也红）。
 * 按需那一批落地时，本文件变成注册表的真源，整包 import 与 dist/index.css 一起删。
 *
 * 三份清单的划分对应三种接线方式，少一种就会在打包版里静默没样式：
 * - EP_TEMPLATE_COMPONENTS：模板里出现的 `<el-*>` 标签，需要 `app.use(ElXxx)`
 * - EP_PROGRAMMATIC：代码里直接调用的服务式组件（ElMessage / ElMessageBox）
 * - EP_DIRECTIVES：自定义指令（v-loading ⇒ ElLoading 插件注册指令本体）
 */

/** 模板标签（kebab，去掉 `el-` 前缀）。由绊线与 src 逐字比对。 */
export const EP_TEMPLATE_COMPONENTS = [
  'alert',
  'badge',
  'breadcrumb',
  'breadcrumb-item',
  'button',
  'button-group',
  'card',
  'checkbox',
  'checkbox-group',
  'col',
  'collapse',
  'collapse-item',
  'collapse-transition',
  'date-picker',
  'descriptions',
  'descriptions-item',
  'dialog',
  'divider',
  'dropdown',
  'dropdown-item',
  'dropdown-menu',
  'empty',
  'form',
  'form-item',
  'icon',
  'input',
  'input-number',
  'option',
  'option-group',
  'pagination',
  'popover',
  'progress',
  'radio',
  'radio-button',
  'radio-group',
  'row',
  'select',
  'skeleton',
  'slider',
  'splitter',
  'splitter-panel',
  'switch',
  'tab-pane',
  'table',
  'table-column',
  'tabs',
  'tag',
  'tooltip',
  'upload',
] as const

/** 服务式组件（ElMessage / ElMessageBox）。 */
export const EP_PROGRAMMATIC = ['message', 'message-box'] as const

/** 自定义指令（v-loading）。 */
export const EP_DIRECTIVES = ['loading'] as const
