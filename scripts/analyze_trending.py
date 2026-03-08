#!/usr/bin/env python3
"""
小红书热门内容分析脚本
分析 xiaohongshu-mcp 搜索结果，提取热门内容特征

使用方法:
    python scripts/analyze_trending.py
    # 按终端提示输入 JSON 路径、关键词、输出路径等信息
"""

import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


@dataclass
class FeedStats:
    """帖子统计数据"""
    total_count: int = 0
    skipped_video_count: int = 0
    skipped_non_note_count: int = 0
    likes: list = None
    collects: list = None
    comments: list = None
    titles: list = None
    contents: list = None
    nicknames: list = None

    def __post_init__(self):
        if self.likes is None:
            self.likes = []
        if self.collects is None:
            self.collects = []
        if self.comments is None:
            self.comments = []
        if self.titles is None:
            self.titles = []
        if self.contents is None:
            self.contents = []
        if self.nicknames is None:
            self.nicknames = []


def parse_number(text: str) -> int:
    """解析数字文本，支持万、k等单位"""
    if not text:
        return 0

    text = str(text).strip().lower()
    text = text.replace('+', '')

    try:
        if '万' in text:
            return int(float(text.replace('万', '')) * 10000)
        elif 'w' in text:
            return int(float(text.replace('w', '')) * 10000)
        elif 'k' in text:
            return int(float(text.replace('k', '')) * 1000)
        else:
            return int(float(text))
    except (ValueError, TypeError):
        return 0


def normalize_text(text: str) -> str:
    """清洗文本中的多余空白"""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def extract_title(feed: dict) -> str:
    """提取帖子标题，兼容多种返回格式"""
    if not isinstance(feed, dict):
        return ""
    note_card = feed.get("noteCard", {}) if isinstance(feed.get("noteCard"), dict) else {}
    candidates = [
        note_card.get("displayTitle"),
        note_card.get("title"),
        feed.get("title"),
        feed.get("note_title"),
        feed.get("display_title"),
    ]
    for item in candidates:
        title = normalize_text(item)
        if title:
            return title
    return ""


def _extract_rich_text_text(value: Any) -> str:
    """从富文本结构中抽取纯文本"""
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, list):
        texts: list[str] = []
        for part in value:
            if isinstance(part, str):
                if normalize_text(part):
                    texts.append(normalize_text(part))
            elif isinstance(part, dict):
                text = normalize_text(
                    part.get("text")
                    or part.get("content")
                    or part.get("value")
                    or ""
                )
                if text:
                    texts.append(text)
        return normalize_text(" ".join(texts))
    if isinstance(value, dict):
        return normalize_text(
            value.get("text")
            or value.get("content")
            or value.get("desc")
            or value.get("description")
            or ""
        )
    return ""


def extract_content(feed: dict) -> str:
    """提取帖子正文内容，兼容 noteCard 与通用字段"""
    if not isinstance(feed, dict):
        return ""
    note_card = feed.get("noteCard", {}) if isinstance(feed.get("noteCard"), dict) else {}

    candidates = [
        note_card.get("desc"),
        note_card.get("description"),
        note_card.get("displayDesc"),
        note_card.get("content"),
        note_card.get("noteContent"),
        note_card.get("noteDesc"),
        note_card.get("richText"),
        feed.get("desc"),
        feed.get("description"),
        feed.get("content"),
        feed.get("note_content"),
    ]
    for item in candidates:
        content = _extract_rich_text_text(item)
        if content:
            return content
    return ""


def is_video_feed(feed: dict) -> bool:
    """判断是否为视频帖子，视频帖子在分析中跳过"""
    if not isinstance(feed, dict):
        return False

    model_type = normalize_text(feed.get("modelType")).lower()
    if "video" in model_type:
        return True

    note_card = feed.get("noteCard", {}) if isinstance(feed.get("noteCard"), dict) else {}
    type_candidates = [
        note_card.get("type"),
        note_card.get("noteType"),
        note_card.get("mediaType"),
        feed.get("type"),
        feed.get("noteType"),
    ]
    for type_value in type_candidates:
        lowered = normalize_text(type_value).lower()
        if lowered and ("video" in lowered or "视频" in lowered):
            return True

    # 兜底：存在视频对象时视为视频帖
    video_fields = ["video", "videoInfo", "videoMedia", "videoDetail", "stream"]
    return any(note_card.get(field) for field in video_fields)


