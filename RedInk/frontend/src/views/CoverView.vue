<template>
  <div class="container latex-workbench">
    <div class="page-header">
      <div>
        <h1 class="page-title">LaTeX 模板工作台</h1>
        <p class="page-subtitle">左侧切换模板，中间编辑 LaTeX，右侧手动渲染预览</p>
      </div>
      <div class="header-actions">
        <button class="btn" @click="router.push('/content')" style="border:1px solid var(--border-color)">
          返回文本
        </button>
        <button class="btn btn-primary" @click="saveAndContinue" :disabled="saving">
          {{ saving ? '保存中...' : '保存并继续' }}
        </button>
      </div>
    </div>

    <div class="workbench-grid">
      <aside class="card template-sidebar">
        <div class="sidebar-title">模板预览</div>
        <button
          v-for="entry in templateEntries"
          :key="entry.key"
          class="template-thumb"
          :class="{ active: selectedTemplateKey === entry.key }"
          @click="selectedTemplateKey = entry.key"
        >
          <div class="template-thumb-image">
            <img v-if="entry.previewUrl" :src="entry.previewUrl" :alt="entry.label" />
            <div v-else class="template-thumb-placeholder">{{ entry.shortLabel }}</div>
          </div>
          <div class="template-thumb-meta">
            <div class="template-thumb-title">{{ entry.label }}</div>
            <div class="template-thumb-subtitle">{{ entry.description }}</div>
          </div>
        </button>
      </aside>

      <section class="card editor-panel">
        <div class="editor-header">
          <div>
            <h3 class="section-title">{{ currentTemplate?.label || '未选择模板' }}</h3>
            <p class="editor-note">
              {{ currentTemplate?.description || '请选择一个模板进行编辑。' }}
            </p>
          </div>
          <div class="editor-actions">
            <button class="btn" @click="generateCurrentDraft" :disabled="drafting || rendering || saving">
              {{ drafting ? '生成中...' : 'AI 生成模板' }}
            </button>
            <button class="btn btn-primary" @click="renderCurrentTemplate" :disabled="rendering || drafting || saving">
              {{ rendering ? '渲染中...' : '渲染预览' }}
            </button>
          </div>
        </div>

        <div v-if="currentTemplate?.kind === 'page'" class="page-content-box">
          <div class="page-content-label">页面文案</div>
          <div class="page-content-text">{{ currentTemplate.page?.content || '未提供页面文案' }}</div>
        </div>

        <textarea
          v-model="currentLatexCode"
          class="latex-editor"
          placeholder="% 在这里输入或生成 LaTeX 模板代码"
          spellcheck="false"
        />

        <div v-if="currentTemplate?.kind === 'cover' && coverVersions.length > 0" class="version-section">
          <div class="version-title">封面历史版本</div>
          <div class="version-list">
            <button
              v-for="version in coverVersions"
              :key="version.id"
              class="version-chip"
              :class="{ active: selectedVersionId === version.id }"
              @click="applyVersion(version.id)"
            >
              {{ version.name }} ({{ version.id }})
            </button>
          </div>
        </div>

        <div class="save-tip">代码会自动保存到历史记录，渲染改为手动触发。</div>
        <div v-if="error" class="error-box">{{ error }}</div>
      </section>

      <section class="card preview-panel">
        <div class="preview-header">
          <h3 class="section-title">渲染结果</h3>
          <span class="preview-meta">{{ currentTemplate?.label || '未选择模板' }}</span>
        </div>

        <div class="preview-box">
          <img v-if="currentPreviewUrl" :src="currentPreviewUrl" :alt="currentTemplate?.label || 'preview'" />
          <div v-else class="preview-empty">点击“渲染预览”查看当前 LaTeX 输出</div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useGeneratorStore } from '../stores/generator'
import {
  createHistory,
  generateLatexDraft,
  getHistory,
  previewLatex,
  regenerateCover,
  selectCoverVersion,
  type CoverVersion,
  type Page,
  updateHistory
} from '../api'

type TemplateEntry = {
  key: string
  kind: 'cover' | 'page'
  label: string
  shortLabel: string
  description: string
  page?: Page
  previewUrl?: string
}

const router = useRouter()
const store = useGeneratorStore()

