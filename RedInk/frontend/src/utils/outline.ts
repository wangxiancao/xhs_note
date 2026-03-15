import type { Page } from '../api'

export function stripCoverPages(pages: Page[] = []): Page[] {
  return pages
    .filter((page) => page.type !== 'cover')
    .map((page, index) => ({
      index,
      type: page.type === 'summary' ? 'summary' : 'content',
      content: page.content,
      render_mode: page.render_mode === 'latex' || page.render_mode === 'upload' ? page.render_mode : 'ai',
      latex_code: page.latex_code || '',
      uploaded_image_task_id: page.uploaded_image_task_id || null,
      uploaded_image_filename: page.uploaded_image_filename || null
    }))
}

export function pagesToRaw(pages: Page[] = []): string {
  return pages.map((page) => page.content).join('\n\n<page>\n\n')
}

export function sanitizeOutline(raw: string, pages: Page[]) {
  const sanitizedPages = stripCoverPages(Array.isArray(pages) ? pages : [])
  return {
    raw: pagesToRaw(sanitizedPages) || raw || '',
    pages: sanitizedPages
  }
}