def extract_keywords(titles: list[str], min_length: int = 2) -> Counter:
    """从标题中提取关键词"""
    # 停用词列表
    stopwords = {
        '的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一',
        '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有',
        '看', '好', '自己', '这', '那', '她', '他', '它', '什么', '怎么', '为什么',
        '这个', '那个', '这些', '那些', '可以', '能', '让', '被', '把', '给',
    }

    keywords = Counter()

    for title in titles:
        if not title:
            continue

        # 移除 emoji 和特殊字符
        title_clean = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]', ' ', title)

        # 分词（简单按空格和标点分割）
        words = re.findall(r'[\u4e00-\u9fa5]{2,}|[a-zA-Z]{3,}', title_clean)

        for word in words:
            word = word.strip()
            if len(word) >= min_length and word not in stopwords:
                keywords[word] += 1

    return keywords


def analyze_data(data: list[dict] | dict) -> FeedStats:
    """分析搜索结果数据"""
    stats = FeedStats()

    # 处理不同的数据格式
    feeds = []
    if isinstance(data, dict):
        if 'data' in data:
            feeds = data['data']
        elif 'feeds' in data:
            feeds = data['feeds']
        elif 'items' in data:
            feeds = data['items']
        else:
            feeds = [data]
    elif isinstance(data, list):
        feeds = data

    for feed in feeds:
        # 跳过非笔记类型（如 rec_query / ad 等）
        model_type = normalize_text(feed.get("modelType")).lower()
        if model_type and model_type != "note":
            stats.skipped_non_note_count += 1
            continue

        # 跳过视频帖子，仅分析图文类帖子
        if is_video_feed(feed):
            stats.skipped_video_count += 1
            continue

        # 提取标题 - 支持多种格式
        title = extract_title(feed)
        stats.titles.append(title or "（无标题）")

        # 提取正文内容 - 支持多种格式
        content = extract_content(feed)
        stats.contents.append(content)

        # 提取互动数据 - 支持多种格式
        like_count = 0
        collect_count = 0
        comment_count = 0

        # xiaohongshu-mcp 格式: feeds[].noteCard.interactInfo
        if 'noteCard' in feed and 'interactInfo' in feed['noteCard']:
            interact = feed['noteCard']['interactInfo']
            like_count = parse_number(interact.get('likedCount', '0'))
            collect_count = parse_number(interact.get('collectedCount', '0'))
            comment_count = parse_number(interact.get('commentCount', '0'))
        else:
            # 其他格式
            like_count = feed.get('like_count') or feed.get('likes') or feed.get('liked_count', 0)
            if isinstance(like_count, str):
                like_count = parse_number(like_count)

            collect_count = feed.get('collect_count') or feed.get('collects') or feed.get('collected_count', 0)
            if isinstance(collect_count, str):
                collect_count = parse_number(collect_count)

            comment_count = feed.get('comment_count') or feed.get('comments', 0)
            if isinstance(comment_count, str):
                comment_count = parse_number(comment_count)

        stats.likes.append(like_count)
        stats.collects.append(collect_count)
        stats.comments.append(comment_count)

        # 提取作者 - 支持多种格式
        nickname = ''
        if 'noteCard' in feed and 'user' in feed['noteCard']:
            nickname = feed['noteCard']['user'].get('nickname', '') or feed['noteCard']['user'].get('nickName', '')
        elif 'author' in feed:
            nickname = feed['author'].get('nickname', '')
        elif 'user' in feed:
            nickname = feed['user'].get('nickname', '') or feed['user'].get('name', '')
        elif 'nickname' in feed:
            nickname = feed['nickname']
        if nickname:
            stats.nicknames.append(nickname)

        stats.total_count += 1

    return stats