const rendering = ref(false)
const drafting = ref(false)
const saving = ref(false)
const error = ref('')
const isInitializing = ref(true)
const selectedTemplateKey = ref('cover')
const selectedVersionId = ref<string>('')
const coverVersions = ref<CoverVersion[]>([])
const coverLatexCode = ref('')
const templatePreviewUrls = ref<Record<string, string>>({})

let autoSaveTimer: ReturnType<typeof setTimeout> | null = null

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
    error.value = result.error || '创建历史记录失败'
    return false
  }
  store.setRecordId(result.record_id)
  return true
}

function getTemplateKey(page: Page) {
  return `page:${page.index}`
}

const latexPages = computed(() => {
  return store.outline.pages.filter((page) => page.render_mode === 'latex')
})

const templateEntries = computed<TemplateEntry[]>(() => {
  const entries: TemplateEntry[] = [
    {
      key: 'cover',
      kind: 'cover',
      label: '封面',
      shortLabel: '封面',
      description: '封面 LaTeX 模板',
      previewUrl: templatePreviewUrls.value.cover
    }
  ]

  latexPages.value.forEach((page) => {
    entries.push({
      key: getTemplateKey(page),
      kind: 'page',
      label: `P${page.index + 1}`,
      shortLabel: `P${page.index + 1}`,
      description: '正文 LaTeX 模板',
      page,
      previewUrl: templatePreviewUrls.value[getTemplateKey(page)]
    })
  })

  return entries
})

const currentTemplate = computed(() => {
  return templateEntries.value.find((entry) => entry.key === selectedTemplateKey.value) || templateEntries.value[0] || null
})

const currentPreviewUrl = computed(() => {
  return currentTemplate.value?.previewUrl || ''
})

const currentLatexCode = computed({
  get() {
    if (!currentTemplate.value) return ''
    if (currentTemplate.value.kind === 'cover') {
      return coverLatexCode.value
    }
    return currentTemplate.value.page?.latex_code || ''
  },
  set(value: string) {
    if (!currentTemplate.value) return
    if (currentTemplate.value.kind === 'cover') {
      coverLatexCode.value = value
      return
    }
    const page = currentTemplate.value.page
    if (page) {
      page.latex_code = value
    }
  }
})

function ensureSelectedTemplateValid() {
  if (!templateEntries.value.some((entry) => entry.key === selectedTemplateKey.value)) {
    selectedTemplateKey.value = templateEntries.value[0]?.key || 'cover'
  }
}

async function loadFromHistory() {
  if (!store.recordId) return
  const res = await getHistory(store.recordId)
  if (!res.success || !res.record) return

  store.setOutline(res.record.outline.raw, res.record.outline.pages)
  store.startCoverEditing()

  coverLatexCode.value = res.record.cover_latex_code || ''
  coverVersions.value = Array.isArray(res.record.cover_versions) ? res.record.cover_versions : []
  selectedVersionId.value = res.record.selected_cover_version || ''

  const nextPreviewUrls: Record<string, string> = {}
  if (selectedVersionId.value) {
    const selected = coverVersions.value.find((item) => item.id === selectedVersionId.value)
    if (selected?.task_id && selected?.image_filename) {
      nextPreviewUrls.cover = `/api/images/${selected.task_id}/${selected.image_filename}?thumbnail=false&t=${Date.now()}`
      if (!coverLatexCode.value) {
        coverLatexCode.value = selected.latex_code || ''
      }
    }
  }

  if (res.record.images.task_id && Array.isArray(res.record.images.generated)) {
    res.record.outline.pages
      .filter((page) => page.render_mode === 'latex')
      .forEach((page) => {
        const filename = res.record?.images.generated?.[page.index]
        if (filename) {
          nextPreviewUrls[getTemplateKey(page)] = `/api/images/${res.record!.images.task_id}/${filename}?thumbnail=false&t=${Date.now()}`
        }
      })
  }

  templatePreviewUrls.value = {
    ...templatePreviewUrls.value,
    ...nextPreviewUrls
  }

  ensureSelectedTemplateValid()
}

async function persistLatexDrafts() {
  if (!store.recordId) return
  await updateHistory(store.recordId, {
    outline: {
      raw: store.outline.raw,
      pages: store.outline.pages
    },
    cover_latex_code: coverLatexCode.value
  })
}

