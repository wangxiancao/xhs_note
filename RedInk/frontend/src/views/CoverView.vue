<template>
  <div class="container cover-container">
    <div class="page-header">
      <div>
        <h1 class="page-title">封面创作台</h1>
        <p class="page-subtitle">先确定封面，再继续正文配图生成</p>
      </div>
      <div style="display: flex; gap: 10px;">
        <button class="btn" @click="router.push('/outline')" style="border:1px solid var(--border-color)">
          返回大纲
        </button>
        <button class="btn btn-primary" @click="saveAndContinue" :disabled="saving">
          {{ saving ? '保存中...' : '保存封面并继续' }}
        </button>
      </div>
    </div>

    <div class="cover-grid">
      <div class="card form-card">
        <h3 class="section-title">文案编辑</h3>
        <div class="field">
          <label>主标题</label>
          <textarea v-model="coverSpec.title" rows="2" />
        </div>
        <div class="field">
          <label>副标题</label>
          <input v-model="coverSpec.subtitle" type="text" />
        </div>
        <div class="field">
          <label>Tag</label>
          <input v-model="coverSpec.tag" type="text" />
        </div>
        <div class="field">
          <label>顶部胶囊</label>
          <input v-model="coverSpec.top_badge" type="text" />
        </div>

        <h3 class="section-title">Hashtag</h3>
        <div class="field" v-for="(tag, idx) in coverSpec.hashtags.slice(0, 3)" :key="idx">
          <label>第 {{ idx + 1 }} 行</label>
          <input :value="tag" type="text" @input="setHashtag(idx, ($event.target as HTMLInputElement).value)" />
        </div>

        <h3 class="section-title">文字坐标</h3>
        <div class="pos-grid">
          <div class="pos-item">
            <label>标题 X</label>
            <input :value="getPos('title', 'x')" type="number" @input="setPos('title', 'x', ($event.target as HTMLInputElement).value)" />
          </div>
          <div class="pos-item">
            <label>标题 Y</label>
            <input :value="getPos('title', 'y')" type="number" @input="setPos('title', 'y', ($event.target as HTMLInputElement).value)" />
          </div>
          <div class="pos-item">
            <label>标题宽度</label>
            <input :value="getPos('title', 'width')" type="number" @input="setPos('title', 'width', ($event.target as HTMLInputElement).value)" />
          </div>

          <div class="pos-item">
            <label>副标题 X</label>
            <input :value="getPos('subtitle', 'x')" type="number" @input="setPos('subtitle', 'x', ($event.target as HTMLInputElement).value)" />
          </div>
          <div class="pos-item">
            <label>副标题 Y</label>
            <input :value="getPos('subtitle', 'y')" type="number" @input="setPos('subtitle', 'y', ($event.target as HTMLInputElement).value)" />
          </div>
          <div class="pos-item">
            <label>副标题宽度</label>
            <input :value="getPos('subtitle', 'width')" type="number" @input="setPos('subtitle', 'width', ($event.target as HTMLInputElement).value)" />
          </div>

          <div class="pos-item">
            <label>Tag X</label>
            <input :value="getPos('tag', 'x')" type="number" @input="setPos('tag', 'x', ($event.target as HTMLInputElement).value)" />
          </div>
          <div class="pos-item">
            <label>Tag Y</label>
            <input :value="getPos('tag', 'y')" type="number" @input="setPos('tag', 'y', ($event.target as HTMLInputElement).value)" />
          </div>
          <div class="pos-item">
            <label>顶部标签 X</label>
            <input :value="getPos('top_badge', 'x')" type="number" @input="setPos('top_badge', 'x', ($event.target as HTMLInputElement).value)" />
          </div>
          <div class="pos-item">
            <label>顶部标签 Y</label>
            <input :value="getPos('top_badge', 'y')" type="number" @input="setPos('top_badge', 'y', ($event.target as HTMLInputElement).value)" />
          </div>
        </div>

        <div class="actions">
          <button class="btn btn-primary" @click="generateAiDraft" :disabled="drafting || rendering || saving">
            {{ drafting ? '生成中...' : 'AI 生成草稿' }}
          </button>
          <button class="btn" @click="renderPreviewImage" :disabled="rendering || drafting || saving">
            {{ rendering ? '渲染中...' : '渲染预览' }}
          </button>
        </div>

        <div v-if="error" class="error-box">{{ error }}</div>
      </div>

      <div class="card preview-card">
        <div class="preview-header">
          <h3 class="section-title">封面预览</h3>
          <div class="meta">
            <span>版本：{{ selectedVersionId || '未选中' }}</span>
          </div>
        </div>

        <div class="preview-box">
          <img v-if="previewUrl" :src="previewUrl" alt="cover preview" />
          <div v-else class="preview-empty">点击“渲染预览”或“AI 生成草稿”</div>
        </div>

        <div v-if="coverVersions.length > 0" class="version-list">
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
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useGeneratorStore } from '../stores/generator'
import {
  type CoverSpec,
  type CoverVersion,
  createHistory,
  getHistory,
  previewCover,
  regenerateCover,
  selectCoverVersion,
  updateHistory
} from '../api'

