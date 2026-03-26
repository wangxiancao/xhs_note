"""
发布相关 API 路由

包含功能：
- 检查 xiaohongshu-mcp 登录状态
- 从当前生成结果直接发布到小红书
"""

import logging
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request

from backend.services.publish_service import get_publish_service
from .utils import log_error, log_request

logger = logging.getLogger(__name__)


def create_publish_blueprint():
    """创建发布路由蓝图（工厂函数，支持多次调用）"""
    publish_bp = Blueprint("publish", __name__)

    @publish_bp.route("/publish/status", methods=["GET"])
    def check_publish_status():
        """检查发布服务登录状态"""
        try:
            log_request("/publish/status")
            publish_service = get_publish_service()
            result = publish_service.check_login_status()
            return jsonify(result), 200
        except Exception as e:
            log_error("/publish/status", e)
            return jsonify({
                "success": False,
                "error": f"检查登录状态失败。\n错误详情: {str(e)}"
            }), 500

    @publish_bp.route("/publish/from-result", methods=["POST"])
    def publish_from_result():
        """
        从当前生成结果发布到小红书

        请求体（application/json）：
        - task_id: 生成任务ID（必填）
        - record_id: 历史记录ID（必填）
        - topic: 主题（可选）
        - title: 标题（可选，未传时使用 topic）
        - content: 正文（必填）
        - tags: 标签数组（可选）
        - image_filenames: 图片文件名数组（可选，未传时自动读取 task_id 目录）
        - image_urls: 图片 URL 数组（可选，会自动提取文件名）
        - schedule_at: 预约发布时间（可选，ISO8601）
        - dry_run: 是否只做参数校验和图片准备（可选，默认 false）
        """
        try:
            data = request.get_json() or {}
            task_id = data.get("task_id", "")
            record_id = data.get("record_id", "")
            topic = data.get("topic", "")
            title = data.get("title", "")
            content = data.get("content", "")
            tags = data.get("tags", [])
            schedule_at = data.get("schedule_at")
            dry_run = bool(data.get("dry_run", False))

            image_filenames = data.get("image_filenames", [])
            image_urls = data.get("image_urls", [])
            if not image_filenames and image_urls:
                image_filenames = _extract_filenames_from_urls(image_urls)

            log_request("/publish/from-result", {
                "task_id": task_id,
                "record_id": record_id,
                "title": title[:30] if title else "",
                "tags_count": len(tags) if isinstance(tags, list) else 0,
                "image_filenames_count": len(image_filenames) if isinstance(image_filenames, list) else 0,
                "dry_run": dry_run,
            })

            publish_service = get_publish_service()
            result = publish_service.publish_from_result(
                task_id=task_id,
                record_id=record_id,
                topic=topic,
                title=title,
                content=content,
                tags=tags if isinstance(tags, list) else [],
                image_filenames=image_filenames if isinstance(image_filenames, list) else [],
                schedule_at=schedule_at,
                dry_run=dry_run,
            )
            return jsonify(result), 200

        except ValueError as e:
            logger.warning("发布参数错误: %s", e)
            return jsonify({
                "success": False,
                "error": str(e),
            }), 400
        except PermissionError as e:
            logger.warning("发布前置校验失败: %s", e)
            return jsonify({
                "success": False,
                "error": str(e),
            }), 401
        except Exception as e:
            log_error("/publish/from-result", e)
            return jsonify({
                "success": False,
                "error": f"发布失败。\n错误详情: {str(e)}",
            }), 500

    @publish_bp.route("/publish/video", methods=["POST"])
    def publish_video():
        """
        上传视频并直接发布到小红书

        请求体（multipart/form-data）：
        - video: 视频文件（必填）
        - cover: 封面图片文件（可选，仅用于当前流程预览与留档）
        - title: 标题（可选，缺失时取正文首行前 20 个字符）
        - content: 正文（必填）
        - tags: 标签（可选，可重复传入或用英文逗号分隔）
        - schedule_at: 预约发布时间（可选，ISO8601）
        - dry_run: 是否只做参数校验和文件准备（可选，默认 false）
        """
        try:
            video = request.files.get("video")
            cover = request.files.get("cover")

            if not video or not video.filename:
                return jsonify({
                    "success": False,
                    "error": "参数错误：video 不能为空。"
                }), 400

            title = (request.form.get("title") or "").strip()
            content = (request.form.get("content") or "").strip()
            schedule_at = request.form.get("schedule_at")
            dry_run = _parse_boolean_form_value(request.form.get("dry_run"))
            tags = _parse_tags_form(request.form.getlist("tags"))

            video_bytes = video.read()
            if not video_bytes:
                return jsonify({
                    "success": False,
                    "error": "参数错误：上传视频内容为空。"
                }), 400

            cover_bytes = None
            cover_filename = ""
            if cover and cover.filename:
                cover_bytes = cover.read()
                cover_filename = cover.filename
                if not cover_bytes:
                    return jsonify({
                        "success": False,
                        "error": "参数错误：上传封面内容为空。"
                    }), 400

            log_request("/publish/video", {
                "title": title[:30],
                "content_length": len(content),
                "tags_count": len(tags),
                "has_cover": bool(cover_bytes),
                "video_filename": video.filename,
                "dry_run": dry_run,
            })

            publish_service = get_publish_service()
            result = publish_service.publish_video(
                title=title,
                content=content,
                video_filename=video.filename,
                video_bytes=video_bytes,
                cover_filename=cover_filename,
                cover_bytes=cover_bytes,
                tags=tags,
                schedule_at=schedule_at,
                dry_run=dry_run,
            )
            return jsonify(result), 200
        except ValueError as e:
            logger.warning("视频发布参数错误: %s", e)
            return jsonify({
                "success": False,
                "error": str(e),
            }), 400
        except PermissionError as e:
            logger.warning("视频发布前置校验失败: %s", e)
            return jsonify({
                "success": False,
                "error": str(e),
            }), 401
        except Exception as e:
            log_error("/publish/video", e)
            return jsonify({
                "success": False,
                "error": f"视频发布失败。\n错误详情: {str(e)}",
            }), 500

    return publish_bp


def _extract_filenames_from_urls(image_urls):
    """从图片 URL 列表中提取文件名"""
    filenames = []
    for image_url in image_urls:
        if not image_url:
            continue
        parsed = urlparse(str(image_url))
        path = parsed.path or ""
        filename = path.split("/")[-1]
        if filename:
            filenames.append(filename)
    return filenames


def _parse_boolean_form_value(value):
    """解析 multipart/form-data 中的布尔字段"""
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_tags_form(values):
    """解析 multipart/form-data 中的 tags 字段"""
    tags = []
    for raw in values:
        if raw is None:
            continue
        for item in str(raw).split(","):
            tag = item.strip()
            if tag:
                tags.append(tag)
    return tags
