# DataPhrase 设计系统

工业技术深色专业风格设计系统，参考 GitHub Dark 和 VS Code 设计语言。

## 文件结构

```
frontend/src/
├── theme/                    # 主题配置（TypeScript）
│   ├── index.ts             # 主题入口，统一导出
│   ├── colors.ts            # 颜色系统
│   ├── typography.ts        # 字体排版
│   └── spacing.ts           # 间距系统
├── styles/                   # 样式文件（CSS）
│   ├── variables.css        # CSS 变量定义
│   └── utilities.css        # 工具类样式
├── constants/
│   └── icons.ts             # 图标映射
└── style.css                # 全局样式入口
```

## 使用方法

### 1. 在 TypeScript/Vue 中使用主题

```typescript
// 导入完整主题
import theme from '@/theme';

// 或按需导入
import { colors, typography, spacing } from '@/theme';
import { backgrounds, brand, semantic } from '@/theme/colors';

// 使用示例
const buttonStyle = {
  backgroundColor: colors.brand.primary,
  color: colors.text.primary,
  padding: `${spacing[3]} ${spacing[6]}`,
  fontSize: typography.fontSize.base,
};
```

### 2. 在 CSS 中使用变量

```css
.custom-button {
  background-color: var(--brand-primary);
  color: var(--text-primary);
  padding: var(--spacing-3) var(--spacing-6);
  font-size: var(--text-base);
  border: 1px solid var(--border-default);
  border-radius: 0.375rem;
}

.custom-button:hover {
  background-color: var(--brand-primary-hover);
}
```

### 3. 使用工具类

```vue
<template>
  <div class="bg-secondary p-6 rounded-lg border">
    <h2 class="text-2xl font-semibold text-primary mb-4">标题</h2>
    <p class="text-base text-secondary leading-normal">内容文本</p>
    <button class="bg-brand text-primary px-6 py-3 rounded cursor-pointer">
      操作按钮
    </button>
  </div>
</template>
```

### 4. 使用图标

```vue
<script setup lang="ts">
import { icons } from '@/constants/icons';
</script>

<template>
  <el-icon :size="20">
    <component :is="icons.dashboard" />
  </el-icon>
</template>
```

## 颜色系统

### 背景色
- `--bg-primary` (#0d1117) - 主背景色
- `--bg-secondary` (#161b22) - 卡片/面板背景
- `--bg-tertiary` (#21262d) - 悬停/激活状态

### 文本色
- `--text-primary` (#e6edf3) - 主文本
- `--text-secondary` (#7d8590) - 次级文本
- `--text-tertiary` (#484f58) - 禁用/弱化文本

### 品牌色
- `--brand-primary` (#58a6ff) - 主品牌色（蓝色）
- `--brand-secondary` (#f78166) - 次级品牌色（橙色）

### 语义色
- `--color-success` (#3fb950) - 成功（绿色）
- `--color-warning` (#d29922) - 警告（黄色）
- `--color-error` (#f85149) - 错误（红色）
- `--color-info` (#58a6ff) - 信息（蓝色）

## 字体系统

### 字体大小
- `--text-xs` (12px) 到 `--text-4xl` (36px)

### 字体粗细
- `--font-normal` (400)
- `--font-medium` (500)
- `--font-semibold` (600)
- `--font-bold` (700)

## 间距系统

基于 4px 倍数系统：
- `--spacing-1` (4px) 到 `--spacing-20` (80px)

## 工具类示例

### 布局
```html
<div class="flex items-center justify-between gap-4">
  <div class="flex-col">...</div>
</div>
```

### 间距
```html
<div class="p-6 mx-4 my-8">...</div>
```

### 文本
```html
<h1 class="text-2xl font-bold text-primary">标题</h1>
<p class="text-base text-secondary leading-relaxed">段落</p>
```

### 边框和圆角
```html
<div class="border rounded-lg">...</div>
```

## 最佳实践

1. **优先使用 CSS 变量**：在样式文件中使用 CSS 变量而非硬编码颜色值
2. **使用工具类**：对于简单样式，优先使用工具类而非自定义 CSS
3. **保持一致性**：使用设计系统中定义的值，避免随意添加新的颜色或间距
4. **语义化命名**：使用语义化的颜色名称（如 `--color-success`）而非具体颜色值
5. **响应式设计**：结合工具类实现响应式布局

## 扩展设计系统

如需添加新的设计令牌：

1. 在对应的 TypeScript 文件中添加常量
2. 在 `variables.css` 中添加对应的 CSS 变量
3. 如需要，在 `utilities.css` 中添加工具类
4. 更新此文档
