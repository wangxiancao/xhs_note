#!/usr/bin/env python3
"""Create a TeX editor session on latex_server and print the editor URL."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


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


def _ask_yes_no(prompt: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = input(f"{prompt} ({hint}): ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes", "1", "true"}


def _ask_choice(prompt: str, choices: list[str], default: str) -> str:
    raw = _ask(f"{prompt} ({'/'.join(choices)})", default).lower()
    if raw not in choices:
        print(f"[warn] invalid choice '{raw}', fallback to {default}")
        return default
    return raw


def main() -> int:
    input_mode = _ask_choice("输入类型", ["tex_json", "md"], "tex_json")
    input_md = ""
    input_tex_json = ""
    if input_mode == "md":
        input_md = _ask("请输入 Markdown 路径", "data/note_draft.md")
    else:
        input_tex_json = _ask("请输入 TeX blueprint json 路径", "data/note_tex_draft.json")

    keyword = _ask("关键词", "")
    analysis_report = _ask("趋势分析报告路径", "")
    auto_tag_topk = _ask_int("从报告提取标签数量上限", 5)
    max_tags = _ask_int("manifest 标签上限", 8)
    theme = _ask_choice("主题", ["classic", "melon", "ocean"], "classic")
    output_dir = _ask("输出目录", "images/notes")
    run_id = _ask("自定义 run_id（留空自动生成）", "")
    publish_mode = _ask_choice("发布模式", ["viewpoint", "checklist"], "checklist")
    body_template = _ask_choice("正文模板", ["list", "case"], "list")
    title_check_passed = _ask_yes_no("标题检查是否已通过", False)
    latex_server = _ask("latex_server 地址", "http://127.0.0.1:8000")

    if not input_md and not input_tex_json:
        print("[error] 需要提供 Markdown 路径或 TeX blueprint json 路径")
        return 2
    if input_md:
        input_md_path = Path(input_md)
        if not input_md_path.exists():
            print(f"[error] input markdown not found: {input_md_path}")
            return 2
    if input_tex_json:
        input_tex_json_path = Path(input_tex_json)
        if not input_tex_json_path.exists():
            print(f"[error] input tex json not found: {input_tex_json_path}")
            return 2

    payload = {
        "input_md": input_md,
        "input_tex_json": input_tex_json,
        "keyword": keyword,
        "analysis_report": analysis_report,
        "auto_tag_topk": auto_tag_topk,
        "max_tags": max_tags,
        "theme": theme,
        "output_dir": output_dir,
        "run_id": run_id,
        "publish_mode": publish_mode,
        "body_template": body_template,
        "title_check_passed": bool(title_check_passed),
    }
    endpoint = latex_server.rstrip("/") + "/api/editor/session/create"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        print(f"[error] failed to create session: HTTP {exc.code} {body}")
        return 2
    except urllib.error.URLError as exc:
        print(f"[error] failed to connect latex_server: {exc}")
        return 2

    session = data.get("session", {})
    session_id = session.get("session_id", "")
    if not session_id:
        print(f"[error] invalid response: {data}")
        return 2

    query = urllib.parse.urlencode({"session_id": session_id})
    editor_url = latex_server.rstrip("/") + "/editor?" + query
    print("编辑会话创建成功")
    print(f"- session_id: {session_id}")
    print(f"- editor_url: {editor_url}")
    print(f"- title: {session.get('title', '')}")
    print(f"- pages: {len(session.get('pages', []))}")
    print("")
    print("下一步: 在浏览器打开 editor_url，逐页点击“预览”和“保存并下一页”。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
