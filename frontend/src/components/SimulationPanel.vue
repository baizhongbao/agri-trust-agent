<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  report: { type: Object, required: true },
})

const showSteps = ref({ hit: {} })

const scenarios = computed(() => props.report.scenarios || [])
const rulebookTotal = computed(() => props.report.rulebook_total || 0)

const scenarioMeta = {
  price_fluctuation: { label: '价格波动', icon: '↕', cls: 'tag-sky' },
  natural_disaster: { label: '自然灾害', icon: '⚠', cls: 'tag-amber' },
  party_breach: { label: '一方违约', icon: '⚖', cls: 'tag-red' },
}

function metaOf(scenario) {
  return scenarioMeta[scenario.scenario] || { label: scenario.label || scenario.scenario, icon: '○', cls: 'tag-slate' }
}

function toggleSteps(scenarioId) {
  showSteps.value.hit[scenarioId] = !showSteps.value.hit[scenarioId]
}

function fmt(value, suffix = '') {
  if (value === null || value === undefined || value === '') return '—'
  return Number(value).toLocaleString('zh-CN', {
    maximumFractionDigits: 2,
  }) + suffix
}

function fmtMoney(value) {
  if (value === null || value === undefined) return '—'
  return `¥${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
}

function fmtStepResult(value) {
  if (value === null || value === undefined) return '—'
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function quote(text) {
  return String(text || '')
}
</script>

<template>
  <div class="fade-in stack">
    <div class="card card-pad">
      <div class="head">
        <div>
          <h2>履约模拟结果</h2>
          <p class="sub">{{ report.contract_title || '未命名合同' }}</p>
        </div>
        <div class="head-badges">
          <span class="tag tag-slate" title="裁判规则库规模">{{ rulebookTotal }} 条判例</span>
        </div>
      </div>
    </div>

    <div
      v-for="scenario in scenarios"
      :key="scenario.scenario"
      class="card card-pad scenario"
    >
      <div class="scenario-head">
        <div class="scenario-title">
          <span class="scenario-icon">{{ metaOf(scenario).icon }}</span>
          <h3>{{ metaOf(scenario).label }}</h3>
          <span class="tag" :class="metaOf(scenario).cls">{{ scenario.scenario }}</span>
        </div>
        <span
          v-if="scenario.computable"
          class="tag tag-green"
          title="数值已由程序计算，步骤可复核"
        >
          可计算
        </span>
        <span v-else class="tag tag-slate" title="缺少数值输入，无法定量计算">不可计算</span>
      </div>

      <p v-if="scenario.reason && !scenario.computable" class="reason note">
        {{ scenario.reason }}
      </p>

      <template v-if="scenario.computable">
        <p class="summary">{{ scenario.summary }}</p>

        <div class="stat-grid">
          <div v-if="scenario.params?.contract_amount !== undefined" class="stat">
            <span class="stat-badge k-badge">合同金额</span>
            <span class="stat-value">{{ fmtMoney(scenario.params.contract_amount) }}</span>
          </div>
          <div v-if="scenario.params?.market_value !== undefined" class="stat">
            <span class="stat-badge v-badge">市场交易额</span>
            <span class="stat-value">{{ fmtMoney(scenario.params.market_value) }}</span>
          </div>
          <div v-if="scenario.params?.deviation !== undefined" class="stat">
            <span class="stat-badge d-badge">偏离额</span>
            <span class="stat-value" :class="{ neg: scenario.params.deviation < 0 }">
              {{ fmtMoney(scenario.params.deviation) }}
            </span>
          </div>
          <div v-if="scenario.params?.deliverable_quantity !== undefined" class="stat">
            <span class="stat-badge q-badge">可交付量</span>
            <span class="stat-value">{{ fmt(scenario.params.deliverable_quantity) }}</span>
          </div>
          <div v-if="scenario.params?.shortfall_quantity !== undefined" class="stat">
            <span class="stat-badge s-badge">交付缺口</span>
            <span class="stat-value" :class="{ neg: scenario.params.shortfall_quantity > 0 }">
              {{ fmt(scenario.params.shortfall_quantity) }}
            </span>
          </div>
          <div v-if="scenario.params?.loss_amount !== undefined" class="stat">
            <span class="stat-badge l-badge">缺口货值</span>
            <span class="stat-value">{{ fmtMoney(scenario.params.loss_amount) }}</span>
          </div>
          <div v-if="scenario.params?.penalty_value !== undefined" class="stat">
            <span class="stat-badge p-badge">违约金</span>
            <span class="stat-value">{{ fmtMoney(scenario.params.penalty_value) }}</span>
          </div>
          <div v-if="scenario.params?.breach_incentive_party" class="stat stat-wide">
            <span class="stat-badge i-badge">毁约诱因</span>
            <span class="stat-value">{{ scenario.params.breach_incentive_party }}</span>
          </div>
        </div>
      </template>

      <div v-if="scenario.legal_note" class="legal-note">
        <strong>参考法条</strong>
        <span>{{ scenario.legal_note }}</span>
      </div>

      <div v-if="scenario.analysis" class="analysis">
        <div class="analysis-head">
          <h4>风险分析</h4>
          <span v-if="scenario.analysis_provider" class="tag tag-slate">
            {{ scenario.analysis_provider === 'mock' ? '模板分析' : scenario.analysis_provider }}
          </span>
        </div>
        <p class="analysis-text">{{ scenario.analysis }}</p>
      </div>

      <div v-if="scenario.citations?.length" class="citations">
        <h4>相关判例</h4>
        <ul>
          <li v-for="cite in scenario.citations" :key="cite.case_no + cite.title" class="cite">
            <div class="cite-head">
              <span class="cite-case mono">{{ cite.case_no }}</span>
              <span class="cite-court">{{ cite.court }}</span>
              <span v-if="cite.signal" class="cite-signal">{{ cite.signal }}</span>
            </div>
            <p v-if="cite.ruling" class="cite-ruling">{{ quote(cite.ruling) }}</p>
            <p v-if="cite.lesson" class="cite-lesson">{{ quote(cite.lesson) }}</p>
          </li>
        </ul>
      </div>

      <div v-if="scenario.calc_steps?.length" class="steps">
        <button class="link steps-toggle" @click="toggleSteps(scenario.scenario)">
          {{ showSteps.hit[scenario.scenario] ? '收起计算过程' : '查看计算过程' }}
        </button>
        <ol v-if="showSteps.hit[scenario.scenario]" class="steps-list">
          <li v-for="(step, index) in scenario.calc_steps" :key="index" class="step">
            <span class="step-formula">{{ step.formula }}</span>
            <span class="step-result mono">{{ fmtStepResult(step.result) }}</span>
          </li>
        </ol>
      </div>
    </div>

    <p class="disclaimer">{{ report.disclaimer }}</p>
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
}

.head h2 {
  font-size: 19px;
  font-weight: 600;
}

.sub {
  font-size: 12.5px;
  color: var(--slate-500);
  margin-top: 2px;
}

.head-badges {
  display: flex;
  gap: 6px;
}

/* ---------- 情景 ---------- */

.scenario {
  border-left: 3px solid var(--slate-300);
}

.scenario-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.scenario-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.scenario-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: var(--slate-100);
  color: var(--slate-500);
  font-size: 15px;
}

.scenario-title h3 {
  font-size: 16px;
  font-weight: 600;
}

.summary {
  margin-top: 10px;
  font-size: 13px;
  color: var(--slate-700);
  line-height: 1.75;
}

.reason {
  font-size: 13px;
  color: var(--amber-600);
}

/* ---------- 数值 ---------- */

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--slate-50);
  border: 1px solid var(--slate-200);
}

.stat-wide {
  grid-column: 1 / -1;
}

.stat-badge {
  font-size: 11px;
  padding: 0 6px;
  border-radius: 4px;
  align-self: flex-start;
}

.k-badge {
  background: var(--green-100);
  color: var(--green-700);
}

.v-badge {
  background: var(--slate-100);
  color: var(--slate-700);
}

.d-badge {
  background: var(--amber-100);
  color: var(--amber-600);
}

.q-badge {
  background: var(--green-100);
  color: var(--green-700);
}

.s-badge {
  background: var(--red-100);
  color: var(--red-600);
}

.l-badge {
  background: var(--amber-100);
  color: var(--amber-600);
}

.p-badge {
  background: var(--red-100);
  color: var(--red-600);
}

.i-badge {
  background: var(--slate-100);
  color: var(--slate-700);
}

.stat-value {
  font-size: 18px;
  font-weight: 600;
}

.stat-value.neg {
  color: var(--red-600);
}

.stat-wide .stat-value {
  font-size: 14px;
  font-weight: 500;
}

/* ---------- 法条与分析 ---------- */

.legal-note {
  display: flex;
  gap: 6px;
  margin-top: 12px;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  background: #fffbeb;
  border-left: 3px solid #fde68a;
  font-size: 12.5px;
  color: var(--slate-700);
  line-height: 1.65;
}

.legal-note strong {
  color: var(--amber-600);
  flex-shrink: 0;
}

.analysis {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--green-100);
}

.analysis-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 5px;
}

.analysis-head h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--green-700);
}

.analysis-text {
  font-size: 13px;
  color: var(--slate-700);
  line-height: 1.75;
  white-space: pre-wrap;
}

/* ---------- 判例 ---------- */

.citations {
  margin-top: 12px;
}

.citations h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--slate-700);
  margin-bottom: 8px;
}

.citations ul {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.cite {
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--slate-200);
}

.cite-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

.cite-case {
  font-size: 12px;
  font-weight: 600;
  color: var(--green-700);
}

.cite-court {
  font-size: 12px;
  color: var(--slate-500);
}

.cite-signal {
  padding: 0 6px;
  border-radius: 4px;
  background: var(--amber-100);
  color: var(--amber-600);
  font-size: 11px;
}

.cite-ruling {
  font-size: 12.5px;
  color: var(--slate-700);
  line-height: 1.6;
}

.cite-lesson {
  margin-top: 3px;
  font-size: 12px;
  color: var(--amber-600);
  line-height: 1.6;
}

/* ---------- 计算过程 ---------- */

.steps {
  margin-top: 12px;
}

.steps-toggle {
  font-size: 12.5px;
}

.steps-list {
  margin-top: 8px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--slate-50);
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.step {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  font-size: 12.5px;
}

.step-formula {
  color: var(--slate-700);
}

.step-result {
  color: var(--slate-500);
  white-space: nowrap;
}

.link {
  font-size: 12.5px;
  color: var(--green-600);
}

.link:hover {
  text-decoration: underline;
}

.disclaimer {
  font-size: 12px;
  color: var(--slate-500);
  line-height: 1.7;
  padding: 0 4px 8px;
}

@media (max-width: 720px) {
  .stat-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>