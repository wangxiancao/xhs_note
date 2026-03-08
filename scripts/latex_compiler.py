#!/usr/bin/env python3
"""
LaTeX 编译工具类
将 LaTeX 代码编译为 PDF，并转换为 PNG 图片

使用方法:
    from latex_compiler import LaTeXCompiler

    compiler = LaTeXCompiler()
    result = compiler.compile_and_preview(latex_code)
    if result.success:
        print(f"PNG base64: {result.png_base64[:50]}...")
"""

import base64
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from pdf2image import convert_from_path


@dataclass
class CompilationResult:
    """LaTeX 编译结果"""
    success: bool
    pdf_path: Optional[Path] = None
    png_path: Optional[Path] = None
    png_base64: Optional[str] = None
    error_message: Optional[str] = None
    compilation_time: float = 0.0


class LaTeXCompiler:
    """LaTeX 编译工具类"""

    # xelatex 路径 (TeX Live 2025)
    XELATEX_PATH = "/usr/local/texlive/2024/bin/x86_64-linux/xelatex"

    # 默认编译超时时间 (秒)
    DEFAULT_TIMEOUT = 30

    # 输出目录
    OUTPUT_DIR = Path(__file__).parent / "generated_covers"

    def __init__(self, output_dir: Optional[Path] = None):
        """
        初始化编译器

        Args:
            output_dir: 输出目录，默认为 scripts/generated_covers
        """
        self.output_dir = output_dir or self.OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def compile_to_pdf(
        self,
        latex_code: str,
        working_dir: Optional[Path] = None,
        timeout: int = DEFAULT_TIMEOUT
    ) -> Tuple[bool, Optional[Path], Optional[str]]:
        """
        将 LaTeX 代码编译为 PDF

        Args:
            latex_code: LaTeX 源代码
            working_dir: 工作目录 (None 则使用临时目录)
            timeout: 编译超时时间 (秒)

        Returns:
            (success, pdf_path, error_message)
        """
        cleanup = working_dir is None
        temp_dir = None

        try:
            if working_dir:
                work_path = working_dir
            else:
                temp_dir = tempfile.TemporaryDirectory()
                work_path = Path(temp_dir.name)

            # 写入 LaTeX 源文件
            tex_file = work_path / "cover.tex"
            tex_file.write_text(latex_code, encoding="utf-8")

            # 运行 xelatex
            env = os.environ.copy()
            env["PATH"] = f"{os.path.dirname(self.XELATEX_PATH)}:{env.get('PATH', '')}"

            result = subprocess.run(
                [
                    self.XELATEX_PATH,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-output-directory", str(work_path),
                    str(tex_file)
                ],
                cwd=str(work_path),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env
            )

            pdf_path = work_path / "cover.pdf"

            if pdf_path.exists():
                return (True, pdf_path, None)
            else:
                # 解析错误信息
                log_file = work_path / "cover.log"
                error_msg = self._parse_latex_error(log_file) if log_file.exists() else result.stdout[-2000:]
                return (False, None, error_msg)

        except subprocess.TimeoutExpired:
            return (False, None, f"Compilation timeout ({timeout}s)")
        except Exception as e:
            return (False, None, str(e))
        finally:
            if cleanup and temp_dir:
                temp_dir.cleanup()

    def pdf_to_png(
        self,
        pdf_path: Path,
        dpi: int = 150
    ) -> Tuple[bool, Optional[Path], Optional[str]]:
        """
        将 PDF 转换为 PNG

        Args:
            pdf_path: PDF 文件路径
            dpi: 图片分辨率

        Returns:
            (success, png_path, error_message)
        """
        try:
            # 使用 pdf2image 转换
            images = convert_from_path(
                str(pdf_path),
                dpi=dpi,
                first_page=1,
                last_page=1
            )

            if not images:
                return (False, None, "No pages found in PDF")

            # 保存 PNG
            png_path = pdf_path.with_suffix(".png")
            images[0].save(png_path, "PNG")

            return (True, png_path, None)

        except Exception as e:
            return (False, None, str(e))

    def compile_and_preview(
        self,
        latex_code: str
    ) -> CompilationResult:
        """
        完整编译流程: LaTeX -> PDF -> PNG (base64)
        用于预览功能

        Args:
            latex_code: LaTeX 源代码

        Returns:
            CompilationResult 包含 base64 编码的 PNG
        """
        start_time = time.time()

        with tempfile.TemporaryDirectory() as temp_dir:
            work_path = Path(temp_dir)

            # 编译 PDF
            success, pdf_path, error = self.compile_to_pdf(latex_code, work_path)
            if not success:
                return CompilationResult(
                    success=False,
                    error_message=error,
                    compilation_time=time.time() - start_time
                )

            # 转换为 PNG
            success, png_path, error = self.pdf_to_png(pdf_path)
            if not success:
                return CompilationResult(
                    success=False,
                    error_message=error,
                    compilation_time=time.time() - start_time
                )

            # 读取并编码为 base64
            png_base64 = base64.b64encode(png_path.read_bytes()).decode("utf-8")

            return CompilationResult(
                success=True,
                png_base64=png_base64,
                compilation_time=time.time() - start_time
            )

    def compile_and_save(
        self,
        latex_code: str,
        filename: str,
        output_dir: Optional[Path] = None,
        save_pdf: bool = False,
    ) -> CompilationResult:
        """
        编译并保存到服务器
        目录结构: generated_covers/YYYY-MM/filename.png

        Args:
            latex_code: LaTeX 源代码
            filename: 文件名 (不含扩展名)
            output_dir: 输出目录 (None 则使用默认)
            save_pdf: 是否额外保存 PDF 文件（默认 False）

        Returns:
            CompilationResult 包含保存的文件路径
        """
        start_time = time.time()

        # 安全处理文件名
        safe_filename = self._sanitize_filename(filename)
        if not safe_filename:
            return CompilationResult(
                success=False,
                error_message="Invalid filename"
            )

        # 创建按日期分组的输出目录
        date_dir = datetime.now().strftime("%Y-%m")
        save_dir = (output_dir or self.output_dir) / date_dir
        save_dir.mkdir(parents=True, exist_ok=True)

        # 在临时目录中编译
        with tempfile.TemporaryDirectory() as temp_dir:
            work_path = Path(temp_dir)

            # 编译 PDF
            success, pdf_path, error = self.compile_to_pdf(latex_code, work_path)
            if not success:
                return CompilationResult(
                    success=False,
                    error_message=error,
                    compilation_time=time.time() - start_time
                )

            # 转换为 PNG
            success, png_path, error = self.pdf_to_png(pdf_path)
            if not success:
                return CompilationResult(
                    success=False,
                    error_message=error,
                    compilation_time=time.time() - start_time
                )

            # 复制到输出目录（默认仅保存 PNG）
            import shutil

            final_png = save_dir / f"{safe_filename}.png"
            final_pdf: Optional[Path] = None

            shutil.copy2(png_path, final_png)
            if save_pdf:
                final_pdf = save_dir / f"{safe_filename}.pdf"
                shutil.copy2(pdf_path, final_pdf)

            return CompilationResult(
                success=True,
                pdf_path=final_pdf,
                png_path=final_png,
                compilation_time=time.time() - start_time
            )

    def _parse_latex_error(self, log_path: Path) -> str:
        """
        从 LaTeX 日志文件中解析错误信息

        Args:
            log_path: .log 文件路径

        Returns:
            格式化的错误信息
        """
        try:
            log_content = log_path.read_text(encoding="utf-8", errors="ignore")

            # 查找错误行
            errors = []

            # 匹配 "! ..." 格式的错误
            error_pattern = r"^! (.+)$"
            for match in re.finditer(error_pattern, log_content, re.MULTILINE):
                errors.append(match.group(1))

            # 匹配 "l.XXX" 格式的行号信息
            line_pattern = r"^l\.(\d+)"
            line_info = re.search(line_pattern, log_content, re.MULTILINE)

            if errors:
                msg = errors[0]
                if line_info:
                    msg += f" (line {line_info.group(1)})"
                return msg

            # 如果没有找到明确错误，返回最后的错误上下文
            if "Emergency stop" in log_content:
                return "Emergency stop - check LaTeX syntax"

            return "LaTeX compilation failed"

        except Exception:
            return "Unknown LaTeX error"

    def _sanitize_filename(self, filename: str) -> str:
        """
        清理文件名，移除危险字符

        Args:
            filename: 原始文件名

        Returns:
            安全的文件名
        """
        # 移除路径分隔符和特殊字符
        safe = re.sub(r'[^\w\u4e00-\u9fff\-_]', '', filename)
        # 限制长度
        return safe[:100] if safe else ""


