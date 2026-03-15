<template>
  <div class="content-display">
    <!-- 生成按钮 -->
    <div v-if="content.status === 'idle'" class="generate-section">
      <button class="btn btn-primary generate-btn" @click="handleGenerate" :disabled="loading">
        <svg v-if="!loading" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 5v14M5 12h14"/>
        </svg>
        <span v-if="loading" class="spinner"></span>
        {{ loading ? '生成中...' : '生成标题、文案和标签' }}
      </button>
    </div>

    <!-- 加载状态 -->
    <div v-else-if="content.status === 'generating'" class="loading-section">
      <div class="loading-spinner"></div>
      <p>正在生成标题、文案和标签...</p>
    </div>

    <!-- 错误状态 -->
    <div v-else-if="content.status === 'error'" class="error-section">
      <div class="error-icon">!</div>
      <p class="error-message">{{ content.error || '生成失败，请重试' }}</p>
      <button class="btn btn-secondary" @click="handleGenerate">重新生成</button>
    </div>

    <!-- 生成结果 -->
    <div v-else-if="content.status === 'done'" class="result-section">
      <!-- 标题区域 -->
      <div class="content-card">
        <div class="card-header">
          <h3>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M4 6h16M4 12h16M4 18h10"/>
            </svg>
            标题
          </h3>
          <button class="copy-btn" @click="copyTitles" :class="{ copied: copiedTitles }">
            <svg v-if="!copiedTitles" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
            </svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            {{ copiedTitles ? '已复制' : '复制' }}
          </button>
        </div>
        <div class="titles-list">
          <div v-for="(_, index) in editableTitles" :key="index" class="title-item">
            <span class="title-badge">{{ index === 0 ? '推荐' : `备选${index}` }}</span>
            <input
              class="title-edit-input"
              :value="editableTitles[index]"
              @input="updateTitle(index, ($event.target as HTMLInputElement).value)"
              placeholder="请输入标题"
            />
            <div class="title-actions">
              <span
                v-if="index === 0"
                class="title-counter"
                :class="{ warn: editableTitles[index].length > 20 }"
              >
                {{ editableTitles[index].length }}/20
              </span>
              <button class="copy-mini-btn" @click="copyTitle(index)">
                {{ copiedTitleIndex === index ? '已复制' : '复制' }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 文案区域 -->
      <div class="content-card">
        <div class="card-header">
          <h3>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="16" y1="13" x2="8" y2="13"/>
              <line x1="16" y1="17" x2="8" y2="17"/>
            </svg>
            文案
          </h3>
          <button class="copy-btn" @click="copyCopywriting" :class="{ copied: copiedCopywriting }">
            <svg v-if="!copiedCopywriting" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
            </svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            {{ copiedCopywriting ? '已复制' : '复制' }}
          </button>
        </div>
        <div class="copywriting-content">
          <textarea
            class="copywriting-edit-area"
            :value="editableCopywriting"
            @input="updateCopywriting(($event.target as HTMLTextAreaElement).value)"
            placeholder="请输入正文内容"
          />
          <div class="copywriting-counter">{{ editableCopywriting.length }} 字</div>
        </div>
      </div>

      <!-- 标签区域 -->
      <div class="content-card">
        <div class="card-header">
          <h3>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/>
              <line x1="7" y1="7" x2="7.01" y2="7"/>
            </svg>
            标签
          </h3>
          <button class="copy-btn" @click="copyTags" :class="{ copied: copiedTags }">
            <svg v-if="!copiedTags" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
            </svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
            {{ copiedTags ? '已复制' : '复制全部' }}
          </button>
        </div>
        <div class="tags-list">
          <span
            v-for="(tag, index) in content.tags"
            :key="index"
            class="tag-item"
            @click="copyTag(tag, index)"
            :class="{ copied: copiedTagIndex === index }"
          >
            #{{ tag }}
          </span>
        </div>
      </div>

      <!-- 重新生成按钮 -->
      <div class="regenerate-section">
        <button class="btn btn-secondary" @click="handleGenerate" :disabled="loading">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M23 4v6h-6M1 20v-6h6"/>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
          {{ loading ? '生成中...' : '重新生成' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useGeneratorStore } from '../../stores/generator'
import { generateContent } from '../../api'

const store = useGeneratorStore()

const loading = ref(false)
const copiedTitles = ref(false)
const copiedCopywriting = ref(false)
const copiedTags = ref(false)
const copiedTitleIndex = ref<number | null>(null)
const copiedTagIndex = ref<number | null>(null)
const editableTitles = ref<string[]>([])
const editableCopywriting = ref('')

const content = computed(() => store.content)

watch(
  () => content.value.titles,
  (titles) => {
    editableTitles.value = Array.isArray(titles) ? [...titles] : []
  },
  { deep: true, immediate: true }
)

watch(
  () => content.value.copywriting,
  (text) => {
    editableCopywriting.value = text || ''
  },
  { immediate: true }
)

// 生成内容
async function handleGenerate() {
  if (loading.value) return

  loading.value = true
  store.setContentMessages([])
  store.startContentGeneration()

  try {
    const result = await generateContent(store.topic, store.outline.raw)

    if (result.success && result.titles && result.copywriting && result.tags) {
      store.setContent(result.titles, result.copywriting, result.tags)
    } else {
      store.setContentError(result.error || '生成失败')
    }
  } catch (error: any) {
    store.setContentError(error.message || '生成失败，请重试')
  } finally {
    loading.value = false
  }
}

// 复制到剪贴板
async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    // 降级方案
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    try {
      document.execCommand('copy')
      return true
    } catch {
      return false
    } finally {
      document.body.removeChild(textarea)
    }
  }
}

