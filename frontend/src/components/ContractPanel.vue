<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  contract: { type: Object, required: true },
})

const showAllClauses = ref(false)

const fields = computed(() => props.contract.fields || [])
const parties = computed(() => props.contract.parties || [])
const clauses = computed(() => props.contract.clauses || [])
const warnings = computed(() => props.contract.warnings || [])

const visibleClauses = computed(() =>
  showAllClauses.value ? clauses.value : clauses.value.slice(0, 4),
)

// 解析质量门禁（L4）：blocked 必须置顶警示，不能只当作一条普通 warning
const gate = computed(() => props.contract.gate || null)
const gateLevel = computed(() => gate.value?.level || 'ok')

const hitCount = computed(() => fields.value.filter((item) => item.value).length)
const hitRate = computed(() =>
  fields.value.length ? Math.round((hitCount.value / fields.value.length) * 100) : 0,
)

function confidenceClass(confidence) {
  if (confidence >= 0.8) return 'high'
  if (confidence >= 0.5) return 'mid'
  return 'low'
}
</script>

<template>
  <div class="fade-in stack">
    <div class="card card-pad">
      <div class="head">
        <div class="head-main">
          <h2>{{ contract.title || '未命名合同' }}</h2>
          <p class="filename mono">{{ contract.source_file }}</p>
        </div>
        <div class="badges">
          <span class="tag tag-green">抽取器 {{ contract.extractor }}</span>
          <span v-if="contract.used_ocr" class="tag tag-amber">经由 OCR</span>
          <span class="tag tag-slate">{{ contract.page_count }} 页</span>
          <span class="tag tag-slate">{{ contract.char_count }} 字</span>
        </div>
      </div>

      <div class="metrics">
        <div class="metric">
          <span class="metric-value">{{ hitCount }}<small>/{{ fields.length }}</small></span>
          <span class="metric-label">字段抽取</span>
        </div>
        <div class="metric">
          <span class="metric-value">{{ hitRate }}<small>%</small></span>
          <span class="metric-label">命中率</span>
        </div>
        <div class="metric">
          <span class="metric-value">{{ parties.length }}</span>
          <span class="metric-label">合同主体</span>
        </div>
        <div class="metric">
          <span class="metric-value">{{ clauses.length }}</span>
          <span class="metric-label">条款数量</span>
        </div>
      </div>
    </div>

    <!-- 解析质量门禁：blocked / degraded 必须在最上方就能看到 -->
    <div
      v-if="gate && gateLevel !== 'ok'"
      class="card card-pad gate-card"
      :class="`gate-${gateLevel}`"
    >
      <div class="gate-head">
        <span class="tag" :class="gateLevel === 'blocked' ? 'tag-red' : 'tag-amber'">
          {{ gateLevel === 'blocked' ? '解析失败' : '解析不完整' }}
        </span>
        <strong>{{ gate.summary }}</strong>
      </div>
      <ul>
        <li v-for="(failure, index) in gate.failures" :key="index">
          <b>{{ failure.label }}</b>：{{ failure.detail }}
        </li>
      </ul>
      <p v-if="gate.escalated" class="gate-escalation">
        L1→L2 升级：触发「{{ gate.escalation_reason }}」→ {{ gate.escalation_note }}
      </p>
      <p class="gate-impact">
        {{ gateLevel === 'blocked'
          ? '下游企业核验 / 标准校验 / 履约模拟的结论不可信，请先修复解析或人工补录。'
          : '下游结论需附带上述缺失标注，不得当作完整结论使用。' }}
      </p>
    </div>

    <div v-if="warnings.length" class="card card-pad warning-card">
      <h3>提示</h3>
      <ul>
        <li v-for="(warning, index) in warnings" :key="index">{{ warning }}</li>
      </ul>
    </div>

    <div v-if="parties.length" class="card card-pad">
      <h3 class="section-title">合同主体</h3>
      <div class="parties">
        <div v-for="(party, index) in parties" :key="index" class="party">
          <span class="party-role">{{ party.role }}</span>
          <span class="party-name">{{ party.name || '未识别' }}</span>
          <span v-if="party.credit_code" class="party-code mono">
            信用代码 {{ party.credit_code }}
          </span>
        </div>
      </div>
    </div>

    <div class="card card-pad">
      <h3 class="section-title">结构化字段</h3>
      <ul class="fields">
        <li v-for="field in fields" :key="field.key" class="field">
          <div class="field-head">
            <span class="field-label">{{ field.label }}</span>
            <span class="field-value" :class="{ empty: !field.value }">
              {{ field.value || '未抽取到' }}
            </span>
            <span
              v-if="field.value"
              class="confidence"
              :class="confidenceClass(field.confidence)"
              :title="`置信度 ${field.confidence}`"
            >
              {{ Math.round(field.confidence * 100) }}%
            </span>
          </div>
          <p v-if="field.evidence" class="evidence">
            <span class="evidence-label">原文依据</span>
            {{ field.evidence }}
          </p>
        </li>
      </ul>
    </div>

    <div v-if="clauses.length" class="card card-pad">
      <div class="section-head">
        <h3 class="section-title">条款切分</h3>
        <button v-if="clauses.length > 4" class="link" @click="showAllClauses = !showAllClauses">
          {{ showAllClauses ? '收起' : `展开全部 ${clauses.length} 条` }}
        </button>
      </div>

      <ul class="clauses">
        <li v-for="clause in visibleClauses" :key="clause.index" class="clause">
          <span class="clause-no">第 {{ clause.index }} 条</span>
          <div class="clause-body">
            <span v-if="clause.title" class="clause-title">{{ clause.title }}</span>
            <p class="clause-text">{{ clause.content }}</p>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.head-main h2 {
  font-size: 19px;
  font-weight: 600;
  letter-spacing: 0.2px;
}

