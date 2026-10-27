import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import './style.css'
import './styles/design-tokens.css'  // 设计指南两层 token（唯一事实来源，见 docs/reference/ui-design-guide.md）
import './styles/element-plus-theme.css'  // Element Plus 夜晚主题覆盖

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus)

app.mount('#app')
