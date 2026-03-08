"""Workflow APIs: trend analyze, AI TeX generation, title check, editor session."""

from __future__ import annotations

import logging
from flask import Blueprint, jsonify, request
from backend.services.workflow import get_workflow_service
from .utils import log_error, log_request

logger = logging.getLogger(__name__)


def create_workflow_blueprint():
    workflow_bp = Blueprint("workflow", __name__)

    @workflow_bp.route("/workflow/analyze", methods=["POST"])
    def workflow_analyze():
        try:
            data = request.get_json() or {}
            log_request("/workflow/analyze", data)
            result = get_workflow_service().analyze_trending(data)
            return jsonify({"success": True, **result}), 200
        except Exception as exc:
            log_error("/workflow/analyze", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @workflow_bp.route("/workflow/ai-tex", methods=["POST"])
    def workflow_ai_tex():
        try:
            data = request.get_json() or {}
            safe_data = data.copy()
            if "api_key" in safe_data:
                safe_data["api_key"] = "***"
            log_request("/workflow/ai-tex", safe_data)
            result = get_workflow_service().run_ai_tex(data)
            return jsonify({"success": True, **result}), 200
        except Exception as exc:
            log_error("/workflow/ai-tex", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @workflow_bp.route("/workflow/title-check", methods=["POST"])
    def workflow_title_check():
        try:
            data = request.get_json() or {}
            log_request("/workflow/title-check", data)
            result = get_workflow_service().run_title_check(data)
            return jsonify({"success": True, **result}), 200
        except Exception as exc:
            log_error("/workflow/title-check", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    @workflow_bp.route("/workflow/editor-session", methods=["POST"])
    def workflow_editor_session():
        try:
            data = request.get_json() or {}
            log_request("/workflow/editor-session", data)
            result = get_workflow_service().create_editor_session(data)
            return jsonify({"success": True, **result}), 200
        except Exception as exc:
            log_error("/workflow/editor-session", exc)
            return jsonify({"success": False, "error": str(exc)}), 500

    return workflow_bp
