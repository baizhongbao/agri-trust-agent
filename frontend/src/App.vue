<script setup>
import { computed, onMounted, ref } from 'vue'

import { checkStandards, getHealth, parseContract, simulateContract, verifyContract } from './api'
import ContractPanel from './components/ContractPanel.vue'
import EnterprisePanel from './components/EnterprisePanel.vue'
import ProviderCard from './components/ProviderCard.vue'
import SimulationPanel from './components/SimulationPanel.vue'
import StandardPanel from './components/StandardPanel.vue'
import UploadPanel from './components/UploadPanel.vue'

const health = ref(null)
const contract = ref(null)
const docId = ref('')
const report = ref(null)
const enterpriseReport = ref(null)
const simReport = ref(null)
const activeTab = ref('contract')
const busy = ref(false)
const error = ref('')
const progressText = ref('')

const isOfflineMode = computed(() => health.value?.providers?.llm?.name === 'mock')

onMounted(loadHealth)

async function loadHealth() {
  try {
    health.value = await getHealth()
  } catch {
    health.value = null
  }
}

async function handleUpload(file) {
  if (!file || busy.value) return

  busy.value = true
  error.value = ''
  report.value = null
  enterpriseReport.value = null
  simReport.value = null
  progressText.value = '正在解析合同…'

  try {
    const payload = await parseContract(file)
    docId.value = payload.doc_id
    contract.value = payload.contract
    activeTab.value = 'contract'
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
    progressText.value = ''
  }
}

async function runStandardCheck() {
  if (!docId.value || busy.value) return

  busy.value = true
  error.value = ''
  progressText.value = '正在检索标准库…'

  try {
    report.value = await checkStandards(docId.value, 3)
    activeTab.value = 'standard'
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
    progressText.value = ''
  }
}

async function runEnterpriseVerify() {
  if (!docId.value || busy.value) return

  busy.value = true
  error.value = ''
  progressText.value = '正在核验合同主体…'

  try {
    enterpriseReport.value = await verifyContract(docId.value)
    activeTab.value = 'enterprise'
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
    progressText.value = ''
  }
}

async function runSimulation() {
  if (!docId.value || busy.value) return

  busy.value = true
  error.value = ''
  progressText.value = '正在推演履约风险…'

  try {
    simReport.value = await simulateContract(docId.value)
    activeTab.value = 'simulate'
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
    progressText.value = ''
  }
}
</script>

<template>
  <div class="app">
    <header class="app-header">
      <div class="brand">
        <div class="logo">农</div>
        <div class="brand-text">
          <h1>订单农业可信性 Agent</h1>
          <p>合同解析 · 标准校验 · 企业核验 · 履约模拟</p>
        </div>
      </div>

      <div class="header-right">
        <span v-if="isOfflineMode" class="tag tag-amber" title="未配置华为云凭证，当前使用离线兜底实现">
          离线模式
        </span>
        <span v-else-if="health" class="tag tag-green">已接入大模型</span>
        <span v-else class="tag tag-red">后端未连接</span>
      </div>
    </header>

    <main class="app-main">
      <aside class="sidebar">
        <UploadPanel :busy="busy" :progress="progressText" @select="handleUpload" />

        <div v-if="error" class="alert fade-in">
          <strong>出错了</strong>
          <span>{{ error }}</span>
        </div>

        <ProviderCard :health="health" />

        <div class="tip card card-pad">
          <div class="tip-title">下一步</div>
          <ol>
            <li>上传一份订单农业合同 PDF</li>
            <li>查看结构化字段与原文依据</li>
            <li>校验标准、核验企业、推演履约风险</li>
          </ol>
        </div>
      </aside>

      <section class="content">
        <nav class="tabs">
          <button
            class="tab"
            :class="{ active: activeTab === 'contract' }"
            @click="activeTab = 'contract'"
          >
            结构化合同
          </button>
          <button
            class="tab"
            :class="{ active: activeTab === 'standard' }"
            :disabled="!report"
            @click="activeTab = 'standard'"
          >
            标准校验
            <span v-if="report" class="tab-badge">{{ report.matched_clauses }}</span>
          </button>
          <button
            class="tab"
            :class="{ active: activeTab === 'enterprise' }"
            :disabled="!enterpriseReport"
            @click="activeTab = 'enterprise'"
          >
            企业核验
            <span v-if="enterpriseReport" class="tab-badge">{{ enterpriseReport.parties?.length }}</span>
          </button>
          <button
            class="tab"
            :class="{ active: activeTab === 'simulate' }"
            :disabled="!simReport"
            @click="activeTab = 'simulate'"
          >
            履约模拟
            <span v-if="simReport" class="tab-badge">{{ simReport.scenarios?.length }}</span>
          </button>

          <div class="tabs-spacer" />

          <button class="btn btn-primary" :disabled="!docId || busy" @click="runStandardCheck">
            校验标准
          </button>
          <button
            class="btn btn-ghost"
            :disabled="!docId || busy"
            @click="runEnterpriseVerify"
          >
            核验企业
          </button>
          <button
            class="btn btn-ghost"
            :disabled="!docId || busy"
            @click="runSimulation"
          >
            履约模拟
          </button>
        </nav>

        <div v-if="!contract" class="empty card">
          <div class="empty-icon">📄</div>
          <h2>还没有合同</h2>
          <p>上传一份 PDF 合同开始体验。</p>
          <p class="empty-hint">
            没有现成文件？运行
            <code>python scripts/make_sample_contract.py</code>
            生成示例合同。
          </p>
        </div>

        <ContractPanel v-else-if="activeTab === 'contract'" :contract="contract" />
        <StandardPanel v-else-if="report && activeTab === 'standard'" :report="report" />
        <EnterprisePanel v-else-if="enterpriseReport && activeTab === 'enterprise'" :report="enterpriseReport" />
        <SimulationPanel v-else-if="simReport && activeTab === 'simulate'" :report="simReport" />
      </section>
    </main>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  min-height: 100%;
}

