"""
内容生成服务

生成小红书风格的标题、文案和标签
"""

import json
import logging
import os
import re
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from backend.utils.text_client import get_text_chat_client
from backend.utils.secret_resolver import resolve_api_key

logger = logging.getLogger(__name__)


class ContentService:
    """内容生成服务：生成标题、文案、标签"""

    def __init__(self):
        logger.debug("初始化 ContentService...")
        self.text_config = self._load_text_config()
        self.client = self._get_client()
        self.prompt_template = self._load_prompt_template()
        self.refine_prompt_template = self._load_refine_prompt_template()
        logger.info(f"ContentService 初始化完成，使用服务商: {self.text_config.get('active_provider')}")

    def _load_text_config(self) -> dict:
        """加载文本生成配置"""
        config_path = Path(__file__).parent.parent.parent / 'text_providers.yaml'
        logger.debug(f"加载文本配置: {config_path}")

        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}
                logger.debug(f"文本配置加载成功: active={config.get('active_provider')}")
                return config
            except yaml.YAMLError as e:
                logger.error(f"文本配置 YAML 解析失败: {e}")
                raise ValueError(
                    f"文本配置文件格式错误: text_providers.yaml\n"
                    f"YAML 解析错误: {e}\n"
                    "解决方案：检查 YAML 缩进和语法"
                )

        logger.warning("text_providers.yaml 不存在，使用默认配置")
        return {
            'active_provider': 'glm_47',
            'providers': {
                'glm_47': {
                    'type': 'openai_compatible',
                    'api_key': '',
                    'base_url': 'https://open.bigmodel.cn/api/paas',
                    'endpoint_type': '/v4/chat/completions',
                    'model': 'glm-4.7',
                    'temperature': 0.7,
                    'max_output_tokens': 8000,
                },
                'deepseek_chat': {
                    'type': 'openai_compatible',
                    'api_key': '',
                    'base_url': 'https://api.deepseek.com',
                    'endpoint_type': '/v1/chat/completions',
                    'model': 'deepseek-chat',
                    'temperature': 0.7,
                    'max_output_tokens': 8000,
                }
            }
        }

    def _get_client(self):
        """根据配置获取客户端"""
        active_provider = self.text_config.get('active_provider', 'glm_47')
        providers = self.text_config.get('providers', {})

        if not providers:
            logger.error("未找到任何文本生成服务商配置")
            raise ValueError(
                "未找到任何文本生成服务商配置。\n"
                "解决方案：\n"
                "1. 在系统设置页面添加文本生成服务商\n"
                "2. 或手动编辑 text_providers.yaml 文件"
            )

        if active_provider not in providers:
            available = ', '.join(providers.keys())
            logger.error(f"文本服务商 [{active_provider}] 不存在，可用: {available}")
            raise ValueError(
                f"未找到文本生成服务商配置: {active_provider}\n"
                f"可用的服务商: {available}\n"
                "解决方案：在系统设置中选择一个可用的服务商"
            )

        provider_config = providers.get(active_provider, {}).copy()
        api_key, api_key_source = resolve_api_key(
            configured_key=provider_config.get('api_key', ''),
        )

        if not api_key:
            logger.error(f"文本服务商 [{active_provider}] 未配置 API Key")
            raise ValueError(
                f"文本服务商 {active_provider} 未配置 API Key。\n"
                "解决方案：\n"
                "1. 在系统设置页面填写 API Key\n"
                "2. 或在 text_providers.yaml 中配置 api_key"
            )

        provider_config['api_key'] = api_key
        logger.debug(f"文本服务商 [{active_provider}] API Key 来源: {api_key_source}")
        logger.info(f"使用文本服务商: {active_provider} (type={provider_config.get('type')})")
        return get_text_chat_client(provider_config)

    def _load_prompt_template(self) -> str:
        """加载提示词模板"""
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "prompts",
            "content_prompt.txt"
        )
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

    def _load_refine_prompt_template(self) -> str:
        """加载文案优化提示词模板"""
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "prompts",
            "content_refine_prompt.txt"
        )
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()

        return (
            "你是一个小红书文案优化助手。请根据主题、大纲、当前文案和对话历史，输出优化后的完整 JSON。\n"
            "只输出 JSON，不要额外解释。\n\n"
            "主题：{topic}\n\n"
            "大纲：\n{outline}\n\n"
            "当前文案：\n{current_content}\n\n"
            "历史对话：\n{conversation_history}\n\n"
            "用户本轮要求：\n{user_message}\n\n"
            "JSON 格式：\n"
            "{{\n"
            '  "assistant_reply": "用自然中文简要说明本轮改动",\n'
            '  "titles": ["标题1", "标题2", "标题3"],\n'
            '  "copywriting": "完整正文",\n'
            '  "tags": ["标签1", "标签2", "标签3"]\n'
            "}}\n"
        )

    def _normalize_content_payload(self, payload: Any) -> Dict[str, Any]:
        """标准化内容载荷，确保结构稳定"""
        if not isinstance(payload, dict):
            return {
                "titles": [],
                "copywriting": "",
                "tags": [],
            }

        titles = payload.get("titles", [])
        if isinstance(titles, str):
            titles = [titles]
        elif not isinstance(titles, list):
            titles = []

        tags = payload.get("tags", [])
        if isinstance(tags, str):
            tags = [item.strip() for item in tags.split(",") if item.strip()]
        elif not isinstance(tags, list):
            tags = []

        return {
            "titles": [str(item).strip() for item in titles if str(item).strip()][:6],
            "copywriting": str(payload.get("copywriting") or ""),
            "tags": [str(item).strip().lstrip("#") for item in tags if str(item).strip()][:12],
        }

    def _format_conversation_history(self, messages: List[Dict[str, Any]]) -> str:
        """将聊天记录压缩成 prompt 文本"""
        if not messages:
            return "暂无历史对话"

        lines: List[str] = []
        for item in messages[-12:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            speaker = "用户" if role == "user" else "助手"
            lines.append(f"{speaker}: {content}")

        return "\n".join(lines) if lines else "暂无历史对话"

    def _parse_json_response(self, response_text: str) -> Dict[str, Any]:
        """解析 AI 返回的 JSON 响应"""
        # 尝试直接解析
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown 代码块中提取
        json_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', response_text)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 尝试找到 JSON 对象的开始和结束
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            try:
                return json.loads(response_text[start_idx:end_idx + 1])
            except json.JSONDecodeError:
                pass

        logger.error(f"无法解析 JSON 响应: {response_text[:200]}...")
        raise ValueError("AI 返回的内容格式不正确，无法解析")

    def generate_content(
        self,
        topic: str,
        outline: str
    ) -> Dict[str, Any]:
        """
        生成标题、文案和标签

        参数：
            topic: 用户输入的主题
            outline: 大纲内容

        返回：
            包含 titles, copywriting, tags 的字典
        """
        try:
            logger.info(f"开始生成内容: topic={topic[:50]}...")

            # 构建提示词
            prompt = self.prompt_template.format(
                topic=topic,
                outline=outline
            )

            # 从配置中获取模型参数
            active_provider = self.text_config.get('active_provider', 'glm_47')
            providers = self.text_config.get('providers', {})
            provider_config = providers.get(active_provider, {})

            model = provider_config.get('model', 'glm-4.7')
            temperature = provider_config.get('temperature', 0.7)
            max_output_tokens = provider_config.get('max_output_tokens', 4000)

            logger.info(f"调用文本生成 API: model={model}, temperature={temperature}")
            response_text = self.client.generate_text(
                prompt=prompt,
                model=model,
                temperature=temperature,
                max_output_tokens=max_output_tokens
            )

            logger.debug(f"API 返回文本长度: {len(response_text)} 字符")

            # 解析 JSON 响应
            content_data = self._parse_json_response(response_text)

            # 验证必要字段
            titles = content_data.get('titles', [])
            copywriting = content_data.get('copywriting', '')
            tags = content_data.get('tags', [])

            # 确保 titles 是列表
            if isinstance(titles, str):
                titles = [titles]

            # 确保 tags 是列表
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(',')]

            logger.info(f"内容生成完成: {len(titles)} 个标题, {len(tags)} 个标签")

            return {
                "success": True,
                "titles": titles,
                "copywriting": copywriting,
                "tags": tags
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"内容生成失败: {error_msg}")

            # 根据错误类型提供更详细的错误信息
            if "api_key" in error_msg.lower() or "unauthorized" in error_msg.lower() or "401" in error_msg:
                detailed_error = (
                    f"API 认证失败。\n"
                    f"错误详情: {error_msg}\n"
                    "可能原因：API Key 无效或已过期\n"
                    "解决方案：在系统设置页面检查并更新 API Key"
                )
            elif "model" in error_msg.lower() or "404" in error_msg:
                detailed_error = (
                    f"模型访问失败。\n"
                    f"错误详情: {error_msg}\n"
                    "解决方案：在系统设置页面检查模型名称配置"
                )
            elif "timeout" in error_msg.lower() or "连接" in error_msg:
                detailed_error = (
                    f"网络连接失败。\n"
                    f"错误详情: {error_msg}\n"
                    "解决方案：检查网络连接，稍后重试"
                )
            elif "rate" in error_msg.lower() or "429" in error_msg or "quota" in error_msg.lower():
                detailed_error = (
                    f"API 配额限制。\n"
                    f"错误详情: {error_msg}\n"
                    "解决方案：等待配额重置，或升级 API 套餐"
                )
            else:
                detailed_error = (
                    f"内容生成失败。\n"
                    f"错误详情: {error_msg}\n"
                    "建议：检查配置文件 text_providers.yaml"
                )

            return {
                "success": False,
                "error": detailed_error
            }

    def refine_content(
        self,
        topic: str,
        outline: str,
        current_content: Dict[str, Any],
        messages: List[Dict[str, Any]],
        user_message: str,
    ) -> Dict[str, Any]:
        """
        基于用户对话继续优化标题、文案和标签
        """
        try:
            normalized_content = self._normalize_content_payload(current_content)
            prompt = self.refine_prompt_template.format(
                topic=topic,
                outline=outline,
                current_content=json.dumps(normalized_content, ensure_ascii=False, indent=2),
                conversation_history=self._format_conversation_history(messages),
                user_message=user_message,
            )

            active_provider = self.text_config.get('active_provider', 'glm_47')
            providers = self.text_config.get('providers', {})
            provider_config = providers.get(active_provider, {})

            model = provider_config.get('model', 'glm-4.7')
            temperature = provider_config.get('temperature', 0.7)
            max_output_tokens = provider_config.get('max_output_tokens', 4000)

            response_text = self.client.generate_text(
                prompt=prompt,
                model=model,
                temperature=min(max(float(temperature or 0.7), 0.0), 1.0),
                max_output_tokens=max_output_tokens
            )

            content_data = self._parse_json_response(response_text)
            normalized_result = self._normalize_content_payload(content_data)
            assistant_reply = str(content_data.get("assistant_reply") or "").strip() or "已按你的要求更新标题、文案和标签。"

            return {
                "success": True,
                "assistant_reply": assistant_reply,
                "titles": normalized_result["titles"],
                "copywriting": normalized_result["copywriting"],
                "tags": normalized_result["tags"],
            }
        except Exception as e:
            error_msg = str(e)
            logger.error(f"文案优化失败: {error_msg}")
            return {
                "success": False,
                "error": f"文案优化失败。\n错误详情: {error_msg}"
            }


def get_content_service() -> ContentService:
    """
    获取内容生成服务实例
    每次调用都创建新实例以确保配置是最新的
    """
    return ContentService()