function scheduleAutoSave() {
  if (isInitializing.value || saving.value) return
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  autoSaveTimer = setTimeout(async () => {
    try {
      await ensureRecordId()
      await persistLatexDrafts()
    } catch (e) {
      console.warn('自动保存 LaTeX 代码失败:', e)
    }
  }, 500)
}

async function renderCurrentTemplate() {
  error.value = ''
  const latexCode = currentLatexCode.value.trim()
  if (!latexCode) {
    error.value = '当前模板还没有 LaTeX 代码，请先手写或点击“AI 生成模板”。'
    return
  }

  rendering.value = true
  try {
    const result = await previewLatex(latexCode)
    if (!result.success || !result.image_base64) {
      error.value = result.error || '预览生成失败'
      return
    }

    if (currentTemplate.value) {
      templatePreviewUrls.value = {
        ...templatePreviewUrls.value,
        [currentTemplate.value.key]: `data:${result.mime_type || 'image/png'};base64,${result.image_base64}`
      }
    }
  } catch (e: any) {
    error.value = e.message || '预览生成失败'
  } finally {
    rendering.value = false
  }
}

async function generateCurrentDraft() {
  error.value = ''
  drafting.value = true
  try {
    const ok = await ensureRecordId()
    if (!ok || !store.recordId || !currentTemplate.value) return

    const result = await generateLatexDraft({
      record_id: store.recordId,
      target: currentTemplate.value.kind,
      page_index: currentTemplate.value.page?.index,
      page_content: currentTemplate.value.page?.content || '',
      full_outline: store.outline.raw,
      user_topic: store.topic
    })

    if (!result.success || !result.latex_code) {
      error.value = result.error || 'LaTeX 草稿生成失败'
      return
    }

    currentLatexCode.value = result.latex_code
    await persistLatexDrafts()
  } catch (e: any) {
    error.value = e.message || 'LaTeX 草稿生成失败'
  } finally {
    drafting.value = false
  }
}

async function applyVersion(versionId: string) {
  error.value = ''
  if (!store.recordId) return
  try {
    const result = await selectCoverVersion({
      record_id: store.recordId,
      version_id: versionId
    })
    if (!result.success) {
      error.value = result.error || '版本切换失败'
      return
    }

    selectedVersionId.value = versionId
    coverLatexCode.value = result.latex_code || ''
    if (result.image_url) {
      templatePreviewUrls.value = {
        ...templatePreviewUrls.value,
        cover: `${result.image_url}${result.image_url.includes('?') ? '&' : '?'}t=${Date.now()}`
      }
    }
    await persistLatexDrafts()
  } catch (e: any) {
    error.value = e.message || '版本切换失败'
  }
}

async function saveAndContinue() {
  error.value = ''
  saving.value = true
  try {
    const ok = await ensureRecordId()
    if (!ok || !store.recordId) return

    await persistLatexDrafts()

    const selectedVersion = coverVersions.value.find((item) => item.id === selectedVersionId.value)
    const hasExistingCoverImage = Boolean(selectedVersion?.task_id && selectedVersion?.image_filename)
    const latexCode = coverLatexCode.value.trim()

    if (latexCode) {
      const result = await regenerateCover({
        record_id: store.recordId,
        latex_code: latexCode,
        version_name: '封面定稿',
        source: 'manual_latex',
        set_selected: true,
        full_outline: store.outline.raw,
        user_topic: store.topic
      })

      if (!result.success) {
        error.value = result.error || '封面保存失败'
        return
      }

      if (result.task_id) {
        store.taskId = result.task_id
      }
      selectedVersionId.value = result.selected_cover_version || result.version_id || ''
      if (result.image_url) {
        templatePreviewUrls.value = {
          ...templatePreviewUrls.value,
          cover: `${result.image_url}${result.image_url.includes('?') ? '&' : '?'}t=${Date.now()}`
        }
      }

      await loadFromHistory()
    } else if (!hasExistingCoverImage) {
      error.value = '请先为封面生成或编写 LaTeX 模板，并至少渲染保存出一个封面版本。'
      return
    }

    router.push('/generate')
  } catch (e: any) {
    error.value = e.message || '保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  if (store.outline.pages.length === 0) {
    router.push('/')
    return
  }

  store.startCoverEditing()
  const ok = await ensureRecordId()
  if (!ok) return
  await loadFromHistory()
  ensureSelectedTemplateValid()
  isInitializing.value = false
})

