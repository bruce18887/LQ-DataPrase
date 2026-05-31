# 浅色主题风格指南

## 目标
将所有页面从深色GitHub风格主题迁移到现代数据实验室浅色主题，确保一致性和可读性。

## 核心原则

### 1. 使用CSS变量，禁止硬编码颜色
**必须做：**
```css
background: var(--bg-secondary);
color: var(--text-primary);
border: 1px solid var(--border-default);
```

**禁止做：**
```css
background: #161b22;
color: #c9d1d9;
border: 1px solid #30363d;
```

### 2. CSS变量参考表

#### 背景色
```css
--bg-primary: #fafbfc;      /* 主背景 - 温暖米白色 */
--bg-secondary: #f3f4f6;    /* 次级背景 - 浅灰色 */
--bg-tertiary: #e5e7eb;     /* 三级背景 - 中浅灰色 */
```

#### 文本色
```css
--text-primary: #1f2937;    /* 主文本 - 深灰黑色 */
--text-secondary: #6b7280;  /* 次级文本 - 中灰色 */
--text-tertiary: #9ca3af;   /* 三级文本 - 浅灰色 */
--text-inverse: #ffffff;    /* 反色文本 - 白色（用于深色背景上）*/
```

#### 边框色
```css
--border-default: #d1d5db;  /* 默认边框 */
--border-muted: #e5e7eb;    /* 柔和边框 */
--border-emphasis: #9ca3af; /* 强调边框 */
```

#### 品牌色
```css
--brand-primary: #2563eb;       /* 主品牌色 - 专业蓝 */
--brand-secondary: #ea580c;     /* 次品牌色 - 橙色 */
--brand-primary-hover: #1d4ed8; /* 主品牌色悬停 */
--brand-secondary-hover: #c2410c; /* 次品牌色悬停 */
```

#### 语义色
```css
--color-success: #059669;           /* 成功 - 绿色 */
--color-success-emphasis: #047857;  /* 成功强调 */
--color-warning: #d97706;           /* 警告 - 橙色 */
--color-warning-emphasis: #b45309;  /* 警告强调 */
--color-error: #dc2626;             /* 错误 - 红色 */
--color-error-emphasis: #b91c1c;    /* 错误强调 */
--color-info: #0284c7;              /* 信息 - 蓝色 */
--color-info-emphasis: #0369a1;     /* 信息强调 */
```

## 常见替换模式

### 背景色替换
```css
/* 旧 → 新 */
#0d1117 → var(--bg-primary)
#161b22 → var(--bg-secondary)
#21262d → var(--bg-tertiary)
rgba(0, 0, 0, 0.2) → var(--bg-tertiary)
```

### 文本色替换
```css
/* 旧 → 新 */
#e6edf3, #c9d1d9, #f0f6fc → var(--text-primary)
#7d8590, #8b949e → var(--text-secondary)
#484f58, #6e7681 → var(--text-tertiary)
```

### 边框色替换
```css
/* 旧 → 新 */
#30363d → var(--border-default)
#21262d → var(--border-muted)
#6e7681 → var(--border-emphasis)
```

### 品牌色替换
```css
/* 旧 → 新 */
#58a6ff, #1f6feb → var(--brand-primary)
#79c0ff, #4895ef → var(--brand-primary-hover)
#f78166 → var(--brand-secondary)
```

### 语义色替换
```css
/* 旧 → 新 */
#3fb950, #2ea043 → var(--color-success)
#d29922, #bb8009 → var(--color-warning)
#f85149, #da3633 → var(--color-error)
```

## 阴影效果调整

### 卡片阴影（浅色主题更轻）
```css
/* 旧（深色主题）*/
box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);

/* 新（浅色主题）*/
box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.06);
```

### 悬停阴影
```css
/* 旧 */
box-shadow: 0 6px 16px rgba(0, 0, 0, 0.4);

/* 新 */
box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12), 0 2px 6px rgba(0, 0, 0, 0.08);
```

