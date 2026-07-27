# 项目结构重构 TODO

## 🔴 P0: FileListTab.vue 拆分
- [ ] 等待探索 Agent 返回分析结果
- [ ] 拆分 FileListTab.vue 为子组件
- [ ] 更新父组件引用
- [ ] 类型检查和构建验证

## 🟠 P1: 测试目录整理
- [ ] 移动散落 test_*.py 到 test/backend/
- [ ] 移动调试截图到 test/screenshots/debug/
- [ ] 重命名 screenshots_night → screenshots/night
- [ ] 更新 test_static_assets.py 中的模块路径引用

## 🟠 P1: 文档统一到 docs/
- [ ] 移动根目录 ATE_*.md → docs/reference/
- [ ] 移动 tasks/ 文档 → docs/tasks/
- [ ] 合并 docs/superpowers/ → docs/
- [ ] 清理空目录

## 🟡 P2: 根目录清理
- [ ] 移动 lq_dataprase.spec → scripts/pyinstaller/
- [ ] 更新 build.bat 中的 spec 路径
- [ ] 更新 .gitignore

## 🟡 P2: data_correlation 合并到 analysis
- [ ] 等待探索 Agent 返回分析结果
- [ ] 移动文件并更新 imports
- [ ] 更新 INSTALLED_APPS / urls

## 🟢 P3: 删除 .venv-wsl/
- [ ] rm -rf .venv-wsl/

## 验证
- [ ] git status 确认
- [ ] Django check 通过
- [ ] 后端测试通过
- [ ] 前端 vue-tsc 通过
- [ ] 前端 build 通过
