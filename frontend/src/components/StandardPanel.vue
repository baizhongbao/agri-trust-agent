<script setup>
import { computed } from 'vue'

const props = defineProps({
  report: { type: Object, required: true },
})

const results = computed(() => props.report.results || [])
const unmatched = computed(() => props.report.unmatched_clauses || [])
const index = computed(() => props.report.index || {})
const required = computed(() => props.report.required_clauses || null)
const compliance = computed(() => props.report.compliance || null)

const coveragePercent = computed(() => Math.round((props.report.coverage || 0) * 100))

function scorePercent(score) {
  return Math.round((score || 0) * 100)
}

function scoreClass(score) {
  if (score >= 0.5) return 'high'
  if (score >= 0.3) return 'mid'
  return 'low'
}

const RISK_LABEL = { high: '高风险', medium: '中风险', low: '低风险' }
function riskLabel(risk) {
  return RISK_LABEL[risk] || '需关注'
}

function riskTagClass(risk) {
  if (risk === 'high') return 'tag-red'
  if (risk === 'medium') return 'tag-amber'
  return 'tag-slate'
}

function vulnTagClass(severity) {
  return severity === 'high' ? 'tag-red' : 'tag-amber'
}

function fmtValue(value, unit) {
  return value === null || value === undefined ? '—' : `${value}${unit || ''}`
}
</script>

