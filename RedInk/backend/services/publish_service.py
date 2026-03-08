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

import requests

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
        #   xhs_note/
        #     ├─ RedInk/                <-- redink_root
        #     │   └─ history/
        #     └─ images/publish/        <-- staged_host_root
        self.redink_root = Path(__file__).resolve().parents[2]
        self.workspace_root = self.redink_root.parent
        self.history_root = self.redink_root / "history"
        self.staged_host_root = self.workspace_root / "images" / "publish"
        self.staged_container_root = "/app/images/publish"

        self.staged_host_root.mkdir(parents=True, exist_ok=True)

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

        resolved_title = (title or topic or "").strip()
        if not resolved_title:
            raise ValueError("参数错误：title 不能为空。")
        if len(resolved_title) > 20:
            raise ValueError("参数错误：title 不能超过 20 个字符。")

        resolved_content = (content or "").strip()
        if not resolved_content:
            raise ValueError("参数错误：content 不能为空。")

        normalized_tags = self._normalize_tags(tags or [])
        source_images = self._collect_source_images(normalized_task_id, image_filenames or [])
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
                    "name": "xhs-note-redink",
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
    def _natural_sort_key(value: str):
        """自然排序键（支持 2.png, 10.png 排序）"""
        return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def get_publish_service() -> PublishService:
    """获取发布服务实例（每次新建，避免状态污染）"""
    return PublishService()
