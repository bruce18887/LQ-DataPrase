<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import MockFrame from './MockFrame.vue'
import { toast } from '../useUi'
const groups = [['display', '显示设置'], ['table', '表格设置'], ['cpk', 'CPK 阈值'], ['template', '导出模板'], ['sftp', 'SFTP 设置'], ['conn', '连接'], ['paths', '存储路径']]
const cur = ref('display')
const cfg = reactive({ renderer: 'SVG（推荐）', dpi: 100, layout: true, wrap: false, pagesize: '100', a: 1.67, b: 1.33, c: 1.0, timeout: 300, tpl: '{product}_{stage}_{date}', sftpTimeout: 120, conn: '本机内嵌', data: '~/LQ-DataPrase/data', tmp: '~/LQ-DataPrase/tmp' })
const hid = reactive<Record<string, boolean>>({ Part_No: true, X_COORD: true, Y_COORD: false, TestTime: false })
const dirty = ref(false)
const grades = computed(() => {
  const top = Math.max(2.2, cfg.a + 0.4)
  return [
    { flex: Math.max(0.4, cfg.c), bg: 'var(--intro-err)', t: `D <${cfg.c.toFixed(2)}` },
    { flex: Math.max(0.4, cfg.b - cfg.c), bg: 'var(--intro-warn)', t: `C ≥${cfg.c.toFixed(2)}` },
    { flex: Math.max(0.4, cfg.a - cfg.b), bg: 'var(--intro-info)', t: `B ≥${cfg.b.toFixed(2)}` },
    { flex: Math.max(0.4, top - cfg.a), bg: 'var(--intro-ok)', t: `A ≥${cfg.a.toFixed(2)}` },
  ]
})
function touch() { dirty.value = true }
function save() { dirty.value = false; toast('已保存（演示）· 标「保存即生效」的项立即生效；连接 / 路径需重启') }
function defaults() {
  Object.assign(cfg, { renderer: 'SVG（推荐）', dpi: 100, layout: true, wrap: false, pagesize: '100', a: 1.67, b: 1.33, c: 1.0, timeout: 300, tpl: '{product}_{stage}_{date}', sftpTimeout: 120, conn: '本机内嵌', data: '~/LQ-DataPrase/data', tmp: '~/LQ-DataPrase/tmp' })
  dirty.value = true
  toast('已恢复默认值（演示）· 记得保存')
}
function insertVar(v: string) { cfg.tpl += v; touch() }
</script>