.filename {
  font-size: 12px;
  color: var(--slate-500);
  margin-top: 2px;
}

.badges {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--slate-200);
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.metric-value {
  font-size: 22px;
  font-weight: 600;
  color: var(--green-700);
  line-height: 1.2;
}

.metric-value small {
  font-size: 13px;
  color: var(--slate-500);
  font-weight: 400;
}

.metric-label {
  font-size: 12px;
  color: var(--slate-500);
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 13px;
}

.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 13px;
}

.section-head .section-title {
  margin-bottom: 0;
}

.link {
  font-size: 12.5px;
  color: var(--green-600);
}

.link:hover {
  text-decoration: underline;
}

/* ---------- 主体 ---------- */

.parties {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 11px;
}

.party {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--slate-50);
  border: 1px solid var(--slate-200);
}

.party-role {
  font-size: 12px;
  color: var(--green-700);
  font-weight: 600;
}

.party-name {
  font-size: 14px;
  font-weight: 500;
}

.party-code {
  font-size: 11.5px;
  color: var(--slate-500);
}

/* ---------- 字段 ---------- */

.fields {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.field {
  padding: 11px 12px;
  border-radius: var(--radius-sm);
  transition: background 0.15s ease;
}

.field:hover {
  background: var(--slate-50);
}

.field-head {
  display: grid;
  grid-template-columns: 92px 1fr auto;
  align-items: baseline;
  gap: 12px;
}

.field-label {
  font-size: 13px;
  color: var(--slate-500);
}

.field-value {
  font-size: 14px;
  font-weight: 500;
  word-break: break-word;
}

.field-value.empty {
  color: var(--slate-300);
  font-weight: 400;
}

.confidence {
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  white-space: nowrap;
}

.confidence.high {
  background: var(--green-100);
  color: var(--green-700);
}

.confidence.mid {
  background: var(--amber-100);
  color: var(--amber-600);
}

.confidence.low {
  background: var(--slate-100);
  color: var(--slate-500);
}

.evidence {
  margin-top: 5px;
  margin-left: 104px;
  padding-left: 10px;
  border-left: 2px solid var(--slate-200);
  font-size: 12.5px;
  color: var(--slate-500);
  line-height: 1.6;
}

.evidence-label {
  display: inline-block;
  margin-right: 6px;
  padding: 0 5px;
  border-radius: 4px;
  background: var(--slate-100);
  color: var(--slate-500);
  font-size: 11px;
}

/* ---------- 条款 ---------- */

.clauses {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.clause {
  display: grid;
  grid-template-columns: 62px 1fr;
  gap: 12px;
  padding: 12px 13px;
  border-radius: var(--radius-sm);
  background: var(--slate-50);
  border: 1px solid var(--slate-200);
}

.clause-no {
  font-size: 12px;
  color: var(--green-700);
  font-weight: 600;
}

.clause-title {
  display: inline-block;
  font-size: 13.5px;
  font-weight: 600;
  margin-bottom: 3px;
}

.clause-text {
  font-size: 13px;
  color: var(--slate-700);
  line-height: 1.75;
  white-space: pre-wrap;
}

.gate-card {
  font-size: 13.5px;
}

.gate-blocked {
  background: #fef2f2;
  border-color: #fecaca;
}

.gate-degraded {
  background: #fffbeb;
  border-color: #fde68a;
}

.gate-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.gate-blocked .gate-head strong {
  color: var(--red-600, #dc2626);
}

.gate-degraded .gate-head strong {
  color: var(--amber-600);
}

.gate-card ul {
  padding-left: 18px;
  color: var(--slate-600, #475569);
}

.gate-card li + li {
  margin-top: 3px;
}

.gate-escalation {
  margin-top: 8px;
  color: var(--slate-500, #64748b);
  font-size: 12.5px;
}

.gate-impact {
  margin-top: 8px;
  font-size: 12.5px;
  font-weight: 600;
}

.warning-card {
  background: #fffbeb;
  border-color: #fde68a;
}

.warning-card h3 {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--amber-600);
  margin-bottom: 7px;
}

.warning-card ul {
  padding-left: 18px;
  color: var(--amber-600);
  font-size: 13px;
}

.warning-card li + li {
  margin-top: 3px;
}

@media (max-width: 720px) {
  .metrics {
    grid-template-columns: repeat(2, 1fr);
  }

  .field-head {
    grid-template-columns: 1fr;
    gap: 3px;
  }

  .evidence {
    margin-left: 0;
  }
}
</style>
