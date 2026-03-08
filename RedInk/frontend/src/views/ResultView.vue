<template>
  <div class="container">
    <div class="page-header">
      <div>
        <h1 class="page-title">创作完成</h1>
        <p class="page-subtitle">恭喜！你的小红书图文已生成完毕，共 {{ store.images.length }} 张</p>
        <p style="margin-top: 6px; font-size: 12px; color: var(--text-sub);">
          发布状态：{{ publishStatusText }}
        </p>
      </div>
      <div style="display: flex; gap: 12px;">
        <button class="btn" @click="startOver" style="background: white; border: 1px solid var(--border-color);">
          再来一篇
        </button>
        <button
          class="btn btn-primary"
          @click="handlePublish"
          :disabled="publishing || !canPublish"
          :style="{ opacity: publishing || !canPublish ? 0.6 : 1 }"
        >
          <span v-if="publishing" class="spinner" style="width: 14px; height: 14px; border-width: 2px; margin-right: 8px;"></span>
          {{ publishing ? '发布中...' : '发布到小红书' }}
        </button>
        <button class="btn btn-primary" @click="downloadAll">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
          一键下载
        </button>
      </div>
    </div>

    <div class="card">
      <div class="grid-cols-4">
        <div v-for="image in store.images" :key="image.index" class="image-card group">
          <!-- Image Area -->
          <div
            v-if="image.url"
            style="position: relative; aspect-ratio: 3/4; overflow: hidden; cursor: pointer;"
            @click="viewImage(image.url)"
          >
            <img
              :src="image.url"
              :alt="`第 ${image.index + 1} 页`"
              style="width: 100%; height: 100%; object-fit: cover; transition: transform 0.3s;"
            />
            <!-- Regenerating Overlay -->
            <div v-if="regeneratingIndex === image.index" style="position: absolute; inset: 0; background: rgba(255,255,255,0.8); display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 10;">
               <div class="spinner" style="width: 24px; height: 24px; border-width: 2px; border-color: var(--primary); border-top-color: transparent;"></div>
               <span style="font-size: 12px; color: var(--primary); margin-top: 8px; font-weight: 600;">重绘中...</span>
            </div>

            <!-- Hover Overlay -->
            <div v-else style="position: absolute; inset: 0; background: rgba(0,0,0,0.3); opacity: 0; transition: opacity 0.2s; display: flex; align-items: center; justify-content: center; color: white; font-weight: 600;" class="hover-overlay">
              预览大图
            </div>
          </div>

          <!-- Action Bar -->
          <div style="padding: 12px; border-top: 1px solid #f0f0f0; display: flex; justify-content: space-between; align-items: center;">
            <span style="font-size: 12px; color: var(--text-sub);">Page {{ image.index + 1 }}</span>
            <div style="display: flex; gap: 8px;">
              <button
                style="border: none; background: none; color: var(--text-sub); cursor: pointer; display: flex; align-items: center;"
                title="重新生成此图"
                @click="handleRegenerate(image)"
                :disabled="regeneratingIndex === image.index"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 4v6h-6"></path><path d="M1 20v-6h6"></path><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
              </button>
              <button
                style="border: none; background: none; color: var(--primary); cursor: pointer; font-size: 12px;"
                @click="downloadOne(image)"
              >
                下载
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 标题、文案、标签生成区域 -->
    <ContentDisplay />
  </div>
</template>

<style scoped>
/* 确保图片预览区域正确填充 */
.image-card > div:first-child {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.image-card:hover .hover-overlay {
  opacity: 1;
}
.image-card:hover img {
  transform: scale(1.05);
}
</style>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useGeneratorStore } from '../stores/generator'
import { checkPublishStatus, publishFromResult, regenerateImage } from '../api'
import ContentDisplay from '../components/result/ContentDisplay.vue'

const router = useRouter()
const store = useGeneratorStore()
const regeneratingIndex = ref<number | null>(null)
const publishing = ref(false)
const publishStatusText = ref('正在检查登录状态...')

const canPublish = computed(() => {
  return Boolean(store.taskId) && store.images.some((image) => Boolean(image.url))
})

