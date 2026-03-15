<template>
  <div class="container content-workbench">
    <div class="page-header">
      <div>
        <h1 class="page-title">文本工作台</h1>
        <p class="page-subtitle">先预览生成的标题、文案和标签，再通过对话继续优化，确认后进入下一步</p>
      </div>
      <div class="header-actions">
        <button class="btn" @click="router.push('/outline')" style="border:1px solid var(--border-color)">
          返回大纲
        </button>
        <button class="btn" @click="regeneratePreview" :disabled="loadingPreview || refining">
          {{ loadingPreview ? '生成中...' : '重新生成预览' }}
        </button>
        <button class="btn btn-primary" @click="saveAndContinue" :disabled="!canContinue || loadingPreview || refining">
          {{ saving ? '保存中...' : '确认文本并继续' }}
        </button>
      </div>
    </div>

    <div class="workbench-grid">
      <section class="card preview-panel">
        <div class="panel-header">
          <div>
            <h3 class="section-title">文本预览</h3>
            <p class="panel-note">左侧可以直接修改标题和正文，右侧可以继续和 AI 对话优化。</p>
          </div>
          <div class="status-chip" :class="content.status">
            {{ contentStatusLabel }}
          </div>
        </div>

        <div v-if="saveError" class="error-box">{{ saveError }}</div>
        <ContentDisplay />
      </section>

      <aside class="card chat-panel">
        <div class="panel-header">
          <div>
            <h3 class="section-title">AI 对话优化</h3>
            <p class="panel-note">例如：标题更口语化、正文压缩到 300 字、增加结尾互动等。</p>
          </div>
        </div>

        <div class="quick-prompts">
          <button
            v-for="prompt in quickPrompts"
            :key="prompt"
            class="quick-prompt"
            :disabled="!canRefine || refining"
            @click="sendPrompt(prompt)"
          >
            {{ prompt }}
          </button>
        </div>

        <div v-if="messages.length > 0" class="message-list">
          <div
            v-for="(message, index) in messages"
            :key="`${message.role}-${index}-${message.created_at || ''}`"
            class="message-item"
            :class="message.role"
          >
            <div class="message-role">{{ message.role === 'user' ? '你' : 'AI' }}</div>
            <div class="message-content">{{ message.content }}</div>
          </div>
        </div>

        <div v-else class="chat-empty">
          <div class="chat-empty-title">还没有优化对话</div>
          <p>文本生成完成后，你可以直接输入修改要求，AI 会返回一版新的完整标题、正文和标签。</p>
        </div>

        <div class="chat-composer">
          <textarea
            v-model="chatInput"
            class="chat-input"
            :disabled="!canRefine || refining"
            placeholder="告诉 AI 你想怎么优化这版文本"
            @keydown.enter.exact.prevent="sendPrompt()"
          />
          <button class="btn btn-primary chat-send" @click="sendPrompt()" :disabled="!canRefine || refining || !chatInput.trim()">
            {{ refining ? '优化中...' : '发送优化要求' }}
          </button>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useGeneratorStore } from '../stores/generator'
import {
  createHistory,
  generateContent,
  getHistory,
  refineContent,
  updateHistory,
  type ContentChatMessage,
  type ContentData
} from '../api'
import ContentDisplay from '../components/result/ContentDisplay.vue'

const router = useRouter()
const store = useGeneratorStore()

const loadingPreview = ref(false)
const refining = ref(false)
const saving = ref(false)
const booting = ref(true)
const saveError = ref('')
const chatInput = ref('')

let autoSaveTimer: ReturnType<typeof setTimeout> | null = null

const quickPrompts = [
  '标题更生活化一点',
  '正文压缩到 300 字左右',
  '增加更强的种草感',
  '语气更真诚一点'
]

const content = computed(() => store.content)
const messages = computed(() => store.content.messages || [])
const contentStatusLabel = computed(() => {
  const mapping: Record<string, string> = {
    idle: '等待生成',
    generating: '生成中',
    done: '可继续优化',
    error: '生成失败'
  }
  return mapping[store.content.status] || '等待生成'
})

