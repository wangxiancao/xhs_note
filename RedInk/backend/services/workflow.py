"""Workflow orchestration service for xhs_note local pipeline."""

from __future__ import annotations

import importlib.util
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Dict


class WorkflowService:
    """Bridge legacy local scripts into RedInk backend APIs."""

    PROJECT_ROOT = Path(__file__).resolve().parents[3]

    def __init__(self):
        self._module_cache: Dict[str, ModuleType] = {}

    def _script_path(self, relative: str) -> Path:
        return (self.PROJECT_ROOT / relative).resolve()

    def _load_module(self, key: str, script_relative_path: str) -> ModuleType:
        cached = self._module_cache.get(key)
        if cached is not None:
            return cached

        script_path = self._script_path(script_relative_path)
        if not script_path.exists():
            raise FileNotFoundError(f"script not found: {script_path}")

        spec = importlib.util.spec_from_file_location(f"workflow_{key}", str(script_path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"failed to load module spec: {script_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._module_cache[key] = module
        return module

    def _to_abs_path(self, raw_path: str, default_relative: str = "") -> Path:
        path = Path((raw_path or "").strip() or default_relative)
        if path.is_absolute():
            return path.resolve()
        return (self.PROJECT_ROOT / path).resolve()

    def _to_rel_path(self, absolute_path: Path) -> str:
        try:
            return str(absolute_path.resolve().relative_to(self.PROJECT_ROOT))
        except Exception:
            return str(absolute_path.resolve())

    @staticmethod
    def _slugify_keyword(keyword: str) -> str:
        if not keyword:
            return "unknown_keyword"
        normalized = keyword.strip().replace(" ", "_")
        normalized = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9_-]", "", normalized)
        return normalized or "unknown_keyword"

    def analyze_trending(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        module = self._load_module("analyze_trending", "scripts/analyze_trending.py")

        keyword = str(payload.get("keyword", "")).strip()
        input_path = self._to_abs_path(str(payload.get("search_results_path", "")), "data/search_results.json")
        if not input_path.exists():
            raise FileNotFoundError(f"search results not found: {input_path}")

        output_path_raw = str(payload.get("output_path", "")).strip()
        output_dir = str(payload.get("output_dir", "data/reports")).strip() or "data/reports"
        auto_name = bool(payload.get("auto_name", not bool(output_path_raw)))

        if output_path_raw and not auto_name:
            output_path = self._to_abs_path(output_path_raw)
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{self._slugify_keyword(keyword)}_analysis.md"
            output_path = self._to_abs_path("", f"{output_dir}/{filename}")

        with input_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        stats = module.analyze_data(data)
        keywords = module.extract_keywords(stats.titles)
        keywords.update(module.extract_keywords(stats.contents))
        module.generate_report(stats, keywords, str(output_path), keyword)

        return {
            "keyword": keyword,
            "input_path": self._to_rel_path(input_path),
            "report_path": self._to_rel_path(output_path),
            "stats": {
                "total_count": int(stats.total_count),
                "skipped_video_count": int(stats.skipped_video_count),
                "skipped_non_note_count": int(stats.skipped_non_note_count),
                "titles_count": len(stats.titles),
                "contents_count": len(stats.contents),
            },
        }

    def run_ai_tex(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        module = self._load_module(
            "run_interactive_agent",
            "skills/xhs-student-content-ops/scripts/run_interactive_agent.py",
        )

        analysis_report = str(payload.get("analysis_report", "")).strip()
        keyword = str(payload.get("keyword", "")).strip()
        if not analysis_report:
            raise ValueError("analysis_report is required")
        if not keyword:
            raise ValueError("keyword is required")

        output_tex_json = str(payload.get("output_tex_json", "data/note_tex_draft.json")).strip() or "data/note_tex_draft.json"
        output_plan = str(payload.get("output_plan", "")).strip()
        publish_mode = str(payload.get("publish_mode", "")).strip()
        body_template = str(payload.get("body_template", "")).strip()
        report_tag_topk = int(payload.get("report_tag_topk", 5))
        max_tags = int(payload.get("max_tags", 8))
        api_base = str(payload.get("api_base", "")).strip() or None
        api_model = str(payload.get("api_model", "")).strip() or None
        api_key_env = str(payload.get("api_key_env", "GLM_API_KEY")).strip() or "GLM_API_KEY"
        latex_server = str(payload.get("latex_server", "http://127.0.0.1:8000")).strip() or "http://127.0.0.1:8000"
        disable_tex_guard = bool(payload.get("disable_tex_guard", False))
        tex_guard_repair_rounds = int(payload.get("tex_guard_repair_rounds", 2))
        tex_guard_preview_timeout = int(payload.get("tex_guard_preview_timeout", 180))
        temperature = float(payload.get("temperature", 0.4))

        status = module.run_ai_generation(
            analysis_report=analysis_report,
            keyword=keyword,
            output_tex_json=output_tex_json,
            output_plan=output_plan,
            publish_mode=publish_mode,
            body_template=body_template,
            report_tag_topk=max(report_tag_topk, 0),
            max_tags=max(max_tags, 1),
            api_base=api_base,
            api_model=api_model,
            api_key_env=api_key_env,
            latex_server=latex_server,
            disable_tex_guard=disable_tex_guard,
            tex_guard_repair_rounds=max(tex_guard_repair_rounds, 0),
            tex_guard_preview_timeout=max(tex_guard_preview_timeout, 1),
            temperature=temperature,
        )
        if status != 0:
            raise RuntimeError(f"AI generation failed with status: {status}")

        output_tex_abs = self._to_abs_path(output_tex_json)
        if output_plan:
            output_plan_abs = self._to_abs_path(output_plan)
        else:
            guessed_plan = module.resolve_output_plan("", keyword, self.PROJECT_ROOT)
            if guessed_plan.exists():
                output_plan_abs = guessed_plan
            else:
                slug = self._slugify_keyword(keyword)
                candidates = sorted(
                    (self.PROJECT_ROOT / "data" / "plans").glob(f"*_{slug}_tex_plan.json"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                output_plan_abs = candidates[0].resolve() if candidates else guessed_plan

        plan_payload: Dict[str, Any] = {}
        if output_plan_abs.exists():
            plan_payload = json.loads(output_plan_abs.read_text(encoding="utf-8"))

        return {
            "analysis_report": analysis_report,
            "keyword": keyword,
            "output_tex_json": self._to_rel_path(output_tex_abs),
            "output_plan": self._to_rel_path(output_plan_abs),
            "compile_guard_enabled": not disable_tex_guard,
            "compile_guard_report": plan_payload.get("compile_guard_report", ""),
            "title": plan_payload.get("title", ""),
            "publish_mode": plan_payload.get("publish_mode", publish_mode),
            "body_template": plan_payload.get("body_template", body_template),
        }

    def run_title_check(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        module = self._load_module("title_compliance_check", "scripts/title_compliance_check.py")

        title = str(payload.get("title", "")).strip()
        keyword = str(payload.get("keyword", "")).strip()

        if not title:
            tex_json_path_raw = str(payload.get("input_tex_json", "data/note_tex_draft.json")).strip()
            tex_json_path = self._to_abs_path(tex_json_path_raw, "data/note_tex_draft.json")
            if not tex_json_path.exists():
                raise FileNotFoundError(f"TeX blueprint not found: {tex_json_path}")
            tex_payload = json.loads(tex_json_path.read_text(encoding="utf-8"))
            title = str(tex_payload.get("title", "")).strip()
            if not keyword:
                keyword = str(tex_payload.get("keyword", "")).strip()

        if not title:
            raise ValueError("title is required")

        policy_path = self._to_abs_path(str(payload.get("policy_path", "")), "data/policy/title_banned_words.yml")
        if not policy_path.exists():
            raise FileNotFoundError(f"policy not found: {policy_path}")

        output_path_raw = str(payload.get("output_path", "")).strip()
        output_dir = str(payload.get("output_dir", "data/compliance")).strip() or "data/compliance"
        max_length = int(payload.get("max_length", 20))

        categories, replacements = module.load_policy(policy_path)
        hits = module.collect_matches(title, categories)
        output_path = Path(module.resolve_output_path(output_path_raw, output_dir, keyword))
        if not output_path.is_absolute():
            output_path = (self.PROJECT_ROOT / output_path).resolve()

        passed = module.render_report(
            output_path=output_path,
            title=title,
            keyword=keyword,
            max_length=max_length,
            hits=hits,
            replacements=replacements,
        )

        return {
            "title": title,
            "keyword": keyword,
            "passed": bool(passed),
            "max_length": max_length,
            "hit_count": len(hits),
            "hits": [{"category": category, "word": word} for category, word in hits],
            "report_path": self._to_rel_path(output_path),
        }

    def create_editor_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        latex_server = str(payload.get("latex_server", "http://127.0.0.1:8000")).strip() or "http://127.0.0.1:8000"
        input_md = str(payload.get("input_md", "")).strip()
        input_tex_json = str(payload.get("input_tex_json", "")).strip()

        if input_md:
            md_path = self._to_abs_path(input_md)
            if not md_path.exists():
                raise FileNotFoundError(f"input markdown not found: {md_path}")
        if input_tex_json:
            tex_path = self._to_abs_path(input_tex_json)
            if not tex_path.exists():
                raise FileNotFoundError(f"input tex json not found: {tex_path}")

        body = {
            "input_md": input_md,
            "input_tex_json": input_tex_json,
            "keyword": str(payload.get("keyword", "")).strip(),
            "analysis_report": str(payload.get("analysis_report", "")).strip(),
            "auto_tag_topk": int(payload.get("auto_tag_topk", 5)),
            "max_tags": int(payload.get("max_tags", 8)),
            "theme": str(payload.get("theme", "classic")).strip() or "classic",
            "output_dir": str(payload.get("output_dir", "images/notes")).strip() or "images/notes",
            "run_id": str(payload.get("run_id", "")).strip(),
            "publish_mode": str(payload.get("publish_mode", "checklist")).strip() or "checklist",
            "body_template": str(payload.get("body_template", "list")).strip() or "list",
            "title_check_passed": bool(payload.get("title_check_passed", False)),
        }

        endpoint = latex_server.rstrip("/") + "/api/editor/session/create"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"create editor session failed: HTTP {exc.code} {body_text[:400]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"failed to connect latex_server: {exc}") from exc

        session = data.get("session", {})
        session_id = str(session.get("session_id", "")).strip()
        if not session_id:
            raise RuntimeError(f"invalid latex_server response: {data}")

        editor_url = latex_server.rstrip("/") + "/editor?" + urllib.parse.urlencode({"session_id": session_id})
        return {
            "editor_url": editor_url,
            "session": session,
        }


def get_workflow_service() -> WorkflowService:
    return WorkflowService()