const router = useRouter()
const store = useGeneratorStore()

const rendering = ref(false)
const drafting = ref(false)
const saving = ref(false)
const error = ref('')
const previewUrl = ref('')
const selectedVersionId = ref<string>('')
const coverVersions = ref<CoverVersion[]>([])

const DEFAULT_SPEC: CoverSpec = {
  title: '未命名封面',
  subtitle: '把生活调成静音模式',
  tag: '@ 夏日氛围感',
  hashtags: ['#治愈系生活', '#夏日碎片收集', '#慢生活'],
  top_badge: '建议收藏',
  footer_words: ['慢下来', '去生活', '爱自己'],
  positions: {
    title: { x: 98, y: 1040, anchor: 'west', width: 860 },
    subtitle: { x: 98, y: 900, anchor: 'west', width: 760 },
    tag: { x: 110, y: 620, anchor: 'west' },
    hashtags: [
      { x: 110, y: 500, anchor: 'west' },
      { x: 110, y: 430, anchor: 'west' },
      { x: 110, y: 360, anchor: 'west' }
    ],
    top_badge: { x: 960, y: 1540, anchor: 'center' },
    footer_words: [
      { x: 220, y: 70, anchor: 'center' },
      { x: 620, y: 70, anchor: 'center' },
      { x: 1020, y: 70, anchor: 'center' }
    ]
  },
  palette: {
    background: ['#9FC5E8', '#A9CCE8', '#C7E0F4', '#D6EAF8'],
    text_primary: '#1E4E79',
    text_secondary: '#5D8AA8',
    card_fill: '#EAF4FB',
    badge_bg: '#1E4E79',
    badge_text: '#EAF4FB'
  }
}

const coverSpec = ref<CoverSpec>(cloneSpec(DEFAULT_SPEC))

function cloneSpec(spec: CoverSpec): CoverSpec {
  return JSON.parse(JSON.stringify(spec))
}

function normalizeSpec(input?: Partial<CoverSpec> | null): CoverSpec {
  const merged = {
    ...cloneSpec(DEFAULT_SPEC),
    ...(input || {})
  } as CoverSpec

  if (!Array.isArray(merged.hashtags)) merged.hashtags = [...DEFAULT_SPEC.hashtags]
  if (!Array.isArray(merged.footer_words)) merged.footer_words = [...DEFAULT_SPEC.footer_words]
  while (merged.hashtags.length < 3) merged.hashtags.push('')
  merged.hashtags = merged.hashtags.slice(0, 3)
  while (merged.footer_words.length < 3) merged.footer_words.push('')
  merged.footer_words = merged.footer_words.slice(0, 3)
  if (!merged.positions || typeof merged.positions !== 'object') merged.positions = cloneSpec(DEFAULT_SPEC).positions
  if (!merged.palette || typeof merged.palette !== 'object') merged.palette = cloneSpec(DEFAULT_SPEC).palette

  return merged
}

function extractField(content: string, prefixes: string[]): string {
  for (const rawLine of (content || '').split('\n')) {
    const line = rawLine.trim()
    for (const prefix of prefixes) {
      if (line.startsWith(prefix)) {
        if (line.includes('：')) return line.split('：', 2)[1].trim()
        if (line.includes(':')) return line.split(':', 2)[1].trim()
      }
    }
  }
  return ''
}

