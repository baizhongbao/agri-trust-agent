<script setup>
import { computed } from 'vue'

const props = defineProps({
  report: { type: Object, required: true },
})

const results = computed(() => props.report.results || [])
const unmatched = computed(() => props.report.unmatched_clauses || [])
const index = computed(() => props.report.index || {})

const coveragePercent = computed(() => Math.round((props.report.coverage || 0) * 100))

function scorePercent(score) {
  return Math.round((score || 0) * 100)
}

function scoreClass(score) {
  if (score >= 0.5) return 'high'
  if (score >= 0.3) return 'mid'
  return 'low'
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