const canRefine = computed(() => {
  return store.content.status === 'done' && (
    store.content.titles.length > 0 ||
    Boolean(store.content.copywriting.trim()) ||
    store.content.tags.length > 0
  )
})

const canContinue = computed(() => canRefine.value)

function getCurrentContentData(): ContentData {
  return {
    titles: [...(store.content.titles || [])],
    copywriting: store.content.copywriting || '',
    tags: [...(store.content.tags || [])]
  }
}

function hasContentData(data?: Partial<ContentData> | null) {
  if (!data) return false
  return Boolean(
    (Array.isArray(data.titles) && data.titles.length > 0) ||
    (data.copywriting && String(data.copywriting).trim()) ||
    (Array.isArray(data.tags) && data.tags.length > 0)
  )
}

async function ensureRecordId(): Promise<boolean> {
  if (store.recordId) return true

  const result = await createHistory(
    store.topic || '未命名主题',
    {
      raw: store.outline.raw,
      pages: store.outline.pages
    },
    store.taskId || undefined
  )

  if (!result.success || !result.record_id) {
    saveError.value = result.error || '创建历史记录失败'
    return false
  }

  store.setRecordId(result.record_id)
  return true
}

async function persistContentState() {
  if (!store.recordId) return

  await updateHistory(store.recordId, {
    content_data: getCurrentContentData(),
    content_chat_messages: messages.value
  })
}

function scheduleAutoSave() {
  if (booting.value || saving.value) return
  if (autoSaveTimer) clearTimeout(autoSaveTimer)

  autoSaveTimer = setTimeout(async () => {
    try {
      const ok = await ensureRecordId()
      if (!ok) return
      await persistContentState()
    } catch (error) {
      console.warn('自动保存文案失败:', error)
    }
  }, 500)
}

async function loadFromHistory() {
  if (!store.recordId) return

  const result = await getHistory(store.recordId)
  if (!result.success || !result.record) return

  store.setTopic(result.record.title)
  store.setOutline(result.record.outline.raw, result.record.outline.pages)
  store.startContentEditing()

  const contentData = result.record.content_data
  if (hasContentData(contentData)) {
    store.setContent(
      contentData?.titles || [],
      contentData?.copywriting || '',
      contentData?.tags || []
    )
  } else if (store.content.status === 'idle') {
    store.clearContent()
  }

  store.setContentMessages(result.record.content_chat_messages || [])
}

async function regeneratePreview() {
  if (loadingPreview.value || refining.value) return

  saveError.value = ''
  loadingPreview.value = true

  try {
    const ok = await ensureRecordId()
    if (!ok) {
      store.setContentError(saveError.value || '创建历史记录失败')
      return
    }

    store.setContentMessages([])
    store.startContentGeneration()

    const result = await generateContent(store.topic, store.outline.raw)
    if (!result.success || !result.titles || !result.copywriting || !result.tags) {
      store.setContentError(result.error || '生成文本失败')
      saveError.value = result.error || '生成文本失败'
      return
    }

    store.setContent(result.titles, result.copywriting, result.tags)
    await persistContentState()
  } catch (error: any) {
    const message = error?.message || '生成文本失败'
    store.setContentError(message)
    saveError.value = message
  } finally {
    loadingPreview.value = false
  }
}

async function sendPrompt(preset?: string) {
  const prompt = (preset || chatInput.value).trim()
  if (!prompt || refining.value) return
  if (!canRefine.value) {
    saveError.value = '请先生成一版文本预览，再继续对话优化。'
    return
  }

  saveError.value = ''
  refining.value = true

  try {
    const result = await refineContent(
      store.topic,
      store.outline.raw,
      getCurrentContentData(),
      messages.value,
      prompt
    )

    if (!result.success || !result.titles || !result.copywriting || !result.tags) {
      saveError.value = result.error || '文本优化失败'
      return
    }

    const now = new Date().toISOString()
    const userMessage: ContentChatMessage = {
      role: 'user',
      content: prompt,
      created_at: now
    }
    const assistantMessage: ContentChatMessage = {
      role: 'assistant',
      content: result.assistant_reply || '已按你的要求优化这版文本。',
      created_at: new Date().toISOString()
    }

    store.appendContentMessage(userMessage)
    store.setContent(result.titles, result.copywriting, result.tags)
    store.appendContentMessage(assistantMessage)
    chatInput.value = ''

    await persistContentState()
  } catch (error: any) {
    saveError.value = error?.message || '文本优化失败'
  } finally {
    refining.value = false
  }
}