function deriveSpecFromOutline(): CoverSpec {
  const coverPage = store.outline.pages.find(page => page.type === 'cover') || store.outline.pages[0]
  const content = coverPage?.content || ''

  const hashtags = content
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.startsWith('#'))
    .slice(0, 3)

  return normalizeSpec({
    title: extractField(content, ['标题：', '主标题：', '标题:', '主标题:']) || store.topic || DEFAULT_SPEC.title,
    subtitle: extractField(content, ['副标题：', '副标题:']) || DEFAULT_SPEC.subtitle,
    tag: extractField(content, ['标签：', '标签:', 'Tag：', 'TAG：']) || DEFAULT_SPEC.tag,
    top_badge: extractField(content, ['顶部标签：', '胶囊标签：']) || DEFAULT_SPEC.top_badge,
    hashtags: hashtags.length > 0 ? hashtags : DEFAULT_SPEC.hashtags
  })
}

function coverSpecToPageContent(spec: CoverSpec): string {
  const lines = ['[封面]', `标题：${spec.title}`]
  if (spec.subtitle?.trim()) lines.push(`副标题：${spec.subtitle.trim()}`)
  if (spec.tag?.trim()) lines.push(`标签：${spec.tag.trim()}`)
  if (spec.top_badge?.trim()) lines.push(`顶部标签：${spec.top_badge.trim()}`)
  for (const hashtag of spec.hashtags.slice(0, 3)) {
    const text = (hashtag || '').trim()
    if (!text) continue
    lines.push(text.startsWith('#') ? text : `#${text}`)
  }
  return lines.join('\n')
}

function getPos(section: 'title' | 'subtitle' | 'tag' | 'top_badge', key: 'x' | 'y' | 'width') {
  const pos = (coverSpec.value.positions?.[section] || {}) as Record<string, any>
  return typeof pos[key] === 'number' ? pos[key] : ''
}

function setPos(section: 'title' | 'subtitle' | 'tag' | 'top_badge', key: 'x' | 'y' | 'width', value: string) {
  const parsed = Number(value)
  if (!coverSpec.value.positions || typeof coverSpec.value.positions !== 'object') {
    coverSpec.value.positions = {}
  }
  if (!coverSpec.value.positions[section] || typeof coverSpec.value.positions[section] !== 'object') {
    coverSpec.value.positions[section] = {}
  }
  coverSpec.value.positions[section][key] = Number.isFinite(parsed) ? parsed : value
}

function setHashtag(index: number, value: string) {
  while (coverSpec.value.hashtags.length < 3) coverSpec.value.hashtags.push('')
  coverSpec.value.hashtags[index] = value
}

async function ensureRecordId(): Promise<boolean> {
  if (store.recordId) return true
  const result = await createHistory(
    store.topic || '未命名主题',
    {
      raw: store.outline.raw,
      pages: store.outline.pages
    },
    store.taskId || undefined,
    coverSpec.value
  )
  if (!result.success || !result.record_id) {
    error.value = result.error || '创建历史记录失败'
    return false
  }
  store.setRecordId(result.record_id)
  return true
}

async function loadFromHistory() {
  if (!store.recordId) return
  const res = await getHistory(store.recordId)
  if (!res.success || !res.record) return

  coverSpec.value = normalizeSpec(res.record.cover_spec as CoverSpec)
  coverVersions.value = Array.isArray(res.record.cover_versions) ? res.record.cover_versions : []
  selectedVersionId.value = res.record.selected_cover_version || ''

  if (selectedVersionId.value) {
    const selected = coverVersions.value.find((item) => item.id === selectedVersionId.value)
    if (selected?.task_id && selected?.image_filename) {
      previewUrl.value = `/api/images/${selected.task_id}/${selected.image_filename}?thumbnail=false&t=${Date.now()}`
    }
  }
}

async function renderPreviewImage() {
  error.value = ''
  rendering.value = true
  try {
    const ok = await ensureRecordId()
    if (!ok || !store.recordId) return

    const result = await previewCover({
      record_id: store.recordId,
      cover_spec: coverSpec.value,
      full_outline: store.outline.raw,
      user_topic: store.topic
    })
    if (!result.success || !result.image_base64) {
      error.value = result.error || '预览生成失败'
      return
    }
    previewUrl.value = `data:${result.mime_type || 'image/png'};base64,${result.image_base64}`
  } catch (e: any) {
    error.value = e.message || '预览生成失败'
  } finally {
    rendering.value = false
  }
}

