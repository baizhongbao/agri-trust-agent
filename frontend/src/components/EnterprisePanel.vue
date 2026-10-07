<script setup>
import { computed, ref } from 'vue'

import { lookupEnterprise } from '../api'

const props = defineProps({
  report: { type: Object, required: true },
})

const lookupKey = ref('')
const lookupBusy = ref(false)
const lookupError = ref('')
const lookupResult = ref(null)

const parties = computed(() => props.report.parties || [])
const summary = computed(() => props.report.summary || {})

const statusMeta = {
  pass: { label: '通过', cls: 'tag-green' },
  warning: { label: '需关注', cls: 'tag-amber' },
  fail: { label: '高风险', cls: 'tag-red' },
  review: { label: '待核对', cls: 'tag-slate' },
}

function statusLabel(status) {
  return statusMeta[status]?.label || status
}

function statusClass(status) {
  return statusMeta[status]?.cls || 'tag-slate'
}

function statusColor(status) {
  return {
    pass: 'var(--green-600)',
    warning: 'var(--amber-600)',
    fail: 'var(--red-600)',
  }[status] || 'var(--slate-500)'
}

function cellClass(status) {
  return { status: true, ['status-' + (status || 'review')]: true }
}

function formatDate(value) {
  return value || '—'
}

async function runLookup() {
  const key = lookupKey.value.trim()
  if (!key || lookupBusy.value) return
  lookupBusy.value = true
  lookupError.value = ''
  lookupResult.value = null
  try {
    lookupResult.value = await lookupEnterprise(key)
  } catch (e) {
    lookupError.value = e.message
  } finally {
    lookupBusy.value = false
  }
}
</script>

<template>
  <div class="fade-in stack">
    <div class="card card-pad">
      <div class="head">
        <div>
          <h2>企业核验结果</h2>
          <p class="sub">{{ report.contract_title || '未命名合同' }}</p>
        </div>
        <span class="tag tag-slate" title="工商数据来源">
          {{ report.provider || 'fixture' }}
        </span>
      </div>

      <div class="metrics">
        <div class="metric" v-for="(count, status) in summary" :key="status">
          <span class="metric-value" :style="{ color: statusColor(status) }">{{ count }}</span>
          <span class="metric-label">{{ statusLabel(status) }}</span>
        </div>
      </div>
    </div>

    <div
      v-for="party in parties"
      :key="party.name + party.role"
      class="card card-pad party-card"
    >
      <div class="party-head">
        <div>
          <span class="party-role">{{ party.role }}</span>
          <h3>{{ party.name || '未识别主体' }}</h3>
          <p class="mono party-code">{{ party.credit_code || '未载明信用代码' }}</p>
        </div>
        <span class="tag" :class="statusClass(party.overall)">
          {{ statusLabel(party.overall) }}
        </span>
      </div>

      <div v-if="party.l1.length" class="block">
        <h4>L1 · 本地校验</h4>
        <ul class="checks">
          <li
            v-for="item in party.l1"
            :key="item.key"
            class="check"
            :class="cellClass(item.status)"
          >
            <span class="dot" />
            <div class="check-main">
              <span class="check-label">{{ item.label }}</span>
              <span class="check-detail">{{ item.detail }}</span>
            </div>
            <span class="check-badge" :class="statusClass(item.status)">
              {{ statusLabel(item.status) }}
            </span>
          </li>
        </ul>
      </div>

      <div v-if="party.l2" class="block">
        <div class="block-head">
          <h4>L2 · 工商信息</h4>
          <span class="tag tag-green">
            {{ party.l2_status === 'found' ? '查询命中' : party.l2_status }}
          </span>
        </div>
        <dl class="reg-grid">
          <div class="reg-item">
            <dt>企业名称</dt>
            <dd>{{ party.l2.name || '—' }}</dd>
          </div>
          <div class="reg-item">
            <dt>统一社会信用代码</dt>
            <dd class="mono">{{ party.l2.credit_code || '—' }}</dd>
          </div>
          <div class="reg-item">
            <dt>法定代表人</dt>
            <dd>{{ party.l2.legal_person || '—' }}</dd>
          </div>
          <div class="reg-item">
            <dt>注册资本</dt>
            <dd>{{ party.l2.registered_capital || '—' }}</dd>
          </div>
          <div class="reg-item">
            <dt>成立日期</dt>
            <dd>{{ formatDate(party.l2.founding_date) }}</dd>
          </div>
          <div class="reg-item">
            <dt>登记状态</dt>
            <dd>{{ party.l2.status || '—' }}</dd>
          </div>
          <div class="reg-item wide">
            <dt>经营范围</dt>
            <dd>{{ party.l2.business_scope || '—' }}</dd>
          </div>
          <div class="reg-item wide">
            <dt>住所</dt>
            <dd>{{ party.l2.address || '—' }}</dd>
          </div>
        </dl>
      </div>

      <div v-else-if="party.l2_note" class="block">
        <h4>L2 · 工商信息</h4>
        <p class="note">{{ party.l2_note }}</p>
      </div>

      <div v-if="party.l3.length" class="block">
        <h4>L3 · 交叉核验</h4>
        <ul class="checks">
          <li
            v-for="item in party.l3"
            :key="item.key"
            class="check"
            :class="cellClass(item.status)"
          >
            <span class="dot" />
            <div class="check-main">
              <span class="check-label">{{ item.label }}</span>
              <span class="check-detail">{{ item.detail }}</span>
              <p v-if="item.evidence" class="evidence">
                <span class="evidence-badge">依据</span>
                {{ item.evidence }}
              </p>
            </div>
            <span class="check-badge" :class="statusClass(item.status)">
              {{ statusLabel(item.status) }}
            </span>
          </li>
        </ul>
      </div>
    </div>

    <div class="card card-pad">
      <h3 class="section-title">单独核验企业</h3>
      <div class="lookup-row">
        <input
          v-model="lookupKey"
          type="text"
          placeholder="输入企业名称或统一社会信用代码"
          @keyup.enter="runLookup"
        />
        <button class="btn btn-ghost" :disabled="lookupBusy || !lookupKey.trim()" @click="runLookup">
          {{ lookupBusy ? '查询中…' : '核验' }}
        </button>
      </div>
      <p v-if="lookupError" class="note note-red">{{ lookupError }}</p>

      <div v-if="lookupResult" class="block lookup-result">
        <div class="block-head">
          <h4>查询结果 · {{ lookupResult.search_key }}</h4>
          <span class="tag" :class="statusClass(lookupResult.l2_status === 'found' ? 'pass' : 'warning')">
            {{ lookupResult.l2_status === 'found' ? '命中' : '未命中' }}
          </span>
        </div>

        <ul v-if="lookupResult.l1.length" class="checks">
          <li
            v-for="item in lookupResult.l1"
            :key="item.key"
            class="check"
            :class="cellClass(item.status)"
          >
            <span class="dot" />
            <div class="check-main">
              <span class="check-label">{{ item.label }}</span>
              <span class="check-detail">{{ item.detail }}</span>
            </div>
            <span class="check-badge" :class="statusClass(item.status)">
              {{ statusLabel(item.status) }}
            </span>
          </li>
        </ul>

        <dl v-if="lookupResult.l2" class="reg-grid">
          <div class="reg-item">
            <dt>企业名称</dt>
            <dd>{{ lookupResult.l2.name || '—' }}</dd>
          </div>
          <div class="reg-item">
            <dt>法定代表人</dt>
            <dd>{{ lookupResult.l2.legal_person || '—' }}</dd>
          </div>
          <div class="reg-item">
            <dt>成立日期</dt>
            <dd>{{ formatDate(lookupResult.l2.founding_date) }}</dd>
          </div>
          <div class="reg-item">
            <dt>登记状态</dt>
            <dd>{{ lookupResult.l2.status || '—' }}</dd>
          </div>
          <div class="reg-item wide">
            <dt>经营范围</dt>
            <dd>{{ lookupResult.l2.business_scope || '—' }}</dd>
          </div>
        </dl>
        <p v-if="lookupResult.l2_note" class="note">{{ lookupResult.l2_note }}</p>
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
  line-height: 1.2;
}

