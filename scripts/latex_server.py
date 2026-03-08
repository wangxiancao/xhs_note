#!/usr/bin/env python3
"""
LaTeX 编辑与渲染服务（FastAPI）

启动方式:
    uvicorn latex_server:app --host 0.0.0.0 --port 8000

主要端点:
    POST /api/preview                  - 编译 LaTeX 返回 PNG base64
    POST /api/save                     - 编译并保存 PNG（可选保存 PDF）
    POST /api/editor/session/create    - 创建图文编辑会话
    GET  /api/editor/session/{id}      - 获取会话与当前页
    POST /api/editor/session/{id}/preview - 预览当前页
    POST /api/editor/session/{id}/save    - 保存当前页并进入下一页
    GET  /editor?session_id=...        - React 编辑器页面
"""

import base64
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

# 添加脚本目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from latex_compiler import LaTeXCompiler, TemplateManager
from render_note_images import (
    THEMES,
    build_body_case_latex,
    build_body_list_latex,
    build_cover_latex,
    extract_tags_from_report,
    merge_tags,
    normalize_tag,
    parse_body_sections,
    parse_markdown,
)

# FastAPI 应用
app = FastAPI(
    title="LaTeX 封面编辑器 API",
    description="小红书图文 LaTeX 编译与 React 编辑服务",
    version="2.0.0",
)

# CORS 配置 (允许局域网访问)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路径与编译器
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(__file__).parent / "generated_covers"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

EDITOR_SESSION_DIR = PROJECT_ROOT / "data" / "editor_sessions"
EDITOR_SESSION_DIR.mkdir(parents=True, exist_ok=True)
EDITOR_STATIC_FILE = Path(__file__).parent / "static" / "tex_editor.html"

compiler = LaTeXCompiler()


# ============ 请求/响应模型 ============

class PreviewRequest(BaseModel):
    code: str


class PreviewResponse(BaseModel):
    success: bool
    image: Optional[str] = None
    error: Optional[str] = None
    compilation_time: Optional[float] = None


class SaveRequest(BaseModel):
    code: str
    filename: str
    save_pdf: bool = False


class SaveResponse(BaseModel):
    success: bool
    message: str
    pdf_path: Optional[str] = None
    png_path: Optional[str] = None
    error: Optional[str] = None


class TemplateInfo(BaseModel):
    id: str
    name: str
    description: str
    preview_color: str


class TemplateDetail(BaseModel):
    id: str
    name: str
    content: str


class EditorSessionCreateRequest(BaseModel):
    input_md: str = ""
    input_tex_json: str = ""
    keyword: str = ""
    analysis_report: str = ""
    auto_tag_topk: int = 5
    max_tags: int = 8
    theme: str = "classic"
    output_dir: str = "images/notes"
    run_id: str = ""
    publish_mode: str = "checklist"
    body_template: str = "list"
    title_check_passed: bool = False


class EditorCodeRequest(BaseModel):
    page_id: str
    code: str


# ============ 工具函数 ============

def _validate_code_size(code: str) -> None:
    if not code or not code.strip():
        raise HTTPException(status_code=400, detail="LaTeX code is empty")
    if len(code) > 100 * 1024:
        raise HTTPException(status_code=400, detail="Code size exceeds limit (100KB)")


def _resolve_repo_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path.resolve()
    return (PROJECT_ROOT / path).resolve()


def _session_path(session_id: str) -> Path:
    return EDITOR_SESSION_DIR / f"{session_id}.json"


