"""图片生成服务"""
import logging
import io
import os
import re
import subprocess
import tempfile
import uuid
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Generator, List, Optional, Tuple
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

from backend.config import Config
from backend.generators.factory import ImageGeneratorFactory
from backend.utils.image_compressor import compress_image
from backend.utils.secret_resolver import resolve_api_key
from backend.utils.text_client import get_text_chat_client

logger = logging.getLogger(__name__)


class ImageService:
    """图片生成服务类"""

    # 并发配置
    MAX_CONCURRENT = 15  # 最大并发数
    AUTO_RETRY_COUNT = 1  # 不自动重试，超时后让用户手动重试
    TARGET_IMAGE_SIZE = (1242, 1660)  # 小红书封面/图文目标尺寸
    COVER_TEX_MAX_RETRY = 3
    COVER_TEX_COMPILE_TIMEOUT = 45
    XELATEX_PATH = "/usr/local/texlive/2024/bin/x86_64-linux/xelatex"
    PDFTOPPM_PATH = "/usr/bin/pdftoppm"

    def __init__(self, provider_name: str = None):
        """
        初始化图片生成服务

        Args:
            provider_name: 服务商名称，如果为None则使用配置文件中的激活服务商
        """
        logger.debug("初始化 ImageService...")

        # 获取服务商配置
        if provider_name is None:
            provider_name = Config.get_active_image_provider()

        logger.info(f"使用图片服务商: {provider_name}")
        provider_config = Config.get_image_provider_config(provider_name)

        # 创建生成器实例
        provider_type = provider_config.get('type', provider_name)
        logger.debug(f"创建生成器: type={provider_type}")
        self.generator = ImageGeneratorFactory.create(provider_type, provider_config)

        # 保存配置信息
        self.provider_name = provider_name
        self.provider_config = provider_config

        # 检查是否启用短 prompt 模式
        self.use_short_prompt = provider_config.get('short_prompt', False)

        # 加载提示词模板
        self.prompt_template = self._load_prompt_template()
        self.prompt_template_short = self._load_prompt_template(short=True)
        self.cover_latex_prompt_template = self._load_cover_prompt_template()
        self.cover_text_client, self.cover_text_model = self._build_cover_text_client()

        # 历史记录根目录
        self.history_root_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "history"
        )
        os.makedirs(self.history_root_dir, exist_ok=True)

        # 当前任务的输出目录（每个任务一个子文件夹）
        self.current_task_dir = None

        # 存储任务状态（用于重试）
        self._task_states: Dict[str, Dict] = {}

        logger.info(f"ImageService 初始化完成: provider={provider_name}, type={provider_type}")

    def _load_prompt_template(self, short: bool = False) -> str:
        """加载 Prompt 模板"""
        filename = "image_prompt_short.txt" if short else "image_prompt.txt"
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "prompts",
            filename
        )
        if not os.path.exists(prompt_path):
            # 如果短模板不存在，返回空字符串
            return ""
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

    def _load_cover_prompt_template(self) -> str:
        """加载封面 LaTeX 生成提示词模板"""
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "prompts",
            "cover_latex_prompt.txt"
        )
        if not os.path.exists(prompt_path):
            return (
                "请基于以下内容生成可直接编译的 xelatex + ctex 封面 TeX 模板。\n"
                "仅输出 TeX 代码，不要解释。\n\n"
                "页面内容:\n{page_content}\n\n"
                "用户主题:\n{user_topic}\n\n"
                "完整大纲:\n{full_outline}\n\n"
                "第 {attempt} 次生成。\n"
                "上一次编译错误:\n{compile_feedback}\n\n"
                "上一次 TeX:\n{previous_tex}\n"
            )
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()

    def _build_cover_text_client(self):
        """构建用于封面 LaTeX 生成的文本客户端"""
        text_config = Config.load_text_providers_config()
        active_provider = text_config.get("active_provider", "glm_47")
        providers = text_config.get("providers", {})
        provider_config = providers.get(active_provider, {}).copy()

        api_key, _ = resolve_api_key(configured_key=provider_config.get("api_key", ""))
        if not api_key:
            raise ValueError(
                "封面 TeX 生成需要文本 API Key。\n"
                "请在系统设置中为当前文本服务商配置 API Key。"
            )
        provider_config["api_key"] = api_key
        model = provider_config.get("model", "glm-4.7")
        client = get_text_chat_client(provider_config)
        return client, model

    def _extract_tex_block(self, response_text: str) -> str:
        """从模型响应中提取 TeX 代码"""
        if not response_text:
            return ""
        fenced_patterns = [
            r"```(?:tex|latex)\s*([\s\S]*?)```",
            r"```([\s\S]*?)```",
        ]
        for pattern in fenced_patterns:
            match = re.search(pattern, response_text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return response_text.strip()

    def _cover_spec_to_page_content(self, cover_spec: Dict[str, Any]) -> str:
        """将结构化 cover_spec 转换为封面页面文本"""
        if not isinstance(cover_spec, dict):
            return "[封面]\n标题：未命名封面"

        title = str(cover_spec.get("title") or "未命名封面").strip()
        subtitle = str(cover_spec.get("subtitle") or "").strip()
        tag = str(cover_spec.get("tag") or "").strip()
        top_badge = str(cover_spec.get("top_badge") or "").strip()
        hashtags = cover_spec.get("hashtags") if isinstance(cover_spec.get("hashtags"), list) else []

        lines = ["[封面]", f"标题：{title}"]
        if subtitle:
            lines.append(f"副标题：{subtitle}")
        if tag:
            lines.append(f"标签：{tag}")
        if top_badge:
            lines.append(f"顶部标签：{top_badge}")
        for item in hashtags[:3]:
            text = str(item).strip()
            if text:
                lines.append(text if text.startswith("#") else f"#{text}")
        return "\n".join(lines)

    def _extract_cover_text_value(self, page_content: str, keys: List[str]) -> str:
        """从封面文本中提取字段值（如标题、副标题）"""
        if not page_content:
            return ""
        for raw_line in page_content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            for key in keys:
                if line.startswith(key):
                    value = line.split("：", 1)[1].strip() if "：" in line else ""
                    if value:
                        return value
        return ""

    def _escape_tex_text(self, text: str) -> str:
        """将普通文本转为相对安全的 TeX 文本"""
        if not text:
            return ""
        replacements = {
            "\\": r"\textbackslash{}",
            "&": r"\&",
            "%": r"\%",
            "$": r"\$",
            "#": r"\#",
            "_": r"\_",
            "{": r"\{",
            "}": r"\}",
            "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}",
        }
        escaped = text
        for old, new in replacements.items():
            escaped = escaped.replace(old, new)
        return escaped

    def _build_cover_text_layout_spec(self, page_content: str, user_topic: str) -> str:
        """构造封面文字与坐标清单，注入提示词强化排版稳定性"""
        title = self._extract_cover_text_value(page_content, ["标题：", "主标题：", "标题:"])
        subtitle = self._extract_cover_text_value(page_content, ["副标题：", "副标题:"])
        tag = self._extract_cover_text_value(page_content, ["Tag：", "TAG：", "标签：", "标签:"])
        top_badge = self._extract_cover_text_value(page_content, ["顶部标签：", "胶囊标签："])

        hashtags: List[str] = []
        for raw_line in (page_content or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                hashtags.append(line)
        hashtags = hashtags[:3]

        if not title:
            title = (user_topic or "夏日美好且治愈").strip()
        if not subtitle:
            subtitle = "把生活调成静音模式"
        if not tag:
            tag = "@ 夏日氛围感"
        if not top_badge:
            top_badge = "建议收藏"
        if not hashtags:
            hashtags = ["#治愈系生活", "#夏日碎片收集", "#慢生活"]

        footer_words = ["慢下来", "去生活", "爱自己"]
        title_tex = self._escape_tex_text(title)
        subtitle_tex = self._escape_tex_text(subtitle)
        tag_tex = self._escape_tex_text(tag)
        top_badge_tex = self._escape_tex_text(top_badge)
        hashtags_tex = [self._escape_tex_text(h) for h in hashtags]
        footer_words_tex = [self._escape_tex_text(w) for w in footer_words]

        spec_lines = [
            "坐标系统：画布 1242x1660，原点在左下角，单位 pt。",
            "所有文字必须按以下位置逐项摆放，不得交换区域，不得越界。",
            "",
            "1) 主标题",
            f"- 文案：{title_tex}",
            "- 锚点：x=98, y=1040, anchor=west",
            "- 文本框宽度：860",
            "- 样式：深蓝色、加粗、大字号、多行左对齐",
            "",
            "2) 副标题",
            f"- 文案：{subtitle_tex}",
            "- 锚点：x=98, y=900, anchor=west",
            "- 文本框宽度：760",
            "- 样式：中等字号、深蓝色或次深蓝",
            "",
            "3) Tag（椭圆描边）",
            f"- 文案：{tag_tex}",
            "- 锚点：x=110, y=620, anchor=west",
            "- 样式：椭圆描边、深蓝描边+深蓝文字",
            "",
            "4) Hashtag（2-3 行）",
            f"- 第1行：{hashtags_tex[0]}；位置 x=110, y=500",
            f"- 第2行：{hashtags_tex[1] if len(hashtags_tex) > 1 else hashtags_tex[0]}；位置 x=110, y=430",
            f"- 第3行：{hashtags_tex[2] if len(hashtags_tex) > 2 else hashtags_tex[min(1, len(hashtags_tex)-1)]}；位置 x=110, y=360",
            "- 样式：小字号、浅蓝灰色、左对齐",
            "",
            "5) 顶部胶囊标签",
            f"- 文案：{top_badge_tex}",
            "- 锚点：x=960, y=1540, anchor=center",
            "- 样式：深蓝底+浅色字，尺寸小，不抢主标题",
            "",
            "6) 底部三词",
            f"- 左词：{footer_words_tex[0]}，位置 x=220, y=70",
            f"- 中词：{footer_words_tex[1]}，位置 x=620, y=70",
            f"- 右词：{footer_words_tex[2]}，位置 x=1020, y=70",
            "- 样式：极小字号，低对比度，配合底部细横线",
        ]

        return "\n".join(spec_lines)

    def _normalize_to_target_size(self, image_data: bytes) -> bytes:
        """统一图片尺寸到 1242x1660"""
        with Image.open(io.BytesIO(image_data)) as img:
            if img.mode in ("RGBA", "LA"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            fitted = ImageOps.fit(
                img,
                self.TARGET_IMAGE_SIZE,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            output = io.BytesIO()
            fitted.save(output, format="PNG", optimize=True)
            return output.getvalue()

    def _parse_latex_compile_error(self, work_dir: Path, fallback: str) -> str:
        """提取 LaTeX 编译错误信息"""
        log_path = work_dir / "cover.log"
        if log_path.exists():
            log_content = log_path.read_text(encoding="utf-8", errors="ignore")
            error_match = re.search(r"^! (.+)$", log_content, flags=re.MULTILINE)
            line_match = re.search(r"^l\.(\d+)", log_content, flags=re.MULTILINE)
            if error_match:
                err = error_match.group(1).strip()
                if line_match:
                    err += f" (line {line_match.group(1)})"
                return err
        fallback = (fallback or "").strip()
        if fallback:
            return fallback[-600:]
        return "Unknown TeX compile error"

    def _sanitize_generated_tex(self, tex_code: str) -> str:
        """
        预处理模型输出的 TeX，修正常见可自动恢复错误

        当前修复：
        - xcolor HTML 颜色写成 {#RRGGBB} 时去掉 #，避免
          `Illegal parameter number in definition of \\@@clr.`
        """
        if not tex_code:
            return tex_code
        sanitized = re.sub(r"\{#([0-9A-Fa-f]{6})\}", r"{\1}", tex_code)
        sanitized = re.sub(r"\{#([0-9A-Fa-f]{3})\}", r"{\1}", sanitized)
        return sanitized

    def _is_image_visually_blank(self, image_data: bytes) -> bool:
        """检测渲染结果是否近似空白图"""
        try:
            with Image.open(io.BytesIO(image_data)).convert("L") as gray_img:
                min_px, max_px = gray_img.getextrema()
                contrast = int(max_px) - int(min_px)
                stddev = float(ImageStat.Stat(gray_img).stddev[0])
                # 低对比度 + 低方差，通常是纯色或近似纯色空白图
                return contrast <= 4 and stddev < 1.5
        except Exception:
            # 无法判断时不拦截，交给后续链路处理
            return False

    def _compile_cover_tex_to_png(self, tex_code: str) -> Tuple[bool, Optional[bytes], str]:
        """编译封面 TeX 并转换为 PNG"""
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                work_dir = Path(temp_dir)
                tex_file = work_dir / "cover.tex"
                pdf_file = work_dir / "cover.pdf"
                ppm_prefix = work_dir / "cover"
                ppm_png = work_dir / "cover.png"

                tex_code = self._sanitize_generated_tex(tex_code)
                tex_file.write_text(tex_code, encoding="utf-8")

                env = os.environ.copy()
                env["PATH"] = f"{os.path.dirname(self.XELATEX_PATH)}:{env.get('PATH', '')}"

                compile_proc = subprocess.run(
                    [
                        self.XELATEX_PATH,
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        "-output-directory",
                        str(work_dir),
                        str(tex_file),
                    ],
                    cwd=str(work_dir),
                    capture_output=True,
                    text=True,
                    timeout=self.COVER_TEX_COMPILE_TIMEOUT,
                    env=env,
                )
                compile_stdout = (compile_proc.stdout or "") + "\n" + (compile_proc.stderr or "")

                if compile_proc.returncode != 0 or not pdf_file.exists():
                    error = self._parse_latex_compile_error(work_dir, compile_stdout)
                    return False, None, error

                convert_proc = subprocess.run(
                    [
                        self.PDFTOPPM_PATH,
                        "-singlefile",
                        "-png",
                        "-r",
                        "300",
                        str(pdf_file),
                        str(ppm_prefix),
                    ],
                    cwd=str(work_dir),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if convert_proc.returncode != 0 or not ppm_png.exists():
                    convert_error = (convert_proc.stderr or convert_proc.stdout or "").strip()
                    return False, None, f"PDF 转 PNG 失败: {convert_error[:300]}"

                normalized_png = self._normalize_to_target_size(ppm_png.read_bytes())
                return True, normalized_png, ""

        except subprocess.TimeoutExpired:
            return False, None, "TeX 编译超时"
        except Exception as e:
            return False, None, f"TeX 编译异常: {str(e)}"

    def _generate_cover_via_latex(
        self,
        page_content: str,
        full_outline: str,
        user_topic: str,
    ) -> bytes:
        """通过文本模型生成封面 TeX，编译失败时自动重试修复"""
        compile_feedback = "无"
        previous_tex = "无"
        text_layout_spec = self._build_cover_text_layout_spec(page_content, user_topic)

        for attempt in range(1, self.COVER_TEX_MAX_RETRY + 1):
            prompt = self.cover_latex_prompt_template.format(
                page_content=page_content,
                full_outline=full_outline or "未提供",
                user_topic=user_topic or "未提供",
                text_layout_spec=text_layout_spec,
                attempt=attempt,
                compile_feedback=compile_feedback,
                previous_tex=previous_tex,
            )

            response_text = self.cover_text_client.generate_text(
                prompt=prompt,
                model=self.cover_text_model,
                temperature=0.35,
                max_output_tokens=4096,
                thinking={"type": "disabled"} if str(self.cover_text_model).lower().startswith("glm") else None,
            )
            tex_code = self._extract_tex_block(response_text)
            if not tex_code:
                compile_feedback = "模型未返回 TeX 代码。"
                previous_tex = "无"
                continue

            ok, png_bytes, compile_error = self._compile_cover_tex_to_png(tex_code)
            if ok and png_bytes:
                if self._is_image_visually_blank(png_bytes):
                    compile_feedback = "封面渲染结果为空白或近似空白，请补充可见背景与文字，并提高前景对比度。"
                    previous_tex = tex_code[:8000]
                    logger.warning(
                        f"封面 TeX 渲染为空白图 (attempt={attempt}/{self.COVER_TEX_MAX_RETRY})"
                    )
                    continue
                return png_bytes

            compile_feedback = compile_error or "未知错误"
            previous_tex = tex_code[:8000]
            logger.warning(
                f"封面 TeX 编译失败 (attempt={attempt}/{self.COVER_TEX_MAX_RETRY}): {compile_feedback}"
            )

        raise RuntimeError(f"封面 TeX 连续编译失败：{compile_feedback}")

    def render_cover_png_bytes(
        self,
        cover_spec: Dict[str, Any],
        full_outline: str = "",
        user_topic: str = "",
    ) -> bytes:
        """
        基于封面结构化参数渲染封面 PNG（二进制）

        Args:
            cover_spec: 封面结构化参数
            full_outline: 完整大纲文本（可选）
            user_topic: 用户主题（可选）

        Returns:
            bytes: PNG 二进制数据
        """
        page_content = self._cover_spec_to_page_content(cover_spec)
        return self._generate_cover_via_latex(
            page_content=page_content,
            full_outline=full_outline,
            user_topic=user_topic,
        )

    def save_cover_png(
        self,
        task_id: str,
        filename: str,
        image_data: bytes,
    ) -> str:
        """
        保存封面 PNG 到任务目录，并生成缩略图

        Args:
            task_id: 任务 ID
            filename: 文件名（如 cover_v2.png）
            image_data: PNG 二进制数据

        Returns:
            str: 文件完整路径
        """
        if not task_id:
            raise ValueError("task_id 不能为空")
        self.current_task_dir = os.path.join(self.history_root_dir, task_id)
        os.makedirs(self.current_task_dir, exist_ok=True)
        return self._save_image(image_data, filename, self.current_task_dir)

    def _save_image(self, image_data: bytes, filename: str, task_dir: str = None) -> str:
        """
        保存图片到本地，同时生成缩略图

        Args:
            image_data: 图片二进制数据
            filename: 文件名
            task_dir: 任务目录（如果为None则使用当前任务目录）

        Returns:
            保存的文件路径
        """
        if task_dir is None:
            task_dir = self.current_task_dir

        if task_dir is None:
            raise ValueError("任务目录未设置")

        # 统一主图尺寸到 1242x1660
        image_data = self._normalize_to_target_size(image_data)

        # 保存原图
        filepath = os.path.join(task_dir, filename)
        with open(filepath, "wb") as f:
            f.write(image_data)

        # 生成缩略图（50KB左右）
        thumbnail_data = compress_image(image_data, max_size_kb=50)
        thumbnail_filename = f"thumb_{filename}"
        thumbnail_path = os.path.join(task_dir, thumbnail_filename)
        with open(thumbnail_path, "wb") as f:
            f.write(thumbnail_data)

        return filepath

    def _generate_single_image(
        self,
        page: Dict,
        task_id: str,
        reference_image: Optional[bytes] = None,
        retry_count: int = 0,
        full_outline: str = "",
        user_images: Optional[List[bytes]] = None,
        user_topic: str = ""
    ) -> Tuple[int, bool, Optional[str], Optional[str]]:
        """
        生成单张图片（带自动重试）

        Args:
            page: 页面数据
            task_id: 任务ID
            reference_image: 参考图片（封面图）
            retry_count: 当前重试次数
            full_outline: 完整的大纲文本
            user_images: 用户上传的参考图片列表
            user_topic: 用户原始输入

        Returns:
            (index, success, filename, error_message)
        """
        index = page["index"]
        page_type = page["type"]
        page_content = page["content"]

        try:
            logger.debug(f"生成图片 [{index}]: type={page_type}")

            # 封面专用链路：文本模型生成 TeX -> 本地编译 PNG
            if page_type == "cover":
                logger.info(f"封面页 [{index}] 使用 LaTeX 渲染链路")
                cover_png = self._generate_cover_via_latex(
                    page_content=page_content,
                    full_outline=full_outline,
                    user_topic=user_topic,
                )
                filename = f"{index}.png"
                self._save_image(cover_png, filename, self.current_task_dir)
                logger.info(f"✅ 封面 [{index}] LaTeX 渲染成功: {filename}")
                return (index, True, filename, None)

            # 根据配置选择模板（短 prompt 或完整 prompt）
            if self.use_short_prompt and self.prompt_template_short:
                # 短 prompt 模式：只包含页面类型和内容
                prompt = self.prompt_template_short.format(
                    page_content=page_content,
                    page_type=page_type
                )
                logger.debug(f"  使用短 prompt 模式 ({len(prompt)} 字符)")
            else:
                # 完整 prompt 模式：包含大纲和用户需求
                prompt = self.prompt_template.format(
                    page_content=page_content,
                    page_type=page_type,
                    full_outline=full_outline,
                    user_topic=user_topic if user_topic else "未提供"
                )

            # 调用生成器生成图片
            if self.provider_config.get('type') == 'google_genai':
                logger.debug(f"  使用 Google GenAI 生成器")
                image_data = self.generator.generate_image(
                    prompt=prompt,
                    aspect_ratio=self.provider_config.get('default_aspect_ratio', '3:4'),
                    temperature=self.provider_config.get('temperature', 1.0),
                    model=self.provider_config.get('model', 'gemini-3-pro-image-preview'),
                    reference_image=reference_image,
                )
            elif self.provider_config.get('type') == 'image_api':
                logger.debug(f"  使用 Image API 生成器")
                # Image API 支持多张参考图片
                # 组合参考图片：用户上传的图片 + 封面图
                reference_images = []
                if user_images:
                    reference_images.extend(user_images)
                if reference_image:
                    reference_images.append(reference_image)

                image_data = self.generator.generate_image(
                    prompt=prompt,
                    aspect_ratio=self.provider_config.get('default_aspect_ratio', '3:4'),
                    temperature=self.provider_config.get('temperature', 1.0),
                    model=self.provider_config.get('model', 'glm-image'),
                    reference_images=reference_images if reference_images else None,
                )
            else:
                logger.debug(f"  使用 OpenAI 兼容生成器")
                image_data = self.generator.generate_image(
                    prompt=prompt,
                    size=self.provider_config.get('default_size', '1024x1024'),
                    model=self.provider_config.get('model'),
                    quality=self.provider_config.get('quality', 'standard'),
                )

            # 保存图片（使用当前任务目录）
            filename = f"{index}.png"
            self._save_image(image_data, filename, self.current_task_dir)
            logger.info(f"✅ 图片 [{index}] 生成成功: {filename}")

            return (index, True, filename, None)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ 图片 [{index}] 生成失败: {error_msg[:200]}")
            return (index, False, None, error_msg)

    def generate_images(
        self,
        pages: list,
        task_id: str = None,
        full_outline: str = "",
        user_images: Optional[List[bytes]] = None,
        user_topic: str = ""
    ) -> Generator[Dict[str, Any], None, None]:
        """
        生成图片（生成器，支持 SSE 流式返回）
        优化版本：先生成封面，然后并发生成其他页面

        Args:
            pages: 页面列表
            task_id: 任务 ID（可选）
            full_outline: 完整的大纲文本（用于保持风格一致）
            user_images: 用户上传的参考图片列表（可选）
            user_topic: 用户原始输入（用于保持意图一致）

        Yields:
            进度事件字典
        """
        if task_id is None:
            task_id = f"task_{uuid.uuid4().hex[:8]}"

        logger.info(f"开始图片生成任务: task_id={task_id}, pages={len(pages)}")

        # 创建任务专属目录
        self.current_task_dir = os.path.join(self.history_root_dir, task_id)
        os.makedirs(self.current_task_dir, exist_ok=True)
        logger.debug(f"任务目录: {self.current_task_dir}")

        total = len(pages)
        generated_images = []
        failed_pages = []
        cover_image_data = None

        # 压缩用户上传的参考图到200KB以内（减少内存和传输开销）
        compressed_user_images = None
        if user_images:
            compressed_user_images = [compress_image(img, max_size_kb=200) for img in user_images]

        # 初始化任务状态
        self._task_states[task_id] = {
            "pages": pages,
            "generated": {},
            "failed": {},
            "cover_image": None,
            "full_outline": full_outline,
            "user_images": compressed_user_images,
            "user_topic": user_topic
        }

        # ==================== 第一阶段：生成封面 ====================
        cover_page = None
        other_pages = []

        for page in pages:
            if page["type"] == "cover":
                cover_page = page
            else:
                other_pages.append(page)

        # 如果没有封面，使用第一页作为封面
        if cover_page is None and len(pages) > 0:
            cover_page = pages[0]
            other_pages = pages[1:]

        if cover_page:
            # 发送封面生成进度
            yield {
                "event": "progress",
                "data": {
                    "index": cover_page["index"],
                    "status": "generating",
                    "message": "正在生成封面...",
                    "current": 1,
                    "total": total,
                    "phase": "cover"
                }
            }

            # 生成封面（使用用户上传的图片作为参考）
            index, success, filename, error = self._generate_single_image(
                cover_page, task_id, reference_image=None, full_outline=full_outline,
                user_images=compressed_user_images, user_topic=user_topic
            )

            if success:
                generated_images.append(filename)
                self._task_states[task_id]["generated"][index] = filename

                # 读取封面图片作为参考，并立即压缩到200KB以内
                cover_path = os.path.join(self.current_task_dir, filename)
                with open(cover_path, "rb") as f:
                    cover_image_data = f.read()

                # 压缩封面图（减少内存占用和后续传输开销）
                cover_image_data = compress_image(cover_image_data, max_size_kb=200)
                self._task_states[task_id]["cover_image"] = cover_image_data

                yield {
                    "event": "complete",
                    "data": {
                        "index": index,
                        "status": "done",
                        "image_url": f"/api/images/{task_id}/{filename}",
                        "phase": "cover"
                    }
                }
            else:
                failed_pages.append(cover_page)
                self._task_states[task_id]["failed"][index] = error

                yield {
                    "event": "error",
                    "data": {
                        "index": index,
                        "status": "error",
                        "message": error,
                        "retryable": True,
                        "phase": "cover"
                    }
                }

        # ==================== 第二阶段：生成其他页面 ====================
        if other_pages:
            # 检查是否启用高并发模式
            high_concurrency = self.provider_config.get('high_concurrency', False)

            if high_concurrency:
                # 高并发模式：并行生成
                yield {
                    "event": "progress",
                    "data": {
                        "status": "batch_start",
                        "message": f"开始并发生成 {len(other_pages)} 页内容...",
                        "current": len(generated_images),
                        "total": total,
                        "phase": "content"
                    }
                }

                # 使用线程池并发生成
                with ThreadPoolExecutor(max_workers=self.MAX_CONCURRENT) as executor:
                    # 提交所有任务
                    future_to_page = {
                        executor.submit(
                            self._generate_single_image,
                            page,
                            task_id,
                            cover_image_data,  # 使用封面作为参考
                            0,  # retry_count
                            full_outline,  # 传入完整大纲
                            compressed_user_images,  # 用户上传的参考图片（已压缩）
                            user_topic  # 用户原始输入
                        ): page
                        for page in other_pages
                    }

                    # 发送每个页面的进度
                    for page in other_pages:
                        yield {
                            "event": "progress",
                            "data": {
                                "index": page["index"],
                                "status": "generating",
                                "current": len(generated_images) + 1,
                                "total": total,
                                "phase": "content"
                            }
                        }

                    # 收集结果
                    for future in as_completed(future_to_page):
                        page = future_to_page[future]
                        try:
                            index, success, filename, error = future.result()

                            if success:
                                generated_images.append(filename)
                                self._task_states[task_id]["generated"][index] = filename

                                yield {
                                    "event": "complete",
                                    "data": {
                                        "index": index,
                                        "status": "done",
                                        "image_url": f"/api/images/{task_id}/{filename}",
                                        "phase": "content"
                                    }
                                }
                            else:
                                failed_pages.append(page)
                                self._task_states[task_id]["failed"][index] = error

                                yield {
                                    "event": "error",
                                    "data": {
                                        "index": index,
                                        "status": "error",
                                        "message": error,
                                        "retryable": True,
                                        "phase": "content"
                                    }
                                }

                        except Exception as e:
                            failed_pages.append(page)
                            error_msg = str(e)
                            self._task_states[task_id]["failed"][page["index"]] = error_msg

                            yield {
                                "event": "error",
                                "data": {
                                    "index": page["index"],
                                    "status": "error",
                                    "message": error_msg,
                                    "retryable": True,
                                    "phase": "content"
                                }
                            }
            else:
                # 顺序模式：逐个生成
                yield {
                    "event": "progress",
                    "data": {
                        "status": "batch_start",
                        "message": f"开始顺序生成 {len(other_pages)} 页内容...",
                        "current": len(generated_images),
                        "total": total,
                        "phase": "content"
                    }
                }

                for page in other_pages:
                    # 发送生成进度
                    yield {
                        "event": "progress",
                        "data": {
                            "index": page["index"],
                            "status": "generating",
                            "current": len(generated_images) + 1,
                            "total": total,
                            "phase": "content"
                        }
                    }

                    # 生成单张图片
                    index, success, filename, error = self._generate_single_image(
                        page,
                        task_id,
                        cover_image_data,
                        0,
                        full_outline,
                        compressed_user_images,
                        user_topic
                    )

                    if success:
                        generated_images.append(filename)
                        self._task_states[task_id]["generated"][index] = filename

                        yield {
                            "event": "complete",
                            "data": {
                                "index": index,
                                "status": "done",
                                "image_url": f"/api/images/{task_id}/{filename}",
                                "phase": "content"
                            }
                        }
                    else:
                        failed_pages.append(page)
                        self._task_states[task_id]["failed"][index] = error

                        yield {
                            "event": "error",
                            "data": {
                                "index": index,
                                "status": "error",
                                "message": error,
                                "retryable": True,
                                "phase": "content"
                            }
                        }

        # ==================== 完成 ====================
        yield {
            "event": "finish",
            "data": {
                "success": len(failed_pages) == 0,
                "task_id": task_id,
                "images": generated_images,
                "total": total,
                "completed": len(generated_images),
                "failed": len(failed_pages),
                "failed_indices": [p["index"] for p in failed_pages]
            }
        }

    def retry_single_image(
        self,
        task_id: str,
        page: Dict,
        use_reference: bool = True,
        full_outline: str = "",
        user_topic: str = ""
    ) -> Dict[str, Any]:
        """
        重试生成单张图片

        Args:
            task_id: 任务ID
            page: 页面数据
            use_reference: 是否使用封面作为参考
            full_outline: 完整大纲文本（从前端传入）
            user_topic: 用户原始输入（从前端传入）

        Returns:
            生成结果
        """
        self.current_task_dir = os.path.join(self.history_root_dir, task_id)
        os.makedirs(self.current_task_dir, exist_ok=True)

        reference_image = None
        user_images = None

        # 首先尝试从任务状态中获取上下文
        if task_id in self._task_states:
            task_state = self._task_states[task_id]
            if use_reference:
                reference_image = task_state.get("cover_image")
            # 如果没有传入上下文，则使用任务状态中的
            if not full_outline:
                full_outline = task_state.get("full_outline", "")
            if not user_topic:
                user_topic = task_state.get("user_topic", "")
            user_images = task_state.get("user_images")

        # 如果任务状态中没有封面图，尝试从文件系统加载
        if use_reference and reference_image is None:
            cover_path = os.path.join(self.current_task_dir, "0.png")
            if os.path.exists(cover_path):
                with open(cover_path, "rb") as f:
                    cover_data = f.read()
                # 压缩封面图到 200KB
                reference_image = compress_image(cover_data, max_size_kb=200)

        index, success, filename, error = self._generate_single_image(
            page,
            task_id,
            reference_image,
            0,
            full_outline,
            user_images,
            user_topic
        )

        if success:
            if task_id in self._task_states:
                self._task_states[task_id]["generated"][index] = filename
                if index in self._task_states[task_id]["failed"]:
                    del self._task_states[task_id]["failed"][index]

            return {
                "success": True,
                "index": index,
                "image_url": f"/api/images/{task_id}/{filename}"
            }
        else:
            return {
                "success": False,
                "index": index,
                "error": error,
                "retryable": True
            }

    def retry_failed_images(
        self,
        task_id: str,
        pages: List[Dict]
    ) -> Generator[Dict[str, Any], None, None]:
        """
        批量重试失败的图片

        Args:
            task_id: 任务ID
            pages: 需要重试的页面列表

        Yields:
            进度事件
        """
        # 获取参考图
        reference_image = None
        if task_id in self._task_states:
            reference_image = self._task_states[task_id].get("cover_image")

        total = len(pages)
        success_count = 0
        failed_count = 0

        yield {
            "event": "retry_start",
            "data": {
                "total": total,
                "message": f"开始重试 {total} 张失败的图片"
            }
        }

        # 并发重试
        # 从任务状态中获取完整大纲
        full_outline = ""
        if task_id in self._task_states:
            full_outline = self._task_states[task_id].get("full_outline", "")

        with ThreadPoolExecutor(max_workers=self.MAX_CONCURRENT) as executor:
            future_to_page = {
                executor.submit(
                    self._generate_single_image,
                    page,
                    task_id,
                    reference_image,
                    0,  # retry_count
                    full_outline  # 传入完整大纲
                ): page
                for page in pages
            }

            for future in as_completed(future_to_page):
                page = future_to_page[future]
                try:
                    index, success, filename, error = future.result()

                    if success:
                        success_count += 1
                        if task_id in self._task_states:
                            self._task_states[task_id]["generated"][index] = filename
                            if index in self._task_states[task_id]["failed"]:
                                del self._task_states[task_id]["failed"][index]

                        yield {
                            "event": "complete",
                            "data": {
                                "index": index,
                                "status": "done",
                                "image_url": f"/api/images/{task_id}/{filename}"
                            }
                        }
                    else:
                        failed_count += 1
                        yield {
                            "event": "error",
                            "data": {
                                "index": index,
                                "status": "error",
                                "message": error,
                                "retryable": True
                            }
                        }

                except Exception as e:
                    failed_count += 1
                    yield {
                        "event": "error",
                        "data": {
                            "index": page["index"],
                            "status": "error",
                            "message": str(e),
                            "retryable": True
                        }
                    }

        yield {
            "event": "retry_finish",
            "data": {
                "success": failed_count == 0,
                "total": total,
                "completed": success_count,
                "failed": failed_count
            }
        }

    def regenerate_image(
        self,
        task_id: str,
        page: Dict,
        use_reference: bool = True,
        full_outline: str = "",
        user_topic: str = ""
    ) -> Dict[str, Any]:
        """
        重新生成图片（用户手动触发，即使成功的也可以重新生成）

        Args:
            task_id: 任务ID
            page: 页面数据
            use_reference: 是否使用封面作为参考
            full_outline: 完整大纲文本
            user_topic: 用户原始输入

        Returns:
            生成结果
        """
        return self.retry_single_image(
            task_id, page, use_reference,
            full_outline=full_outline,
            user_topic=user_topic
        )

    def get_image_path(self, task_id: str, filename: str) -> str:
        """
        获取图片完整路径

        Args:
            task_id: 任务ID
            filename: 文件名

        Returns:
            完整路径
        """
        task_dir = os.path.join(self.history_root_dir, task_id)
        return os.path.join(task_dir, filename)

    def get_task_state(self, task_id: str) -> Optional[Dict]:
        """获取任务状态"""
        return self._task_states.get(task_id)

    def cleanup_task(self, task_id: str):
        """清理任务状态（释放内存）"""
        if task_id in self._task_states:
            del self._task_states[task_id]


# 全局服务实例
_service_instance = None

def get_image_service() -> ImageService:
    """获取全局图片生成服务实例"""
    global _service_instance
    if _service_instance is None:
        _service_instance = ImageService()
    return _service_instance

def reset_image_service():
    """重置全局服务实例（配置更新后调用）"""
    global _service_instance
    _service_instance = None
