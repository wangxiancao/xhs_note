<template>
  <div class="container" style="max-width: 100%;">
    <div class="page-header" style="max-width: 1200px; margin: 0 auto 30px auto;">
      <div>
        <h1 class="page-title">编辑大纲</h1>
        <p class="page-subtitle">
          调整页面顺序，修改文案，打造完美内容
          <span v-if="isSaving" class="save-indicator saving">保存中...</span>
          <span v-else class="save-indicator saved">已保存</span>
        </p>
      </div>
      <div style="display: flex; gap: 12px;">
        <button class="btn btn-secondary" @click="goBack" style="background: white; border: 1px solid var(--border-color);">
          上一步
        </button>
        <button class="btn btn-primary" @click="startGeneration">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px;"><path d="M20.24 12.24a6 6 0 0 0-8.49-8.49L5 10.5V19h8.5z"></path><line x1="16" y1="8" x2="2" y2="22"></line><line x1="17.5" y1="15" x2="9" y2="15"></line></svg>
          进入 LaTeX 工作台
        </button>
      </div>
    </div>

    <div class="outline-grid">
      <div 
        v-for="(page, idx) in store.outline.pages" 
        :key="page.index"
        class="card outline-card"
        :draggable="true"
        @dragstart="onDragStart($event, idx)"
        @dragover.prevent="onDragOver($event, idx)"
        @drop="onDrop($event, idx)"
        :class="{ 'dragging-over': dragOverIndex === idx }"
      >
        <!-- 拖拽手柄 (改为右上角或更加隐蔽) -->
        <div class="card-top-bar">
          <div class="page-info">
             <span class="page-number">P{{ idx + 1 }}</span>
             <span class="page-type" :class="page.type">{{ getPageTypeName(page.type) }}</span>
             <span class="render-mode-badge" :class="getRenderModeClass(page.render_mode)">{{ getRenderModeName(page.render_mode) }}</span>
          </div>
          
          <div class="card-controls">
            <div class="drag-handle" title="拖拽排序">
               <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#999" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="12" r="1"></circle><circle cx="9" cy="5" r="1"></circle><circle cx="9" cy="19" r="1"></circle><circle cx="15" cy="12" r="1"></circle><circle cx="15" cy="5" r="1"></circle><circle cx="15" cy="19" r="1"></circle></svg>
            </div>
            <button class="icon-btn" @click="deletePage(idx)" title="删除此页">
               <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            </button>
          </div>
        </div>

        <textarea
          v-model="page.content"
          class="textarea-paper"
          placeholder="在此输入文案..."
          @input="store.updatePage(page.index, page.content)"
        />

        <div class="render-mode-panel">
          <label class="mode-label">渲染方式</label>
          <select
            class="mode-select"
            :value="page.render_mode || 'ai'"
            @change="updateRenderMode(page, ($event.target as HTMLSelectElement).value)"
          >
            <option value="ai">文生图</option>
            <option value="latex">LaTeX 模板</option>
            <option value="upload">用户上传图片</option>
          </select>
        </div>

        <div v-if="page.render_mode === 'latex'" class="mode-hint">
          当前页面会在下一步的 LaTeX 工作台里和封面一起编辑，并走模板化渲染链路。
        </div>

        <div v-if="page.render_mode === 'upload'" class="upload-panel">
          <div v-if="page.uploaded_image_task_id && page.uploaded_image_filename" class="upload-preview">
            <img :src="getUploadedPreviewUrl(page)" :alt="`第 ${idx + 1} 页上传图`" />
          </div>
          <label class="upload-btn">
            <input
              type="file"
              accept="image/*"
              style="display: none;"
              @change="onUploadPageImage(page, $event)"
            />
            {{ uploadingIndices.has(page.index) ? '上传中...' : (page.uploaded_image_filename ? '更换图片' : '上传图片') }}
          </label>
        </div>
        
        <div class="word-count">{{ page.content.length }} 字</div>
      </div>

      <!-- 添加按钮卡片 -->
      <div class="card add-card-dashed" @click="addPage('content')">
        <div class="add-content">
          <div class="add-icon">+</div>
          <span>添加页面</span>
        </div>
      </div>
    </div>
    
    <div style="height: 100px;"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useGeneratorStore } from '../stores/generator'
