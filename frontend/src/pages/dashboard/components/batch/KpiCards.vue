<template>
  <el-row :gutter="16" class="kpi-row">
    <el-col :span="6">
      <div class="kpi-card kpi-blue">
        <div class="kpi-label">📥 CP+FT 投入数量</div>
        <div class="kpi-value">{{ kpi.input_total?.toLocaleString() }}</div>
      </div>
    </el-col>
    <el-col :span="6">
      <div class="kpi-card kpi-green">
        <div class="kpi-label">✅ 总 Pass</div>
        <div class="kpi-value">{{ kpi.pass?.toLocaleString() }}</div>
      </div>
    </el-col>
    <el-col :span="6">
      <div class="kpi-card kpi-orange">
        <div class="kpi-label">📈 整体良率</div>
        <div class="kpi-value">{{ kpi.overall_yield }}%</div>
        <div class="kpi-sub">Bin1 / CP+FT投入</div>
      </div>
    </el-col>
    <el-col :span="6">
      <div class="kpi-card kpi-purple">
        <div class="kpi-label">❌ 总 Fail</div>
        <div class="kpi-value">{{ kpi.fail?.toLocaleString() }}</div>
      </div>
    </el-col>
  </el-row>
</template>

<script setup lang="ts">
defineProps<{
  kpi: {
    input_total: number
    pass: number
    overall_yield: number
    fail: number
  }
}>()
</script>

<style scoped>
.kpi-row {
  margin-bottom: 20px;
}

.kpi-card {
  padding: 20px 16px;
  border-radius: 10px;
  text-align: center;
  color: #fff;
}

.kpi-blue { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
.kpi-green { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
.kpi-orange { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
.kpi-purple { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }

.kpi-value {
  font-size: 28px;
  font-weight: 700;
  margin: 8px 0 4px;
}

.kpi-label {
  font-size: 13px;
  opacity: 0.9;
}

.kpi-sub {
  font-size: 11px;
  opacity: 0.7;
  margin-top: 2px;
}
</style>
