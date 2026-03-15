"""
历史记录服务

负责管理绘本生成历史记录的存储、查询、更新和删除。
支持草稿、生成中、完成等多种状态流转。
"""

import os
import json
import io
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

from PIL import Image, ImageOps

from backend.utils.image_compressor import compress_image
from backend.utils.outline_utils import normalize_outline_payload


class RecordStatus:
    """历史记录状态常量"""
    DRAFT = "draft"          # 草稿：已创建大纲，未开始生成
    GENERATING = "generating"  # 生成中：正在生成图片
    PARTIAL = "partial"       # 部分完成：有部分图片生成
    COMPLETED = "completed"   # 已完成：所有图片已生成
    ERROR = "error"          # 错误：生成过程中出现错误


class HistoryService:
    TARGET_IMAGE_SIZE = (1242, 1660)

    def __init__(self):
        """
        初始化历史记录服务

        创建历史记录存储目录和索引文件
        """
        # 历史记录存储目录（项目根目录/history）
        self.history_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "history"
        )
        os.makedirs(self.history_dir, exist_ok=True)

        # 索引文件路径
        self.index_file = os.path.join(self.history_dir, "index.json")
        self._init_index()

    def _init_index(self) -> None:
        """
        初始化索引文件

        如果索引文件不存在，则创建一个空索引
        """
        if not os.path.exists(self.index_file):
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump({"records": []}, f, ensure_ascii=False, indent=2)

    def _load_index(self) -> Dict:
        """
        加载索引文件

        Returns:
            Dict: 索引数据，包含 records 列表
        """
        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"records": []}

    def _save_index(self, index: Dict) -> None:
        """
        保存索引文件

        Args:
            index: 索引数据
        """
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    def _get_record_path(self, record_id: str) -> str:
        """
        获取历史记录文件路径

        Args:
            record_id: 记录 ID

        Returns:
            str: 记录文件的完整路径
        """
        return os.path.join(self.history_dir, f"{record_id}.json")

    def _get_upload_task_id(self, record_id: str) -> str:
        return f"upload_{record_id.replace('-', '')}"

    def _normalize_uploaded_image(self, image_bytes: bytes) -> bytes:
        with Image.open(io.BytesIO(image_bytes)) as img:
            normalized = ImageOps.fit(
                img.convert("RGB"),
                self.TARGET_IMAGE_SIZE,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            output = io.BytesIO()
            normalized.save(output, format="PNG", optimize=True)
            return output.getvalue()

    def save_page_uploaded_image(self, record_id: str, image_bytes: bytes) -> Dict[str, str]:
        record = self.get_record(record_id)
        if not record:
            raise ValueError(f"历史记录不存在：{record_id}")

        task_id = self._get_upload_task_id(record_id)
        task_dir = os.path.join(self.history_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)

        filename = f"{uuid.uuid4().hex[:12]}.png"
        normalized = self._normalize_uploaded_image(image_bytes)
        filepath = os.path.join(task_dir, filename)
        with open(filepath, "wb") as f:
            f.write(normalized)

        thumbnail_path = os.path.join(task_dir, f"thumb_{filename}")
        with open(thumbnail_path, "wb") as f:
            f.write(compress_image(normalized, max_size_kb=50))

        return {
            "task_id": task_id,
            "filename": filename,
            "image_url": f"/api/images/{task_id}/{filename}?thumbnail=false",
        }

    def get_selected_cover_image_bytes(self, record_id: str) -> Optional[bytes]:
        record = self.get_record(record_id)
        if not record:
            return None

        selected_version_id = (record.get("selected_cover_version") or "").strip()
        versions = record.get("cover_versions") or []
        selected_version = next(
            (item for item in versions if isinstance(item, dict) and item.get("id") == selected_version_id),
            None,
        )
        if not selected_version:
            return None

        task_id = (selected_version.get("task_id") or "").strip()
        filename = (selected_version.get("image_filename") or "").strip()
        if not task_id or not filename:
            return None

        filepath = os.path.join(self.history_dir, task_id, filename)
        if not os.path.exists(filepath):
            return None

        with open(filepath, "rb") as f:
            return f.read()

    def _extract_cover_field(self, text: str, prefixes: List[str]) -> str:
        """从封面文本中按前缀提取字段值"""
        if not text:
            return ""
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            for prefix in prefixes:
                if line.startswith(prefix):
                    if "：" in line:
                        return line.split("：", 1)[1].strip()
                    if ":" in line:
                        return line.split(":", 1)[1].strip()
                    return ""
        return ""

    def _default_cover_spec(self, outline: Optional[Dict], topic: str) -> Dict[str, Any]:
        """
        根据大纲和主题生成默认封面结构化参数

        仅用于 Phase A 的基础数据模型，确保后续封面创作台可直接读取和编辑。
        """
        pages = (outline or {}).get("pages", []) if isinstance(outline, dict) else []
        cover_content = ""
        for page in pages:
            if page.get("type") == "cover":
                cover_content = page.get("content", "") or ""
                break
        title = self._extract_cover_field(cover_content, ["标题：", "主标题：", "标题:", "主标题:"])
        subtitle = self._extract_cover_field(cover_content, ["副标题：", "副标题:"])
        tag = self._extract_cover_field(cover_content, ["标签：", "标签:", "Tag：", "TAG："])
        top_badge = self._extract_cover_field(cover_content, ["顶部标签：", "胶囊标签："])

        hashtags: List[str] = []
        for raw_line in cover_content.splitlines():
            line = raw_line.strip()
            if line.startswith("#"):
                hashtags.append(line)

        if not title:
            title = (topic or "未命名封面").strip()
        if not subtitle:
            subtitle = "把生活调成静音模式"
        if not tag:
            tag = "@ 夏日氛围感"
        if not top_badge:
            top_badge = "建议收藏"
        if not hashtags:
            hashtags = ["#治愈系生活", "#夏日碎片收集", "#慢生活"]

        return {
            "title": title,
            "subtitle": subtitle,
            "tag": tag,
            "hashtags": hashtags[:3],
            "top_badge": top_badge,
            "footer_words": ["慢下来", "去生活", "爱自己"],
            "positions": {
                "title": {"x": 98, "y": 1040, "anchor": "west", "width": 860},
                "subtitle": {"x": 98, "y": 900, "anchor": "west", "width": 760},
                "tag": {"x": 110, "y": 620, "anchor": "west"},
                "hashtags": [
                    {"x": 110, "y": 500, "anchor": "west"},
                    {"x": 110, "y": 430, "anchor": "west"},
                    {"x": 110, "y": 360, "anchor": "west"},
                ],
                "top_badge": {"x": 960, "y": 1540, "anchor": "center"},
                "footer_words": [
                    {"x": 220, "y": 70, "anchor": "center"},
                    {"x": 620, "y": 70, "anchor": "center"},
                    {"x": 1020, "y": 70, "anchor": "center"},
                ],
            },
            "palette": {
                "background": ["#9FC5E8", "#A9CCE8", "#C7E0F4", "#D6EAF8"],
                "text_primary": "#1E4E79",
                "text_secondary": "#5D8AA8",
                "card_fill": "#EAF4FB",
                "badge_bg": "#1E4E79",
                "badge_text": "#EAF4FB",
            },
        }

    def _normalize_cover_spec(self, cover_spec: Any, outline: Optional[Dict], topic: str) -> Dict[str, Any]:
        """标准化封面结构化参数，缺省字段自动补齐"""
        base = self._default_cover_spec(outline, topic)
        if not isinstance(cover_spec, dict):
            return base

        merged = {**base, **cover_spec}
        merged["hashtags"] = (
            cover_spec.get("hashtags")
            if isinstance(cover_spec.get("hashtags"), list)
            else base["hashtags"]
        )
        merged["footer_words"] = (
            cover_spec.get("footer_words")
            if isinstance(cover_spec.get("footer_words"), list)
            else base["footer_words"]
        )
        merged["positions"] = (
            cover_spec.get("positions")
            if isinstance(cover_spec.get("positions"), dict)
            else base["positions"]
        )
        merged["palette"] = (
            cover_spec.get("palette")
            if isinstance(cover_spec.get("palette"), dict)
            else base["palette"]
        )
        return merged

    def _ensure_cover_fields(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """兼容旧记录：补齐 cover_spec / cover_versions / selected_cover_version"""
        outline = record.get("outline") if isinstance(record.get("outline"), dict) else {}
        topic = record.get("title", "")
        cover_spec = self._normalize_cover_spec(record.get("cover_spec"), outline, topic)
        record["cover_spec"] = cover_spec

        cover_versions = record.get("cover_versions")
        if not isinstance(cover_versions, list):
            cover_versions = []

        if not cover_versions:
            created_at = record.get("created_at") or datetime.now().isoformat()
            version_id = "v1"
            cover_versions = [
                {
                    "id": version_id,
                    "name": "初始封面",
                    "source": "outline",
                    "created_at": created_at,
                    "cover_spec": cover_spec,
                    "latex_code": record.get("cover_latex_code"),
                    "task_id": (record.get("images") or {}).get("task_id"),
                    "image_filename": None,
                }
            ]
        record["cover_versions"] = cover_versions

        selected_cover_version = record.get("selected_cover_version")
        if not selected_cover_version:
            selected_cover_version = cover_versions[0].get("id") if cover_versions else None
        record["selected_cover_version"] = selected_cover_version

        cover_latex_code = record.get("cover_latex_code")
        if not isinstance(cover_latex_code, str):
            cover_latex_code = ""
        if not cover_latex_code and selected_cover_version:
            selected_version = next(
                (item for item in cover_versions if isinstance(item, dict) and item.get("id") == selected_cover_version),
                None
            )
            if isinstance(selected_version, dict):
                cover_latex_code = str(selected_version.get("latex_code") or "")
        record["cover_latex_code"] = cover_latex_code
        return record

    def create_record(
        self,
        topic: str,
        outline: Dict,
        task_id: Optional[str] = None,
        cover_spec: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        创建新的历史记录

        初始状态为 draft（草稿），表示大纲已创建但尚未开始生成图片。

        Args:
            topic: 绘本主题/标题
            outline: 大纲内容，包含 pages 数组等信息
            task_id: 关联的生成任务 ID（可选）

        Returns:
            str: 新创建的记录 ID（UUID 格式）

        状态流转：
            新建 -> draft（草稿状态）
        """
        # 生成唯一记录 ID
        record_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        outline = normalize_outline_payload(outline)
        normalized_cover_spec = self._normalize_cover_spec(cover_spec, outline, topic)
        initial_cover_version_id = "v1"

        # 创建完整的记录对象
        record = {
            "id": record_id,
            "title": topic,
            "created_at": now,
            "updated_at": now,
            "outline": outline,  # 保存完整的大纲数据
            "images": {
                "task_id": task_id,
                "generated": []  # 初始无生成图片
            },
            "status": RecordStatus.DRAFT,  # 初始状态：草稿
            "thumbnail": None,  # 初始无缩略图
            "cover_spec": normalized_cover_spec,
            "cover_latex_code": "",
            "cover_versions": [
                {
                    "id": initial_cover_version_id,
                    "name": "初始封面",
                    "source": "outline",
                    "created_at": now,
                    "cover_spec": normalized_cover_spec,
                    "latex_code": "",
                    "task_id": task_id,
                    "image_filename": None,
                }
            ],
            "selected_cover_version": initial_cover_version_id,
        }

        # 保存完整记录到独立文件
        record_path = self._get_record_path(record_id)
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        # 更新索引（用于快速列表查询）
        index = self._load_index()
        index["records"].insert(0, {
            "id": record_id,
            "title": topic,
            "created_at": now,
            "updated_at": now,
            "status": RecordStatus.DRAFT,  # 索引中也记录状态
            "thumbnail": None,
            "page_count": len(outline.get("pages", [])),  # 预期页数
            "task_id": task_id
        })
        self._save_index(index)

        return record_id

    def get_record(self, record_id: str) -> Optional[Dict]:
        """
        获取历史记录详情

        Args:
            record_id: 记录 ID

        Returns:
            Optional[Dict]: 记录详情，如果不存在则返回 None

        返回数据包含：
            - id: 记录 ID
            - title: 标题
            - created_at: 创建时间
            - updated_at: 更新时间
            - outline: 大纲内容
            - images: 图片信息（task_id 和 generated 列表）
            - status: 当前状态
            - thumbnail: 缩略图文件名
        """
        record_path = self._get_record_path(record_id)

        if not os.path.exists(record_path):
            return None

        try:
            with open(record_path, "r", encoding="utf-8") as f:
                record = json.load(f)
                return self._ensure_cover_fields(record)
        except Exception:
            return None

    def record_exists(self, record_id: str) -> bool:
        """
        检查历史记录是否存在

        Args:
            record_id: 记录 ID

        Returns:
            bool: 记录是否存在
        """
        record_path = self._get_record_path(record_id)
        return os.path.exists(record_path)

    def update_record(
        self,
        record_id: str,
        outline: Optional[Dict] = None,
        images: Optional[Dict] = None,
        status: Optional[str] = None,
        thumbnail: Optional[str] = None,
        cover_spec: Optional[Dict[str, Any]] = None,
        cover_latex_code: Optional[str] = None,
        cover_versions: Optional[List[Dict[str, Any]]] = None,
        selected_cover_version: Optional[str] = None,
    ) -> bool:
        """
        更新历史记录

        支持部分更新，只更新提供的字段。
        每次更新都会自动刷新 updated_at 时间戳。

        Args:
            record_id: 记录 ID
            outline: 大纲内容（可选，用于修改大纲）
            images: 图片信息（可选，包含 task_id 和 generated 列表）
            status: 状态（可选）
            thumbnail: 缩略图文件名（可选）

        Returns:
            bool: 更新是否成功，记录不存在时返回 False

        状态流转说明：
            draft -> generating: 开始生成图片
            generating -> partial: 部分图片生成完成
            generating -> completed: 所有图片生成完成
            generating -> error: 生成过程出错
            partial -> generating: 继续生成剩余图片
            partial -> completed: 剩余图片生成完成
        """
        # 获取现有记录
        record = self.get_record(record_id)
        if not record:
            return False
        record = self._ensure_cover_fields(record)

        # 更新时间戳
        now = datetime.now().isoformat()
        record["updated_at"] = now

        # 更新大纲内容（支持修改大纲）
        if outline is not None:
            outline = normalize_outline_payload(outline)
            record["outline"] = outline

        # 更新图片信息
        if images is not None:
            record["images"] = images

        # 更新状态（状态流转）
        if status is not None:
            record["status"] = status

        # 更新缩略图
        if thumbnail is not None:
            record["thumbnail"] = thumbnail

        # 更新封面结构化参数
        if cover_spec is not None:
            current_outline = record.get("outline") if isinstance(record.get("outline"), dict) else {}
            record["cover_spec"] = self._normalize_cover_spec(cover_spec, current_outline, record.get("title", ""))

        if cover_latex_code is not None:
            record["cover_latex_code"] = str(cover_latex_code)

        # 更新封面版本列表
        if cover_versions is not None:
            normalized_versions: List[Dict[str, Any]] = []
            current_outline = record.get("outline") if isinstance(record.get("outline"), dict) else {}
            for idx, version in enumerate(cover_versions):
                if not isinstance(version, dict):
                    continue
                version_id = str(version.get("id") or f"v{idx + 1}")
                version_cover_spec = self._normalize_cover_spec(
                    version.get("cover_spec"), current_outline, record.get("title", "")
                )
                normalized_versions.append({
                    "id": version_id,
                    "name": version.get("name") or f"封面版本 {idx + 1}",
                    "source": version.get("source") or "manual",
                    "created_at": version.get("created_at") or now,
                    "cover_spec": version_cover_spec,
                    "latex_code": str(version.get("latex_code") or ""),
                    "task_id": version.get("task_id") or (record.get("images") or {}).get("task_id"),
                    "image_filename": version.get("image_filename"),
                })
            record["cover_versions"] = normalized_versions

        # 更新选中版本
        if selected_cover_version is not None:
            record["selected_cover_version"] = selected_cover_version

        # 若已选版本存在，自动同步顶层 cover_spec 到选中版本
        selected_id = record.get("selected_cover_version")
        if selected_id and isinstance(record.get("cover_versions"), list):
            selected_version = next(
                (v for v in record["cover_versions"] if v.get("id") == selected_id),
                None
            )
            if selected_version and isinstance(selected_version.get("cover_spec"), dict):
                record["cover_spec"] = selected_version["cover_spec"]
                record["cover_latex_code"] = str(selected_version.get("latex_code") or record.get("cover_latex_code") or "")

        # 保存完整记录
        record_path = self._get_record_path(record_id)
        with open(record_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        # 同步更新索引
        index = self._load_index()
        for idx_record in index["records"]:
            if idx_record["id"] == record_id:
                idx_record["updated_at"] = now

                # 更新状态
                if status:
                    idx_record["status"] = status

                # 更新缩略图
                if thumbnail:
                    idx_record["thumbnail"] = thumbnail

                # 更新页数（如果大纲被修改）
                if outline:
                    idx_record["page_count"] = len(outline.get("pages", []))

                # 更新任务 ID
                if images is not None and images.get("task_id"):
                    idx_record["task_id"] = images.get("task_id")

                break

        self._save_index(index)
        return True

    def delete_record(self, record_id: str) -> bool:
        """
        删除历史记录

        会同时删除：
        1. 记录 JSON 文件
        2. 关联的任务图片目录
        3. 索引中的记录

        Args:
            record_id: 记录 ID

        Returns:
            bool: 删除是否成功，记录不存在时返回 False
        """
        record = self.get_record(record_id)
        if not record:
            return False

        # 删除关联的任务图片目录
        if record.get("images") and record["images"].get("task_id"):
            task_id = record["images"]["task_id"]
            task_dir = os.path.join(self.history_dir, task_id)
            if os.path.exists(task_dir) and os.path.isdir(task_dir):
                try:
                    import shutil
                    shutil.rmtree(task_dir)
                    print(f"已删除任务目录: {task_dir}")
                except Exception as e:
                    print(f"删除任务目录失败: {task_dir}, {e}")

        upload_task_dir = os.path.join(self.history_dir, self._get_upload_task_id(record_id))
        if os.path.exists(upload_task_dir) and os.path.isdir(upload_task_dir):
            try:
                import shutil
                shutil.rmtree(upload_task_dir)
                print(f"已删除上传素材目录: {upload_task_dir}")
            except Exception as e:
                print(f"删除上传素材目录失败: {upload_task_dir}, {e}")

        # 删除记录 JSON 文件
        record_path = self._get_record_path(record_id)
        try:
            os.remove(record_path)
        except Exception:
            return False

        # 从索引中移除
        index = self._load_index()
        index["records"] = [r for r in index["records"] if r["id"] != record_id]
        self._save_index(index)

        return True

    def list_records(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None
    ) -> Dict:
        """
        分页获取历史记录列表

        Args:
            page: 页码，从 1 开始
            page_size: 每页记录数
            status: 状态过滤（可选），支持：draft/generating/partial/completed/error

        Returns:
            Dict: 分页结果
                - records: 当前页的记录列表
                - total: 总记录数
                - page: 当前页码
                - page_size: 每页大小
                - total_pages: 总页数
        """
        index = self._load_index()
        records = index.get("records", [])

        # 按状态过滤
        if status:
            records = [r for r in records if r.get("status") == status]

        # 分页计算
        total = len(records)
        start = (page - 1) * page_size
        end = start + page_size
        page_records = records[start:end]

        return {
            "records": page_records,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size
        }

    def search_records(self, keyword: str) -> List[Dict]:
        """
        根据关键词搜索历史记录

        Args:
            keyword: 搜索关键词（不区分大小写）

        Returns:
            List[Dict]: 匹配的记录列表（按创建时间倒序）
        """
        index = self._load_index()
        records = index.get("records", [])

        # 不区分大小写的标题搜索
        keyword_lower = keyword.lower()
        results = [
            r for r in records
            if keyword_lower in r.get("title", "").lower()
        ]

        return results

    def get_statistics(self) -> Dict:
        """
        获取历史记录统计信息

        Returns:
            Dict: 统计数据
                - total: 总记录数
                - by_status: 各状态的记录数
                    - draft: 草稿数
                    - generating: 生成中数
                    - partial: 部分完成数
                    - completed: 已完成数
                    - error: 错误数
        """
        index = self._load_index()
        records = index.get("records", [])

        total = len(records)
        status_count = {}

        # 统计各状态的记录数
        for record in records:
            status = record.get("status", RecordStatus.DRAFT)
            status_count[status] = status_count.get(status, 0) + 1

        return {
            "total": total,
            "by_status": status_count
        }

    def scan_and_sync_task_images(self, task_id: str) -> Dict[str, Any]:
        """
        扫描任务文件夹，同步图片列表

        根据实际生成的图片数量自动更新记录状态：
        - 无图片 -> draft（草稿）
        - 部分图片 -> partial（部分完成）
        - 全部图片 -> completed（已完成）

        Args:
            task_id: 任务 ID

        Returns:
            Dict[str, Any]: 扫描结果
                - success: 是否成功
                - record_id: 关联的记录 ID
                - task_id: 任务 ID
                - images_count: 图片数量
                - images: 图片文件名列表
                - status: 更新后的状态
                - error: 错误信息（失败时）
        """
        task_dir = os.path.join(self.history_dir, task_id)

        if not os.path.exists(task_dir) or not os.path.isdir(task_dir):
            return {
                "success": False,
                "error": f"任务目录不存在: {task_id}"
            }

        try:
            # 扫描目录下所有图片文件（排除缩略图）
            image_files = []
            for filename in os.listdir(task_dir):
                # 跳过缩略图文件（以 thumb_ 开头）
                if filename.startswith('thumb_'):
                    continue
                if filename.endswith('.png') or filename.endswith('.jpg') or filename.endswith('.jpeg'):
                    image_files.append(filename)

            # 按文件名排序（数字排序）
            def get_index(filename):
                try:
                    return int(filename.split('.')[0])
                except:
                    return 999

            image_files.sort(key=get_index)

            # 查找关联的历史记录
            index = self._load_index()
            record_id = None
            for rec in index.get("records", []):
                # 通过遍历所有记录，找到 task_id 匹配的记录
                record_detail = self.get_record(rec["id"])
                if record_detail and record_detail.get("images", {}).get("task_id") == task_id:
                    record_id = rec["id"]
                    break

            if record_id:
                # 更新历史记录
                record = self.get_record(record_id)
                if record:
                    # 根据生成图片数量判断状态
                    expected_count = len(record.get("outline", {}).get("pages", []))
                    actual_count = len(image_files)

                    if actual_count == 0:
                        status = RecordStatus.DRAFT  # 无图片：草稿
                    elif actual_count >= expected_count:
                        status = RecordStatus.COMPLETED  # 全部完成
                    else:
                        status = RecordStatus.PARTIAL  # 部分完成

                    # 更新图片列表和状态
                    self.update_record(
                        record_id,
                        images={
                            "task_id": task_id,
                            "generated": image_files
                        },
                        status=status,
                        thumbnail=image_files[0] if image_files else None
                    )

                    return {
                        "success": True,
                        "record_id": record_id,
                        "task_id": task_id,
                        "images_count": len(image_files),
                        "images": image_files,
                        "status": status
                    }

            # 没有关联的记录，返回扫描结果
            return {
                "success": True,
                "task_id": task_id,
                "images_count": len(image_files),
                "images": image_files,
                "no_record": True
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"扫描任务失败: {str(e)}"
            }

    def scan_all_tasks(self) -> Dict[str, Any]:
        """
        扫描所有任务文件夹，同步图片列表

        批量扫描 history 目录下的所有任务文件夹，
        同步图片列表并更新记录状态。

        Returns:
            Dict[str, Any]: 扫描结果统计
                - success: 是否成功
                - total_tasks: 扫描的任务总数
                - synced: 成功同步的任务数
                - failed: 失败的任务数
                - orphan_tasks: 孤立任务列表（有图片但无记录）
                - results: 详细结果列表
                - error: 错误信息（失败时）
        """
        if not os.path.exists(self.history_dir):
            return {
                "success": False,
                "error": "历史记录目录不存在"
            }

        try:
            synced_count = 0
            failed_count = 0
            orphan_tasks = []  # 没有关联记录的任务
            results = []

            # 遍历 history 目录
            for item in os.listdir(self.history_dir):
                item_path = os.path.join(self.history_dir, item)

                # 只处理目录（任务文件夹）
                if not os.path.isdir(item_path):
                    continue

                # 假设任务文件夹名就是 task_id
                task_id = item

                # 扫描并同步
                result = self.scan_and_sync_task_images(task_id)
                results.append(result)

                if result.get("success"):
                    if result.get("no_record"):
                        orphan_tasks.append(task_id)
                    else:
                        synced_count += 1
                else:
                    failed_count += 1

            return {
                "success": True,
                "total_tasks": len(results),
                "synced": synced_count,
                "failed": failed_count,
                "orphan_tasks": orphan_tasks,
                "results": results
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"扫描所有任务失败: {str(e)}"
            }


_service_instance = None


def get_history_service() -> HistoryService:
    """
    获取历史记录服务实例（单例模式）

    Returns:
        HistoryService: 历史记录服务实例
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = HistoryService()
    return _service_instance
