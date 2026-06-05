# SFTP 浏览器下载改进设计

**日期:** 2026-06-04
**范围:** SftpBrowser.vue + sftp views.py

## 需求

1. 目录下载按钮从工具栏移到表格操作列
2. 修复目录下载 bug
3. 下载按钮内嵌进度（百分比 + 速率）

## 设计

### 1. 目录下载按钮位置

- **移除**工具栏中的"下载目录"按钮
- 操作列：目录行显示 `[下载] [打开]`，文件行不变 `[下载] [解析]`
- 列宽 220px → 180px

### 2. 目录下载 Bug 修复

**后端 `sftp/views.py`：**
- 路径拼接统一 `remote_dir.rstrip('/') + '/' + name`，避免双斜杠
- `_collect_files` 异常记录到 logger，不完全静默
- ZIP 写入循环中单文件失败记录日志但继续

**前端 `SftpBrowser.vue`：**
- 目录下载函数传入正确路径（用 `row.name` 拼接，非直接用 `currentPath`）

### 3. 按钮内嵌进度

**状态模型：**
```typescript
// 每个下载任务一个状态
interface DownloadProgress {
  loaded: number       // 已下载字节
  total: number        // 总字节（可能为0=未知）
  speed: number        // bytes/s
  percent: number      // 0-100（total=0时为-1）
  startTime: number
}
```

**UI 变化：**
- 下载中：按钮文字变为 `⟳ 下载中 65%`，带 loading 旋转
- 按钮下方显示一行小字：`2.3 MB/s · ~3s`
- 下载完成：恢复原状，ElMessage 提示

**实现：**
- axios 请求配置 `onDownloadProgress` 回调
- 滑动平均计算速率（每 500ms 更新一次）
- 单文件下载、目录下载、批量下载均支持

**不确定大小时：**
- 只显示已下载量 + 速率，不显示百分比
- 按钮显示 `⟳ 下载中 12.5MB`
