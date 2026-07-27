# 异常值裁剪 RDL 修复计划

**问题**: 当前异常值检测使用 IQR 方法，但没有考虑 RDL（规格限）。在 RDL 范围内的数据不应该被视为异常值。

**目标**: 修改异常值检测逻辑，使其考虑 RDL，将 RDL 范围内的数据排除在异常值检测之外。

---

## 问题分析

### 当前实现
1. `detect_outliers_iqr(data, include_values)` 使用 IQR 方法检测异常值
2. IQR 边界: `lower_bound = Q1 - 1.5 * IQR`, `upper_bound = Q3 + 1.5 * IQR`
3. 没有考虑 RDL（规格限）范围

### 问题场景
- 数据点在 RDL 范围内（如 LSL=24.0, USL=26.0）
- 但 IQR 边界可能更窄（如 lower_bound=24.5, upper_bound=25.5）
- 导致 RDL 范围内但 IQR 范围外的数据被错误标记为异常值

### 用户需求
"在rowdatalimit范围内的肯定不是异常值"

### 调用点分析
| 调用点 | 能否获取 RDL | 备注 |
|--------|-------------|------|
| `histogram.py` | ✅ 可以 | 已有 `stats['rdl']` |
| `serial_distribution.py` | ✅ 可以 | 已有 `stats['rdl']` |
| `correlation.py` | ❌ 不能 | 需要修改函数签名 |
| `computations.py` (QQ plot) | ❌ 不能 | 需要修改函数签名 |

---

## 解决方案

### 方案 1: 修改 `detect_outliers_iqr` 函数（推荐）
- 添加可选参数 `spec_limits: tuple = None`
- 如果提供 spec_limits，则将异常值边界扩展到 spec_limits
- 保证 spec_limits 范围内的数据不被视为异常值

### 方案 2: 在调用方处理
- 在 `histogram.py`, `serial_distribution.py` 等调用方中
- 先调用 `detect_outliers_iqr` 获取 IQR 边界
- 然后与 RDL 合并，取更宽的范围
- 这种方案不需要修改核心函数

### 推荐方案: 方案 1
- 更符合单一职责原则
- 所有调用方自动受益
- 逻辑更清晰

---

## 实现步骤

### Step 1: 修改 `apps/analysis/services/statistics/outliers.py` ✅
- 添加 `spec_limits` 参数
- 如果提供 spec_limits，将边界扩展到 spec_limits
- 更新函数文档

### Step 2: 更新所有调用方 ✅
- `histogram.py`: 传递 `stats['rdl']` 作为 spec_limits
- `serial_distribution.py`: 传递 `stats['rdl']` 作为 spec_limits
- `correlation.py`: 传递 x/y 轴的 spec_limits（如果可用）
- `computations.py`: 传递 spec_limits（如果可用）

### Step 3: 更新单元测试 ✅
- 添加测试用例: spec_limits 范围内的数据不应被视为异常值
- 添加测试用例: spec_limits 范围外的数据仍应被视为异常值

### Step 4: 更新前端显示
- `OutlierHintBar.vue`: 显示 RDL 范围信息（可选）
- `HistogramChart.vue`: 确保裁剪逻辑与后端一致

### Step 5: 添加 E2E 测试
- 测试 RDL 模式下异常值裁剪行为
- 验证 spec_limits 范围内的数据不被裁剪

---

## 验证标准

1. **单元测试**: 通过所有新增和现有测试 ✅
2. **E2E 测试**: RDL 模式下异常值裁剪行为正确
3. **手动验证**:
   - 数据在 RDL 范围内但 IQR 范围外时，不被标记为异常值
   - 数据在 RDL 范围外时，仍被标记为异常值
   - 前端显示与后端逻辑一致

---

## 风险与注意事项

1. **向后兼容性**: 添加可选参数，不影响现有调用 ✅
2. **性能影响**: minimal，只是多一次边界比较 ✅
3. **前端同步**: 确保前端裁剪逻辑与后端一致

---

## 附加功能: IQR 倍数可配置

### 需求
用户希望保留"不是特别离谱"的异常值，只裁剪极端异常值。

### 实现
添加 `iqr_multiplier` 参数，允许用户选择：
- **严格 (1.5x IQR)**: 标准阈值，检测轻微异常值
- **宽松 (3.0x IQR)**: 仅检测极端异常值，保留更多数据点

### 修改内容
1. `outliers.py`: 添加 `iqr_multiplier` 参数
2. `histogram.py`: 传递 `iqr_multiplier` 参数
3. `analysis_views.py`: 从请求中获取 `iqr_multiplier` 参数
4. `analysis.ts`: API 调用添加 `iqr_multiplier` 参数
5. `useHistogram.ts`: 传递 `iqr_multiplier` 参数
6. `SingleParamTab.vue`: 添加 `iqrMultiplier` 状态
7. `AnalysisPage.vue`: 添加敏感度选择器
8. `stores/analysis.ts`: 添加 `iqrMultiplier` 状态

### 测试结果
- 所有单元测试通过 ✅
- IQR 倍数测试通过 ✅

---

## 附加功能: 范围对比表格使用裁剪后统计值

### 需求
范围对比表格应该显示裁剪后的统计数据，而不是原始数据。

### 实现
1. 后端返回裁剪后的统计值：
   - `filtered_mean`: 裁剪后的均值
   - `filtered_std`: 裁剪后的标准差
   - `filtered_data_min`: 裁剪后的最小值
   - `filtered_data_max`: 裁剪后的最大值
2. 前端使用裁剪后的统计值：
   - 当有异常值时，显示裁剪后的均值、标准差、最小值、最大值
   - 当没有异常值时，显示原始统计值
   - 3/4/6 Sigma 范围使用裁剪后的均值和标准差计算
   - 当数据被裁剪时，在 Data Range、3/4/6 Sigma 标签后加上"(cut)"后缀

### 修改内容
1. `histogram.py`: 计算并返回裁剪后的统计值
2. `useHistogram.ts`: 使用裁剪后的统计值更新范围对比表格，包括 3/4/6 Sigma，并添加"(cut)"后缀

### 测试结果
- 所有单元测试通过 ✅