def _load_session(session_id: str) -> dict[str, Any]:
    path = _session_path(session_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_session(session: dict[str, Any]) -> None:
    path = _session_path(session["session_id"])
    path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_page(session: dict[str, Any], page_id: str) -> dict[str, Any]:
    for page in session["pages"]:
        if page["id"] == page_id:
            return page
    raise HTTPException(status_code=404, detail=f"Page not found: {page_id}")


def _first_unsaved_page(session: dict[str, Any]) -> Optional[dict[str, Any]]:
    for page in session["pages"]:
        if not page.get("saved", False):
            return page
    return None


FALLBACK_TEX = r"""\documentclass[preview,border=0pt]{standalone}
\usepackage{ctex}
\begin{document}
待补充内容
\end{document}
"""


EXPECTED_PAGES = {
    "viewpoint": [
        ("01_cover", "封面", "01_cover.png"),
    ],
    "checklist": [
        ("01_cover", "封面", "01_cover.png"),
        ("02_body", "正文卡1", "02_body.png"),
        ("03_body", "正文卡2", "03_body.png"),
        ("04_body", "正文卡3", "04_body.png"),
    ],
}


def _create_pages(
    *,
    parsed: dict[str, Any],
    theme: str,
    publish_mode: str,
    body_template: str,
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = [
        {
            "id": "01_cover",
            "label": "封面",
            "filename": "01_cover.png",
            "saved": False,
            "image_path": "",
            "code": build_cover_latex(theme, parsed["title"], parsed["cover"]),
        }
    ]

    if publish_mode == "checklist":
        body1_sections = parse_body_sections(parsed["body1"])
        body2_sections = parse_body_sections(parsed["body2"])
        body3_sections = parse_body_sections(parsed["body3"])

        if body_template == "case":
            pages.extend(
                [
                    {
                        "id": "02_body",
                        "label": "正文卡1",
                        "filename": "02_body.png",
                        "saved": False,
                        "image_path": "",
                        "code": build_body_case_latex(theme, parsed["title"], "案例拆解", body1_sections),
                    },
                    {
                        "id": "03_body",
                        "label": "正文卡2",
                        "filename": "03_body.png",
                        "saved": False,
                        "image_path": "",
                        "code": build_body_case_latex(theme, parsed["title"], "误区修正", body2_sections),
                    },
                    {
                        "id": "04_body",
                        "label": "正文卡3",
                        "filename": "04_body.png",
                        "saved": False,
                        "image_path": "",
                        "code": build_body_case_latex(theme, parsed["title"], "行动建议", body3_sections),
                    },
                ]
            )
        else:
            pages.extend(
                [
                    {
                        "id": "02_body",
                        "label": "正文卡1",
                        "filename": "02_body.png",
                        "saved": False,
                        "image_path": "",
                        "code": build_body_list_latex(theme, parsed["title"], "方法步骤", body1_sections),
                    },
                    {
                        "id": "03_body",
                        "label": "正文卡2",
                        "filename": "03_body.png",
                        "saved": False,
                        "image_path": "",
                        "code": build_body_list_latex(theme, parsed["title"], "常见误区", body2_sections),
                    },
                    {
                        "id": "04_body",
                        "label": "正文卡3",
                        "filename": "04_body.png",
                        "saved": False,
                        "image_path": "",
                        "code": build_body_list_latex(theme, parsed["title"], "执行复盘", body3_sections),
                    },
                ]
            )

    return pages


def _normalize_publish_mode(value: str) -> str:
    return value if value in {"viewpoint", "checklist"} else "checklist"


def _normalize_body_template(value: str, publish_mode: str) -> str:
    if publish_mode == "viewpoint":
        return ""
    return value if value in {"list", "case"} else "list"


def _normalize_tags(raw_tags: Any) -> list[str]:
    tags: list[str] = []
    if isinstance(raw_tags, list):
        for item in raw_tags:
            cleaned = normalize_tag(str(item))
            if cleaned and cleaned not in tags:
                tags.append(cleaned)
    return tags


def _normalize_tex_pages(raw_pages: Any, publish_mode: str) -> list[dict[str, Any]]:
    expected = EXPECTED_PAGES[publish_mode]
    if not isinstance(raw_pages, list):
        raw_pages = []

    by_id: dict[str, dict[str, Any]] = {}
    for page in raw_pages:
        if isinstance(page, dict):
            pid = str(page.get("id", "")).strip()
            if pid:
                by_id[pid] = page

    pages: list[dict[str, Any]] = []
    for idx, (pid, label, filename) in enumerate(expected):
        source = by_id.get(pid)
        if source is None and idx < len(raw_pages) and isinstance(raw_pages[idx], dict):
            source = raw_pages[idx]
        code = str(source.get("code", "")).strip() if isinstance(source, dict) else ""
        if not code:
            code = FALLBACK_TEX
        pages.append(
            {
                "id": pid,
                "label": label,
                "filename": filename,
                "saved": False,
                "image_path": "",
                "code": code,
            }
        )
    return pages


def _load_tex_blueprint(tex_json_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(tex_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid tex json: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid tex json: root must be object")
    return payload


def _build_session_summary(session: dict[str, Any]) -> dict[str, Any]:
    current_page = _first_unsaved_page(session) or session["pages"][-1]
    return {
        "session_id": session["session_id"],
        "title": session["title"],
        "keyword": session["keyword"],
        "theme": session["theme"],
        "publish_mode": session["publish_mode"],
        "body_template": session["body_template"],
        "output_dir": session["output_dir"],
        "run_id": session["run_id"],
        "manifest_path": session.get("manifest_path", ""),
        "completed": bool(session.get("manifest_path")),
        "pages": [
            {
                "id": page["id"],
                "label": page["label"],
                "filename": page["filename"],
                "saved": page.get("saved", False),
                "image_path": page.get("image_path", ""),
            }
            for page in session["pages"]
        ],
        "current_page": {
            "id": current_page["id"],
            "label": current_page["label"],
            "code": current_page["code"],
            "saved": current_page.get("saved", False),
        },
    }


def _write_manifest_if_completed(session: dict[str, Any]) -> None:
    if not all(page.get("saved", False) for page in session["pages"]):
        return

    out_dir = Path(session["output_dir"])
    manifest = {
        "title": session["title"],
        "images": [page["image_path"] for page in session["pages"]],
        "tags": session["tags"],
        "keyword": session["keyword"],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "title_check_passed": bool(session["title_check_passed"]),
        "publish_mode": session["publish_mode"],
    }
    if session["publish_mode"] == "checklist":
        manifest["body_template"] = session["body_template"]
    if session.get("analysis_report"):
        manifest["analysis_report"] = session["analysis_report"]
        manifest["report_tags_added"] = session.get("report_tags_added", [])

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    session["manifest_path"] = str(manifest_path)


# ============ API 端点 ============

@app.get("/")
async def root():
    return {"message": "LaTeX Cover Editor API", "version": "2.0.0", "editor": "/editor"}


@app.get("/editor", response_class=HTMLResponse)
async def editor_page():
    if not EDITOR_STATIC_FILE.exists():
        return HTMLResponse(
            "<h3>Editor page not found</h3><p>Please check scripts/static/tex_editor.html</p>",
            status_code=404,
        )
    return HTMLResponse(EDITOR_STATIC_FILE.read_text(encoding="utf-8"))


@app.get("/api/templates", response_model=List[TemplateInfo])
async def list_templates():
    return TemplateManager.list_templates()


@app.get("/api/templates/{template_id}", response_model=TemplateDetail)
async def get_template(template_id: str):
    content = TemplateManager.get_template(template_id)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    info = TemplateManager.TEMPLATE_INFO.get(template_id, {})
    return TemplateDetail(id=template_id, name=info.get("name", template_id), content=content)


@app.post("/api/preview", response_model=PreviewResponse)
async def preview(request: PreviewRequest):
    _validate_code_size(request.code)
    result = compiler.compile_and_preview(request.code)
    if result.success:
        return PreviewResponse(
            success=True,
            image=result.png_base64,
            compilation_time=result.compilation_time,
        )
    return PreviewResponse(success=False, error=result.error_message)


@app.post("/api/save", response_model=SaveResponse)
async def save(request: SaveRequest):
    _validate_code_size(request.code)
    if not request.filename or not request.filename.strip():
        return SaveResponse(success=False, message="Filename is required", error="Filename is required")

    result = compiler.compile_and_save(request.code, request.filename, save_pdf=bool(request.save_pdf))
    if not result.success or not result.png_path:
        return SaveResponse(success=False, message="Compilation failed", error=result.error_message)

    relative_png = str(result.png_path.relative_to(OUTPUT_DIR.parent))
    relative_pdf = str(result.pdf_path.relative_to(OUTPUT_DIR.parent)) if result.pdf_path else None
    return SaveResponse(
        success=True,
        message="Cover saved successfully",
        png_path=f"/outputs/{relative_png}",
        pdf_path=f"/outputs/{relative_pdf}" if relative_pdf else None,
    )


@app.post("/api/editor/session/create")
async def create_editor_session(request: EditorSessionCreateRequest):
    if request.theme not in THEMES:
        raise HTTPException(status_code=400, detail=f"Invalid theme: {request.theme}")
    if not request.input_md and not request.input_tex_json:
        raise HTTPException(status_code=400, detail="Either input_md or input_tex_json is required")

    publish_mode = _normalize_publish_mode(request.publish_mode)
    body_template = _normalize_body_template(request.body_template, publish_mode)
    source_input_md = ""
    source_input_tex_json = ""
    title = ""
    draft_tags: list[str] = []
    pages: list[dict[str, Any]] = []

    if request.input_tex_json:
        tex_json_path = _resolve_repo_path(request.input_tex_json)
        if not tex_json_path.exists():
            raise HTTPException(status_code=404, detail=f"Input tex json not found: {tex_json_path}")

        blueprint = _load_tex_blueprint(tex_json_path)
        source_input_tex_json = str(tex_json_path)
        publish_mode = _normalize_publish_mode(str(blueprint.get("publish_mode", "")) or publish_mode)
        body_template = _normalize_body_template(str(blueprint.get("body_template", "")) or body_template, publish_mode)
        title = str(blueprint.get("title", "")).strip() or "未命名标题"
        draft_tags = _normalize_tags(blueprint.get("tags", []))
        pages = _normalize_tex_pages(blueprint.get("pages"), publish_mode)
    else:
        input_md = _resolve_repo_path(request.input_md)
        if not input_md.exists():
            raise HTTPException(status_code=404, detail=f"Input markdown not found: {input_md}")
        parsed = parse_markdown(input_md)
        source_input_md = str(input_md)
        title = parsed["title"]
        draft_tags = parsed["tags"]
        pages = _create_pages(
            parsed=parsed,
            theme=request.theme,
            publish_mode=publish_mode,
            body_template=body_template or "list",
        )

    run_id = request.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = (PROJECT_ROOT / request.output_dir / run_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    report_tags: list[str] = []
    analysis_report_path = ""
    if request.analysis_report:
        report_path = _resolve_repo_path(request.analysis_report)
        if not report_path.exists():
            raise HTTPException(status_code=404, detail=f"Analysis report not found: {report_path}")
        analysis_report_path = str(report_path)
        report_tags = extract_tags_from_report(
            report_path,
            max(request.auto_tag_topk, 0),
            request.keyword,
        )

    tags = merge_tags(draft_tags, report_tags, max(request.max_tags, 1))
    if not tags and request.keyword:
        keyword_tag = normalize_tag(request.keyword)
        tags = [keyword_tag] if keyword_tag else []

    session_id = uuid4().hex
    session = {
        "session_id": session_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input_md": source_input_md,
        "input_tex_json": source_input_tex_json,
        "title": title,
        "keyword": request.keyword,
        "theme": request.theme,
        "publish_mode": publish_mode,
        "body_template": body_template,
        "title_check_passed": bool(request.title_check_passed),
        "analysis_report": analysis_report_path,
        "report_tags_added": report_tags,
        "tags": tags,
        "run_id": run_id,
        "output_dir": str(out_dir),
        "manifest_path": "",
        "pages": pages,
    }
    _save_session(session)
    return {"success": True, "session": _build_session_summary(session)}


@app.get("/api/editor/session/{session_id}")
async def get_editor_session(session_id: str):
    session = _load_session(session_id)
    return {"success": True, "session": _build_session_summary(session)}


@app.post("/api/editor/session/{session_id}/preview")
async def preview_editor_page(session_id: str, request: EditorCodeRequest):
    session = _load_session(session_id)
    _find_page(session, request.page_id)
    _validate_code_size(request.code)

    result = compiler.compile_and_preview(request.code)
    if not result.success:
        return {"success": False, "error": result.error_message}
    return {
        "success": True,
        "page_id": request.page_id,
        "image": result.png_base64,
        "compilation_time": result.compilation_time,
    }


@app.post("/api/editor/session/{session_id}/save")
async def save_editor_page(session_id: str, request: EditorCodeRequest):
    session = _load_session(session_id)
    page = _find_page(session, request.page_id)
    _validate_code_size(request.code)

    file_prefix = f"{session['run_id']}_{request.page_id}"
    result = compiler.compile_and_save(request.code, file_prefix, save_pdf=False)
    if not result.success or not result.png_path:
        return {"success": False, "error": result.error_message or "Compilation failed"}

    out_dir = Path(session["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    dst_png = out_dir / page["filename"]
    shutil.copy2(result.png_path, dst_png)

    page["code"] = request.code
    page["saved"] = True
    page["image_path"] = str(dst_png)
    page["saved_at"] = datetime.now().isoformat(timespec="seconds")

    _write_manifest_if_completed(session)
    _save_session(session)

    next_page = _first_unsaved_page(session)
    preview_base64 = base64.b64encode(dst_png.read_bytes()).decode("utf-8")

    return {
        "success": True,
        "completed": bool(session.get("manifest_path")),
        "saved_page_id": request.page_id,
        "saved_image": preview_base64,
        "manifest_path": session.get("manifest_path", ""),
        "next_page": (
            {
                "id": next_page["id"],
                "label": next_page["label"],
                "code": next_page["code"],
            }
            if next_page
            else None
        ),
    }


@app.get("/outputs/{year_month}/{filename}")
async def get_output_file(year_month: str, filename: str):
    file_path = OUTPUT_DIR / year_month / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=file_path, filename=filename)


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "templates": len(TemplateManager.list_templates()),
        "editor_sessions": len(list(EDITOR_SESSION_DIR.glob("*.json"))),
    }


if __name__ == "__main__":
    import uvicorn

    print("Starting LaTeX Cover Editor API...")
    print("API docs: http://localhost:8000/docs")
    print("Editor: http://localhost:8000/editor")

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
