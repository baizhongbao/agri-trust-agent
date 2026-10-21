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
const disagreements = computed(() => gate.value?.disagreements || [])
// 门禁 ok 但仍可能有"非必备字段的双源冲突"——留痕了就必须让人看见
const gateNeedsAttention = computed(
  () => gateLevel.value !== 'ok' || disagreements.value.length > 0,
)

// 事实自检（确定性，无 LLM）
const checks = computed(() => props.contract.checks || [])
const checkProblems = computed(() =>
  checks.value.filter((item) => item.status && item.status !== 'ok'),
)

const hitCount = computed(() => fields.value.filter((item) => item.value).length)
const hitRate = computed(() =>
  fields.value.length ? Math.round((hitCount.value / fields.value.length) * 100) : 0,
)

function confidenceClass(confidence) {
  if (confidence >= 0.8) return 'high'
  if (confidence >= 0.5) return 'mid'
  return 'low'
}

// 双源一致性标签。只在真的比过两个抽取器时才显示——
// 单源时没有可比对象，标"一致"会是撒谎。
const AGREEMENT_LABELS = {
  agreed: '双源一致',
  l1_only: '仅规则',
  l2_only: '仅大模型',
  conflict: '双源冲突',
  missing: '未抽到',
}

function agreementLabel(field) {
  return AGREEMENT_LABELS[field.agreement] || ''
}

function agreementClass(field) {
  if (field.agreement === 'agreed') return 'agree-ok'
  if (field.agreement === 'conflict') return 'agree-bad'
  if (field.agreement === 'l2_only') return 'agree-llm'
  return 'agree-neutral'
}

function showsAgreement(field) {
  return Boolean(field.agreement) && field.agreement !== 'single' && field.agreement !== 'missing'
}

// 百分比的含义随来源而变，鼠标悬停必须说清楚，否则就是在误导使用者
function confidenceTitle(field) {
  if (field.agreement === 'agreed') {
    return `置信度 ${field.confidence}：规则与大模型给出相同值，由双源一致导出`
  }
  if (field.agreement === 'conflict') {
    return `置信度 ${field.confidence}：两个抽取器给出的值不一致，已明显下调`
  }
  if (field.agreement === 'l2_only') {
    return `置信度 ${field.confidence}：仅大模型给出，无第二来源可交叉验证`
  }
  if (field.agreement === 'l1_only') {
    return `置信度 ${field.confidence}：仅规则给出，无第二来源可交叉验证`
  }
  return `置信度 ${field.confidence}：单一抽取器的静态先验值，不携带交叉验证信息`
}

function checkClass(status) {
  if (status === 'warning') return 'check-warning'
  if (status === 'review') return 'check-review'
  return 'check-ok'
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

    <!-- 解析质量门禁：blocked / degraded / 双源冲突 必须在最上方就能看到 -->
    <div
      v-if="gate && gateNeedsAttention"
      class="card card-pad gate-card"
      :class="`gate-${gateLevel}`"
    >
      <div class="gate-head">
        <span class="tag" :class="gateLevel === 'blocked' ? 'tag-red' : 'tag-amber'">
          {{ gateLevel === 'blocked'
            ? '解析失败'
            : (gateLevel === 'degraded' ? '解析不完整' : '需人工核对') }}
        </span>
        <strong>{{ gate.summary }}</strong>
      </div>
      <ul>
        <li v-for="(failure, index) in gate.failures" :key="index">
          <b>{{ failure.label }}</b>：{{ failure.detail }}
        </li>
        <li v-for="(item, index) in disagreements" :key="'dis' + index">
          <b>双源冲突 · {{ item.label }}</b>：规则取「{{ item.l1_value }}」，
          大模型取「{{ item.l2_value }}」——系统不判断哪一侧正确，请核对原文
        </li>
      </ul>
      <p v-if="gate.escalated" class="gate-escalation">
        L1→L2 升级：触发「{{ gate.escalation_reason }}」→ {{ gate.escalation_note }}
      </p>
      <p class="gate-impact">
        {{ gateLevel === 'blocked'
          ? '下游企业核验 / 标准校验 / 履约模拟的结论不可信，请先修复解析或人工补录。'
          : '下游结论需附带上述标注，不得当作完整结论使用。' }}
      </p>
    </div>

    <!-- 事实自检：字段都抽到了，但彼此矛盾（程序跑得通 ≠ 算得对） -->
    <div
      v-if="checks.length"
      class="card card-pad"
      :class="{ 'warning-card': checkProblems.length }"
    >
      <h3 class="section-title">
        事实自检
        <span class="hint">确定性校验 · 未调用大模型</span>
      </h3>
      <ul class="checks">
        <li v-for="(item, index) in checks" :key="index" class="check" :class="checkClass(item.status)">
          <span class="check-code mono">{{ item.code }}</span>
          <span class="check-detail">{{ item.detail }}</span>
          <span v-if="item.legal_basis" class="check-legal">法定依据：{{ item.legal_basis }}</span>
        </li>
      </ul>
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
            <span class="field-tags">
              <span
                v-if="showsAgreement(field)"
                class="confidence"
                :class="agreementClass(field)"
                :title="`双源一致性：${agreementLabel(field)}`"
              >
                {{ agreementLabel(field) }}
              </span>
              <span
                v-if="field.value"
                class="confidence"
                :class="confidenceClass(field.confidence)"
                :title="confidenceTitle(field)"
              >
                {{ Math.round(field.confidence * 100) }}%
              </span>
            </span>
          </div>
          <p v-if="field.agreement === 'conflict'" class="conflict-alt">
            <span class="evidence-label">另一抽取器给出</span>
            {{ field.alternative || '（空）' }}
            <span class="conflict-note">系统不做取舍，请核对原文</span>
          </p>
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

/* ---------- 双源一致性 ---------- */

.field-tags {
  display: flex;
  gap: 5px;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.confidence.agree-ok {
  background: var(--green-100);
  color: var(--green-700);
}

.confidence.agree-llm {
  background: #e0e7ff;
  color: #3730a3;
}

.confidence.agree-bad {
  background: #fee2e2;
  color: var(--red-600, #dc2626);
}

.confidence.agree-neutral {
  background: var(--slate-100);
  color: var(--slate-500);
}

.conflict-alt {
  margin-top: 5px;
  margin-left: 104px;
  padding-left: 10px;
  border-left: 2px solid #fecaca;
  font-size: 12.5px;
  color: var(--red-600, #dc2626);
  line-height: 1.6;
}

.conflict-note {
  margin-left: 6px;
  color: var(--slate-500);
}

/* ---------- 事实自检 ---------- */

.hint {
  margin-left: 7px;
  font-size: 11.5px;
  font-weight: 400;
  color: var(--slate-500);
}

.checks {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.check {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 9px 11px;
  border-radius: var(--radius-sm);
  background: var(--slate-50);
  border-left: 3px solid var(--slate-300);
  font-size: 12.5px;
  line-height: 1.6;
}

.check-ok {
  border-left-color: var(--green-600);
}

.check-warning {
  border-left-color: var(--red-600, #dc2626);
  background: #fef2f2;
}

.check-review {
  border-left-color: var(--amber-600);
  background: #fffbeb;
}

.check-code {
  font-size: 11.5px;
  color: var(--slate-500);
}

.check-legal {
  color: var(--slate-500);
  font-size: 11.5px;
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

  .field-tags {
    justify-content: flex-start;
  }

  .evidence {
    margin-left: 0;
  }

  .conflict-alt {
    margin-left: 0;
  }
}
</style>