### 发光效果（品牌色）
```css
/* 旧（亮蓝色 #58a6ff）*/
box-shadow: 0 0 10px rgba(88, 166, 255, 0.3);

/* 新（专业蓝色 #2563eb = rgb(37, 99, 235)）*/
box-shadow: 0 0 10px rgba(37, 99, 235, 0.2);
```

## 圆角统一标准

```css
/* 统一使用 8px 圆角 */
border-radius: 8px;  /* 卡片、按钮、输入框 */
border-radius: 12px; /* 徽章 */
border-radius: 16px; /* 大型卡片 */
```

## Element Plus 组件覆盖

### 输入框
```css
:deep(.el-input) {
  --el-input-bg-color: var(--bg-primary);
  --el-input-border-color: var(--border-default);
  --el-input-hover-border-color: var(--brand-primary);
  --el-input-focus-border-color: var(--brand-primary);
  --el-input-text-color: var(--text-primary);
  --el-input-placeholder-color: var(--text-secondary);
}

:deep(.el-input__wrapper) {
  background-color: var(--bg-primary);
  border-radius: 8px;
}
```

### 表格
```css
:deep(.el-table) {
  --el-table-bg-color: var(--bg-secondary);
  --el-table-tr-bg-color: var(--bg-secondary);
  --el-table-header-bg-color: var(--bg-tertiary);
  --el-table-border-color: var(--border-default);
  --el-table-text-color: var(--text-primary);
}
```

### 下拉菜单
```css
:deep(.el-dropdown-menu) {
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-default);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

:deep(.el-dropdown-menu__item) {
  color: var(--text-primary);
}

:deep(.el-dropdown-menu__item:hover) {
  background-color: var(--bg-tertiary);
  color: var(--brand-primary);
}
```

## 特殊场景处理

### 1. 渐变背景
```css
/* 旧 */
background: linear-gradient(135deg, #1f6feb 0%, #58a6ff 100%);

/* 新 */
background: var(--brand-primary);
/* 或者如果必须使用渐变 */
background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 100%);
```

### 2. 半透明背景
```css
/* 旧 */
background: rgba(88, 166, 255, 0.1);

/* 新 */
background: rgba(37, 99, 235, 0.08);
```

### 3. 滚动条样式
```css
.scrollable::-webkit-scrollbar {
  width: 8px;
}

.scrollable::-webkit-scrollbar-track {
  background: var(--bg-primary);
}

.scrollable::-webkit-scrollbar-thumb {
  background: var(--border-default);
  border-radius: 4px;
}

.scrollable::-webkit-scrollbar-thumb:hover {
  background: var(--border-emphasis);
}
```

## 检查清单

更新每个页面时，确保：

- [ ] 所有硬编码的十六进制颜色都替换为CSS变量
- [ ] 阴影效果调整为浅色主题强度
- [ ] 圆角统一为8px（或12px/16px）
- [ ] Element Plus组件使用CSS变量覆盖
- [ ] 悬停效果清晰可见
- [ ] 文本对比度足够（深色文字在浅色背景上）
- [ ] 边框清晰可见
- [ ] 品牌色使用一致（#2563eb）

## 不要修改的内容

- **Roadmap页面** - 保持原样
- **CSS变量定义文件** (`variables.css`) - 已经更新完成
- **已更新的组件** - Card, Button, Badge, Empty, Loading, GridBackground, Sidebar, Topbar, MainLayout, LoginPage

## 验证方法

更新完成后：
1. 运行 `npm run build` 确保没有TypeScript错误
2. 检查页面在浏览器中的显示效果
3. 确认所有交互状态（hover, active, focus）都正常工作
4. 验证文本可读性

---

**风格目标**：现代、专业、清晰、高对比度
**设计理念**：现代数据实验室 - 温暖、专业、易读
