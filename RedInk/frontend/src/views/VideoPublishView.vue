<template>
  <div class="container video-publish-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">视频发布</h1>
        <p class="page-subtitle">跳过大纲、文案优化和配图流程，直接上传视频素材并发布到小红书</p>
        <p class="status-text">发布状态：{{ publishStatusText }}</p>
      </div>
      <div class="header-actions">
        <button class="btn" type="button" @click="goHome">返回首页</button>
        <button
          class="btn btn-primary"
          type="button"
          @click="handlePublish"
          :disabled="!canPublish || publishing || extractingCover"
          :style="{ opacity: !canPublish || publishing || extractingCover ? 0.65 : 1 }"
        >
          <span
            v-if="publishing || extractingCover"
            class="spinner"
            style="width: 14px; height: 14px; border-width: 2px; margin-right: 8px;"
          ></span>
          {{ publishing ? '发布中...' : extractingCover ? '截取封面中...' : '一键发布视频' }}
        </button>
      </div>
    </div>

    <div class="video-grid">
      <div class="card upload-card">
        <div class="section-head">
          <h2>视频素材</h2>
          <label class="picker-btn">
            <input type="file" accept="video/*" @change="handleVideoChange" />
            上传视频
          </label>
        </div>

        <div v-if="videoPreviewUrl" class="video-preview">
          <video :src="videoPreviewUrl" controls playsinline preload="metadata"></video>
        </div>
        <div v-else class="empty-state">
          请选择一个视频文件，封面会默认截取第一帧
        </div>

        <div v-if="videoFile" class="meta-list">
          <div class="meta-row">
            <span>文件名</span>
            <strong>{{ videoFile.name }}</strong>
          </div>
          <div class="meta-row">
            <span>文件大小</span>
            <strong>{{ formatFileSize(videoFile.size) }}</strong>
          </div>
        </div>
      </div>

      <div class="card upload-card">
        <div class="section-head">
          <h2>封面预览</h2>
          <div class="section-actions">
            <label class="picker-btn secondary">
              <input type="file" accept="image/*" @change="handleCoverChange" />
              上传封面
            </label>
            <button
              class="text-btn"
              type="button"
              @click="regenerateAutoCover"
              :disabled="!videoFile || extractingCover"
            >
              重新截取
            </button>
          </div>
        </div>

        <div v-if="coverPreviewUrl" class="cover-preview">
          <img :src="coverPreviewUrl" alt="视频封面预览" />
          <div class="cover-badge">
            {{ coverMode === 'manual' ? '手动上传' : '自动截取' }}
          </div>
        </div>
        <div v-else class="empty-state">
          上传视频后会自动生成封面，你也可以手动替换
        </div>

        <p class="helper-text">
          当前会把封面一并保存到本地流程中；若不手动上传，默认使用自动截取结果。
        </p>
      </div>
    </div>

    <div class="card form-card">
      <div class="form-head">
        <div>
          <h2>发布文案</h2>
          <p>标题可留空，系统会自动取正文首行前 20 个字符</p>
        </div>
        <div class="title-pill" :class="{ warning: effectiveTitle.length > 20 || !effectiveTitle }">
          实际标题：{{ effectiveTitle || '待从正文生成' }}
        </div>
      </div>

      <div class="form-grid">
        <div class="field">
          <label for="video-title">标题（可选）</label>
          <input
            id="video-title"
            v-model="title"
            type="text"
            maxlength="20"
            placeholder="留空时自动取正文首行前 20 个字符"
          />
        </div>

        <div class="field full">
          <label for="video-content">正文</label>
          <textarea
            id="video-content"
            v-model="content"
            rows="10"
            placeholder="输入要发布的视频文案，支持多行内容"
          ></textarea>
        </div>
      </div>

      <div class="tips-box">
        <div>1. 选择视频后会自动截取第一帧作为封面预览。</div>
        <div>2. 你可以手动上传封面，覆盖自动截取结果。</div>
        <div>3. 点击“一键发布视频”后，会直接调用 `xiaohongshu-mcp` 的视频发布能力。</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { checkPublishStatus, publishVideo } from '../api'

type CoverMode = 'auto' | 'manual' | 'none'

const router = useRouter()

const publishStatusText = ref('正在检查登录状态...')
const publishing = ref(false)
const extractingCover = ref(false)

