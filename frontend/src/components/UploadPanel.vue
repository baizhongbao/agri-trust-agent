<script setup>
import { ref } from 'vue'

const props = defineProps({
  busy: { type: Boolean, default: false },
  progress: { type: String, default: '' },
})

const emit = defineEmits(['select'])

const dragging = ref(false)
const fileInput = ref(null)

function pick() {
  if (props.busy) return
  fileInput.value?.click()
}

function onChange(event) {
  const file = event.target.files?.[0]
  if (file) emit('select', file)
  event.target.value = ''
}

function onDrop(event) {
  dragging.value = false
  if (props.busy) return
  const file = event.dataTransfer?.files?.[0]
  if (file) emit('select', file)
}
</script>

<template>
  <div class="card card-pad upload-card">
    <div class="title">
      <h3>上传合同</h3>
      <span class="tag tag-slate">PDF / 图片</span>
    </div>

    <div
      class="dropzone"
      :class="{ dragging, busy }"
      @click="pick"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <template v-if="busy">
        <div class="loader" />
        <p class="hint">{{ progress || '处理中…' }}</p>
      </template>
      <template v-else>
        <div class="drop-icon">⬆</div>
        <p class="drop-main">点击选择，或拖拽 PDF / 图片到此处</p>
        <p class="hint">支持电子版、扫描件与 JPG / PNG 照片（扫描件与图片需配置 OCR）</p>
      </template>
    </div>

    <input
      ref="fileInput"
      type="file"
      accept="application/pdf,.pdf,image/png,image/jpeg,.png,.jpg,.jpeg"
      class="hidden-input"
      @change="onChange"
    />

    <p class="footnote">
      支持 PDF 与图片（JPG/PNG）。文件保存于 <code>data/contracts/</code>，不会外传。
    </p>
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

.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-height: 152px;
  padding: 20px;
  border: 1.5px dashed var(--slate-300);
  border-radius: var(--radius-sm);
  background: var(--slate-50);
  text-align: center;
  cursor: pointer;
  transition: all 0.18s ease;
}

.dropzone:hover:not(.busy) {
  border-color: var(--green-500);
  background: var(--green-100);
}

.dropzone.dragging {
  border-color: var(--green-600);
  background: var(--green-100);
  transform: scale(1.01);
}

.dropzone.busy {
  cursor: progress;
}

.drop-icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: var(--green-100);
  color: var(--green-700);
  font-size: 17px;
  margin-bottom: 3px;
}

.drop-main {
  font-size: 13px;
  font-weight: 500;
  color: var(--slate-700);
}

.hint {
  font-size: 12px;
  color: var(--slate-500);
}

.hidden-input {
  display: none;
}

.loader {
  width: 26px;
  height: 26px;
  border: 3px solid var(--green-100);
  border-top-color: var(--green-600);
  border-radius: 50%;
  animation: spin 0.75s linear infinite;
  margin-bottom: 6px;
}

.footnote {
  margin-top: 11px;
  font-size: 12px;
  color: var(--slate-500);
  line-height: 1.6;
}

.footnote code {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--slate-100);
  font-size: 11px;
}
</style>
