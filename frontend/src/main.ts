import { createApp } from 'vue'
import { createPinia } from 'pinia'
// 逐件注册的 EP（含各件样式入口）。必须排在下面三张自有 CSS 之前：EP 的样式要在下层，
// 我们对 `.el-*` 的主题覆盖才能按原来的层叠顺序赢（判据见 e2e/theme/element-plus-styles.spec.ts）。
import { setupElementPlus } from './plugins/element-plus'
import App from './App.vue'
import router from './router'
import './style.css'
import './styles/design-tokens.css'  // 设计指南两层 token（唯一事实来源，见 docs/reference/ui-design-guide.md）
import './styles/element-plus-theme.css'  // Element Plus 夜晚主题覆盖

const app = createApp(App)

app.use(createPinia())
app.use(router)
setupElementPlus(app)

app.mount('#app')