const title = ref('')
const content = ref('')

const videoFile = ref<File | null>(null)
const videoPreviewUrl = ref('')

const coverFile = ref<File | null>(null)
const coverPreviewUrl = ref('')
const coverMode = ref<CoverMode>('none')

const effectiveTitle = computed(() => resolveVideoTitle(title.value, content.value))
const canPublish = computed(() => {
  return Boolean(videoFile.value)
    && Boolean(coverFile.value)
    && Boolean(content.value.trim())
    && Boolean(effectiveTitle.value)
    && effectiveTitle.value.length <= 20
})

onMounted(async () => {
  await refreshPublishStatus()
})

onUnmounted(() => {
  revokeObjectUrl(videoPreviewUrl.value)
  revokeObjectUrl(coverPreviewUrl.value)
})

function goHome() {
  router.push('/')
}

async function refreshPublishStatus() {
  try {
    const result = await checkPublishStatus()
    if (result.success) {
      publishStatusText.value = result.is_logged_in
        ? `已登录（${result.username || '未知账号'}）`
        : '未登录，请先扫码登录 xiaohongshu-mcp'
      return
    }
    publishStatusText.value = result.error || '无法获取发布状态'
  } catch (error: any) {
    publishStatusText.value = error.message || '无法连接发布服务'
  }
}

async function handleVideoChange(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  revokeObjectUrl(videoPreviewUrl.value)
  revokeObjectUrl(coverPreviewUrl.value)
  videoFile.value = file
  videoPreviewUrl.value = URL.createObjectURL(file)
  coverFile.value = null
  coverPreviewUrl.value = ''
  coverMode.value = 'none'
  await generateCoverFromVideo(file)

  target.value = ''
}

function handleCoverChange(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  applyCoverFile(file, 'manual')
  target.value = ''
}

async function regenerateAutoCover() {
  if (!videoFile.value) return
  await generateCoverFromVideo(videoFile.value)
}

async function generateCoverFromVideo(file: File) {
  extractingCover.value = true
  try {
    const generatedCover = await captureFirstFrame(file)
    applyCoverFile(generatedCover, 'auto')
  } catch (error: any) {
    alert(error.message || '自动截取封面失败，请手动上传封面。')
  } finally {
    extractingCover.value = false
  }
}

function applyCoverFile(file: File, mode: CoverMode) {
  revokeObjectUrl(coverPreviewUrl.value)
  coverFile.value = file
  coverPreviewUrl.value = URL.createObjectURL(file)
  coverMode.value = mode
}

async function handlePublish() {
  if (!videoFile.value || !coverFile.value || !content.value.trim() || publishing.value) {
    return
  }

  publishing.value = true
  try {
    const result = await publishVideo({
      title: title.value.trim() || undefined,
      content: content.value.trim(),
      video: videoFile.value,
      cover: coverFile.value,
    })

    if (result.success) {
      alert(result.message || '视频发布请求已提交。')
    } else {
      alert(`视频发布失败: ${result.error || '未知错误'}`)
    }
  } catch (error: any) {
    alert(`视频发布失败: ${error.message || '未知错误'}`)
  } finally {
    publishing.value = false
    await refreshPublishStatus()
  }
}