watch(
  () => JSON.stringify({
    cover: coverLatexCode.value,
    pages: store.outline.pages.map((page) => ({
      index: page.index,
      render_mode: page.render_mode,
      latex_code: page.latex_code || ''
    }))
  }),
  () => {
    if (isInitializing.value) return
    scheduleAutoSave()
    ensureSelectedTemplateValid()
  }
)

onBeforeUnmount(() => {
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
})
</script>

<style scoped>
.latex-workbench {
  max-width: 1420px;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.workbench-grid {
  display: grid;
  grid-template-columns: 250px 1.1fr 0.9fr;
  gap: 18px;
  align-items: start;
}

.section-title {
  font-size: 15px;
  font-weight: 700;
  margin: 0;
}

.template-sidebar {
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sidebar-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-sub);
  margin-bottom: 4px;
}

.template-thumb {
  border: 1px solid var(--border-color);
  background: #fff;
  border-radius: 14px;
  padding: 10px;
  display: flex;
  gap: 10px;
  align-items: center;
  cursor: pointer;
  text-align: left;
  transition: all 0.2s ease;
}

.template-thumb:hover,
.template-thumb.active {
  border-color: var(--primary);
  box-shadow: 0 8px 20px rgba(255, 36, 66, 0.08);
}

.template-thumb-image {
  width: 62px;
  aspect-ratio: 3 / 4;
  border-radius: 10px;
  overflow: hidden;
  background: #f3f5f8;
  flex-shrink: 0;
}

.template-thumb-image img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.template-thumb-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #8b93a1;
  font-size: 12px;
  font-weight: 700;
}

.template-thumb-meta {
  min-width: 0;
}

.template-thumb-title {
  font-size: 13px;
  font-weight: 700;
  color: #253041;
}

.template-thumb-subtitle {
  font-size: 12px;
  color: var(--text-sub);
  margin-top: 4px;
}

.editor-panel,
.preview-panel {
  padding: 16px;
}

.editor-header,
.preview-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.editor-note,
.preview-meta {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-sub);
}

.editor-actions {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}

.page-content-box {
  margin-bottom: 12px;
  border: 1px solid #e7ebf0;
  border-radius: 12px;
  background: #fafbfd;
  padding: 12px;
}

.page-content-label {
  font-size: 12px;
  color: var(--text-sub);
  margin-bottom: 6px;
}

.page-content-text {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.7;
  color: #364052;
}

.latex-editor {
  width: 100%;
  min-height: 640px;
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 14px 16px;
  background: #0f1720;
  color: #e6edf7;
  font-size: 13px;
  line-height: 1.65;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  resize: vertical;
  outline: none;
}

.latex-editor:focus {
  border-color: var(--primary);
}

.version-section {
  margin-top: 12px;
}

.version-title {
  font-size: 12px;
  color: var(--text-sub);
  margin-bottom: 8px;
}

.version-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.version-chip {
  border: 1px solid #d9dde3;
  background: #fff;
  color: #3f4956;
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
}

.version-chip.active {
  border-color: var(--primary);
  color: var(--primary);
  background: rgba(255, 36, 66, 0.08);
}

.save-tip {
  margin-top: 12px;
  font-size: 12px;
  color: var(--text-sub);
}

.error-box {
  margin-top: 10px;
  color: #c62828;
  background: #fff1f0;
  border: 1px solid #ffccc7;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 12px;
  white-space: pre-wrap;
}

.preview-box {
  width: 100%;
  aspect-ratio: 3 / 4;
  border: 1px dashed var(--border-color);
  border-radius: 14px;
  overflow: hidden;
  background: #f7f9fc;
}

.preview-box img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #fff;
}

.preview-empty {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: #7d8794;
  font-size: 13px;
  padding: 20px;
}

@media (max-width: 1180px) {
  .workbench-grid {
    grid-template-columns: 1fr;
  }

  .template-sidebar {
    flex-direction: row;
    overflow-x: auto;
  }

  .template-thumb {
    min-width: 220px;
  }

  .latex-editor {
    min-height: 420px;
  }
}
</style>
