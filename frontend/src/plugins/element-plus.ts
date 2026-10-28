/**
 * Element Plus 逐件注册（按需）。
 *
 * 取代 `import ElementPlus from 'element-plus'` + `element-plus/dist/index.css` 的整包注册：
 * 整包那条把 EP 全部 124 件（含我们一件没用到的 tree-select、carousel、calendar…）都装进
 * 首屏，而 EP 的 `sideEffects` 只把各件的 `style/css` 入口与 `dist` 目录标成有副作用，
 * 组件 JS 本身可以被摇掉 —— 前提是别再从 default export 那个「全量插件」入口进。
 *
 * 清单不是手写的愿望，而是被钉住的事实：`test/unit/elementPlusUsage.spec.ts` 双向比对
 * `src/constants/element-plus-usage.ts` ↔ src 真实用量 ↔ 本文件的 import 名单，
 * 三个方向任意一个漂了都会红。样式是否真的落到元素上由
 * `e2e/theme/element-plus-styles.spec.ts` 在两种主题下验。
 *
 * ⚠ 本模块必须**在** main.ts 里三张自有 CSS（style.css / design-tokens.css /
 * element-plus-theme.css）**之前**被 import：EP 的样式要在下层，我们对 `.el-*` 的
 * 夜晚主题覆盖才能按原来的层叠顺序赢（这条顺序由 T2 绊线钉着）。
 *
 * 2026-10-28 实测：element-vendor 的 JS 896,954B → 548,846B、CSS 356,008B → 250,870B，
 * 首屏合计 1,483,027B → 1,030,398B（−30.5%）。
 */
import type { App } from 'vue'
import {
  ElAlert,
  ElBadge,
  ElBreadcrumb,
  ElBreadcrumbItem,
  ElButton,
  ElButtonGroup,
  ElCard,
  ElCheckbox,
  ElCheckboxGroup,
  ElCollapse,
  ElCollapseItem,
  ElCollapseTransition,
  ElCol,
  ElDatePicker,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElDivider,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElLoading,
  ElOption,
  ElOptionGroup,
  ElPagination,
  ElPopover,
  ElProgress,
  ElRadio,
  ElRadioButton,
  ElRadioGroup,
  ElRow,
  ElSelect,
  ElSkeleton,
  ElSlider,
  ElSplitter,
  ElSplitterPanel,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag,
  ElTooltip,
  ElUpload,
} from 'element-plus'

/** 样式逐件引入（EP 的 style/css 会连带把 base/popper/scrollbar 等依赖的 CSS 一起带进来）。 */
import 'element-plus/es/components/alert/style/css'
import 'element-plus/es/components/badge/style/css'
import 'element-plus/es/components/breadcrumb/style/css'
import 'element-plus/es/components/breadcrumb-item/style/css'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/button-group/style/css'
import 'element-plus/es/components/card/style/css'
import 'element-plus/es/components/checkbox/style/css'
import 'element-plus/es/components/checkbox-group/style/css'
import 'element-plus/es/components/col/style/css'
import 'element-plus/es/components/collapse/style/css'
import 'element-plus/es/components/collapse-item/style/css'
import 'element-plus/es/components/collapse-transition/style/css'
import 'element-plus/es/components/date-picker/style/css'
import 'element-plus/es/components/descriptions/style/css'
import 'element-plus/es/components/descriptions-item/style/css'
import 'element-plus/es/components/dialog/style/css'
import 'element-plus/es/components/divider/style/css'
import 'element-plus/es/components/dropdown/style/css'
import 'element-plus/es/components/dropdown-item/style/css'
import 'element-plus/es/components/dropdown-menu/style/css'
import 'element-plus/es/components/empty/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import 'element-plus/es/components/icon/style/css'
import 'element-plus/es/components/input/style/css'
import 'element-plus/es/components/input-number/style/css'
import 'element-plus/es/components/loading/style/css'
// 服务式组件（ElMessage / ElMessageBox）全站都是具名 import、不需要 install，
// 但样式必须有个落点 —— 这两行就是那个落点。
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import 'element-plus/es/components/option/style/css'
import 'element-plus/es/components/option-group/style/css'
import 'element-plus/es/components/pagination/style/css'
import 'element-plus/es/components/popover/style/css'
import 'element-plus/es/components/progress/style/css'
import 'element-plus/es/components/radio/style/css'
import 'element-plus/es/components/radio-button/style/css'
import 'element-plus/es/components/radio-group/style/css'
import 'element-plus/es/components/row/style/css'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/skeleton/style/css'
import 'element-plus/es/components/slider/style/css'
import 'element-plus/es/components/splitter/style/css'
import 'element-plus/es/components/splitter-panel/style/css'
import 'element-plus/es/components/switch/style/css'
import 'element-plus/es/components/tab-pane/style/css'
import 'element-plus/es/components/table/style/css'
import 'element-plus/es/components/table-column/style/css'
import 'element-plus/es/components/tabs/style/css'
import 'element-plus/es/components/tag/style/css'
import 'element-plus/es/components/tooltip/style/css'
import 'element-plus/es/components/upload/style/css'

/** 带 install 的件：模板里的 49 个标签 + 提供 v-loading 指令的 ElLoading。 */
const installables = [
  ElAlert,
  ElBadge,
  ElBreadcrumb,
  ElBreadcrumbItem,
  ElButton,
  ElButtonGroup,
  ElCard,
  ElCheckbox,
  ElCheckboxGroup,
  ElCol,
  ElCollapse,
  ElCollapseItem,
  ElCollapseTransition,
  ElDatePicker,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElDivider,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElIcon,
  ElInput,
  ElInputNumber,
  ElLoading,
  ElOption,
  ElOptionGroup,
  ElPagination,
  ElPopover,
  ElProgress,
  ElRadio,
  ElRadioButton,
  ElRadioGroup,
  ElRow,
  ElSelect,
  ElSkeleton,
  ElSlider,
  ElSplitter,
  ElSplitterPanel,
  ElSwitch,
  ElTabPane,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTag,
  ElTooltip,
  ElUpload,
]

/**
 * 逐件装到 app 上。ElMessage / ElMessageBox 是函数式 API，全站都走具名 import
 * （全仓没有任何 `this.$message` 用法），所以不进这里，只留样式入口。
 */
export function setupElementPlus(app: App): void {
  for (const comp of installables) app.use(comp)
}