.metric-label {
  font-size: 12px;
  color: var(--slate-500);
}

/* ---------- 主体卡片 ---------- */

.party-card {
  border-left: 3px solid var(--slate-300);
}

.party-card.status-fail {
  border-left-color: var(--red-600);
}

.party-card.status-warning {
  border-left-color: var(--amber-600);
}

.party-card.status-pass {
  border-left-color: var(--green-600);
}

.party-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.party-role {
  font-size: 12px;
  font-weight: 600;
  color: var(--green-700);
}

.party-head h3 {
  font-size: 16px;
  font-weight: 600;
  margin-top: 1px;
}

.party-code {
  font-size: 11.5px;
  color: var(--slate-500);
  margin-top: 2px;
}

.block {
  margin-top: 16px;
}

.block h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--slate-700);
  margin-bottom: 8px;
}

.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.block-head h4 {
  margin-bottom: 0;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 13px;
}

/* ---------- 判定项 ---------- */

.checks {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.check {
  display: grid;
  grid-template-columns: 8px 1fr auto;
  gap: 10px;
  align-items: center;
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  background: var(--slate-50);
}

.check + .check {
  margin-top: 2px;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--slate-300);
}

.check.status-pass .dot {
  background: var(--green-600);
}

.check.status-warning .dot {
  background: var(--amber-600);
}

.check.status-fail .dot {
  background: var(--red-600);
}

.check.status-review .dot {
  background: var(--slate-300);
}

.check-main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.check-label {
  font-size: 13px;
  font-weight: 600;
}

.check-detail {
  font-size: 12.5px;
  color: var(--slate-500);
  line-height: 1.6;
}

.check-badge {
  font-size: 11px;
  padding: 1px 7px;
}

.note {
  font-size: 12.5px;
  color: var(--slate-500);
  line-height: 1.7;
  padding: 4px 0;
}

.note-red {
  color: var(--red-600);
}

/* ---------- 工商信息 ---------- */

.reg-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px 18px;
}

.reg-item {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 9px 12px;
  border-radius: var(--radius-sm);
  background: var(--slate-50);
  min-width: 0;
}

.reg-item.wide {
  grid-column: 1 / -1;
}

.reg-item dt {
  font-size: 11.5px;
  color: var(--slate-500);
}

.reg-item dd {
  font-size: 13px;
  color: var(--slate-900);
  word-break: break-word;
  line-height: 1.6;
}

.reg-item dd.mono {
  font-size: 12px;
}

/* ---------- 依据 ---------- */

.evidence {
  margin-top: 4px;
  padding-left: 9px;
  border-left: 2px solid var(--slate-200);
  font-size: 12px;
  color: var(--slate-500);
  line-height: 1.6;
}

.evidence-badge {
  display: inline-block;
  margin-right: 6px;
  padding: 0 5px;
  border-radius: 4px;
  background: var(--slate-100);
  font-size: 10.5px;
}

/* ---------- 单独核验 ---------- */

.lookup-row {
  display: flex;
  gap: 8px;
}

.lookup-row input {
  flex: 1;
}

.lookup-result {
  margin-top: 14px;
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

  .reg-grid {
    grid-template-columns: 1fr;
  }
}
</style>