async function generateAiDraft() {
  error.value = ''
  drafting.value = true
  try {
    const ok = await ensureRecordId()
    if (!ok || !store.recordId) return

    const result = await regenerateCover({
      record_id: store.recordId,
      cover_spec: coverSpec.value,
      version_name: 'AI草稿',
      source: 'ai_draft',
      set_selected: false,
      full_outline: store.outline.raw,
      user_topic: store.topic
    })
    if (!result.success) {
      error.value = result.error || 'AI 草稿生成失败'
      return
    }
    if (result.image_url) {
      previewUrl.value = `${result.image_url}${result.image_url.includes('?') ? '&' : '?'}t=${Date.now()}`
    }
    await loadFromHistory()
  } catch (e: any) {
    error.value = e.message || 'AI 草稿生成失败'
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
    if (result.cover_spec) {
      coverSpec.value = normalizeSpec(result.cover_spec)
    }
    if (result.image_url) {
      previewUrl.value = `${result.image_url}${result.image_url.includes('?') ? '&' : '?'}t=${Date.now()}`
    }
    await syncCoverToOutlineAndHistory(false)
  } catch (e: any) {
    error.value = e.message || '版本切换失败'
  }
}

async function syncCoverToOutlineAndHistory(syncSelectedVersion: boolean) {
  let coverPage = store.outline.pages.find((page) => page.type === 'cover')
  if (!coverPage) {
    if (store.outline.pages.length === 0) {
      store.addPage('cover', '')
      coverPage = store.outline.pages[0]
    } else {
      coverPage = store.outline.pages[0]
      coverPage.type = 'cover'
    }
  }

  coverPage.content = coverSpecToPageContent(coverSpec.value)
  store.syncRawFromPages()

  if (store.recordId) {
    await updateHistory(store.recordId, {
      outline: {
        raw: store.outline.raw,
        pages: store.outline.pages
      },
      cover_spec: coverSpec.value,
      selected_cover_version: syncSelectedVersion ? selectedVersionId.value || null : undefined
    })
  }
}

async function saveAndContinue() {
  error.value = ''
  saving.value = true
  try {
    const ok = await ensureRecordId()
    if (!ok || !store.recordId) return

    const result = await regenerateCover({
      record_id: store.recordId,
      cover_spec: coverSpec.value,
      version_name: '封面定稿',
      source: 'manual',
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
      previewUrl.value = `${result.image_url}${result.image_url.includes('?') ? '&' : '?'}t=${Date.now()}`
    }

    await loadFromHistory()
    await syncCoverToOutlineAndHistory(true)
    router.push('/generate')
  } catch (e: any) {
    error.value = e.message || '封面保存失败'
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
  coverSpec.value = deriveSpecFromOutline()

  const ok = await ensureRecordId()
  if (!ok) return
  await loadFromHistory()
})
</script>

<style scoped>
.cover-container {
  max-width: 1280px;
}

.cover-grid {
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 18px;
  align-items: start;
}

.section-title {
  font-size: 15px;
  font-weight: 700;
  margin: 0 0 12px;
}

.field {
  margin-bottom: 10px;
}

.field label {
  display: block;
  font-size: 12px;
  color: var(--text-sub);
  margin-bottom: 6px;
}

.field input,
.field textarea {
  width: 100%;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 14px;
  outline: none;
  background: #fff;
}

.field textarea {
  resize: vertical;
}

.field input:focus,
.field textarea:focus {
  border-color: var(--primary);
}

.pos-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.pos-item label {
  display: block;
  font-size: 12px;
  color: var(--text-sub);
  margin-bottom: 4px;
}

.pos-item input {
  width: 100%;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
}

.actions {
  margin-top: 14px;
  display: flex;
  gap: 10px;
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

.preview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.preview-header .meta {
  font-size: 12px;
  color: var(--text-sub);
}

.preview-box {
  width: 100%;
  aspect-ratio: 3 / 4;
  border: 1px dashed var(--border-color);
  border-radius: 12px;
  overflow: hidden;
  background: #f8f9fb;
}

.preview-box img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.preview-empty {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-sub);
  font-size: 13px;
}

.version-list {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.version-chip {
  border: 1px solid var(--border-color);
  background: white;
  color: var(--text-main);
  border-radius: 999px;
  padding: 5px 10px;
  font-size: 12px;
  cursor: pointer;
}

.version-chip.active {
  border-color: var(--primary);
  color: var(--primary);
  background: rgba(255, 36, 66, 0.08);
}

@media (max-width: 1024px) {
  .cover-grid {
    grid-template-columns: 1fr;
  }
}
</style>
