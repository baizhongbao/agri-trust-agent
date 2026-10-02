<script setup>
import { computed } from 'vue'

const props = defineProps({
  health: { type: Object, default: null },
})

const rows = computed(() => {
  const providers = props.health?.providers
  if (!providers) return []

  return [
    { label: '大模型', info: providers.llm, kind: 'LLM' },
    { label: '文字识别', info: providers.ocr, kind: 'OCR' },
    { label: '向量化', info: providers.embedding, kind: 'Embed' },
    { label: '重排', info: providers.rerank, kind: 'Rerank' },
  ]
})

const runtime = computed(() => props.health?.runtime || {})
</script>

<template>
  <div class="card card-pad">
    <div class="title">
      <h3>运行环境</h3>
      <button class="refresh" title="状态由后端启动时确定，重启后端可刷新">?</button>
    </div>

    <div v-if="!health" class="offline">后端未连接，请确认服务已启动</div>

    <template v-else>
      <ul class="rows">
        <li v-for="row in rows" :key="row.label">
          <span class="label">{{ row.label }}</span>
          <span class="value mono">{{ row.info?.name || '—' }}</span>
          <span class="tag" :class="row.info?.ready ? 'tag-green' : 'tag-slate'">
            {{ row.info?.ready ? '就绪' : '未启用' }}
          </span>
        </li>
      </ul>

      <div class="divider" />

      <ul class="rows muted">
        <li>
          <span class="label">合同抽取</span>
          <span class="value mono">{{ runtime.contract_structurer || '—' }}</span>
        </li>
        <li>
          <span class="label">向量库</span>
          <span class="value mono">{{ runtime.vector_store || '—' }}</span>
        </li>
        <li>
          <span class="label">存储</span>
          <span class="value mono">{{ runtime.storage || '—' }}</span>
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.title h3 {
  font-size: 14px;
  font-weight: 600;
}

.refresh {
  width: 17px;
  height: 17px;
  border-radius: 50%;
  background: var(--slate-100);
  color: var(--slate-500);
  font-size: 11px;
  line-height: 17px;
  text-align: center;
}

.rows {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.rows li {
  display: grid;
  grid-template-columns: 62px 1fr auto;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.label {
  color: var(--slate-500);
  font-size: 12px;
}

.value {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--slate-700);
  font-size: 12px;
}

.rows.muted .value {
  color: var(--slate-500);
}

.divider {
  height: 1px;
  background: var(--slate-200);
  margin: 13px 0;
}

.offline {
  font-size: 13px;
  color: var(--red-600);
  padding: 6px 0;
}
</style>