onMounted(async () => {
  await refreshPublishStatus()
})

const viewImage = (url: string) => {
  const baseUrl = url.split('?')[0]
  window.open(baseUrl + '?thumbnail=false', '_blank')
}

const startOver = () => {
  store.reset()
  router.push('/')
}

const downloadOne = (image: any) => {
  if (image.url) {
    const link = document.createElement('a')
    const baseUrl = image.url.split('?')[0]
    link.href = baseUrl + '?thumbnail=false'
    link.download = `rednote_page_${image.index + 1}.png`
    link.click()
  }
}

const downloadAll = () => {
  if (store.recordId) {
    const link = document.createElement('a')
    link.href = `/api/history/${store.recordId}/download`
    link.click()
  } else {
    store.images.forEach((image, index) => {
      if (image.url) {
        setTimeout(() => {
          const link = document.createElement('a')
          const baseUrl = image.url.split('?')[0]
          link.href = baseUrl + '?thumbnail=false'
          link.download = `rednote_page_${image.index + 1}.png`
          link.click()
        }, index * 300)
      }
    })
  }
}

const refreshPublishStatus = async () => {
  try {
    const result = await checkPublishStatus()
    if (result.success) {
      publishStatusText.value = result.is_logged_in
        ? `已登录（${result.username || '未知账号'}）`
        : '未登录，请先扫码登录 xiaohongshu-mcp'
    } else {
      publishStatusText.value = result.error || '无法获取发布状态'
    }
  } catch (e: any) {
    publishStatusText.value = e.message || '无法连接发布服务'
  }
}

const getImageFilenameFromUrl = (url: string): string | null => {
  if (!url) return null
  const baseUrl = url.split('?')[0]
  const parts = baseUrl.split('/')
  const filename = parts[parts.length - 1]
  return filename || null
}

const handlePublish = async () => {
  if (!store.taskId || publishing.value) return

  const imageFilenames = store.images
    .map(image => getImageFilenameFromUrl(image.url))
    .filter((name): name is string => Boolean(name))

  if (imageFilenames.length === 0) {
    alert('没有可发布的图片，请先完成图片生成。')
    return
  }

  const title = (store.content.titles?.[0] || store.topic || '').trim()
  const content = (store.content.copywriting || '').trim()

  if (!title) {
    alert('缺少发布标题，请先生成标题或填写主题。')
    return
  }
  if (!content) {
    alert('缺少发布正文，请先生成文案。')
    return
  }

  const confirmed = window.confirm(
    `确认发布到小红书吗？\n\n标题：${title}\n图片数：${imageFilenames.length}\n标签数：${store.content.tags.length}`
  )
  if (!confirmed) return

  publishing.value = true
  try {
    const result = await publishFromResult({
      task_id: store.taskId,
      topic: store.topic,
      title,
      content,
      tags: store.content.tags || [],
      image_filenames: imageFilenames,
    })

    if (result.success) {
      alert(result.message || '发布请求已提交。')
    } else {
      alert('发布失败: ' + (result.error || '未知错误'))
    }
  } catch (e: any) {
    alert('发布失败: ' + (e.message || '未知错误'))
  } finally {
    publishing.value = false
    await refreshPublishStatus()
  }
}

const handleRegenerate = async (image: any) => {
  if (!store.taskId || regeneratingIndex.value !== null) return

  regeneratingIndex.value = image.index
  try {
    // Find the page content from outline
    const pageContent = store.outline.pages.find(p => p.index === image.index)
    if (!pageContent) {
       alert('无法找到对应页面的内容')
       return
    }

    // 构建上下文信息
    const context = {
      fullOutline: store.outline.raw || '',
      userTopic: store.topic || ''
    }

    const result = await regenerateImage(store.taskId, pageContent, true, context)
    if (result.success && result.image_url) {
       const newUrl = result.image_url
       store.updateImage(image.index, newUrl)
    } else {
       alert('重绘失败: ' + (result.error || '未知错误'))
    }
  } catch (e: any) {
    alert('重绘失败: ' + e.message)
  } finally {
    regeneratingIndex.value = null
  }
}
</script>
