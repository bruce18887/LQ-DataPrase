---
alwaysApply: false
---
# 规则索引
前端Vue文件不得超过500行,超过请考虑拆分组件或模块。
后端Python文件不得超过500行,超过请考虑拆分模块或函数。
旧项目源码在C:\Users\Administrator\Desktop\DataPrase\DataPhrase\src，需要对比时直接查看。
原始数据在Data\SampleData目录下，需要检查数据结构时请直接查看。
当用户的请求涉及以下任一场景时，**必须先读取** `.trae/rules/project_rules.md` 获取完整约束：

- 编写 Django 后端代码（Model / View / Serializer / Service / Celery Task / API）
- 编写 Vue 前端代码（Page / Component / Store / Router / Composable）
- 新增或修改数据模型、API 接口、前端路由
- 处理文件上传下载、图表渲染、用户认证、权限控制
- 进行 Streamlit → Django+Vue 的代码迁移或重构
- 涉及数据库、缓存、存储、部署等技术选型或配置
- 代码审查或方案评审

简记：**只要涉及本项目的 Django 后端或 Vue 前端代码，就去查大规则。**
