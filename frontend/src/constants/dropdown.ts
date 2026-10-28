/**
 * 非虚拟化下拉（`el-select` + `el-option`）的渲染封顶值。
 *
 * 为什么要有这个数：`el-select` 不做虚拟滚动（EP 2.14 里虚拟化的是自带的
 * `el-select-v2`，`el-select` 甚至没有 `virtual` 这个 prop），而每个 `el-option`
 * 是一个完整组件实例。本仓真实数据面上，测试项可达 1,702 个（SingleParamTab.vue:505
 * 记的实测文件）、测试列可达上千、序列号上万 —— 原样挂载即冻结主线程
 * （SerialSelector.vue:70 的注释就是先按 300 封顶时踩出来的）。
 *
 * 封顶只作用于**渲染**：过滤/计数/全选仍作用于完整集合，用户靠输入缩小范围。
 * 因此每个用到它的下拉都必须给出可见提示（见各组件的 .match-hint），
 * 不能让人以为列表只有这些。
 */
export const DROPDOWN_RENDER_CAP = 300