<template>
  <div class="fade-in stack">
    <div class="card card-pad">
      <div class="head">
        <div>
          <h2>标准校验结果</h2>
          <p class="sub">{{ report.contract_title || '未命名合同' }}</p>
        </div>
        <span class="tag" :class="coveragePercent === 100 ? 'tag-green' : 'tag-amber'">
          覆盖率 {{ coveragePercent }}%
        </span>
      </div>

      <div class="metrics">
        <div class="metric">
          <span class="metric-value">
            {{ report.matched_clauses }}<small>/{{ report.total_clauses }}</small>
          </span>
          <span class="metric-label">条款已匹配</span>
        </div>
        <div class="metric">
          <span class="metric-value">{{ index.documents || 0 }}</span>
          <span class="metric-label">标准条款库</span>
        </div>
        <div class="metric">
          <span class="metric-value mono small">{{ index.embedding?.name || '—' }}</span>
          <span class="metric-label">向量化方式</span>
        </div>
        <div class="metric">
          <span class="metric-value">{{ unmatched.length }}</span>
          <span class="metric-label">未匹配条款</span>
        </div>
      </div>
    </div>

    <div v-if="required" class="card card-pad">
      <div class="head">
        <div>
          <h2>必备条款覆盖</h2>
          <p class="sub">{{ required.summary }}</p>
        </div>
        <span class="tag" :class="required.risk_level === '低风险' ? 'tag-green' : 'tag-amber'">
          {{ required.risk_level }}
        </span>
      </div>

      <div class="metrics">
        <div class="metric">
          <span class="metric-value">
            {{ required.required_covered }}<small>/{{ required.required_total }}</small>
          </span>
          <span class="metric-label">必备条款已覆盖</span>
        </div>
        <div class="metric">
          <span class="metric-value">{{ (required.missing_required || []).length }}</span>
          <span class="metric-label">缺失必备条款</span>
        </div>
        <div class="metric">
          <span class="metric-value">{{ (required.missing_recommended || []).length }}</span>
          <span class="metric-label">缺失建议条款</span>
        </div>
        <div class="metric">
          <span class="metric-value">{{ required.risk_score }}</span>
          <span class="metric-label">条款风险分</span>
        </div>
      </div>
    </div>

    <div v-if="required && (required.missing_required || []).length" class="card card-pad warn">
      <h3>缺失的必备条款（必须补）</h3>
      <ul class="missing">
        <li v-for="item in required.missing_required" :key="item.key">
          <div class="missing-head">
            <strong>{{ item.name }}</strong>
            <span class="tag" :class="riskTagClass(item.risk)">{{ riskLabel(item.risk) }}</span>
          </div>
          <p v-if="item.advice" class="missing-advice">{{ item.advice }}</p>
          <p v-if="item.source" class="missing-src">依据：{{ item.source }}</p>
        </li>
      </ul>
    </div>

    <div v-if="required && (required.missing_recommended || []).length" class="card card-pad">
      <h3 class="block-title">缺失的建议条款（可选补）</h3>
      <ul class="missing">
        <li v-for="item in required.missing_recommended" :key="item.key">
          <div class="missing-head">
            <strong>{{ item.name }}</strong>
            <span class="tag tag-slate">建议</span>
          </div>
          <p v-if="item.advice" class="missing-advice">{{ item.advice }}</p>
          <p v-if="item.source" class="missing-src">依据：{{ item.source }}</p>
        </li>
      </ul>
    </div>

    <div v-if="compliance" class="card card-pad">
      <div class="head">
        <div>
          <h2>数值合规比对</h2>
          <p class="sub">{{ compliance.summary }}</p>
          <p v-if="compliance.subject_category" class="sub">
            标的品类：{{ compliance.subject_category }}
            <template v-if="compliance.filtered_out_count">
              （已过滤 {{ compliance.filtered_out_count }} 条不适用限值）
            </template>
          </p>
        </div>
        <span
          v-if="compliance.mandatory_violation_count"
          class="tag tag-red"
        >
          违反强制 {{ compliance.mandatory_violation_count }}
        </span>
        <span v-else-if="compliance.violation_count" class="tag tag-amber">存在偏离</span>
        <span v-else class="tag tag-green">未发现偏离</span>
      </div>

      <div class="metrics">
        <div class="metric">
          <span class="metric-value">{{ compliance.total }}</span>
          <span class="metric-label">可比对指标</span>
        </div>
        <div class="metric">
          <span class="metric-value">{{ compliance.violation_count }}</span>
          <span class="metric-label">偏离依据</span>
        </div>
        <div class="metric">
          <span class="metric-value">{{ compliance.mandatory_violation_count }}</span>
          <span class="metric-label">违反强制性</span>
        </div>
        <div class="metric">
          <span class="metric-value">{{ compliance.review_count }}</span>
          <span class="metric-label">待人工核对</span>
        </div>
      </div>

      <div v-if="(compliance.violations || []).length" class="matches">
        <div v-for="(item, i) in compliance.violations" :key="i" class="match">
          <div class="match-head">
            <span class="match-code mono">{{ item.standard_code }}</span>
            <span class="match-standard">{{ item.standard_title }}</span>
            <span class="match-clause">{{ item.clause_no }} {{ item.clause_title }}</span>
            <span class="tag" :class="vulnTagClass(item.severity)">{{ item.basis }}</span>
            <span v-if="(item.applies_to || []).length" class="tag tag-slate">
              适用 {{ item.applies_to.join('、') }}
            </span>
          </div>
          <p class="cmp">
            <span class="cmp-label">合同约定</span>
            <span class="cmp-val">
              {{ item.contract_metric }} {{ item.contract_op }} {{ fmtValue(item.contract_value, item.contract_unit) }}
            </span>
            <span class="cmp-vs">vs</span>
            <span class="cmp-label">依据限值</span>
            <span class="cmp-val">
              {{ item.metric }} {{ item.standard_op }} {{ fmtValue(item.standard_value, item.standard_unit) }}
            </span>
          </p>
          <p v-if="item.reason" class="match-text">{{ item.reason }}</p>
        </div>
      </div>

      <div v-if="(compliance.reviews || []).length" class="matches">
        <div v-for="(item, i) in compliance.reviews" :key="`r${i}`" class="match">
          <div class="match-head">
            <span class="match-code mono">{{ item.standard_code }}</span>
            <span class="match-clause">{{ item.clause_no }} {{ item.clause_title }}</span>
            <span class="tag tag-slate">待人工核对</span>
          </div>
          <p v-if="item.reason" class="match-text">{{ item.reason }}</p>
        </div>
      </div>

      <p v-if="!compliance.total" class="disclaimer">{{ compliance.summary }}</p>
    </div>

    <div v-if="unmatched.length" class="card card-pad warn">
      <h3>以下条款未检索到对应标准</h3>
      <ul>
        <li v-for="item in unmatched" :key="item.clause_index">
          <strong>第 {{ item.clause_index }} 条</strong>
          <span>{{ item.clause_title || item.clause_excerpt }}</span>
        </li>
      </ul>
    </div>

    <div v-for="entry in results" :key="entry.clause_index" class="card card-pad">
      <div class="clause-head">
        <span class="clause-no">合同第 {{ entry.clause_index }} 条</span>
        <span v-if="entry.clause_title" class="clause-title">{{ entry.clause_title }}</span>
        <span v-if="!entry.matches.length" class="tag tag-slate">未匹配</span>
      </div>

      <p class="clause-text">{{ entry.clause_excerpt }}</p>

      <div v-if="entry.matches.length" class="matches">
        <div v-for="match in entry.matches" :key="match.id" class="match">
          <div class="match-head">
            <span class="match-code mono">{{ match.standard_code }}</span>
            <span class="match-standard">{{ match.standard_title }}</span>
            <span class="match-clause">{{ match.clause_no }} {{ match.clause_title }}</span>
            <span class="score" :class="scoreClass(match.score)">
              {{ scorePercent(match.score) }}%
            </span>
          </div>

          <div class="bar">
            <div class="bar-fill" :class="scoreClass(match.score)" :style="{ width: `${scorePercent(match.score)}%` }" />
          </div>

          <p class="match-text">{{ match.body || match.text }}</p>
        </div>
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