import { updateHistory, createHistory, getImageUrl, uploadPageImage, type Page } from '../api'

const router = useRouter()
const store = useGeneratorStore()

const dragOverIndex = ref<number | null>(null)
const draggedIndex = ref<number | null>(null)
// 保存状态指示
const isSaving = ref(false)
const uploadingIndices = ref<Set<number>>(new Set())

const getPageTypeName = (type: string) => {
  const names = {
    cover: '封面',
    content: '内容',
    summary: '总结'
  }
  return names[type as keyof typeof names] || '内容'
}

const getRenderModeName = (mode?: string) => {
  const names = {
    ai: '文生图',
    latex: 'LaTeX',
    upload: '上传图'
  }
  return names[mode as keyof typeof names] || '文生图'
}

const getRenderModeClass = (mode?: string) => {
  if (mode === 'latex') return 'latex'
  if (mode === 'upload') return 'upload'
  return 'ai'
}

// 拖拽逻辑
const onDragStart = (e: DragEvent, index: number) => {
  draggedIndex.value = index
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.dropEffect = 'move'
  }
}

const onDragOver = (e: DragEvent, index: number) => {
  if (draggedIndex.value === index) return
  dragOverIndex.value = index
}

const onDrop = (e: DragEvent, index: number) => {
  dragOverIndex.value = null
  if (draggedIndex.value !== null && draggedIndex.value !== index) {
    store.movePage(draggedIndex.value, index)
  }
  draggedIndex.value = null
}

const deletePage = (index: number) => {
  if (confirm('确定要删除这一页吗？')) {
    store.deletePage(index)
  }
}

const addPage = (type: 'cover' | 'content' | 'summary') => {
  store.addPage(type, '')
  // 滚动到底部
  nextTick(() => {
    window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })
  })
}

const goBack = () => {
  router.back()
}

const startGeneration = async () => {
  const invalidUploadPage = store.outline.pages.find(
    (page) => page.render_mode === 'upload' && (!page.uploaded_image_task_id || !page.uploaded_image_filename)
  )
  if (invalidUploadPage) {
    alert(`第 ${invalidUploadPage.index + 1} 页已切换为“用户上传图片”，但还没有上传图片。`)
    return
  }

  // 如果有待保存的内容，先强制保存
  if (saveTimer !== null) {
    clearTimeout(saveTimer)
    saveTimer = null
    await autoSaveOutline()
  }
  store.startCoverEditing()
  router.push('/cover')
}

// ==================== 自动保存功能 ====================

// 防抖定时器
let saveTimer: number | null = null

/**
 * 自动保存大纲到历史记录
 * 当大纲内容发生变化时，自动更新到后端
 */
const autoSaveOutline = async () => {
  // 如果没有 recordId，说明还未创建历史记录，无法自动保存
  if (!store.recordId) {
    console.warn('未找到历史记录ID，无法自动保存')
    return
  }

  // 如果没有大纲内容，不需要保存
  if (!store.outline.pages || store.outline.pages.length === 0) {
    return
  }

  try {
    isSaving.value = true

    // 调用更新历史记录 API
    const result = await updateHistory(store.recordId, {
      outline: {
        raw: store.outline.raw,
        pages: store.outline.pages
      }
    })

    if (!result.success) {
      console.error('自动保存失败:', result.error)
    } else {
      console.log('大纲已自动保存')
    }
  } catch (error) {
    console.error('自动保存出错:', error)
  } finally {
    isSaving.value = false
  }
}

/**
 * 防抖函数：延迟执行保存操作
 * 避免用户频繁编辑时产生大量请求
 */