// 复制所有标题
async function copyTitles() {
  const text = editableTitles.value.join('\n')
  if (await copyToClipboard(text)) {
    copiedTitles.value = true
    setTimeout(() => copiedTitles.value = false, 2000)
  }
}

// 复制单个标题
async function copyTitle(index: number) {
  const title = editableTitles.value[index] || ''
  if (await copyToClipboard(title)) {
    copiedTitleIndex.value = index
    setTimeout(() => copiedTitleIndex.value = null, 2000)
  }
}

// 复制文案
async function copyCopywriting() {
  if (await copyToClipboard(editableCopywriting.value)) {
    copiedCopywriting.value = true
    setTimeout(() => copiedCopywriting.value = false, 2000)
  }
}

function updateTitle(index: number, value: string) {
  editableTitles.value[index] = value
  store.updateContentTitle(index, value)
}

function updateCopywriting(value: string) {
  editableCopywriting.value = value
  store.updateContentCopywriting(value)
}

// 复制所有标签
async function copyTags() {
  const text = content.value.tags.map(t => `#${t}`).join(' ')
  if (await copyToClipboard(text)) {
    copiedTags.value = true
    setTimeout(() => copiedTags.value = false, 2000)
  }
}

// 复制单个标签
async function copyTag(tag: string, index: number) {
  if (await copyToClipboard(`#${tag}`)) {
    copiedTagIndex.value = index
    setTimeout(() => copiedTagIndex.value = null, 2000)
  }
}
</script>

<style scoped>
.content-display {
  margin-top: 32px;
}

.generate-section {
  text-align: center;
  padding: 40px 20px;
  background: var(--bg-card);
  border-radius: var(--radius-xl);
  border: 2px dashed var(--border-color);
}

.generate-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 16px 32px;
  font-size: 16px;
}

.generate-btn svg {
  width: 20px;
  height: 20px;
}

.loading-section {
  text-align: center;
  padding: 60px 20px;
  background: var(--bg-card);
  border-radius: var(--radius-xl);
}

.loading-spinner {
  width: 48px;
  height: 48px;
  border: 3px solid var(--border-color);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 16px;
}

.loading-section p {
  color: var(--text-sub);
  font-size: 16px;
}

.error-section {
  text-align: center;
  padding: 40px 20px;
  background: #FFF2F0;
  border-radius: var(--radius-xl);
  border: 1px solid #FFCCC7;
}

.error-icon {
  width: 48px;
  height: 48px;
  background: #FF4D4F;
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  font-weight: bold;
  margin: 0 auto 16px;
}

.error-message {
  color: #CF1322;
  margin-bottom: 20px;
  white-space: pre-line;
}

.result-section {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.content-card {
  background: var(--bg-card);
  border-radius: var(--radius-lg);
  padding: 24px;
  box-shadow: var(--shadow-sm);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-color);
}

.card-header h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-main);
  margin: 0;
}

.card-header h3 svg {
  width: 20px;
  height: 20px;
  color: var(--primary);
}

.copy-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  font-size: 13px;
  color: var(--text-sub);
  background: var(--bg-body);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.2s ease;
}

.copy-btn:hover {
  background: var(--primary-light);
  color: var(--primary);
  border-color: var(--primary);
}

.copy-btn.copied {
  background: #E6FFFB;
  color: #13C2C2;
  border-color: #13C2C2;
}

.copy-btn svg {
  width: 14px;
  height: 14px;
}

/* 标题列表 */
.titles-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.title-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--bg-body);
  border-radius: var(--radius-md);
  transition: all 0.2s ease;
  position: relative;
}

.title-badge {
  flex-shrink: 0;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 4px;
  background: var(--primary);
  color: white;
}

.title-item:not(:first-child) .title-badge {
  background: var(--text-sub);
}

.title-edit-input {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  background: white;
  color: var(--text-main);
  font-size: 14px;
  line-height: 1.4;
}

.title-edit-input:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(255, 107, 107, 0.12);
}

.title-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.title-counter {
  font-size: 12px;
  color: var(--text-sub);
}

.title-counter.warn {
  color: #FF4D4F;
  font-weight: 600;
}

.copy-mini-btn {
  border: 1px solid var(--border-color);
  background: white;
  color: var(--text-sub);
  border-radius: var(--radius-sm);
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
}

.copy-mini-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}

/* 文案内容 */
.copywriting-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.copywriting-edit-area {
  width: 100%;
  min-height: 220px;
  resize: vertical;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 12px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-main);
  background: white;
  font-family: inherit;
}

.copywriting-edit-area:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 2px rgba(255, 107, 107, 0.12);
}

.copywriting-counter {
  align-self: flex-end;
  font-size: 12px;
  color: var(--text-sub);
}

/* 标签列表 */
.tags-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.tag-item {
  padding: 8px 16px;
  font-size: 14px;
  color: var(--primary);
  background: var(--primary-light);
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tag-item:hover {
  background: var(--primary);
  color: white;
}

.tag-item.copied {
  background: #13C2C2;
  color: white;
}

/* 重新生成 */
.regenerate-section {
  text-align: center;
  padding-top: 8px;
}

.regenerate-section .btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.regenerate-section .btn svg {
  width: 16px;
  height: 16px;
}

/* 动画 */
@keyframes spin {
  to { transform: rotate(360deg); }
}

.spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
</style>
