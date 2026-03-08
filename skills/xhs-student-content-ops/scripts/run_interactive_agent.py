#!/usr/bin/env python3
"""AI direct TeX generator: analysis report -> LaTeX pages JSON blueprint."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


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


def find_project_root() -> Path:
    cwd = Path.cwd()
    if (cwd / "scripts" / "render_note_images.py").exists():
        return cwd

    script_path = Path(__file__).resolve()
    candidate = script_path.parents[3]
    if (candidate / "scripts" / "render_note_images.py").exists():
        return candidate
    raise RuntimeError("Cannot locate project root")


def normalize_tag(raw: str) -> str:
    cleaned = raw.strip().lstrip("#").strip()
    cleaned = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9_-]", "", cleaned)
    return cleaned


def is_valid_tag(tag: str) -> bool:
    if len(tag) < 2 or len(tag) > 6:
        return False
    if tag.isdigit():
        return False
    blocked = {"skills", "skill", "title", "checklist", "viewpoint"}
    if tag.lower() in blocked:
        return False
    if re.fullmatch(r"[a-zA-Z_-]+", tag):
        return tag.isupper() and len(tag) <= 6
    return True


def keyword_segments(keyword: str) -> list[str]:
    tokens = [normalize_tag(tok) for tok in re.findall(r"[A-Za-z]+|[\u4e00-\u9fa5]+", keyword or "")]
    tokens = [tok for tok in tokens if len(tok) >= 2]
    return list(dict.fromkeys(tokens))


def is_related_to_keyword(tag: str, keyword: str) -> bool:
    tokens = keyword_segments(keyword)
    if not tokens:
        return True
    for token in tokens:
        if token in tag or tag in token:
            return True
    return False


def uniq_keep_order(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def extract_keyword_tags(report_path: Path, top_k: int, keyword: str) -> list[str]:
    text = report_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    in_keyword_section = False
    row_pattern = re.compile(r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*\d+\s*\|")
    tags: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and "关键词" in stripped:
            in_keyword_section = True
            continue
        if in_keyword_section and stripped.startswith("## "):
            break
        if not in_keyword_section:
            continue

        match = row_pattern.match(stripped)
        if not match:
            continue
        tag = normalize_tag(match.group(1))
        if tag and is_valid_tag(tag) and is_related_to_keyword(tag, keyword) and tag not in tags:
            tags.append(tag)
        if len(tags) >= top_k:
            break

    return tags


def extract_top_titles(report_path: Path, top_k: int = 3) -> list[str]:
    text = report_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    in_title_section = False
    row_pattern = re.compile(r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*\d+\s*\|\s*\d+\s*\|\s*\d+\s*\|")
    titles: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and "热门标题" in stripped:
            in_title_section = True
            continue
        if in_title_section and stripped.startswith("## "):
            break
        if not in_title_section:
            continue

        match = row_pattern.match(stripped)
        if not match:
            continue
        title = match.group(1).strip()
        if title and title not in titles:
            titles.append(title)
        if len(titles) >= top_k:
            break

    return titles


def call_chat_completions(
    *,
    api_base: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.6,
) -> str:
    base = api_base.rstrip("/")
    if base.endswith("/chat/completions"):
        endpoint = base
    elif base.endswith("/v1") or base.endswith("/v4"):
        endpoint = base + "/chat/completions"
    else:
        endpoint = base + "/v1/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    def send(request_payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(request_payload).encode("utf-8"),
            method="POST",
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        data = send(payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        if exc.code == 400 and "response_format" in body:
            payload.pop("response_format", None)
            data = send(payload)
        else:
            raise RuntimeError(f"API 请求失败: HTTP {exc.code} - {body[:400]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"API 请求失败: {exc}") from exc

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"API 响应缺少 choices 字段: {data}")
    message = choices[0].get("message", {})
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    raise RuntimeError(f"API 响应缺少 message.content: {data}")


def parse_model_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def enforce_title(title: str, keyword: str) -> str:
    normalized = re.sub(r"\s+", "", str(title or "")).strip()
    if not normalized:
        normalized = f"{keyword}实用方法" if keyword else "研究生实用方法"
    if keyword and keyword not in normalized:
        normalized = f"{keyword}{normalized}"
    if len(normalized) > 20:
        normalized = normalized[:20]
        if keyword and keyword not in normalized:
            left = max(0, 20 - len(keyword))
            normalized = keyword[:20] if left <= 0 else keyword + normalized[:left]
    return normalized


def choose_publish_mode(raw: str, preset: str) -> str:
    if preset in {"viewpoint", "checklist"}:
        return preset
    value = str(raw or "").strip().lower()
    return value if value in {"viewpoint", "checklist"} else "checklist"


def choose_body_template(raw: str, publish_mode: str) -> str:
    if publish_mode == "viewpoint":
        return ""
    value = str(raw or "").strip().lower()
    return value if value in {"list", "case"} else "list"


def resolve_tags(
    *,
    model_tags: Any,
    report_tags: list[str],
    keyword: str,
    max_tags: int,
) -> list[str]:
    candidates: list[str] = []
    if isinstance(model_tags, list):
        candidates = [str(x) for x in model_tags]
    elif isinstance(model_tags, str):
        candidates = re.split(r"[\s,，;；]+", model_tags.strip())

    normalized_model = [normalize_tag(x) for x in candidates]
    normalized_model = [x for x in normalized_model if x and is_valid_tag(x)]
    normalized_report = [x for x in report_tags if x and is_valid_tag(x)]

    base: list[str] = []
    if keyword:
        k = normalize_tag(keyword)
        if k:
            base.append(k)
    merged = uniq_keep_order([*base, *normalized_model, *normalized_report])
    return merged[: max(max_tags, 1)]


def _normalize_secret_value(raw: str) -> str:
    value = raw.strip()
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        value = value[1:-1].strip()
    return value


def _load_api_key_from_claude_md(project_root: Path) -> tuple[str, str]:
    claude_md = project_root / ".claude" / "CLAUDE.md"
    if not claude_md.exists():
        return "", ""

    pattern = re.compile(
        r'^\s*(?:export\s+)?(?P<name>GLM_API_KEY|GLM_tokens|ZHIPUAI_API_KEY|OPENAI_API_KEY)\s*[:=]\s*(?P<value>.+?)\s*$'
    )
    for line in claude_md.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        name = match.group("name")
        value = _normalize_secret_value(match.group("value"))
        if value:
            return value, f"{claude_md}#{name}"
    return "", ""


def resolve_api_key(primary_env_name: str, project_root: Path) -> tuple[str, str]:
    candidates = [
        primary_env_name,
        "GLM_API_KEY",
        "ZHIPUAI_API_KEY",
        "OPENAI_API_KEY",
        "GLM_tokens",
    ]
    seen: set[str] = set()
    for env_name in candidates:
        if not env_name or env_name in seen:
            continue
        seen.add(env_name)
        value = os.getenv(env_name, "").strip()
        if value:
            return value, env_name

    file_key, source = _load_api_key_from_claude_md(project_root)
    if file_key:
        return file_key, source

    return "", primary_env_name


def build_ai_prompts(
    *,
    keyword: str,
    publish_mode: str,
    body_template: str,
    report_tags: list[str],
    top_titles: list[str],
    report_excerpt: str,
) -> tuple[str, str]:
    system_prompt = (
        "你是小红书研究生/学生赛道内容策划与LaTeX设计助手。"
        "你必须直接生成可编译的LaTeX模板，输出纯JSON，不要解释。"
        "你的内容必须具体、可执行、信息密度高，拒绝空洞口号。"
    )

    mode_hint = publish_mode or "由你在 viewpoint/checklist 中选择"
    user_prompt = f"""