const debouncedSave = () => {
  // 清除之前的定时器
  if (saveTimer !== null) {
    clearTimeout(saveTimer)
  }

  // 设置新的定时器，300ms 后执行保存
  saveTimer = window.setTimeout(() => {
    autoSaveOutline()
    saveTimer = null
  }, 300)
}

/**
 * 页面加载时检查历史记录
 * 如果没有 recordId 但有大纲数据，尝试创建历史记录
 */
const checkAndCreateHistory = async () => {
  // 如果已经有 recordId，无需创建
  if (store.recordId) {
    console.log('已存在历史记录ID:', store.recordId)
    return true
  }

  // 如果有大纲数据但没有 recordId，说明是异常情况，尝试创建
  if (store.outline.pages && store.outline.pages.length > 0) {
    console.log('检测到大纲数据但无历史记录ID，尝试创建历史记录')

    try {
      const result = await createHistory(
        store.topic || '未命名主题',
        {
          raw: store.outline.raw,
          pages: store.outline.pages
        },
        store.taskId || undefined
      )

      if (result.success && result.record_id) {
        store.setRecordId(result.record_id)
        console.log('历史记录创建成功，ID:', result.record_id)
        return true
      } else {
        console.error('创建历史记录失败:', result.error)
      }
    } catch (error) {
      console.error('创建历史记录出错:', error)
    }
  }

  return false
}

const updateRenderMode = (page: Page, mode: string) => {
  page.render_mode = mode === 'latex' || mode === 'upload' ? mode : 'ai'
}

const getUploadedPreviewUrl = (page: Page) => {
  if (!page.uploaded_image_task_id || !page.uploaded_image_filename) return ''
  return getImageUrl(page.uploaded_image_task_id, page.uploaded_image_filename, false)
}

const onUploadPageImage = async (page: Page, event: Event) => {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file) return

  const ok = await checkAndCreateHistory()
  if (!ok || !store.recordId) {
    alert('创建历史记录失败，暂时无法上传页面图片。')
    return
  }

  uploadingIndices.value = new Set(uploadingIndices.value).add(page.index)
  try {
    const result = await uploadPageImage(store.recordId, file)
    if (!result.success || !result.upload_task_id || !result.upload_filename) {
      alert(result.error || '上传图片失败')
      return
    }

    page.render_mode = 'upload'
    page.uploaded_image_task_id = result.upload_task_id
    page.uploaded_image_filename = result.upload_filename
    await autoSaveOutline()
  } catch (error) {
    console.error('上传页面图片出错:', error)
    alert('上传图片失败: ' + String(error))
  } finally {
    const nextUploading = new Set(uploadingIndices.value)
    nextUploading.delete(page.index)
    uploadingIndices.value = nextUploading
  }
}

// 组件挂载时检查历史记录
onMounted(() => {
  checkAndCreateHistory()
})

// 组件卸载时清理定时器
onUnmounted(() => {
  if (saveTimer !== null) {
    clearTimeout(saveTimer)
    saveTimer = null
  }
})

// 监听大纲变化，触发自动保存
watch(
  () => store.outline.pages,
  () => {
    // 使用防抖函数，避免频繁请求
    debouncedSave()
  },
  { deep: true } // 深度监听，确保能检测到数组内部对象的变化
)
</script>

<style scoped>
/* 保存状态指示器 */
.save-indicator {
  margin-left: 12px;
  font-size: 12px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 4px;
  transition: all 0.3s ease;
}

.save-indicator.saving {
  color: #1890ff;
  background: #e6f7ff;
  border: 1px solid #91d5ff;
}

.save-indicator.saved {
  color: #52c41a;
  background: #f6ffed;
  border: 1px solid #b7eb8f;
  opacity: 0.7;
}

/* 网格布局 */
.outline-grid {
  display: grid;
  /* 响应式列：最小宽度 280px，自动填充 */
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 24px;
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 20px;
}