/* ---------- 顶部 ---------- */

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 28px;
  background: linear-gradient(120deg, var(--green-900) 0%, var(--green-700) 100%);
  color: #fff;
  box-shadow: var(--shadow);
}

.brand {
  display: flex;
  align-items: center;
  gap: 14px;
}

.logo {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.16);
  border: 1px solid rgba(255, 255, 255, 0.28);
  font-size: 20px;
  font-weight: 700;
}

.brand-text h1 {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.3px;
}

.brand-text p {
  font-size: 12px;
  opacity: 0.75;
}

/* ---------- 主体布局 ---------- */

.app-main {
  display: grid;
  grid-template-columns: 332px minmax(0, 1fr);
  gap: 22px;
  padding: 22px 28px 40px;
  align-items: start;
  width: 100%;
  max-width: 1560px;
  margin: 0 auto;
}

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 16px;
  position: sticky;
  top: 22px;
}

.content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

/* ---------- 页签 ---------- */

.tabs {
  display: flex;
  align-items: center;
  gap: 6px;
  background: #fff;
  border: 1px solid var(--slate-200);
  border-radius: var(--radius);
  padding: 6px;
  box-shadow: var(--shadow-sm);
}

.tab {
  position: relative;
  padding: 8px 16px;
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-weight: 500;
  color: var(--slate-500);
  transition: all 0.16s ease;
}

.tab:hover:not(:disabled) {
  background: var(--slate-50);
  color: var(--slate-700);
}

.tab.active {
  background: var(--green-100);
  color: var(--green-700);
}

.tab-badge {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--green-600);
  color: #fff;
  font-size: 11px;
  line-height: 17px;
}

.tabs-spacer {
  flex: 1;
}

/* ---------- 空状态 ---------- */

.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 76px 32px;
  text-align: center;
}

.empty-icon {
  font-size: 42px;
  opacity: 0.55;
}

.empty h2 {
  font-size: 17px;
  font-weight: 600;
}

.empty p {
  color: var(--slate-500);
  font-size: 13px;
}

.empty-hint code {
  padding: 2px 6px;
  border-radius: 5px;
  background: var(--slate-100);
  font-size: 12px;
  color: var(--slate-700);
}

/* ---------- 提示 ---------- */

.alert {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--red-100);
  border: 1px solid #fecaca;
  color: var(--red-600);
  font-size: 13px;
}

.tip-title {
  font-weight: 600;
  margin-bottom: 6px;
  font-size: 13px;
}

.tip ol {
  padding-left: 18px;
  color: var(--slate-500);
  font-size: 13px;
}

.tip li + li {
  margin-top: 3px;
}

@media (max-width: 1080px) {
  .app-main {
    grid-template-columns: 1fr;
  }

  .sidebar {
    position: static;
  }
}
</style>