请基于趋势报告直接输出 LaTeX 图文模板，不要提问，不要互动。

硬性要求：
1) 标题 <=20字，必须包含关键词「{keyword}」
2) 输出模式：{mode_hint}
3) 如果是 checklist，必须输出 4 页（封面+3正文）
4) 每个 page.code 必须是完整可编译 LaTeX 文档
5) LaTeX 至少包含：\\documentclass[preview,border=0pt]{{standalone}} 和 \\usepackage{{ctex}}
6) tags 输出 3-8 个，尽量结合趋势标签
7) 禁止空洞内容：不要只写“高效提升/坚持执行/保持心态”这类泛话，而是给出具体的指导意见
8) 至少引用 1 个趋势事实（如平均点赞、收藏率、热门关键词/标题）
9) 兼容性要求：不要使用 TikZ 的 `drop shadow`、`blur shadow` 等易报错样式

参数：
- 指定正文模板: {body_template or "由你选择 list/case"}
- 趋势报告推荐标签: {", ".join(report_tags) if report_tags else "无"}
- 热门标题参考: {", ".join(top_titles) if top_titles else "无"}
- 趋势摘要:
{report_excerpt}

严格输出 JSON：
{{
  "title": "标题",
  "publish_mode": "viewpoint 或 checklist",
  "body_template": "list 或 case",
  "tags": ["标签1", "标签2", "标签3"],
  "pages": [
    {{
      "id": "01_cover",
      "label": "封面",
      "filename": "01_cover.png",
      "code": "完整latex"
    }},
    {{
      "id": "02_body",
      "label": "正文卡1",
      "filename": "02_body.png",
      "code": "完整latex"
    }},
    {{
      "id": "03_body",
      "label": "正文卡2",
      "filename": "03_body.png",
      "code": "完整latex"
    }},
    {{
      "id": "04_body",
      "label": "正文卡3",
      "filename": "04_body.png",
      "code": "完整latex"
    }}
  ]
}}
""".strip()

    return system_prompt, user_prompt


def _extract_visible_texts_from_tex(code: str) -> list[str]:
    texts = re.findall(r"\{([^{}]{2,220})\}", code or "")
    cleaned: list[str] = []
    for text in texts:
        t = text.strip()
        if not t:
            continue
        if t.startswith("\\"):
            continue
        if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", t):
            continue
        cleaned.append(t)
    return cleaned


def _looks_generic_text(text: str) -> bool:
    generic_phrases = [
        "高效提升",
        "坚持执行",
        "保持心态",
        "持续优化",
        "方法技巧",
        "实用建议",
        "待补充",
        "请补充",
    ]
    return any(p in text for p in generic_phrases)


def is_blueprint_too_generic(payload: dict[str, Any], publish_mode: str) -> bool:
    raw_pages = payload.get("pages", [])
    if not isinstance(raw_pages, list) or not raw_pages:
        return True

    page_codes = []
    for page in raw_pages:
        if isinstance(page, dict):
            code = str(page.get("code", "")).strip()
            if code:
                page_codes.append(code)

    if publish_mode == "checklist" and len(page_codes) < 4:
        return True
    if publish_mode == "viewpoint" and len(page_codes) < 1:
        return True

    for code in page_codes:
        if "drop shadow" in code or "blur shadow" in code:
            return True
        texts = _extract_visible_texts_from_tex(code)
        text_len = sum(len(t) for t in texts)
        if len(texts) < 4 or text_len < 60:
            return True
        if _looks_generic_text(" ".join(texts)):
            return True
    return False


def build_refine_prompt(previous_payload: dict[str, Any]) -> str:
    return (
        "上一版 TeX 模板内容过于空洞或存在兼容问题，请重写。"
        "要求：信息密度更高、每页至少5条有效信息、给出可执行动作和可验证标准、"
        "不要使用 drop shadow/blur shadow。"
        "下面是上一版JSON，请基于它重写并仅输出新的JSON：\n"
        + json.dumps(previous_payload, ensure_ascii=False)
    )


def normalize_pages(raw_pages: Any, publish_mode: str) -> list[dict[str, str]]:
    expected = EXPECTED_PAGES[publish_mode]
    if not isinstance(raw_pages, list):
        raw_pages = []

    by_id: dict[str, dict[str, Any]] = {}
    for page in raw_pages:
        if isinstance(page, dict):
            pid = str(page.get("id", "")).strip()
            if pid:
                by_id[pid] = page

    normalized: list[dict[str, str]] = []
    for idx, (pid, label, filename) in enumerate(expected):
        source = by_id.get(pid)
        if source is None and idx < len(raw_pages) and isinstance(raw_pages[idx], dict):
            source = raw_pages[idx]
        code = ""
        if isinstance(source, dict):
            code = str(source.get("code", "")).strip()
        if not code:
            code = FALLBACK_TEX
        normalized.append(
            {
                "id": pid,
                "label": label,
                "filename": filename,
                "code": code,
            }
        )
    return normalized


def resolve_output_plan(output_plan: str, keyword: str, project_root: Path) -> Path:
    if output_plan:
        return (project_root / output_plan).resolve()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_keyword = normalize_tag(keyword) or "unknown_keyword"
    return (project_root / "data" / "plans" / f"{timestamp}_{safe_keyword}_tex_plan.json").resolve()


def resolve_guard_report_path(output_tex_json: Path, project_root: Path) -> Path:
    plans_dir = project_root / "data" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    stem = output_tex_json.stem
    return (plans_dir / f"{stem}_tex_guard_report.json").resolve()


def run_ai_generation(
    *,
    analysis_report: str,
    keyword: str,
    output_tex_json: str = "data/note_tex_draft.json",
    output_plan: str = "",
    publish_mode: str = "",
    body_template: str = "",
    report_tag_topk: int = 5,
    max_tags: int = 8,
    api_base: str | None = None,
    api_model: str | None = None,
    api_key_env: str = "GLM_API_KEY",
    latex_server: str = "http://127.0.0.1:8000",
    disable_tex_guard: bool = False,
    tex_guard_repair_rounds: int = 2,
    tex_guard_preview_timeout: int = 180,
    temperature: float = 0.4,
) -> int:
    project_root = find_project_root()
    resolved_api_base = api_base or os.getenv("GLM_API_BASE", os.getenv("OPENAI_API_BASE", "https://open.bigmodel.cn/api/paas/v4"))
    resolved_api_model = api_model or os.getenv("GLM_MODEL", os.getenv("OPENAI_MODEL", "glm-4.7"))

    report_path = (project_root / analysis_report).resolve()
    if not report_path.exists():
        print(f"[error] analysis report not found: {report_path}", file=sys.stderr)
        return 2

    api_key, api_key_source = resolve_api_key(api_key_env, project_root)
    if not api_key:
        print(f"[error] API key not found in env or .claude/CLAUDE.md: {api_key_env}", file=sys.stderr)
        return 2

    report_tags = extract_keyword_tags(report_path, top_k=max(report_tag_topk, 0), keyword=keyword)
    top_titles = extract_top_titles(report_path, top_k=3)
    report_text = report_path.read_text(encoding="utf-8")
    report_excerpt = report_text[:1800]

    system_prompt, user_prompt = build_ai_prompts(
        keyword=keyword,
        publish_mode=publish_mode,
        body_template=body_template,
        report_tags=report_tags,
        top_titles=top_titles,
        report_excerpt=report_excerpt,
    )

    print(f"正在调用 AI API 生成 TeX 模板... (model={resolved_api_model}, key_env={api_key_source})")
    raw = call_chat_completions(
        api_base=resolved_api_base,
        api_key=api_key,
        model=resolved_api_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
    )
    payload = parse_model_json(raw)

    publish_mode = choose_publish_mode(payload.get("publish_mode"), publish_mode)
    if is_blueprint_too_generic(payload, publish_mode):
        print("检测到内容空洞或模板兼容风险，触发一次自动重写...")
        refine_prompt = build_refine_prompt(payload)
        raw_refined = call_chat_completions(
            api_base=resolved_api_base,
            api_key=api_key,
            model=resolved_api_model,
            system_prompt=(
                "你是小红书研究生赛道的资深内容策划+LaTeX排版专家。"
                "你必须输出信息密度高、可执行、可编译的JSON模板。"
            ),
            user_prompt=refine_prompt,
            temperature=0.3,
        )
        refined_payload = parse_model_json(raw_refined)
        refined_mode = choose_publish_mode(refined_payload.get("publish_mode"), publish_mode)
        if not is_blueprint_too_generic(refined_payload, refined_mode):
            payload = refined_payload
            publish_mode = refined_mode
        else:
            print("自动重写后仍偏空洞，保留首版结果。")

    body_template = choose_body_template(payload.get("body_template") or body_template, publish_mode)
    title = enforce_title(str(payload.get("title", "")), keyword)
    tags = resolve_tags(
        model_tags=payload.get("tags", []),
        report_tags=report_tags,
        keyword=keyword,
        max_tags=max_tags,
    )
    pages = normalize_pages(payload.get("pages"), publish_mode)

    tex_blueprint = {
        "title": title,
        "keyword": keyword,
        "publish_mode": publish_mode,
        "body_template": body_template,
        "tags": tags,
        "analysis_report": str(report_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generation_mode": "ai_direct_tex",
        "ai_model": resolved_api_model,
        "pages": pages,
    }

    output_tex_json = (project_root / output_tex_json).resolve()
    output_tex_json.parent.mkdir(parents=True, exist_ok=True)
    output_tex_json.write_text(json.dumps(tex_blueprint, ensure_ascii=False, indent=2), encoding="utf-8")

    guard_report_path = ""
    if not disable_tex_guard:
        guard_script = (project_root / "scripts" / "tex_compile_guard_agent.py").resolve()
        if not guard_script.exists():
            print(f"[warn] TeX guard agent not found: {guard_script}")
        else:
            guard_report = resolve_guard_report_path(output_tex_json, project_root)
            scripts_dir = project_root / "scripts"
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            try:
                from tex_compile_guard_agent import run_guard
            except Exception as exc:
                print(f"[error] failed to import TeX guard agent: {exc}", file=sys.stderr)
                return 2
            print("正在运行 TeX 编译守卫 agent...")
            guard_status = run_guard(
                input_tex_json=str(output_tex_json),
                output_tex_json=str(output_tex_json),
                report_json=str(guard_report),
                latex_server=latex_server,
                api_base=resolved_api_base,
                api_model=resolved_api_model,
                api_key_env=api_key_env,
                max_repair_rounds=max(tex_guard_repair_rounds, 0),
                preview_timeout=max(tex_guard_preview_timeout, 1),
            )
            if guard_status != 0:
                print("[error] TeX 编译守卫未通过，已阻断输出。", file=sys.stderr)
                return 2
            guard_report_path = str(guard_report)

    output_plan = resolve_output_plan(output_plan, keyword, project_root)
    output_plan.parent.mkdir(parents=True, exist_ok=True)
    plan_payload = {
        "analysis_report": str(report_path),
        "keyword": keyword,
        "title": title,
        "publish_mode": publish_mode,
        "body_template": body_template,
        "tags": tags,
        "output_tex_json": str(output_tex_json),
        "compile_guard_enabled": not disable_tex_guard,
        "compile_guard_report": guard_report_path,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generation_mode": "ai_direct_tex",
        "ai_model": resolved_api_model,
        "next_step": {
            "script": "scripts/start_tex_editor_session.py",
            "mode": "interactive_input",
            "prefill": {
                "input_tex_json": str(output_tex_json),
                "keyword": keyword,
                "publish_mode": publish_mode,
                "body_template": body_template,
                "analysis_report": str(report_path),
            },
        },
    }
    output_plan.write_text(json.dumps(plan_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("AI TeX 模板生成完成")
    print(f"- 模板: {output_tex_json}")
    print(f"- 计划: {output_plan}")
    print("- 下一步:")
    print("  python scripts/start_tex_editor_session.py")
    return 0


def _ask(prompt: str, default: str = "") -> str:
    value = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return value or default


def _ask_int(prompt: str, default: int) -> int:
    raw = _ask(prompt, str(default))
    try:
        return int(raw)
    except ValueError:
        print(f"[warn] invalid integer '{raw}', fallback to {default}")
        return default


def _ask_float(prompt: str, default: float) -> float:
    raw = _ask(prompt, str(default))
    try:
        return float(raw)
    except ValueError:
        print(f"[warn] invalid float '{raw}', fallback to {default}")
        return default


def _ask_yes_no(prompt: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = input(f"{prompt} ({hint}): ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes", "1", "true"}


def _latest_report_rel(project_root: Path) -> str:
    reports_dir = project_root / "data" / "reports"
    if not reports_dir.exists():
        return "data/reports/latest_analysis.md"
    candidates = sorted(
        reports_dir.glob("*_analysis.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return "data/reports/latest_analysis.md"
    return str(candidates[0].resolve().relative_to(project_root))


def _ask_optional_choice(prompt: str, choices: set[str], default: str = "") -> str:
    hint = "/".join(sorted(x for x in choices if x))
    raw = _ask(f"{prompt}（可留空; 可选: {hint}）", default).strip().lower()
    if raw not in choices:
        print(f"[warn] invalid choice '{raw}', fallback to '{default}'")
        return default
    return raw


def main() -> int:
    try:
        project_root = find_project_root()
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    default_report = _latest_report_rel(project_root)
    analysis_report = _ask("趋势报告路径（相对项目根目录）", default_report)
    keyword = ""
    while not keyword:
        keyword = _ask("关键词（标题必须包含）", "")
    output_tex_json = _ask("TeX blueprint 输出路径", "data/note_tex_draft.json")
    output_plan = _ask("计划文件输出路径（留空自动命名）", "")
    publish_mode = _ask_optional_choice("发布模式", {"", "viewpoint", "checklist"}, "")
    body_template = _ask_optional_choice("正文模板", {"", "list", "case"}, "")
    report_tag_topk = _ask_int("趋势标签提取数量上限", 5)
    max_tags = _ask_int("输出标签上限", 8)
    api_base = _ask("API Base（留空使用默认）", "")
    api_model = _ask("模型名（留空使用默认）", "")
    api_key_env = _ask("API Key 环境变量名", "GLM_API_KEY")
    latex_server = _ask("latex_server 地址", "http://127.0.0.1:8000")
    disable_tex_guard = _ask_yes_no("是否禁用 TeX 编译守卫", False)
    tex_guard_repair_rounds = _ask_int("TeX 守卫每页最大修复轮数", 2)
    tex_guard_preview_timeout = _ask_int("TeX 守卫预览超时（秒）", 180)
    temperature = _ask_float("生成温度 temperature", 0.4)

    return run_ai_generation(
        analysis_report=analysis_report,
        keyword=keyword,
        output_tex_json=output_tex_json,
        output_plan=output_plan,
        publish_mode=publish_mode,
        body_template=body_template,
        report_tag_topk=max(report_tag_topk, 0),
        max_tags=max(max_tags, 1),
        api_base=api_base or None,
        api_model=api_model or None,
        api_key_env=api_key_env,
        latex_server=latex_server,
        disable_tex_guard=disable_tex_guard,
        tex_guard_repair_rounds=max(tex_guard_repair_rounds, 0),
        tex_guard_preview_timeout=max(tex_guard_preview_timeout, 1),
        temperature=temperature,
    )


if __name__ == "__main__":
    raise SystemExit(main())