<template>
  <MockFrame title="系统设置">
    <div class="rail">
      <div class="rail-nav">
        <button v-for="g in groups" :key="g[0]" :class="{ on: cur === g[0] }" @click="cur = g[0]">{{ g[1] }}</button>
      </div>
      <div>
        <div v-if="cur === 'display'" class="rail-pane">
          <div class="setrow"><span class="sl"><b>ECharts 渲染器</b><span>SVG 推荐：无损缩放、支持 CSS 操控；Canvas 大数据量性能更好</span></span>
            <select v-model="cfg.renderer" class="m-select" @change="touch"><option>SVG（推荐）</option><option>Canvas</option></select><span class="eff now">保存即生效</span></div>
          <div class="setrow"><span class="sl"><b>图表 DPI</b><span>导出 Excel / PPT 内嵌图像素密度；调大显著增大导出体积</span></span>
            <input type="range" min="72" max="600" v-model.number="cfg.dpi" style="width:150px" @input="touch"><span class="m-label">{{ cfg.dpi }}</span><span class="eff now">保存即生效</span></div>
          <div class="setrow"><span class="sl"><b>图表布局记忆</b><span>记住单文件分析的图表布局与勾选，跟随账号</span></span>
            <label class="m-label"><input type="checkbox" v-model="cfg.layout" @change="touch"> 开启</label>
            <button class="m-btn" @click="toast('图表布局已恢复默认（演示）'); touch()">恢复默认布局</button><span class="eff now">保存即生效</span></div>
        </div>
        <div v-if="cur === 'table'" class="rail-pane">
          <div class="setrow"><span class="sl"><b>文件名换行</b><span>列表中长文件名是否折行显示</span></span><label class="m-label"><input type="checkbox" v-model="cfg.wrap" @change="touch"> 开启</label><span class="eff now">保存即生效</span></div>
          <div class="setrow"><span class="sl"><b>每页条数</b><span>表格分页大小</span></span><select v-model="cfg.pagesize" class="m-select" @change="touch"><option>50</option><option>100</option><option>200</option><option>500</option></select><span class="eff now">保存即生效</span></div>
          <div class="setrow"><span class="sl"><b>默认隐藏列</b><span>按平台分组的元数据列默认隐藏</span></span>
            <span class="chips"><button v-for="(v, k) in hid" :key="k" class="chipx" :class="{ on: hid[k] }" @click="hid[k] = !hid[k]; touch()">{{ k }}</button></span><span class="eff now">保存即生效</span></div>
        </div>
        <div v-if="cur === 'cpk'" class="rail-pane">
          <div class="setrow"><span class="sl"><b>A 级下限</b><span>CPK ≥ 此值为 A</span></span><input v-model.number="cfg.a" type="number" step="0.01" class="m-input" style="width:80px" @input="touch"><span class="eff now">保存即生效</span></div>
          <div class="setrow"><span class="sl"><b>B 级下限</b><span>CPK ≥ 此值为 B</span></span><input v-model.number="cfg.b" type="number" step="0.01" class="m-input" style="width:80px" @input="touch"><span class="eff now">保存即生效</span></div>
          <div class="setrow"><span class="sl"><b>C 级下限</b><span>CPK ≥ 此值为 C，其余 D</span></span><input v-model.number="cfg.c" type="number" step="0.01" class="m-input" style="width:80px" @input="touch"><span class="eff now">保存即生效</span></div>
          <div class="gradestrip"><div v-for="(g, i) in grades" :key="i" :style="{ flex: g.flex, background: g.bg }">{{ g.t }}</div></div>
          <div class="m-foot">改完全平台分级、告警与导出同步生效。示例：CPK 0.7945 落在 D 级。</div>
        </div>
        <div v-if="cur === 'template'" class="rail-pane">
          <div class="setrow"><span class="sl"><b>导出超时（秒）</b><span>后台作业超时上限</span></span><input v-model.number="cfg.timeout" type="number" class="m-input" style="width:90px" @input="touch"><span class="eff now">保存即生效</span></div>
          <div class="setrow"><span class="sl"><b>文件名模板（10 类）</b><span>点变量追加到模板末尾</span></span>
            <input v-model="cfg.tpl" class="m-input" style="flex:1;min-width:200px" @input="touch">
            <span class="chips"><button v-for="v in ['{product}', '{stage}', '{date}', '{lot}', '{site}']" :key="v" class="chipx" @click="insertVar(v)">{{ v }}</button></span></div>
          <div class="m-foot">真实应用含 10 类导出文件名模板（单文件报表 / 批量 Excel / PPT / Gage / Buyoff / 权重 / 对比 / 审计 …），此处演示其一。</div>
        </div>
        <div v-if="cur === 'sftp'" class="rail-pane">
          <div class="setrow"><span class="sl"><b>SFTP 下载超时（秒）</b><span>单文件下载超时上限</span></span><input v-model.number="cfg.sftpTimeout" type="number" class="m-input" style="width:90px" @input="touch"><span class="eff now">保存即生效</span></div>
          <div class="m-foot">搜索并发（1–8，默认 4）在搜索页控制，见 §6。</div>
        </div>
        <div v-if="cur === 'conn'" class="rail-pane">
          <div class="setrow"><span class="sl"><b>后端连接形态</b><span>本机内嵌 / 远端服务器</span></span><select v-model="cfg.conn" class="m-select" @change="touch"><option>本机内嵌</option><option>远端</option></select><span class="eff restart">需重启</span></div>
          <div class="intro-note warn">更改连接形态需重启应用生效；服务器形态下 SFTP 存密需重新录入。</div>
        </div>
        <div v-if="cur === 'paths'" class="rail-pane">
          <div class="setrow"><span class="sl"><b>数据目录</b><span>仅管理员可见</span></span><input v-model="cfg.data" class="m-input" style="flex:1;min-width:200px" @input="touch"><span class="eff restart">需重启 + 迁移</span></div>
          <div class="setrow"><span class="sl"><b>临时目录</b><span>解析与导出中间产物</span></span><input v-model="cfg.tmp" class="m-input" style="flex:1;min-width:200px" @input="touch"><span class="eff restart">需重启 + 迁移</span></div>
          <div class="intro-note warn">改路径后重启会触发存量数据迁移；迁移完成前不要断电或强杀进程。</div>
        </div>
      </div>
    </div>
    <div class="m-toolbar" style="margin:14px 0 0">
      <button class="m-btn pri" :disabled="!dirty" @click="save">保存设置</button>
      <button class="m-btn" @click="defaults">恢复默认</button>
      <span class="m-label">{{ dirty ? '有未保存改动' : '无改动' }}</span>
    </div>
  </MockFrame>
</template>