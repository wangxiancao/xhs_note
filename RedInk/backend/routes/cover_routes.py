"""
封面创作相关 API 路由

包含功能：
- 基于 cover_spec 生成封面预览
- 重新生成封面并写入版本历史
- 选择当前发布使用的封面版本
"""

import base64
import uuid
from datetime import datetime
from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

from backend.services.history import get_history_service
from backend.services.image import get_image_service
from .utils import log_error, log_request


def _next_cover_version_id(versions: List[Dict[str, Any]]) -> str:
    max_idx = 0
    for item in versions:
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id") or "")
        if raw_id.startswith("v"):
            try:
                max_idx = max(max_idx, int(raw_id[1:]))
            except ValueError:
                continue
    return f"v{max_idx + 1}"


def _encode_png_base64(image_data: bytes) -> str:
    return base64.b64encode(image_data).decode("utf-8")


def create_cover_blueprint():
    """创建封面路由蓝图"""
    cover_bp = Blueprint("cover", __name__)

    @cover_bp.route("/cover/preview", methods=["POST"])
    def preview_cover():
        """
        生成封面预览（不落库）

        请求体：
        - record_id: 历史记录 ID（可选）
        - cover_spec: 封面结构化参数（可选，优先级高于 record）
        - full_outline: 完整大纲文本（可选）
        - user_topic: 用户主题（可选）
        """
        try:
            data = request.get_json() or {}
            record_id = data.get("record_id")
            cover_spec = data.get("cover_spec")
            full_outline = data.get("full_outline", "")
            user_topic = data.get("user_topic", "")

            history_service = get_history_service()
            if record_id:
                record = history_service.get_record(record_id)
                if not record:
                    return jsonify({
                        "success": False,
                        "error": f"历史记录不存在：{record_id}"
                    }), 404
                if not cover_spec:
                    cover_spec = record.get("cover_spec")
                if not full_outline:
                    full_outline = (record.get("outline") or {}).get("raw", "")
                if not user_topic:
                    user_topic = record.get("title", "")

            if not isinstance(cover_spec, dict):
                return jsonify({
                    "success": False,
                    "error": "参数错误：cover_spec 不能为空且必须为对象。"
                }), 400

            log_request("/cover/preview", {
                "record_id": record_id,
                "has_cover_spec": True,
                "outline_length": len(full_outline or ""),
            })

            image_service = get_image_service()
            image_data = image_service.render_cover_png_bytes(
                cover_spec=cover_spec,
                full_outline=full_outline or "",
                user_topic=user_topic or "",
            )
            image_b64 = _encode_png_base64(image_data)

            return jsonify({
                "success": True,
                "image_base64": image_b64,
                "mime_type": "image/png",
                "width": 1242,
                "height": 1660,
            }), 200
        except Exception as e:
            log_error("/cover/preview", e)
            return jsonify({
                "success": False,
                "error": f"封面预览生成失败。\n错误详情: {str(e)}"
            }), 500

    @cover_bp.route("/cover/regenerate", methods=["POST"])
    def regenerate_cover():
        """
        重新生成封面并保存为版本

        请求体：
        - record_id: 历史记录 ID（必填）
        - cover_spec: 封面结构化参数（可选）
        - version_name: 版本名称（可选）
        - source: 版本来源（可选，默认 manual）
        - set_selected: 是否立即设为当前版本（默认 true）
        - full_outline: 完整大纲文本（可选）
        - user_topic: 用户主题（可选）
        """
        try:
            data = request.get_json() or {}
            record_id = data.get("record_id")
            if not record_id:
                return jsonify({
                    "success": False,
                    "error": "参数错误：record_id 不能为空。"
                }), 400

            history_service = get_history_service()
            record = history_service.get_record(record_id)
            if not record:
                return jsonify({
                    "success": False,
                    "error": f"历史记录不存在：{record_id}"
                }), 404

            cover_spec = data.get("cover_spec") or record.get("cover_spec")
            if not isinstance(cover_spec, dict):
                return jsonify({
                    "success": False,
                    "error": "参数错误：cover_spec 不能为空且必须为对象。"
                }), 400

            full_outline = data.get("full_outline") or (record.get("outline") or {}).get("raw", "")
            user_topic = data.get("user_topic") or record.get("title", "")
            version_name = (data.get("version_name") or "").strip()
            source = (data.get("source") or "manual").strip() or "manual"
            set_selected = data.get("set_selected", True)

            images = record.get("images") or {}
            task_id = images.get("task_id")
            if not task_id:
                task_id = f"cover_task_{uuid.uuid4().hex[:8]}"
                images = {
                    "task_id": task_id,
                    "generated": images.get("generated", []) if isinstance(images.get("generated"), list) else []
                }

            versions = record.get("cover_versions")
            if not isinstance(versions, list):
                versions = []
            version_id = _next_cover_version_id(versions)
            if not version_name:
                version_name = f"封面版本 {version_id}"

            filename = f"cover_{version_id}.png"

            log_request("/cover/regenerate", {
                "record_id": record_id,
                "task_id": task_id,
                "version_id": version_id,
                "set_selected": bool(set_selected),
            })

            image_service = get_image_service()
            image_data = image_service.render_cover_png_bytes(
                cover_spec=cover_spec,
                full_outline=full_outline or "",
                user_topic=user_topic or "",
            )
            image_service.save_cover_png(task_id=task_id, filename=filename, image_data=image_data)

            new_version = {
                "id": version_id,
                "name": version_name,
                "source": source,
                "created_at": datetime.now().isoformat(),
                "cover_spec": cover_spec,
                "task_id": task_id,
                "image_filename": filename,
            }
            versions.append(new_version)

            selected_version = version_id if set_selected else record.get("selected_cover_version")
            if not selected_version and versions:
                selected_version = versions[-1].get("id")

            thumbnail = record.get("thumbnail")
            if set_selected:
                thumbnail = filename

            success = history_service.update_record(
                record_id,
                images=images,
                thumbnail=thumbnail,
                cover_spec=cover_spec,
                cover_versions=versions,
                selected_cover_version=selected_version,
            )
            if not success:
                return jsonify({
                    "success": False,
                    "error": f"更新历史记录失败：{record_id}"
                }), 500

            return jsonify({
                "success": True,
                "record_id": record_id,
                "task_id": task_id,
                "version_id": version_id,
                "selected_cover_version": selected_version,
                "image_filename": filename,
                "image_url": f"/api/images/{task_id}/{filename}?thumbnail=false",
            }), 200
        except Exception as e:
            log_error("/cover/regenerate", e)
            return jsonify({
                "success": False,
                "error": f"封面重生失败。\n错误详情: {str(e)}"
            }), 500

    @cover_bp.route("/cover/select", methods=["POST"])
    def select_cover_version():
        """
        选择当前封面版本

        请求体：
        - record_id: 历史记录 ID（必填）
        - version_id: 封面版本 ID（必填）
        """
        try:
            data = request.get_json() or {}
            record_id = data.get("record_id")
            version_id = data.get("version_id")
            if not record_id or not version_id:
                return jsonify({
                    "success": False,
                    "error": "参数错误：record_id 和 version_id 不能为空。"
                }), 400

            history_service = get_history_service()
            record = history_service.get_record(record_id)
            if not record:
                return jsonify({
                    "success": False,
                    "error": f"历史记录不存在：{record_id}"
                }), 404

            versions = record.get("cover_versions") or []
            selected = next((v for v in versions if v.get("id") == version_id), None)
            if not selected:
                return jsonify({
                    "success": False,
                    "error": f"封面版本不存在：{version_id}"
                }), 404

            selected_cover_spec = selected.get("cover_spec")
            thumbnail = selected.get("image_filename") or record.get("thumbnail")

            log_request("/cover/select", {
                "record_id": record_id,
                "version_id": version_id,
            })

            success = history_service.update_record(
                record_id,
                cover_spec=selected_cover_spec,
                selected_cover_version=version_id,
                thumbnail=thumbnail,
            )
            if not success:
                return jsonify({
                    "success": False,
                    "error": f"更新历史记录失败：{record_id}"
                }), 500

            task_id = (selected.get("task_id") or (record.get("images") or {}).get("task_id"))
            image_filename = selected.get("image_filename")
            image_url = None
            if task_id and image_filename:
                image_url = f"/api/images/{task_id}/{image_filename}?thumbnail=false"

            return jsonify({
                "success": True,
                "record_id": record_id,
                "selected_cover_version": version_id,
                "cover_spec": selected_cover_spec,
                "image_url": image_url,
            }), 200
        except Exception as e:
            log_error("/cover/select", e)
            return jsonify({
                "success": False,
                "error": f"切换封面版本失败。\n错误详情: {str(e)}"
            }), 500

    return cover_bp

