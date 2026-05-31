# DataPhrase 通用组件库

工业技术风格的 Vue 3 组件库，采用深色主题和霓虹效果。

## 组件列表

### 1. Card 卡片组件

**Props:**
- `variant`: 'default' | 'elevated' | 'bordered' | 'neon' (默认: 'default')

**Slots:**
- `header`: 卡片头部
- `default`: 卡片内容
- `footer`: 卡片底部

**使用示例:**
```vue
<Card variant="neon">
  <template #header>
    <h3>标题</h3>
  </template>
  
  <p>这是卡片内容区域</p>
  
  <template #footer>
    <span>底部信息</span>
  </template>
</Card>
```

---

### 2. Button 按钮组件

**Props:**
- `variant`: 'primary' | 'secondary' | 'neon' (默认: 'primary')
- 继承所有 Element Plus Button 的 props

**使用示例:**
```vue
<Button variant="primary">主要按钮</Button>
<Button variant="secondary">次要按钮</Button>
<Button variant="neon">霓虹按钮</Button>
```

---

### 3. Badge 徽章组件

**Props:**
- `value`: string | number (必填)
- `type`: 'success' | 'warning' | 'error' | 'info' (默认: 'info')

**使用示例:**
```vue
<Badge value="成功" type="success" />
<Badge value="99+" type="error" />
<Badge value="警告" type="warning" />
<Badge value="信息" type="info" />
```

---

### 4. Loading 加载动画组件

**Props:**
- `size`: string (默认: '50px')
- `color`: string (默认: '#58a6ff')

**使用示例:**
```vue
<Loading />
<Loading size="60px" color="#3fb950" />
<Loading size="40px" color="#f85149" />
```

---

### 5. Empty 空状态组件

**Props:**
- `description`: string (默认: '暂无数据')

**Slots:**
- `default`: 额外操作区域

**使用示例:**
```vue
<Empty description="暂无数据" />

<Empty description="没有找到相关内容">
  <Button variant="primary">刷新</Button>
</Empty>
```

---

## 导入方式

### 单个导入
```typescript
import { Card, Button, Badge, Loading, Empty } from '@/components/common'
```

### 全局注册（可选）
```typescript
// main.ts
import CommonComponents from '@/components/common'

app.component('Card', CommonComponents.Card)
app.component('DpButton', CommonComponents.Button)
app.component('Badge', CommonComponents.Badge)
app.component('Loading', CommonComponents.Loading)
app.component('Empty', CommonComponents.Empty)
```

---

## 设计规范

### 颜色系统
- **背景色**: #21262d (卡片背景)
- **边框色**: #30363d (默认边框)
- **主色调**: #58a6ff (霓虹蓝)
- **成功色**: #3fb950
- **警告色**: #d29922
- **错误色**: #f85149
- **文字色**: #c9d1d9 (主要文字), #8b949e (次要文字)

### 霓虹效果
所有 `neon` 变体都包含：
- 发光边框
- 悬停时增强的光晕效果
- 内部微光效果

### 动画
- 过渡时间: 0.3s
- 缓动函数: ease
- 悬停提升: translateY(-1px ~ -2px)

---

## 注意事项

1. 所有组件都使用 Vue 3 Composition API
2. 使用 TypeScript 定义 Props
3. 样式使用 scoped CSS，不会污染全局
4. Button 组件基于 Element Plus，需要确保已安装 Element Plus
5. 所有组件都支持深色主题，适配工业技术风格
