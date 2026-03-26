"""
发布服务

将 RedInk 的生成结果转换为 xiaohongshu-mcp 可消费的发布请求，
并通过 MCP 协议调用 publish_content 工具。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
from uuid import uuid4

import requests

from backend.services.history import get_history_service

logger = logging.getLogger(__name__)


class PublishService:
    """小红书发布服务"""

    def __init__(self):
        base_url = os.getenv("XHS_MCP_BASE_URL", "http://127.0.0.1:18060").rstrip("/")
        timeout_raw = os.getenv("XHS_MCP_TIMEOUT", "60")

        try:
            self.timeout = float(timeout_raw)
        except ValueError:
            self.timeout = 60.0

        self.base_url = base_url
        self.mcp_url = urljoin(f"{base_url}/", "mcp")
        self.login_status_url = urljoin(f"{base_url}/", "api/v1/login/status")

        # 目录结构：
        #   RedInk-glm/
        #     ├─ RedInk/                <-- redink_root
        #     │   └─ history/
        #     └─ images/publish/        <-- staged_host_root
        self.redink_root = Path(__file__).resolve().parents[2]
        self.workspace_root = self.redink_root.parent
        self.history_root = self.redink_root / "history"
        self.staged_host_root = self.workspace_root / "images" / "publish"
        self.staged_container_root = "/app/images/publish"
        self.video_staged_host_root = self.workspace_root / "images" / "video_publish"
        self.video_staged_container_root = "/app/images/video_publish"

        self.staged_host_root.mkdir(parents=True, exist_ok=True)
        self.video_staged_host_root.mkdir(parents=True, exist_ok=True)

    def check_login_status(self) -> Dict[str, Any]:
        """检查 xiaohongshu-mcp 登录状态"""
        try:
            response = requests.get(self.login_status_url, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            logger.error("检查登录状态失败: %s", exc)
            raise RuntimeError(f"无法连接 xiaohongshu-mcp: {exc}") from exc
        except ValueError as exc:
            logger.error("登录状态响应不是 JSON: %s", exc)
            raise RuntimeError("xiaohongshu-mcp 返回了无法解析的登录状态数据") from exc

        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        return {
            "success": bool(payload.get("success", False)),
            "is_logged_in": bool(data.get("is_logged_in", False)),
            "username": data.get("username", ""),
            "message": payload.get("message", ""),
            "raw": payload,
        }

    def publish_from_result(
        self,
        task_id: str,
        record_id: str,
        topic: str = "",
        title: str = "",
        content: str = "",
        tags: Optional[List[str]] = None,
        image_filenames: Optional[List[str]] = None,
        schedule_at: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """从当前生成结果发布到小红书"""
        normalized_task_id = (task_id or "").strip()
        if not normalized_task_id:
            raise ValueError("参数错误：task_id 不能为空。")
        normalized_record_id = (record_id or "").strip()
        if not normalized_record_id:
            raise ValueError("参数错误：record_id 不能为空。")

        resolved_title = (title or topic or "").strip()
        if not resolved_title:
            raise ValueError("参数错误：title 不能为空。")
        if len(resolved_title) > 20:
            raise ValueError("参数错误：title 不能超过 20 个字符。")

        resolved_content = (content or "").strip()
        if not resolved_content:
            raise ValueError("参数错误：content 不能为空。")

        normalized_tags = self._normalize_tags(tags or [])
        source_images = self._resolve_publish_images(
            task_id=normalized_task_id,
            record_id=normalized_record_id,
            image_filenames=image_filenames or [],
        )
        staged = self._stage_images(normalized_task_id, source_images)

        publish_args: Dict[str, Any] = {
            "title": resolved_title,
            "content": resolved_content,
            "images": staged["container_paths"],
        }
        if normalized_tags:
            publish_args["tags"] = normalized_tags
        if schedule_at:
            publish_args["schedule_at"] = schedule_at

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "message": "dry_run 模式：已完成参数组装与图片路径准备，未实际调用 publish_content。",
                "publish_payload": publish_args,
                "staged_host_paths": staged["host_paths"],
                "staged_container_paths": staged["container_paths"],
            }

        login_status = self.check_login_status()
        if not login_status.get("is_logged_in"):
            raise PermissionError("发布失败：xiaohongshu-mcp 未登录，请先扫码登录。")

        tool_result = self._call_mcp_tool("publish_content", publish_args)
        tool_message = self._extract_tool_message(tool_result)

        if tool_result.get("isError"):
            raise RuntimeError(tool_message or "publish_content 返回错误结果。")

        return {
            "success": True,
            "message": tool_message or "发布请求已提交。",
            "publish_payload": publish_args,
            "tool_result": tool_result,
            "staged_host_paths": staged["host_paths"],
            "staged_container_paths": staged["container_paths"],
        }

    def publish_video(
        self,
        title: str = "",
        content: str = "",
        video_filename: str = "",
        video_bytes: bytes = b"",
        cover_filename: str = "",
        cover_bytes: Optional[bytes] = None,
        tags: Optional[List[str]] = None,
        schedule_at: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """上传视频并通过 MCP 发布到小红书"""
        resolved_content = (content or "").strip()
        if not resolved_content:
            raise ValueError("参数错误：content 不能为空。")

        resolved_title = self._resolve_video_title(title=title, content=resolved_content)
        normalized_tags = self._normalize_tags(tags or [])
        staged = self._stage_video_assets(
            video_filename=video_filename,
            video_bytes=video_bytes,
            cover_filename=cover_filename,
            cover_bytes=cover_bytes,
        )

        publish_args: Dict[str, Any] = {
            "title": resolved_title,
            "content": resolved_content,
            "video": staged["video_container_path"],
        }
        if normalized_tags:
            publish_args["tags"] = normalized_tags
        if schedule_at:
            publish_args["schedule_at"] = schedule_at

        response_payload = {
            "success": True,
            "publish_payload": publish_args,
            "staged_host_paths": staged["host_paths"],
            "staged_container_paths": staged["container_paths"],
            "staged_video_host_path": staged["video_host_path"],
            "staged_video_container_path": staged["video_container_path"],
            "staged_cover_host_path": staged["cover_host_path"],
            "staged_cover_container_path": staged["cover_container_path"],
            "resolved_title": resolved_title,
        }

        if dry_run:
            return {
                **response_payload,
                "dry_run": True,
                "message": "dry_run 模式：已完成视频与封面准备，未实际调用 publish_with_video。",
            }

        login_status = self.check_login_status()
        if not login_status.get("is_logged_in"):
            raise PermissionError("发布失败：xiaohongshu-mcp 未登录，请先扫码登录。")

        tool_result = self._call_mcp_tool("publish_with_video", publish_args)
        tool_message = self._extract_tool_message(tool_result)

        if tool_result.get("isError"):
            raise RuntimeError(tool_message or "publish_with_video 返回错误结果。")

        return {
            **response_payload,
            "message": tool_message or "视频发布请求已提交。",
            "tool_result": tool_result,
        }

    def _resolve_publish_images(self, task_id: str, record_id: str, image_filenames: List[str]) -> List[Path]:
        """
        解析发布图片列表，并强制将 selected_cover_version 对应封面放在首位。
        """
        history_service = get_history_service()
        record = history_service.get_record(record_id)
        if not record:
            raise ValueError(f"参数错误：record_id 不存在（{record_id}）。")

        selected_cover_path = self._resolve_selected_cover_path(record)
        source_images = self._collect_source_images(task_id, image_filenames)

        ordered_images: List[Path] = [selected_cover_path]
        selected_cover_real = str(selected_cover_path.resolve())
        for image in source_images:
            if str(image.resolve()) == selected_cover_real:
                continue
            ordered_images.append(image)

        if len(ordered_images) < 1:
            raise ValueError("发布失败：未找到可发布图片。")

        return ordered_images

    def _resolve_selected_cover_path(self, record: Dict[str, Any]) -> Path:
        """
        读取历史记录中 selected_cover_version 对应封面，并校验其可访问性。
        """
        selected_version_id = (record.get("selected_cover_version") or "").strip()
        if not selected_version_id:
            raise ValueError("发布失败：未选择封面版本，请先在封面创作台确认封面。")

        versions = record.get("cover_versions")
        if not isinstance(versions, list) or not versions:
            raise ValueError("发布失败：封面版本为空，请先生成并保存封面。")

        selected_version = next(
            (item for item in versions if isinstance(item, dict) and item.get("id") == selected_version_id),
            None,
        )
        if not selected_version:
            raise ValueError("发布失败：当前选中的封面版本不存在，请重新选择封面。")

        selected_task_id = (
            selected_version.get("task_id")
            or (record.get("images") or {}).get("task_id")
            or ""
        ).strip()
        image_filename = (selected_version.get("image_filename") or "").strip()

        if not selected_task_id or not image_filename:
            raise ValueError("发布失败：封面版本缺少图片文件，请先重新渲染封面并保存。")

        cover_path = self.history_root / selected_task_id / image_filename
        if not cover_path.exists() or not cover_path.is_file():
            raise ValueError(f"发布失败：封面文件不存在（{cover_path}）。")
        if not os.access(cover_path, os.R_OK):
            raise ValueError(f"发布失败：封面文件不可读（{cover_path}）。")
        if cover_path.stat().st_size <= 0:
            raise ValueError(f"发布失败：封面文件为空（{cover_path}）。")

        return cover_path

    def _call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """通过 MCP 会话调用工具"""
        session_id = self._create_mcp_session()
        request_payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }
        response_json = self._post_mcp_json(request_payload, session_id=session_id)
        if "error" in response_json:
            message = response_json.get("error", {}).get("message", "unknown MCP error")
            raise RuntimeError(f"MCP 工具调用失败: {message}")
        return response_json.get("result", {})

    def _create_mcp_session(self) -> str:
        """初始化 MCP 会话并发送 initialized 通知"""
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {
                    "name": "redink-glm",
                    "version": "0.1.0",
                },
            },
        }
        response = requests.post(
            self.mcp_url,
            json=init_payload,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        session_id = response.headers.get("Mcp-Session-Id")
        if not session_id:
            raise RuntimeError("MCP initialize 返回缺少 Mcp-Session-Id。")

        # 发送 initialized 通知，进入可调用工具状态
        initialized_payload = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }
        self._post_mcp_json(initialized_payload, session_id=session_id)
        return session_id

    def _post_mcp_json(self, payload: Dict[str, Any], session_id: Optional[str] = None) -> Dict[str, Any]:
        """向 /mcp 发送 JSON-RPC 请求"""
        headers = {"Content-Type": "application/json"}
        if session_id:
            headers["Mcp-Session-Id"] = session_id

        try:
            response = requests.post(
                self.mcp_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"MCP 请求失败: {exc}") from exc

        # notifications/initialized 可能返回空 body
        if not response.text.strip():
            return {}

        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError("MCP 返回非 JSON 数据。") from exc

    def _collect_source_images(self, task_id: str, image_filenames: List[str]) -> List[Path]:
        """收集需要发布的图片文件（来自 RedInk/history/{task_id}）"""
        task_dir = self.history_root / task_id
        if not task_dir.exists():
            raise ValueError(f"图片任务目录不存在：{task_dir}")

        if image_filenames:
            source_files: List[Path] = []
            for name in image_filenames:
                filename = Path(name).name
                if not filename:
                    continue
                candidate = task_dir / filename
                if not candidate.exists():
                    raise ValueError(f"图片文件不存在：{candidate}")
                source_files.append(candidate)
        else:
            source_files = [
                file_path
                for file_path in task_dir.glob("*.png")
                if not file_path.name.startswith("thumb_")
            ]
            source_files.sort(key=lambda p: self._natural_sort_key(p.name))

        if not source_files:
            raise ValueError("未找到可发布的 PNG 图片。")

        return source_files

    def _stage_images(self, task_id: str, source_files: List[Path]) -> Dict[str, List[str]]:
        """复制图片到共享挂载目录，并返回宿主机路径与容器路径"""
        staged_dir_name = f"{task_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        staged_host_dir = self.staged_host_root / staged_dir_name
        staged_host_dir.mkdir(parents=True, exist_ok=True)

        host_paths: List[str] = []
        container_paths: List[str] = []

        for index, source_file in enumerate(source_files, start=1):
            target_name = f"{index:02d}_{source_file.name}"
            target_file = staged_host_dir / target_name
            shutil.copy2(source_file, target_file)

            host_paths.append(str(target_file))
            container_paths.append(f"{self.staged_container_root}/{staged_dir_name}/{target_name}")

        return {
            "host_paths": host_paths,
            "container_paths": container_paths,
        }

    def _stage_video_assets(
        self,
        video_filename: str,
        video_bytes: bytes,
        cover_filename: str = "",
        cover_bytes: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """保存视频发布素材到共享挂载目录，并返回宿主机路径与容器路径"""
        if not video_bytes:
            raise ValueError("参数错误：video 不能为空。")

        staged_dir_name = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        staged_host_dir = self.video_staged_host_root / staged_dir_name
        staged_host_dir.mkdir(parents=True, exist_ok=True)

        video_suffix = self._normalize_file_suffix(video_filename, default=".mp4")
        video_host_path = staged_host_dir / f"video{video_suffix}"
        video_host_path.write_bytes(video_bytes)
        video_container_path = f"{self.video_staged_container_root}/{staged_dir_name}/video{video_suffix}"

        host_paths: List[str] = [str(video_host_path)]
        container_paths: List[str] = [video_container_path]

        cover_host_path: Optional[str] = None
        cover_container_path: Optional[str] = None
        if cover_bytes:
            cover_suffix = self._normalize_file_suffix(cover_filename, default=".png")
            cover_path = staged_host_dir / f"cover{cover_suffix}"
            cover_path.write_bytes(cover_bytes)
            cover_host_path = str(cover_path)
            cover_container_path = f"{self.video_staged_container_root}/{staged_dir_name}/cover{cover_suffix}"
            host_paths.append(cover_host_path)
            container_paths.append(cover_container_path)

        return {
            "host_paths": host_paths,
            "container_paths": container_paths,
            "video_host_path": str(video_host_path),
            "video_container_path": video_container_path,
            "cover_host_path": cover_host_path,
            "cover_container_path": cover_container_path,
        }

    @staticmethod
    def _extract_tool_message(tool_result: Dict[str, Any]) -> str:
        """从 MCP tool 返回中提取文本信息"""
        messages: List[str] = []
        for item in tool_result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text":
                text = (item.get("text") or "").strip()
                if text:
                    messages.append(text)
        return "\n".join(messages).strip()

    @staticmethod
    def _normalize_tags(tags: List[str]) -> List[str]:
        """清洗标签列表"""
        normalized: List[str] = []
        seen = set()
        for raw in tags:
            tag = str(raw).strip().lstrip("#")
            if not tag:
                continue
            if tag in seen:
                continue
            seen.add(tag)
            normalized.append(tag)
        return normalized

    @staticmethod
    def _resolve_video_title(title: str, content: str) -> str:
        """解析视频标题，若未提供则取正文首行前 20 个字符"""
        resolved_title = (title or "").strip()
        if resolved_title:
            if len(resolved_title) > 20:
                raise ValueError("参数错误：title 不能超过 20 个字符。")
            return resolved_title

        first_line = ""
        for line in content.splitlines():
            candidate = re.sub(r"\s+", " ", line).strip().lstrip("#").strip()
            if candidate:
                first_line = candidate
                break

        if not first_line:
            raise ValueError("参数错误：无法从 content 中提取标题，请填写 title。")

        return first_line[:20].strip()

    @staticmethod
    def _normalize_file_suffix(filename: str, default: str) -> str:
        """提取安全的文件后缀，缺失时回退到默认值"""
        suffix = Path(filename or "").suffix.lower().strip()
        if not suffix:
            return default

        if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
            return default

        return suffix

    @staticmethod
    def _natural_sort_key(value: str):
        """自然排序键（支持 2.png, 10.png 排序）"""
        return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def get_publish_service() -> PublishService:
    """获取发布服务实例（每次新建，避免状态污染）"""
    return PublishService()
