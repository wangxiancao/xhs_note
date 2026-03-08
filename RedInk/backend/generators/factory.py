"""图片生成器工厂"""
from importlib import import_module
from typing import Dict, Any
from .base import ImageGeneratorBase


class ImageGeneratorFactory:
    """图片生成器工厂类"""

    # 注册的生成器类型（模块路径, 类名）
    GENERATORS = {
        'google_genai': ('.google_genai', 'GoogleGenAIGenerator'),
        'openai': ('.openai_compatible', 'OpenAICompatibleGenerator'),
        'openai_compatible': ('.openai_compatible', 'OpenAICompatibleGenerator'),
        'image_api': ('.image_api', 'ImageApiGenerator'),
    }

    @classmethod
    def _resolve_generator_class(cls, provider: str) -> type:
        generator_info = cls.GENERATORS.get(provider)
        if generator_info is None:
            available = ', '.join(cls.GENERATORS.keys())
            raise ValueError(
                f"不支持的图片生成服务商: {provider}\n"
                f"支持的服务商类型: {available}\n"
                "解决方案：\n"
                "1. 检查 image_providers.yaml 中的 active_provider 配置\n"
                "2. 确认 provider.type 字段是否正确\n"
                "3. 或使用环境变量 IMAGE_PROVIDER 指定服务商"
            )

        if isinstance(generator_info, tuple):
            module_path, class_name = generator_info
            try:
                module = import_module(module_path, package=__package__)
                return getattr(module, class_name)
            except ModuleNotFoundError as exc:
                if provider == 'google_genai':
                    raise RuntimeError(
                        "google_genai 依赖缺失，请安装 google-genai。\n"
                        "建议：在当前环境执行 `pip install google-genai` 或 `uv sync`。"
                    ) from exc
                raise
        return generator_info

    @classmethod
    def create(cls, provider: str, config: Dict[str, Any]) -> ImageGeneratorBase:
        """
        创建图片生成器实例

        Args:
            provider: 服务商类型 ('google_genai', 'openai', 'openai_compatible')
            config: 配置字典

        Returns:
            图片生成器实例

        Raises:
            ValueError: 不支持的服务商类型
        """
        generator_class = cls._resolve_generator_class(provider)
        return generator_class(config)

    @classmethod
    def register_generator(cls, name: str, generator_class: type):
        """
        注册自定义生成器

        Args:
            name: 生成器名称
            generator_class: 生成器类
        """
        if not issubclass(generator_class, ImageGeneratorBase):
            raise TypeError(
                f"注册失败：生成器类必须继承自 ImageGeneratorBase。\n"
                f"提供的类: {generator_class.__name__}\n"
                f"基类: ImageGeneratorBase"
            )

        cls.GENERATORS[name] = generator_class