# 模板管理
class TemplateManager:
    """LaTeX 模板管理器"""

    TEMPLATES_DIR = Path(__file__).parent / "latex_templates"

    # 模板元数据
    TEMPLATE_INFO = {
        "classic": {
            "name": "博朗经典",
            "description": "温暖米色配橙色点缀",
            "preview_color": "#F5F0E8"
        },
        "melon": {
            "name": "青提甜瓜",
            "description": "清新自然的绿色调",
            "preview_color": "#E8F5E9"
        },
        "ocean": {
            "name": "海盐冰淇淋",
            "description": "清爽的海洋蓝色",
            "preview_color": "#E3F2FD"
        }
    }

    @classmethod
    def list_templates(cls) -> list[dict]:
        """
        获取所有可用模板列表

        Returns:
            模板信息列表
        """
        templates = []
        for template_id, info in cls.TEMPLATE_INFO.items():
            template_path = cls.TEMPLATES_DIR / f"{template_id}.tex"
            if template_path.exists():
                templates.append({
                    "id": template_id,
                    "name": info["name"],
                    "description": info["description"],
                    "preview_color": info["preview_color"]
                })
        return templates

    @classmethod
    def get_template(cls, template_id: str) -> Optional[str]:
        """
        获取模板内容

        Args:
            template_id: 模板 ID

        Returns:
            模板内容，如果不存在返回 None
        """
        template_path = cls.TEMPLATES_DIR / f"{template_id}.tex"
        if template_path.exists():
            return template_path.read_text(encoding="utf-8")
        return None


if __name__ == "__main__":
    # 测试编译器
    compiler = LaTeXCompiler()

    test_code = r"""
\documentclass[preview,border=0pt]{standalone}
\usepackage{ctex}
\begin{document}
测试中文编译
\end{document}
"""

    print("Testing LaTeX compilation...")
    result = compiler.compile_and_preview(test_code)

    if result.success:
        print(f"Success! Compilation time: {result.compilation_time:.2f}s")
        print(f"PNG base64 length: {len(result.png_base64)} chars")
    else:
        print(f"Failed: {result.error_message}")