def generate_report(stats: FeedStats, keywords: Counter, output_path: str, keyword: str = "") -> str:
    """生成 Markdown 分析报告"""

    # 计算统计数据
    avg_likes = sum(stats.likes) / len(stats.likes) if stats.likes else 0
    avg_collects = sum(stats.collects) / len(stats.collects) if stats.collects else 0
    avg_comments = sum(stats.comments) / len(stats.comments) if stats.comments else 0

    max_likes = max(stats.likes) if stats.likes else 0
    max_collects = max(stats.collects) if stats.collects else 0
    max_comments = max(stats.comments) if stats.comments else 0

    # 按点赞数排序，获取 Top 帖子
    title_like_pairs = list(zip(stats.titles, stats.likes, stats.collects, stats.comments))
    top_by_likes = sorted(title_like_pairs, key=lambda x: x[1], reverse=True)[:10]
    top_content_by_likes = sorted(
        list(zip(stats.titles, stats.contents, stats.likes)),
        key=lambda x: x[2],
        reverse=True,
    )[:10]

    # 计算互动率 (收藏/点赞比)
    collect_rate = (sum(stats.collects) / sum(stats.likes) * 100) if sum(stats.likes) > 0 else 0

    report = f"""# 小红书热门内容分析报告

> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
> 搜索关键词: {keyword or '未指定'}
> 分析帖子数: {stats.total_count}

---

## 1. 数据概览

| 指标 | 数值 |
|------|------|
| 总帖子数 | {stats.total_count} |
| 跳过视频帖 | {stats.skipped_video_count} |
| 跳过非笔记项 | {stats.skipped_non_note_count} |
| 平均点赞 | {avg_likes:.0f} |
| 平均收藏 | {avg_collects:.0f} |
| 平均评论 | {avg_comments:.0f} |
| 最高点赞 | {max_likes} |
| 最高收藏 | {max_collects} |
| 收藏/点赞比 | {collect_rate:.1f}% |

---

## 2. 互动数据分析

### 点赞分布
- **0-100**: {sum(1 for x in stats.likes if 0 <= x < 100)} 篇
- **100-500**: {sum(1 for x in stats.likes if 100 <= x < 500)} 篇
- **500-1000**: {sum(1 for x in stats.likes if 500 <= x < 1000)} 篇
- **1000-5000**: {sum(1 for x in stats.likes if 1000 <= x < 5000)} 篇
- **5000+**: {sum(1 for x in stats.likes if x >= 5000)} 篇

### 收藏分布
- **0-50**: {sum(1 for x in stats.collects if 0 <= x < 50)} 篇
- **50-200**: {sum(1 for x in stats.collects if 50 <= x < 200)} 篇
- **200-500**: {sum(1 for x in stats.collects if 200 <= x < 500)} 篇
- **500+**: {sum(1 for x in stats.collects if x >= 500)} 篇

---

## 3. 热门标题 TOP 10

| 排名 | 标题 | 点赞 | 收藏 | 评论 |
|------|------|------|------|------|
"""

    for i, (title, likes, collects, comments) in enumerate(top_by_likes, 1):
        # 截断过长的标题
        title_display = title[:30] + '...' if len(title) > 30 else title
        report += f"| {i} | {title_display} | {likes} | {collects} | {comments} |\n"

    report += f"""
---

## 4. 热门帖子正文摘录（Top 10）

| 排名 | 标题 | 正文摘录 |
|------|------|----------|
"""

    for i, (title, content, _) in enumerate(top_content_by_likes, 1):
        title_display = title[:24] + "..." if len(title) > 24 else title
        content_text = content or "（未提取到正文）"
        content_display = content_text[:50] + "..." if len(content_text) > 50 else content_text
        report += f"| {i} | {title_display} | {content_display} |\n"

    report += f"""
---

## 5. 高频关键词 TOP 20

| 排名 | 关键词 | 出现次数 |
|------|--------|----------|
"""

    for i, (word, count) in enumerate(keywords.most_common(20), 1):
        report += f"| {i} | {word} | {count} |\n"

    report += f"""
---

## 6. 标题特征分析

### 标题长度分布
"""

    title_lengths = [len(t) for t in stats.titles if t]
    if title_lengths:
        avg_length = sum(title_lengths) / len(title_lengths)
        report += f"""- **平均长度**: {avg_length:.1f} 字符
- **最短标题**: {min(title_lengths)} 字符
- **最长标题**: {max(title_lengths)} 字符
"""
    else:
        report += "- 暂无标题数据\n"

    # 分析标题句式
    question_titles = sum(1 for t in stats.titles if '?' in t or '？' in t)
    number_titles = sum(1 for t in stats.titles if re.search(r'\d+', t))
    emoji_titles = sum(1 for t in stats.titles if re.search(r'[\U0001F300-\U0001F9FF]', t))

    total_count = stats.total_count if stats.total_count > 0 else 1

    report += f"""
### 标题句式分析
- **疑问句**: {question_titles} 篇 ({question_titles/total_count*100:.1f}%)
- **含数字**: {number_titles} 篇 ({number_titles/total_count*100:.1f}%)
- **含 Emoji**: {emoji_titles} 篇 ({emoji_titles/total_count*100:.1f}%)

---

## 7. 内容创作建议

基于以上分析，给出以下创作建议：

### 标题建议
"""

    if keywords.most_common(3):
        top_keywords = [kw[0] for kw in keywords.most_common(3)]
        report += f"1. 热门关键词: **{'、'.join(top_keywords)}** 可融入标题\n"

    if title_lengths and avg_length > 0:
        if avg_length < 15:
            report += "2. 热门标题偏短，建议标题控制在 10-20 字\n"
        elif avg_length > 25:
            report += "2. 热门标题偏长，建议标题控制在 15-25 字\n"
        else:
            report += f"2. 热门标题平均 {avg_length:.0f} 字，保持此长度即可\n"

    if stats.total_count > 0 and question_titles / stats.total_count > 0.3:
        report += "3. 疑问句式受欢迎，可尝试 \"为什么...\"、\"如何...\" 等句式\n"

    if stats.total_count > 0 and number_titles / stats.total_count > 0.3:
        report += "4. 数字型标题效果好，如 \"N个方法\"、\"N种技巧\"\n"

    report += """
### 互动建议
"""

    if collect_rate > 50:
        report += "- 收藏率高，用户喜欢保存内容，可增加干货类、教程类内容\n"
    elif collect_rate > 30:
        report += "- 收藏率中等，可适当增加实用性和收藏价值\n"
    else:
        report += "- 收藏率较低，建议增加内容的实用性和参考价值\n"

    report += """
---

## 8. 推荐标签

基于热门内容分析，推荐以下标签组合：

```
"""

    # 基于关键词生成标签建议
    tag_keywords = [kw[0] for kw in keywords.most_common(5)]
    report += ' '.join([f'#{kw}' for kw in tag_keywords])
    report += "\n```\n"

    report += """
---

*报告由 analyze_trending.py 自动生成*
"""

    # 保存报告
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)

    return report