.outline-card {
  display: flex;
  flex-direction: column;
  padding: 16px; /* 减小内边距 */
  transition: all 0.2s ease;
  border: none;
  border-radius: 8px; /* 较小的圆角 */
  background: white;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  /* 保持一定的长宽比感，虽然高度自适应，但由于 flex column 和内容撑开，
     这里设置一个 min-height 让它看起来像个竖向卡片 */
  min-height: 360px; 
  position: relative;
}

.outline-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0,0,0,0.08);
  z-index: 10;
}

.outline-card.dragging-over {
  border: 2px dashed var(--primary);
  opacity: 0.8;
}

/* 顶部栏 */
.card-top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f5f5f5;
}

.page-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-number {
  font-size: 14px;
  font-weight: 700;
  color: #ccc;
  font-family: 'Inter', sans-serif;
}

.page-type {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.page-type.cover { color: #FF4D4F; background: #FFF1F0; }
.page-type.content { color: #8c8c8c; background: #f5f5f5; }
.page-type.summary { color: #52C41A; background: #F6FFED; }

.render-mode-badge {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 999px;
  font-weight: 600;
}

.render-mode-badge.ai {
  color: #1677ff;
  background: #e6f4ff;
}

.render-mode-badge.latex {
  color: #7a4cff;
  background: #f3edff;
}

.render-mode-badge.upload {
  color: #d46b08;
  background: #fff7e6;
}

.card-controls {
  display: flex;
  gap: 8px;
  opacity: 0.4;
  transition: opacity 0.2s;
}
.outline-card:hover .card-controls { opacity: 1; }

.drag-handle {
  cursor: grab;
  padding: 2px;
}
.drag-handle:active { cursor: grabbing; }

.icon-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: #999;
  padding: 2px;
  transition: color 0.2s;
}
.icon-btn:hover { color: #FF4D4F; }

/* 文本区域 - 核心 */
.textarea-paper {
  flex: 1; /* 占据剩余空间 */
  width: 100%;
  border: none;
  background: transparent;
  padding: 0;
  font-size: 16px; /* 更大的字号 */
  line-height: 1.7; /* 舒适行高 */
  color: #333;
  resize: none; /* 禁止手动拉伸，保持卡片整体感 */
  font-family: inherit;
  margin-bottom: 10px;
}

.textarea-paper:focus {
  outline: none;
}

.render-mode-panel {
  margin-top: 10px;
}

.mode-label {
  display: block;
  font-size: 12px;
  color: var(--text-sub);
  margin-bottom: 6px;
}

.mode-select {
  width: 100%;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 8px 10px;
  background: #fff;
  font-size: 13px;
}

.mode-hint {
  margin-top: 10px;
  font-size: 12px;
  color: #7a4cff;
  background: #f7f3ff;
  border: 1px solid #e4d7ff;
  border-radius: 10px;
  padding: 8px 10px;
}

.upload-panel {
  margin-top: 10px;
}

.upload-preview {
  width: 100%;
  aspect-ratio: 3 / 4;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid #eceff3;
  background: #f6f7f9;
  margin-bottom: 10px;
}

.upload-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.upload-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 8px 12px;
  border-radius: 10px;
  background: #fff7e6;
  color: #ad6800;
  border: 1px solid #ffd591;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.word-count {
  text-align: right;
  font-size: 11px;
  color: #ddd;
  margin-top: auto;
}

/* 添加卡片 */
.add-card-dashed {
  border: 2px dashed #eee;
  background: transparent;
  box-shadow: none;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  min-height: 360px;
  color: #ccc;
  transition: all 0.2s;
}

.add-card-dashed:hover {
  border-color: var(--primary);
  color: var(--primary);
  background: rgba(255, 36, 66, 0.02);
}

.add-content {
  text-align: center;
}

.add-icon {
  font-size: 32px;
  font-weight: 300;
  margin-bottom: 8px;
}
</style>
