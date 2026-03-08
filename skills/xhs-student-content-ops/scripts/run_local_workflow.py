#!/usr/bin/env python3
"""Run the local xhs student content workflow with local data/images outputs."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import datetime
from pathlib import Path


DEFAULT_PROJECT_ROOT = Path("/root/notebook_repo/xhs_note")


def slugify(text: str) -> str:
    value = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9_-]", "", (text or "").strip().replace(" ", "_"))
    return value or "unknown_keyword"


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


def _ask_optional_choice(prompt: str, choices: set[str], default: str = "") -> str:
    hint = "/".join(sorted(x for x in choices if x))
    raw = _ask(f"{prompt}（可留空; 可选: {hint}）", default).strip().lower()
    if raw not in choices:
        print(f"[warn] invalid choice '{raw}', fallback to '{default}'")
        return default
    return raw


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module spec: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    project_root = Path(_ask("项目根目录", str(DEFAULT_PROJECT_ROOT))).resolve()
    if not (project_root / "scripts" / "analyze_trending.py").exists():
        print(f"[error] invalid project root: {project_root}", file=sys.stderr)
        return 2

    keyword = ""
    while not keyword:
        keyword = _ask("关键词（必填）", "")
    search_results = _ask("search_results 路径（相对项目根目录）", "data/search_results.json")
    report_rel = _ask("已有趋势报告路径（留空则先做趋势分析）", "")
    output_tex_json = _ask("TeX blueprint 输出路径", "data/note_tex_draft.json")
    output_plan = _ask("AI 计划输出路径（留空自动命名）", "")
    publish_mode = _ask_optional_choice("发布模式", {"", "viewpoint", "checklist"}, "")
    body_template = _ask_optional_choice("正文模板", {"", "list", "case"}, "")
    latex_server = _ask("latex_server 地址", "http://127.0.0.1:8000")
    tex_guard_repair_rounds = _ask_int("TeX 守卫每页最大修复轮数", 2)
    tex_guard_preview_timeout = _ask_int("TeX 守卫预览超时（秒）", 180)
    disable_tex_guard = _ask_yes_no("是否禁用 TeX 编译守卫", False)

    if not report_rel:
        search_results_path = (project_root / search_results).resolve()
        if not search_results_path.exists():
            print(f"[error] search results not found: {search_results_path}", file=sys.stderr)
            return 2
        analyze_script = project_root / "scripts" / "analyze_trending.py"
        analyze_mod = _load_module("analyze_trending_mod", analyze_script)
        data = json.loads(search_results_path.read_text(encoding="utf-8"))
        print(f"[step] 趋势分析，输入数据条数: {len(data) if isinstance(data, list) else '...'}")
        stats = analyze_mod.analyze_data(data)
        keywords = analyze_mod.extract_keywords(stats.titles)
        keywords.update(analyze_mod.extract_keywords(stats.contents))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_rel = f"data/reports/{timestamp}_{slugify(keyword)}_analysis.md"
        report_abs = (project_root / report_rel).resolve()
        analyze_mod.generate_report(stats, keywords, str(report_abs), keyword)
        print(f"[step] 趋势分析完成: {report_rel}")
    else:
        if not (project_root / report_rel).exists():
            print(f"[error] analysis report not found: {(project_root / report_rel)}", file=sys.stderr)
            return 2
        print(f"[step] 使用已有趋势报告: {report_rel}")

    agent_script = project_root / "skills" / "xhs-student-content-ops" / "scripts" / "run_interactive_agent.py"
    if not agent_script.exists():
        print(f"[error] skill agent script not found: {agent_script}", file=sys.stderr)
        return 2

    print("[step] AI 定稿 + TeX 编译守卫")
    agent_mod = _load_module("run_interactive_agent_mod", agent_script)
    ai_status = agent_mod.run_ai_generation(
        analysis_report=report_rel,
        keyword=keyword,
        output_tex_json=output_tex_json,
        output_plan=output_plan,
        publish_mode=publish_mode,
        body_template=body_template,
        latex_server=latex_server,
        disable_tex_guard=disable_tex_guard,
        tex_guard_repair_rounds=max(tex_guard_repair_rounds, 0),
        tex_guard_preview_timeout=max(tex_guard_preview_timeout, 1),
    )
    if ai_status != 0:
        return ai_status

    tex_path = (project_root / output_tex_json).resolve()
    if not tex_path.exists():
        print(f"[error] tex blueprint not found: {tex_path}", file=sys.stderr)
        return 2

    payload = json.loads(tex_path.read_text(encoding="utf-8"))
    title = str(payload.get("title", "")).strip()
    publish_mode = str(payload.get("publish_mode", "checklist")).strip() or "checklist"
    body_template = str(payload.get("body_template", "list")).strip() or "list"

    if title:
        print("[step] 标题合规检查")
        title_check_mod = _load_module("title_check_mod", project_root / "scripts" / "title_compliance_check.py")
        policy_path = project_root / "data" / "policy" / "title_banned_words.yml"
        if not policy_path.exists():
            print(f"[error] title policy not found: {policy_path}", file=sys.stderr)
            return 2
        categories, replacements = title_check_mod.load_policy(policy_path)
        hits = title_check_mod.collect_matches(title, categories)
        output_check_path = title_check_mod.resolve_output_path("", "data/compliance", keyword)
        passed = title_check_mod.render_report(
            output_path=Path(output_check_path),
            title=title,
            keyword=keyword,
            max_length=20,
            hits=hits,
            replacements=replacements,
        )
        print(f"[step] 标题合规检查完成: {'通过' if passed else '不通过'}")
        print(f"[step] 标题合规报告: {output_check_path}")
        if not passed:
            return 1
    else:
        print("[warn] missing title in tex blueprint, skip title compliance check")

    editor_cmd = [
        "python",
        "scripts/start_tex_editor_session.py",
    ]

    print("")
    print("[done] 本地流程完成，下一步启动 React 编辑会话:")
    print(" ".join(editor_cmd))
    print(f"参考预填: keyword={keyword}, analysis_report={report_rel}, publish_mode={publish_mode}, body_template={body_template}")
    print("输出目录:")
    print("- data/")
    print("- images/notes/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
