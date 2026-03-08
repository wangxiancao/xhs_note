#!/usr/bin/env python3
"""Compile guard agent for AI-generated TeX pages.

Flow:
1) Validate each page via latex_server /api/preview.
2) If failed, ask LLM to repair TeX according to compile error.
3) Retry compile for limited rounds.
4) If still failed, use a guaranteed fallback TeX.
"""

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


def resolve_api_key(project_root: Path, primary_env_name: str = "GLM_API_KEY") -> tuple[str, str]:
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


def _chat_endpoint(api_base: str) -> str:
    base = api_base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1") or base.endswith("/v4"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def call_chat_completions(
    *,
    api_base: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
) -> str:
    endpoint = _chat_endpoint(api_base)
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

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        if exc.code == 400 and "response_format" in body:
            payload.pop("response_format", None)
            request = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers=headers,
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        else:
            raise RuntimeError(f"LLM request failed: HTTP {exc.code} - {body[:400]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"LLM response missing choices: {data}")
    content = choices[0].get("message", {}).get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    raise RuntimeError(f"LLM response missing message.content: {data}")


def parse_json_obj(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def call_preview_api(latex_server: str, code: str, timeout: int) -> tuple[bool, str]:
    endpoint = latex_server.rstrip("/") + "/api/preview"
    payload = {"code": code}
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=max(timeout, 1)) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        return False, f"HTTP {exc.code}: {body[:300]}"
    except urllib.error.URLError as exc:
        return False, str(exc)

    if data.get("success"):
        return True, ""
    return False, str(data.get("error") or "Unknown compile error")


def build_safe_fallback_tex(title: str, label: str) -> str:
    safe_title = re.sub(r"[{}$&#_%^~\\\\]", "", title or "研究生学习")
    safe_label = re.sub(r"[{}$&#_%^~\\\\]", "", label or "正文")
    return rf"""\documentclass[preview,border=0pt]{{standalone}}
\usepackage{{ctex}}
\begin{{document}}
\begin{{minipage}}[c][14cm][c]{{10cm}}
\centering
{{\LARGE\bfseries {safe_title}}}\\[0.8cm]
{{\Large {safe_label}}}\\[0.6cm]
{{\large 1. 明确输入：研究问题、关键词、目标期刊}}\\[0.3cm]
{{\large 2. 明确过程：速读摘要+精读图表+复核方法}}\\[0.3cm]
{{\large 3. 明确输出：结构化笔记与行动清单}}
\end{{minipage}}
\end{{document}}
"""


def repair_tex_with_ai(
    *,
    api_base: str,
    api_key: str,
    model: str,
    page_id: str,
    code: str,
    compile_error: str,
) -> str:
    system_prompt = (
        "你是 LaTeX 修复专家。"
        "你的目标是修复无法编译的 TeX，并保证兼容 xelatex + ctex + standalone。"
        "只输出 JSON，格式: {\"code\":\"...\"}。"
    )
    user_prompt = f"""
请修复下面这段 TeX，使其可编译。
要求：
1) 保留原页面主题与文案风格，不要删空内容
2) 必须输出完整可编译文档
3) 禁用不兼容样式，例如 drop shadow / blur shadow
4) 不要输出解释

page_id: {page_id}
compile_error:
{compile_error}

original_code:
{code}
"""
    raw = call_chat_completions(
        api_base=api_base,
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
    )
    payload = parse_json_obj(raw)
    repaired = str(payload.get("code", "")).strip()
    if not repaired:
        raise RuntimeError("LLM repair returned empty code")
    return repaired


def normalize_pages(raw_pages: Any, publish_mode: str) -> list[dict[str, Any]]:
    expected = [("01_cover", "封面", "01_cover.png")]
    if publish_mode == "checklist":
        expected.extend(
            [
                ("02_body", "正文卡1", "02_body.png"),
                ("03_body", "正文卡2", "03_body.png"),
                ("04_body", "正文卡3", "04_body.png"),
            ]
        )

    if not isinstance(raw_pages, list):
        raw_pages = []
    page_by_id: dict[str, dict[str, Any]] = {}
    for page in raw_pages:
        if isinstance(page, dict):
            pid = str(page.get("id", "")).strip()
            if pid:
                page_by_id[pid] = page

    pages: list[dict[str, Any]] = []
    for i, (pid, label, filename) in enumerate(expected):
        src = page_by_id.get(pid)
        if src is None and i < len(raw_pages) and isinstance(raw_pages[i], dict):
            src = raw_pages[i]
        pages.append(
            {
                "id": pid,
                "label": label,
                "filename": filename,
                "code": str((src or {}).get("code", "")).strip(),
            }
        )
    return pages


def compile_guard(
    *,
    pages: list[dict[str, Any]],
    title: str,
    latex_server: str,
    api_base: str,
    api_key: str,
    model: str,
    max_repair_rounds: int,
    preview_timeout: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    report: list[dict[str, Any]] = []
    all_ok = True

    for page in pages:
        page_id = page["id"]
        label = page["label"]
        code = page["code"]
        if not code:
            code = build_safe_fallback_tex(title, label)

        ok, error = call_preview_api(latex_server, code, preview_timeout)
        attempts = 0
        used_fallback = False

        while not ok and attempts < max(max_repair_rounds, 0):
            attempts += 1
            try:
                code = repair_tex_with_ai(
                    api_base=api_base,
                    api_key=api_key,
                    model=model,
                    page_id=page_id,
                    code=code,
                    compile_error=error,
                )
            except Exception as exc:
                error = f"repair_error: {exc}"
                break
            ok, error = call_preview_api(latex_server, code, preview_timeout)

        if not ok:
            fallback = build_safe_fallback_tex(title, label)
            fb_ok, fb_err = call_preview_api(latex_server, fallback, preview_timeout)
            if fb_ok:
                code = fallback
                ok = True
                error = ""
                used_fallback = True
            else:
                error = f"{error}; fallback_error: {fb_err}"

        page["code"] = code
        report.append(
            {
                "id": page_id,
                "ok": bool(ok),
                "attempts": attempts,
                "used_fallback": used_fallback,
                "error": error[:260] if error else "",
            }
        )
        if not ok:
            all_ok = False

    return pages, report, all_ok


def run_guard(
    *,
    input_tex_json: str,
    output_tex_json: str = "",
    report_json: str = "",
    latex_server: str = "http://127.0.0.1:8000",
    api_base: str | None = None,
    api_model: str | None = None,
    api_key_env: str = "GLM_API_KEY",
    max_repair_rounds: int = 2,
    preview_timeout: int = 180,
) -> int:
    resolved_api_base = api_base or os.getenv("GLM_API_BASE", os.getenv("OPENAI_API_BASE", "https://open.bigmodel.cn/api/paas/v4"))
    resolved_api_model = api_model or os.getenv("GLM_MODEL", os.getenv("OPENAI_MODEL", "glm-4.7"))

    input_path = Path(input_tex_json).resolve()
    if not input_path.exists():
        print(f"[error] input tex json not found: {input_path}", file=sys.stderr)
        return 2

    project_root = Path(__file__).resolve().parent.parent
    api_key, api_source = resolve_api_key(project_root, api_key_env)
    if not api_key:
        print(f"[error] API key not found in env or .claude/CLAUDE.md: {api_key_env}", file=sys.stderr)
        return 2

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    title = str(payload.get("title", "研究生学习")).strip() or "研究生学习"
    publish_mode = str(payload.get("publish_mode", "checklist")).strip().lower()
    if publish_mode not in {"viewpoint", "checklist"}:
        publish_mode = "checklist"
    pages = normalize_pages(payload.get("pages"), publish_mode)

    print(f"TeX Guard Agent compiling pages... (model={resolved_api_model}, key_env={api_source})")
    pages, guard_report, all_ok = compile_guard(
        pages=pages,
        title=title,
        latex_server=latex_server,
        api_base=resolved_api_base,
        api_key=api_key,
        model=resolved_api_model,
        max_repair_rounds=max_repair_rounds,
        preview_timeout=preview_timeout,
    )

    payload["pages"] = pages
    payload["compile_guard"] = {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "all_ok": bool(all_ok),
        "pages": guard_report,
    }

    output_path = Path(output_tex_json).resolve() if output_tex_json else input_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report_path = Path(report_json).resolve() if report_json else output_path.with_name(output_path.stem + "_guard_report.json")
    report_path.write_text(
        json.dumps(
            {
                "input": str(input_path),
                "output": str(output_path),
                "all_ok": bool(all_ok),
                "pages": guard_report,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"- output_tex_json: {output_path}")
    print(f"- guard_report: {report_path}")
    print(f"- all_ok: {all_ok}")
    return 0 if all_ok else 1


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


def main() -> int:
    input_tex_json = ""
    while not input_tex_json:
        input_tex_json = _ask("请输入 input tex json 路径", "data/note_tex_draft.json")
    output_tex_json = _ask("请输入 output tex json 路径（留空则覆盖输入）", "")
    report_json = _ask("请输入 guard report 输出路径（留空自动命名）", "")
    latex_server = _ask("请输入 latex_server 地址", "http://127.0.0.1:8000")
    api_base = _ask("请输入 API Base（留空使用默认）", "")
    api_model = _ask("请输入模型名（留空使用默认）", "")
    api_key_env = _ask("请输入 API Key 环境变量名", "GLM_API_KEY")
    max_repair_rounds = _ask_int("每页最大修复轮数", 2)
    preview_timeout = _ask_int("预览编译超时（秒）", 180)
    return run_guard(
        input_tex_json=input_tex_json,
        output_tex_json=output_tex_json,
        report_json=report_json,
        latex_server=latex_server,
        api_base=api_base or None,
        api_model=api_model or None,
        api_key_env=api_key_env,
        max_repair_rounds=max(max_repair_rounds, 0),
        preview_timeout=max(preview_timeout, 1),
    )


if __name__ == "__main__":
    raise SystemExit(main())
