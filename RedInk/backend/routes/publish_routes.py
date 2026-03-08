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
                "title": title[:30] if title else "",
                "tags_count": len(tags) if isinstance(tags, list) else 0,
                "image_filenames_count": len(image_filenames) if isinstance(image_filenames, list) else 0,
                "dry_run": dry_run,
            })

            publish_service = get_publish_service()
            result = publish_service.publish_from_result(
                task_id=task_id,
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
