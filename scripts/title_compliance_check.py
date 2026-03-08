#!/usr/bin/env python3
"""
标题合规检查脚本（仅检查标题，不检查正文）

功能：
1. 使用本地词库检查标题违禁词
2. 生成 Markdown 合规报告
3. 命中违禁词时返回非 0 退出码，便于阻断后续流程
"""

import re
import sys
from datetime import datetime
from pathlib import Path


RULE_CATEGORIES = ("high_risk", "marketing_exaggeration", "diversion")


def slugify_keyword(keyword: str) -> str:
    if not keyword:
        return "unknown_keyword"
    normalized = keyword.strip().replace(" ", "_")
    normalized = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9_-]", "", normalized)
    return normalized or "unknown_keyword"


def _strip_inline_comment(text: str) -> str:
    # 简单 YAML 场景：# 后视为注释
    return text.split("#", 1)[0].strip()


def load_policy(policy_path: Path) -> tuple[dict[str, list[str]], dict[str, str]]:
    categories = {key: [] for key in RULE_CATEGORIES}
    replacements: dict[str, str] = {}
    current_section = ""

    with policy_path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            stripped = line.strip()

            if not stripped or stripped.startswith("#"):
                continue

            if re.match(r"^[a-z_]+:$", stripped):
                current_section = stripped[:-1]
                continue

            content = _strip_inline_comment(stripped)
            if not content:
                continue

            if current_section in categories and content.startswith("- "):
                word = content[2:].strip().strip("\"'")
                if word:
                    categories[current_section].append(word)
                continue

            if current_section == "replacements" and ":" in content:
                key, value = content.split(":", 1)
                key = key.strip().strip("\"'")
                value = value.strip().strip("\"'")
                if key and value:
                    replacements[key] = value

    return categories, replacements


def collect_matches(title: str, categories: dict[str, list[str]]) -> list[tuple[str, str]]:
    seen = set()
    hits: list[tuple[str, str]] = []
    for category, words in categories.items():
        for word in words:
            if word and word in title and (category, word) not in seen:
                seen.add((category, word))
                hits.append((category, word))
    return hits


def resolve_output_path(output: str, output_dir: str, keyword: str) -> Path:
    if output:
        return Path(output)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = slugify_keyword(keyword)
    return Path(output_dir) / f"{timestamp}_{slug}_title_check.md"


def render_report(
    output_path: Path,
    title: str,
    keyword: str,
    max_length: int,
    hits: list[tuple[str, str]],
    replacements: dict[str, str],
) -> bool:
    length_ok = len(title) <= max_length
    passed = length_ok and not hits
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# 标题合规检查报告",
        "",
        f"> 生成时间: {now}",
        f"> 关键词: {keyword or '未指定'}",
        "> 检查范围: 仅标题（不检查正文）",
        "",
        "## 1. 基本信息",
        "",
        f"- 标题: {title}",
        f"- 标题长度: {len(title)}",
        f"- 标题长度阈值: {max_length}",
        "",
        "## 2. 检查结果",
        "",
        f"- 结果: {'✅ 通过' if passed else '❌ 不通过'}",
        f"- 长度检查: {'通过' if length_ok else '不通过'}",
        f"- 违禁词命中数: {len(hits)}",
        "",
    ]

    if hits:
        lines.extend(
            [
                "## 3. 命中详情",
                "",
                "| 分类 | 命中词 | 替换建议 |",
                "|------|--------|----------|",
            ]
        )
        for category, word in hits:
            suggestion = replacements.get(word, "请改为中性表达")
            lines.append(f"| {category} | {word} | {suggestion} |")
        lines.append("")
    else:
        lines.extend(
            [
                "## 3. 命中详情",
                "",
                "- 未命中词库中的违禁词。",
                "",
            ]
        )

    lines.extend(
        [
            "## 4. 处理建议",
            "",
            "- 发布前再次人工复核标题语义，避免夸张、导流、违规承诺表述。",
            "- 如检查未通过，请修改标题后重新运行本脚本。",
            "",
            "---",
            "",
            "*报告由 title_compliance_check.py 自动生成*",
            "",
        ]
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return passed


def main() -> int:
    title = ""
    while not title:
        title = input("请输入待检查标题: ").strip()
    keyword = input("请输入关键词（可留空）: ").strip()
    policy = input("请输入本地词库路径 [data/policy/title_banned_words.yml]: ").strip() or "data/policy/title_banned_words.yml"
    output = input("请输入输出报告路径（留空自动命名）: ").strip()
    output_dir = input("请输入自动命名输出目录 [data/compliance]: ").strip() or "data/compliance"
    max_length_raw = input("请输入标题最大长度 [20]: ").strip() or "20"
    try:
        max_length = int(max_length_raw)
    except ValueError:
        print(f"错误: 标题最大长度必须是整数: {max_length_raw}")
        return 2

    policy_path = Path(policy)
    if not policy_path.exists():
        print(f"错误: 词库文件不存在: {policy_path}")
        return 2

    categories, replacements = load_policy(policy_path)
    hits = collect_matches(title, categories)
    output_path = resolve_output_path(output, output_dir, keyword)
    passed = render_report(
        output_path=output_path,
        title=title,
        keyword=keyword,
        max_length=max_length,
        hits=hits,
        replacements=replacements,
    )

    print(f"标题合规检查完成: {'通过' if passed else '不通过'}")
    print(f"报告路径: {output_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
