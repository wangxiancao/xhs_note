from __future__ import annotations

from typing import Any, Dict, List


VALID_PAGE_TYPES = {"content", "summary"}
VALID_RENDER_MODES = {"ai", "latex", "upload"}


def filter_cover_pages(pages: Any) -> List[Dict[str, Any]]:
    """Strip cover pages from outline payloads and reindex the remaining pages."""
    if not isinstance(pages, list):
        return []

    normalized_pages: List[Dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue

        page_type = str(page.get("type") or "content").strip().lower()
        if page_type == "cover":
            continue
        if page_type not in VALID_PAGE_TYPES:
            page_type = "content"
        render_mode = str(page.get("render_mode") or "ai").strip().lower()
        if render_mode not in VALID_RENDER_MODES:
            render_mode = "ai"

        normalized_pages.append({
            "index": len(normalized_pages),
            "type": page_type,
            "content": str(page.get("content") or ""),
            "render_mode": render_mode,
            "latex_code": str(page.get("latex_code") or ""),
            "uploaded_image_task_id": page.get("uploaded_image_task_id") or None,
            "uploaded_image_filename": page.get("uploaded_image_filename") or None,
        })

    return normalized_pages


def serialize_pages(pages: Any) -> str:
    normalized_pages = filter_cover_pages(pages)
    return "\n\n<page>\n\n".join(page["content"] for page in normalized_pages)


def normalize_outline_payload(outline: Any) -> Dict[str, Any]:
    if not isinstance(outline, dict):
        return {
            "raw": "",
            "pages": [],
        }

    normalized_pages = filter_cover_pages(outline.get("pages"))
    return {
        "raw": serialize_pages(normalized_pages),
        "pages": normalized_pages,
    }