async function saveAndContinue() {
  if (!canContinue.value || saving.value) return

  saveError.value = ''
  saving.value = true
  try {
    const ok = await ensureRecordId()
    if (!ok) return

    await persistContentState()
    store.startCoverEditing()
    router.push('/cover')
  } catch (error: any) {
    saveError.value = error?.message || '保存文本失败'
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  if (store.outline.pages.length === 0) {
    router.push('/')
    return
  }

  store.startContentEditing()
  const ok = await ensureRecordId()
  if (!ok) return

  await loadFromHistory()

  if (!canRefine.value && store.content.status !== 'generating') {
    await regeneratePreview()
  }

  booting.value = false
})

watch(
  () => JSON.stringify({
    titles: store.content.titles,
    copywriting: store.content.copywriting,
    tags: store.content.tags,
    messages: store.content.messages
  }),
  () => {
    scheduleAutoSave()
  }
)

onBeforeUnmount(() => {
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
})
</script>

<style scoped>
.content-workbench {
  max-width: 1480px;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.workbench-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) 420px;
  gap: 18px;
  align-items: start;
}

.preview-panel,
.chat-panel {
  padding: 18px;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.section-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
}

.panel-note {
  margin: 4px 0 0;
  color: var(--text-sub);
  font-size: 12px;
}

.status-chip {
  flex-shrink: 0;
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 600;
  background: #f3f4f6;
  color: #526071;
}

.status-chip.generating {
  background: #e8f3ff;
  color: #1463c5;
}

.status-chip.done {
  background: #ecfdf3;
  color: #14804a;
}

.status-chip.error {
  background: #fff1f0;
  color: #c62828;
}

.error-box {
  margin-bottom: 12px;
  color: #c62828;
  background: #fff1f0;
  border: 1px solid #ffccc7;
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 12px;
  white-space: pre-wrap;
}

.quick-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.quick-prompt {
  border: 1px solid #d9dde3;
  background: #fff;
  border-radius: 999px;
  padding: 7px 11px;
  font-size: 12px;
  color: #425062;
  cursor: pointer;
}

.quick-prompt:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 340px;
  max-height: 540px;
  overflow: auto;
  padding-right: 4px;
}

.message-item {
  border-radius: 14px;
  padding: 12px;
  white-space: pre-wrap;
}

.message-item.user {
  background: #fff6e9;
  border: 1px solid #ffe1b4;
}

.message-item.assistant {
  background: #f6f8fb;
  border: 1px solid #e4eaf1;
}

.message-role {
  font-size: 11px;
  font-weight: 700;
  margin-bottom: 6px;
  color: #7b8694;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.message-content {
  font-size: 13px;
  line-height: 1.7;
  color: #273242;
}

.chat-empty {
  min-height: 260px;
  border: 1px dashed var(--border-color);
  border-radius: 14px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  color: #728093;
  background: #fafbfd;
}

.chat-empty-title {
  font-size: 14px;
  font-weight: 700;
  color: #334155;
  margin-bottom: 8px;
}

.chat-composer {
  margin-top: 14px;
}

.chat-input {
  width: 100%;
  min-height: 120px;
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 12px 14px;
  resize: vertical;
  outline: none;
  font-size: 13px;
  line-height: 1.7;
  background: #fff;
}

.chat-input:focus {
  border-color: var(--primary);
}

.chat-send {
  width: 100%;
  margin-top: 10px;
}

@media (max-width: 1180px) {
  .workbench-grid {
    grid-template-columns: 1fr;
  }
}
</style>
