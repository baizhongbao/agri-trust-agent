<script setup>
import { computed } from 'vue'

import { verdictReportUrl } from '../api'

const props = defineProps({
  report: { type: Object, required: true },
})

const pdfUrl = computed(() => verdictReportUrl(props.report.doc_id, 'pdf'))
const docxUrl = computed(() => verdictReportUrl(props.report.doc_id, 'docx'))

const dimensions = computed(() => props.report.dimensions || [])
const blockers = computed(() => props.report.blockers || [])
const notices = computed(() => props.report.notices || [])
const missing = computed(() => props.report.missing_dimensions || [])

const GRADE_CLASS = {
  可信: 'grade-green',
  基本可信: 'grade-green',
  需关注: 'grade-amber',
  高风险: 'grade-red',
  不可评: 'grade-slate',
}

const gradeClass = computed(() => GRADE_CLASS[props.report.grade] || 'grade-slate')

function levelTag(level) {
  if (level === '可信' || level === '基本可信') return 'tag-green'
  if (level === '需关注') return 'tag-amber'
  if (level === '高风险') return 'tag-red'
  return 'tag-slate'
}
</script>

<template>
  <div class="fade-in stack">
    <div class="card card-pad grade-card" :class="gradeClass">
      <div class="grade-main">
        <span class="grade-label">总体可信度</span>
        <strong class="grade-value">{{ report.grade }}</strong>
      </div>
      <p class="grade-reason">{{ report.grade_reason }}</p>
      <p class="grade-meta">
        {{ report.contract_title || '未命名合同' }} ·
        <span class="mono">{{ report.doc_id }}</span>
        <span v-if="report.generated_at"> · {{ report.generated_at }}</span>
      </p>
      <div class="export-row">
        <a class="btn btn-ghost" :href="pdfUrl" download>导出 PDF</a>
        <a class="btn btn-ghost" :href="docxUrl" download>导出 Word</a>
      </div>
    </div>

    <div v-if="blockers.length" class="card card-pad danger">
      <h3>否决项（客观硬伤，优先处理）</h3>
      <ul class="list">
        <li v-for="(item, i) in blockers" :key="i">
          <div class="item-head">
            <span class="tag tag-red">{{ item.label }}</span>
          </div>
          <p v-if="item.detail" class="item-detail">{{ item.detail }}</p>
          <p v-if="item.evidence" class="item-src">依据：{{ item.evidence }}</p>
        </li>
      </ul>
    </div>

    <div class="card card-pad">
      <h3 class="section-title">分项判定</h3>
      <div class="dims">
        <div v-for="dim in dimensions" :key="dim.key" class="dim">
          <div class="dim-head">
            <strong class="dim-label">{{ dim.label }}</strong>
            <span class="tag" :class="levelTag(dim.level)">{{ dim.level }}</span>
            <span v-if="dim.score" class="dim-score">{{ dim.score }}</span>
          </div>
          <p class="dim-summary">{{ dim.summary }}</p>
          <ul v-if="dim.findings.length" class="findings">
            <li v-for="(f, i) in dim.findings" :key="i">{{ f }}</li>
          </ul>
          <p v-if="dim.notice" class="dim-notice">未完整评估：{{ dim.notice }}</p>
        </div>
      </div>
    </div>

    <div v-if="missing.length || notices.length" class="card card-pad warn">
      <h3>未评估 / 需注意</h3>
      <p v-if="missing.length" class="missing-line">
        未评估维度：<strong>{{ missing.join('、') }}</strong>——缺失不等于无风险。
      </p>
      <ul v-if="notices.length" class="list plain">
        <li v-for="(n, i) in notices" :key="i">{{ n }}</li>
      </ul>
    </div>

    <div v-if="report.narrative" class="card card-pad">
      <h3 class="section-title">结论文本</h3>
      <p class="narrative">{{ report.narrative }}</p>
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

/* ---------- 总等级 ---------- */

.grade-card {
  border-left: 4px solid var(--slate-300);
}

.grade-green {
  border-left-color: var(--green-500);
}
.grade-amber {
  border-left-color: #f59e0b;
}
.grade-red {
  border-left-color: var(--red-600);
}
.grade-slate {
  border-left-color: var(--slate-300);
}

.grade-main {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.grade-label {
  font-size: 13px;
  color: var(--slate-500);
}

.grade-value {
  font-size: 30px;
  font-weight: 700;
  color: var(--slate-900);
  line-height: 1.1;
}

.grade-green .grade-value {
  color: var(--green-700);
}
.grade-amber .grade-value {
  color: var(--amber-600);
}
.grade-red .grade-value {
  color: var(--red-600);
}

.grade-reason {
  margin-top: 8px;
  font-size: 14px;
  color: var(--slate-700);
  line-height: 1.7;
}

.grade-meta {
  margin-top: 6px;
  font-size: 12px;
  color: var(--slate-500);
}

.export-row {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}

.export-row .btn {
  text-decoration: none;
  font-size: 13px;
  padding: 7px 14px;
}

/* ---------- 否决 / 注意 ---------- */

.danger {
  background: #fef2f2;
  border-color: #fecaca;
}

.danger h3 {
  font-size: 14px;
  font-weight: 600;
  color: var(--red-600);
  margin-bottom: 9px;
}

.warn {
  background: #fffbeb;
  border-color: #fde68a;
}

.warn h3 {
  font-size: 14px;
  font-weight: 600;
  color: var(--amber-600);
  margin-bottom: 9px;
}

.missing-line {
  font-size: 13px;
  color: var(--amber-600);
  margin-bottom: 6px;
}

.list {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 11px;
}

.list.plain {
  gap: 5px;
  font-size: 12.5px;
  color: var(--amber-600);
  padding-left: 18px;
  list-style: disc;
}

.list li {
  font-size: 13px;
}

.item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.item-detail {
  font-size: 12.5px;
  color: var(--slate-700);
  margin-top: 4px;
  line-height: 1.7;
}

.item-src {
  font-size: 11.5px;
  color: var(--slate-500);
  margin-top: 3px;
}

/* ---------- 分项 ---------- */

.section-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 12px;
}

.dims {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.dim {
  padding: 12px 13px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--slate-200);
  background: var(--slate-50);
}

.dim-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.dim-label {
  font-size: 13.5px;
}

.dim-score {
  margin-left: auto;
  font-size: 13px;
  font-weight: 600;
  color: var(--slate-500);
}

.dim-summary {
  font-size: 12.5px;
  color: var(--slate-700);
  line-height: 1.7;
}

.findings {
  margin-top: 7px;
  padding-left: 16px;
  list-style: disc;
  font-size: 12px;
  color: var(--slate-500);
  line-height: 1.65;
}

.dim-notice {
  margin-top: 7px;
  font-size: 12px;
  color: var(--red-600);
}

.narrative {
  font-size: 13px;
  color: var(--slate-700);
  line-height: 1.85;
}

.disclaimer {
  font-size: 12px;
  color: var(--slate-500);
  line-height: 1.7;
  padding: 0 4px 8px;
}

@media (max-width: 720px) {
  .dims {
    grid-template-columns: 1fr;
  }
}
</style>