function resolveVideoTitle(inputTitle: string, inputContent: string) {
  const rawTitle = inputTitle.trim()
  if (rawTitle) return rawTitle

  const firstLine = inputContent
    .split('\n')
    .map(line => line.replace(/^#+/, '').trim())
    .find(Boolean)

  return firstLine ? firstLine.slice(0, 20).trim() : ''
}

function revokeObjectUrl(url: string) {
  if (url) {
    URL.revokeObjectURL(url)
  }
}

function formatFileSize(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

function captureFirstFrame(file: File): Promise<File> {
  return new Promise((resolve, reject) => {
    const video = document.createElement('video')
    const objectUrl = URL.createObjectURL(file)

    const cleanup = () => {
      video.pause()
      video.removeAttribute('src')
      video.load()
      URL.revokeObjectURL(objectUrl)
    }

    video.preload = 'auto'
    video.muted = true
    video.playsInline = true
    video.crossOrigin = 'anonymous'

    video.onloadeddata = () => {
      try {
        const canvas = document.createElement('canvas')
        const width = video.videoWidth || 720
        const height = video.videoHeight || 1280
        canvas.width = width
        canvas.height = height

        const ctx = canvas.getContext('2d')
        if (!ctx) {
          cleanup()
          reject(new Error('无法创建封面画布。'))
          return
        }

        ctx.drawImage(video, 0, 0, width, height)
        canvas.toBlob((blob) => {
          cleanup()
          if (!blob) {
            reject(new Error('视频封面生成失败，请手动上传封面。'))
            return
          }

          resolve(new File([blob], `${file.name.replace(/\.[^.]+$/, '') || 'video'}_cover.png`, {
            type: 'image/png'
          }))
        }, 'image/png')
      } catch (error) {
        cleanup()
        reject(error instanceof Error ? error : new Error('视频封面生成失败'))
      }
    }

    video.onerror = () => {
      cleanup()
      reject(new Error('视频解析失败，请更换文件后重试。'))
    }

    video.src = objectUrl
    video.load()
  })
}
</script>

<style scoped>
.video-publish-page {
  max-width: 1180px;
  padding-bottom: 40px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: flex-start;
  margin-bottom: 20px;
}

.page-subtitle {
  margin-top: 8px;
  color: var(--text-sub);
}

.status-text {
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-sub);
}

.header-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.video-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
  margin-bottom: 20px;
}

.upload-card,
.form-card {
  padding: 20px;
}

.section-head,
.form-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  margin-bottom: 16px;
}

.section-head h2,
.form-head h2 {
  margin: 0;
  font-size: 18px;
}

.section-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.picker-btn {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  padding: 8px 14px;
  background: var(--primary);
  color: white;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}

.picker-btn.secondary {
  background: white;
  color: var(--text-main);
  border: 1px solid var(--border-color);
}

.picker-btn input {
  display: none;
}

.text-btn {
  border: none;
  background: none;
  color: var(--primary);
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}

.text-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.video-preview {
  width: 100%;
  aspect-ratio: 9 / 16;
  border-radius: 16px;
  overflow: hidden;
  background: #000;
}

.video-preview video {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: contain;
}

.cover-preview {
  position: relative;
  width: 100%;
  aspect-ratio: 9 / 16;
  border-radius: 16px;
  overflow: hidden;
  background: #f6f7fb;
  border: 1px solid var(--border-color);
}

.cover-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.cover-badge {
  position: absolute;
  top: 12px;
  left: 12px;
  background: rgba(0, 0, 0, 0.72);
  color: white;
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
}

.empty-state {
  min-height: 220px;
  border: 1px dashed var(--border-color);
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-sub);
  background: #fafafa;
  text-align: center;
  padding: 16px;
}

.meta-list {
  margin-top: 16px;
  display: grid;
  gap: 10px;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 14px;
  color: var(--text-sub);
}

.meta-row strong {
  color: var(--text-main);
  text-align: right;
  word-break: break-all;
}

.helper-text {
  margin-top: 12px;
  font-size: 13px;
  color: var(--text-sub);
}

.title-pill {
  max-width: 420px;
  background: rgba(255, 36, 66, 0.08);
  color: var(--primary);
  border-radius: 999px;
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1.4;
}

.title-pill.warning {
  background: rgba(255, 166, 0, 0.12);
  color: #a96800;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field.full {
  grid-column: 1 / -1;
}

.field label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-main);
}

.field input,
.field textarea {
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 12px 14px;
  font-size: 15px;
  font-family: inherit;
  color: var(--text-main);
  background: white;
}

.field textarea {
  resize: vertical;
  min-height: 220px;
  line-height: 1.6;
}

.field input:focus,
.field textarea:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(255, 36, 66, 0.08);
}

.tips-box {
  margin-top: 16px;
  display: grid;
  gap: 8px;
  padding: 14px 16px;
  border-radius: 12px;
  background: rgba(255, 36, 66, 0.04);
  color: var(--text-sub);
  font-size: 13px;
}

@media (max-width: 960px) {
  .page-header,
  .form-head,
  .section-head {
    flex-direction: column;
    align-items: flex-start;
  }

  .video-grid,
  .form-grid {
    grid-template-columns: 1fr;
  }

  .title-pill {
    max-width: none;
    width: 100%;
  }
}
</style>