def _ask(prompt: str, default: str = "") -> str:
    value = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return value or default


def _ask_yes_no(prompt: str, default: bool = False) -> bool:
    default_hint = "Y/n" if default else "y/N"
    value = input(f"{prompt} ({default_hint}): ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "1", "true"}


def main() -> int:
    input_path = _ask("请输入 JSON 文件路径", "data/search_results.json")
    keyword = _ask("请输入关键词（用于报告标题，可留空）", "")
    output = _ask("请输入输出报告路径（留空自动命名）", "")
    output_dir = _ask("自动命名输出目录", "data/reports")
    auto_name = _ask_yes_no("是否强制自动命名（时间+关键词）", default=not bool(output))
    print_report = _ask_yes_no("是否在终端打印完整报告", default=False)

    input_file = Path(input_path)
    if not input_file.exists():
        print(f"错误: 输入文件不存在: {input_file}")
        return 2

    with input_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # 分析数据
    print(f"正在分析 {len(data) if isinstance(data, list) else '...'} 条数据...")
    stats = analyze_data(data)
    keywords = extract_keywords(stats.titles)
    keywords.update(extract_keywords(stats.contents))

    def slugify_keyword(keyword: str) -> str:
        if not keyword:
            return "unknown_keyword"
        normalized = keyword.strip().replace(" ", "_")
        normalized = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9_-]", "", normalized)
        return normalized or "unknown_keyword"

    def resolve_output_path() -> str:
        if output and not auto_name:
            return output
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        keyword_slug = slugify_keyword(keyword)
        filename = f"{timestamp}_{keyword_slug}_analysis.md"
        return str(Path(output_dir) / filename)

    output_path = resolve_output_path()

    # 生成报告
    report = generate_report(stats, keywords, output_path, keyword)

    print(f"分析完成!")
    print(f"- 分析帖子: {stats.total_count} 篇")
    print(f"- 平均点赞: {sum(stats.likes)/len(stats.likes):.0f}" if stats.likes else "")
    print(f"- 报告已保存: {output_path}")

    if print_report:
        print("\n" + "="*50 + "\n")
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