.metric-value.small {
  font-size: 15px;
  padding-top: 5px;
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

/* ---------- 条款 ---------- */

.clause-head {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
  margin-bottom: 7px;
}

.clause-no {
  font-size: 12px;
  font-weight: 600;
  color: var(--green-700);
}

.clause-title {
  font-size: 13.5px;
  font-weight: 600;
}

.clause-text {
  font-size: 12.5px;
  color: var(--slate-500);
  line-height: 1.7;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  background: var(--slate-50);
  border-left: 3px solid var(--slate-300);
}

/* ---------- 匹配项 ---------- */

.matches {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 14px;
}

.match {
  padding: 12px 13px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--slate-200);
}

.match-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.match-code {
  padding: 1px 7px;
  border-radius: 5px;
  background: var(--green-100);
  color: var(--green-700);
  font-size: 11.5px;
  font-weight: 600;
}

.match-standard {
  font-size: 12.5px;
  color: var(--slate-500);
}

.match-clause {
  font-size: 13px;
  font-weight: 600;
}

.score {
  margin-left: auto;
  font-size: 13px;
  font-weight: 600;
}

.score.high {
  color: var(--green-700);
}

.score.mid {
  color: var(--amber-600);
}

.score.low {
  color: var(--slate-500);
}

.bar {
  height: 4px;
  border-radius: 999px;
  background: var(--slate-100);
  overflow: hidden;
  margin-bottom: 9px;
}

.bar-fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.4s ease;
}

.bar-fill.high {
  background: var(--green-500);
}

.bar-fill.mid {
  background: #f59e0b;
}

.bar-fill.low {
  background: var(--slate-300);
}

.match-text {
  font-size: 13px;
  color: var(--slate-700);
  line-height: 1.75;
}

/* ---------- 其他 ---------- */

.warn {
  background: #fffbeb;
  border-color: #fde68a;
}

.warn h3 {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--amber-600);
  margin-bottom: 7px;
}

.warn ul {
  padding-left: 18px;
  color: var(--amber-600);
  font-size: 13px;
}

.warn li + li {
  margin-top: 3px;
}

.warn strong {
  margin-right: 6px;
}

.block-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 10px;
}

.missing {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.missing li {
  padding: 11px 13px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--slate-200);
  background: var(--slate-50);
}

.missing-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 5px;
}

.missing-head strong {
  font-size: 13.5px;
}

.missing-advice {
  font-size: 12.5px;
  color: var(--slate-700);
  line-height: 1.7;
}

.missing-src {
  font-size: 11.5px;
  color: var(--slate-500);
  margin-top: 4px;
}

.cmp {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
  margin-bottom: 8px;
}

.cmp-label {
  font-size: 11.5px;
  color: var(--slate-500);
}

.cmp-val {
  font-weight: 600;
  color: var(--slate-900);
}

.cmp-vs {
  color: var(--slate-300);
  font-size: 11.5px;
}

.disclaimer {
  font-size: 12px;
  color: var(--slate-500);
  line-height: 1.7;
  padding: 0 4px 8px;
}

@media (max-width: 720px) {
  .metrics {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
