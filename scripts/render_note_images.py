#!/usr/bin/env python3
"""
将图文文案渲染为图片（调用 latex_server /api/save）

输入：
- Markdown 文案（标题 + 封面 + 正文卡1 + 正文卡2 + 正文卡3 + 标签）

输出：
- 观点表达型：01_cover.png
- 清单型：01_cover.png + 02_body.png + 03_body.png + 04_body.png
- manifest.json
"""

import json
import re
import shutil
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


THEMES = {
    "classic": {
        "background": "F5F0E8",
        "primary": "2D2D2D",
        "secondary": "FF6B35",
        "accent": "FFB800",
    },
    "melon": {
        "background": "E8F5E9",
        "primary": "2E7D32",
        "secondary": "81C784",
        "accent": "C8E6C9",
    },
    "ocean": {
        "background": "E3F2FD",
        "primary": "1565C0",
        "secondary": "42A5F5",
        "accent": "90CAF9",
    },
}


def slugify(text: str) -> str:
    cleaned = text.strip().replace(" ", "_")
    cleaned = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9_-]", "", cleaned)
    return cleaned or "untitled"


def escape_latex(text: str) -> str:
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
    escaped = []
    for ch in text:
        escaped.append(replacements.get(ch, ch))
    return "".join(escaped)


def to_multiline_latex(text: str) -> str:
    lines = [escape_latex(x.strip()) for x in text.splitlines() if x.strip()]
    if not lines:
        return "待补充内容"
    return r"\\ ".join(lines)


def split_heading_detail(line: str) -> tuple[str, str]:
    for sep in ("：", ":"):
        if sep in line:
            left, right = line.split(sep, 1)
            return left.strip(), right.strip()
    return line.strip(), ""


def section_key_from_heading(heading: str) -> str:
    h = heading.strip().lower()
    if any(k in h for k in ("封面", "cover", "图1")):
        return "cover"
    if any(k in h for k in ("正文卡1", "正文1", "卡片1", "图2", "body1")):
        return "body1"
    if any(k in h for k in ("正文卡2", "正文2", "卡片2", "图3", "body2")):
        return "body2"
    if any(k in h for k in ("正文卡3", "正文3", "卡片3", "图4", "body3")):
        return "body3"
    if any(k in h for k in ("标签", "tags")):
        return "tags"
    return ""


def parse_markdown(markdown_path: Path) -> dict:
    text = markdown_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    title = ""
    sections = {"cover": [], "body1": [], "body2": [], "body3": [], "tags": []}
    current = ""

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            if not title:
                title = stripped[2:].strip()
            continue

        if stripped.startswith("## "):
            current = section_key_from_heading(stripped[3:])
            continue

        if current:
            sections[current].append(line.rstrip())
        elif stripped and not title:
            title = stripped

    if not title:
        raise ValueError("未在 Markdown 中识别到标题，请至少包含一行 '# 标题'")

    cover = "\n".join([x for x in sections["cover"] if x.strip()]).strip() or title
    body1 = "\n".join([x for x in sections["body1"] if x.strip()]).strip()
    body2 = "\n".join([x for x in sections["body2"] if x.strip()]).strip()
    body3 = "\n".join([x for x in sections["body3"] if x.strip()]).strip()

    if not body1:
        body1 = "方法与步骤\n- 提炼核心问题\n- 给出可执行动作"
    if not body2:
        body2 = "案例与避坑\n- 复盘关键错误\n- 给出行动建议"
    if not body3:
        body3 = "执行与复盘\n- 明确当周交付物\n- 每周复盘并迭代"

    tags_text = "\n".join(sections["tags"])
    tags = re.findall(r"#([^\s#]+)", tags_text)
    tags = list(dict.fromkeys(tags))[:10]

    return {
        "title": title.strip(),
        "cover": cover,
        "body1": body1,
        "body2": body2,
        "body3": body3,
        "tags": tags,
    }


def normalize_tag(raw: str) -> str:
    tag = raw.strip().lstrip("#").strip()
    tag = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9_-]", "", tag)
    return tag


def is_valid_tag(tag: str) -> bool:
    if len(tag) < 2 or len(tag) > 6:
        return False
    if tag.isdigit():
        return False

    lowered = tag.lower()
    blocked = {"skills", "skill", "title", "checklist", "viewpoint"}
    if lowered in blocked:
        return False

    if re.fullmatch(r"[a-zA-Z_-]+", tag):
        return tag.isupper() and len(tag) <= 6
    return True


def keyword_segments(keyword: str) -> list[str]:
    tokens = [normalize_tag(tok) for tok in re.findall(r"[A-Za-z]+|[\u4e00-\u9fa5]+", keyword or "")]
    tokens = [tok for tok in tokens if len(tok) >= 2]
    return list(dict.fromkeys(tokens))


def is_related_to_keyword(tag: str, keyword: str) -> bool:
    tokens = keyword_segments(keyword)
    if not tokens:
        return True
    for token in tokens:
        if token in tag or tag in token:
            return True
    return False


def merge_tags(base_tags: list[str], report_tags: list[str], max_tags: int) -> list[str]:
    merged: list[str] = []
    for tag in base_tags:
        cleaned = normalize_tag(tag)
        if cleaned and cleaned not in merged:
            merged.append(cleaned)
        if len(merged) >= max_tags:
            break
    for tag in report_tags:
        cleaned = normalize_tag(tag)
        if cleaned and is_valid_tag(cleaned) and cleaned not in merged:
            merged.append(cleaned)
        if len(merged) >= max_tags:
            break
    return merged


def extract_tags_from_report(report_path: Path, top_k: int, keyword: str = "") -> list[str]:
    if not report_path.exists():
        raise FileNotFoundError(f"趋势报告不存在: {report_path}")

    text = report_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tags: list[str] = []
    in_keyword_section = False
    row_pattern = re.compile(r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*\d+\s*\|")

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and "关键词" in stripped:
            in_keyword_section = True
            continue
        if in_keyword_section and stripped.startswith("## "):
            break
        if not in_keyword_section:
            continue
        match = row_pattern.match(stripped)
        if not match:
            continue
        candidate = normalize_tag(match.group(1))
        if (
            candidate
            and is_valid_tag(candidate)
            and is_related_to_keyword(candidate, keyword)
            and candidate not in tags
        ):
            tags.append(candidate)
        if len(tags) >= top_k:
            break

    return tags


def parse_body_sections(text: str) -> list[tuple[str, str]]:
    raw_lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not raw_lines:
        return [("待补充正文要点", "请补充该页内容。")]

    list_line_re = re.compile(r"^\s*(?:[-*•]\s+|\d+\s*[).、]\s*)")
    has_list_after_first = any(list_line_re.match(line) for line in raw_lines[1:])

    # 优先将列表项拆为独立段落，适配“步骤/清单/误区修正”场景
    if has_list_after_first:
        sections: list[tuple[str, str]] = []
        for line in raw_lines[1:]:
            cleaned = list_line_re.sub("", line).strip()
            if not cleaned:
                continue
            heading, detail = split_heading_detail(cleaned)
            sections.append((heading, detail))
        if sections:
            return sections[:4]

    blocks = [blk.strip() for blk in re.split(r"\n\s*\n", text.strip()) if blk.strip()]
    if len(blocks) > 1:
        sections: list[tuple[str, str]] = []
        for blk in blocks:
            lines = [line.strip() for line in blk.splitlines() if line.strip()]
            if not lines:
                continue
            heading = lines[0]
            detail = " ".join(lines[1:]).strip()
            sections.append((heading, detail))
        if sections:
            return sections[:4]

    if len(raw_lines) >= 2:
        heading = raw_lines[0].strip()
        detail = " ".join(raw_lines[1:]).strip()
        return [(heading, detail)]

    return [(raw_lines[0].strip(), "")]


def latex_font_setup() -> str:
    # Noto Sans CJK / Source Han Sans 均为可免费商用字体（OFL）
    return r"""
\usepackage{fontspec}
\IfFontExistsTF{Noto Sans CJK SC}{
  \setmainfont{Noto Sans CJK SC}
  \setCJKmainfont{Noto Sans CJK SC}
}{
  \IfFontExistsTF{Source Han Sans SC}{
    \setmainfont{Source Han Sans SC}
    \setCJKmainfont{Source Han Sans SC}
  }{
    \setmainfont{FandolHei-Regular}
    \setCJKmainfont{FandolHei-Regular}
  }
}
"""


def build_cover_latex(theme_name: str, title: str, subtitle: str) -> str:
    theme = THEMES.get(theme_name, THEMES["classic"])
    title_text = to_multiline_latex(title)
    subtitle_text = to_multiline_latex(subtitle)
    font_setup = latex_font_setup()

    return f"""\\documentclass[preview,border=0pt]{{standalone}}
\\usepackage{{ctex}}
\\usepackage{{tikz}}
\\usepackage{{xcolor}}
{font_setup}

\\definecolor{{bg}}{{HTML}}{{{theme["background"]}}}
\\definecolor{{primary}}{{HTML}}{{{theme["primary"]}}}
\\definecolor{{secondary}}{{HTML}}{{{theme["secondary"]}}}
\\definecolor{{accent}}{{HTML}}{{{theme["accent"]}}}

\\begin{{document}}
\\begin{{tikzpicture}}
  \\fill[bg] (0,0) rectangle (10.8cm,14.4cm);
  \\fill[secondary, rounded corners=2pt] (0.9cm,13.6cm) rectangle (9.9cm,13.75cm);

  \\node[font=\\fontsize{{38pt}}{{46pt}}\\selectfont\\bfseries,
        text=primary, align=center, text width=9.2cm]
    at (5.4cm,10.0cm) {{{title_text}}};

  \\node[font=\\fontsize{{24pt}}{{30pt}}\\selectfont,
        text=primary, fill=accent, rounded corners=8pt, inner sep=10pt,
        align=center, text width=8.6cm]
    at (5.4cm,6.5cm) {{{subtitle_text}}};
\\end{{tikzpicture}}
\\end{{document}}
"""


def build_body_list_latex(theme_name: str, title: str, section_title: str, sections: list[tuple[str, str]]) -> str:
    theme = THEMES.get(theme_name, THEMES["classic"])
    title_text = to_multiline_latex(title)
    section_title_text = escape_latex(section_title) if section_title.strip() else "正文要点"
    font_setup = latex_font_setup()

    if not sections:
        sections = [("待补充正文要点", "请补充该页内容。")]
    sections = sections[:4]

    top_y = 8.6
    bottom_y = 2.2
    if len(sections) == 1:
        y_positions = [5.8]
    else:
        gap = (top_y - bottom_y) / (len(sections) - 1)
        y_positions = [top_y - idx * gap for idx in range(len(sections))]

    section_nodes = []
    for idx, (heading, detail) in enumerate(sections):
        y = y_positions[idx]
        heading_text = escape_latex(heading) or "要点"
        detail_text = escape_latex(detail)

        section_nodes.append(
            f"""
  \\fill[accent] (1.10cm,{y:.2f}cm) circle (0.10cm);

  \\node[anchor=west,
        font=\\fontsize{{12pt}}{{16pt}}\\selectfont\\bfseries,
        text=black,
        text width=8.5cm,
        align=left]
    at (1.45cm,{y:.2f}cm) {{{heading_text}}};
"""
        )
        if detail_text:
            section_nodes.append(
                f"""
  \\node[anchor=north west,
        font=\\fontsize{{12pt}}{{16pt}}\\selectfont,
        text=black!75,
        text width=8.5cm,
        align=left]
    at (1.45cm,{y - 0.38:.2f}cm) {{{detail_text}}};
"""
            )

    section_nodes_text = "".join(section_nodes)

    return f"""\\documentclass[preview,border=0pt]{{standalone}}
\\usepackage{{ctex}}
\\usepackage{{tikz}}
\\usepackage{{xcolor}}
{font_setup}

\\definecolor{{bg}}{{HTML}}{{{theme["background"]}}}
\\definecolor{{primary}}{{HTML}}{{{theme["primary"]}}}
\\definecolor{{secondary}}{{HTML}}{{{theme["secondary"]}}}
\\definecolor{{accent}}{{HTML}}{{FFB066}}

\\begin{{document}}
\\begin{{tikzpicture}}
  % 背景底色
  \\fill[bg] (0,0) rectangle (10.8cm,14.4cm);

  % 棋盘纹理（参考图风格）
  \\foreach \\x in {{0,0.6,...,10.8}} {{
    \\foreach \\y in {{0,0.6,...,14.4}} {{
      \\fill[white, opacity=0.16] (\\x,\\y) rectangle ++(0.28cm,0.28cm);
    }}
  }}

  % 顶部标题
  \\node[font=\\fontsize{{28pt}}{{34pt}}\\selectfont\\bfseries,
        text=primary,
        align=center,
        text width=9.8cm]
    at (5.40cm,12.80cm) {{{title_text}}};

  % 白色正文卡片 + 虚线边框
  \\fill[white, rounded corners=0.60cm] (0.45cm,0.50cm) rectangle (10.35cm,10.75cm);
  \\draw[primary, dashed, line width=1.1pt, rounded corners=0.60cm] (0.45cm,0.50cm) rectangle (10.35cm,10.75cm);

  % 卡片内栏目标识
  \\node[anchor=west,
        fill=primary!10,
        rounded corners=4pt,
        inner xsep=10pt,
        inner ysep=5pt,
        font=\\fontsize{{12pt}}{{16pt}}\\selectfont\\bfseries,
        text=primary]
    at (0.90cm,10.10cm) {{{section_title_text}}};

{section_nodes_text}
\\end{{tikzpicture}}
\\end{{document}}
"""


def build_body_case_latex(theme_name: str, title: str, section_title: str, sections: list[tuple[str, str]]) -> str:
    theme = THEMES.get(theme_name, THEMES["classic"])
    title_text = to_multiline_latex(title)
    section_title_text = escape_latex(section_title) if section_title.strip() else "案例与行动"
    font_setup = latex_font_setup()

    if not sections:
        sections = [("案例", "请补充案例描述"), ("行动", "请补充行动建议")]
    sections = sections[:3]

    top_y = 8.9
    bottom_y = 2.3
    if len(sections) == 1:
        y_positions = [5.8]
    else:
        gap = (top_y - bottom_y) / (len(sections) - 1)
        y_positions = [top_y - idx * gap for idx in range(len(sections))]

    case_nodes = []
    for idx, (heading, detail) in enumerate(sections):
        y = y_positions[idx]
        heading_text = escape_latex(heading) or "要点"
        detail_text = escape_latex(detail) or "请补充说明。"
        block_top = y + 0.48
        block_bottom = y - 0.86
        case_nodes.append(
            f"""
  \\fill[primary!5, rounded corners=0.18cm] (1.00cm,{block_bottom:.2f}cm) rectangle (9.95cm,{block_top:.2f}cm);
  \\fill[secondary] (1.05cm,{block_bottom + 0.10:.2f}cm) rectangle (1.20cm,{block_top - 0.10:.2f}cm);

  \\node[anchor=west,
        font=\\fontsize{{12pt}}{{16pt}}\\selectfont\\bfseries,
        text=black,
        text width=8.35cm,
        align=left]
    at (1.38cm,{y + 0.13:.2f}cm) {{{heading_text}}};

  \\node[anchor=north west,
        font=\\fontsize{{12pt}}{{16pt}}\\selectfont,
        text=black!78,
        text width=8.35cm,
        align=left]
    at (1.38cm,{y - 0.10:.2f}cm) {{{detail_text}}};
"""
        )

    case_nodes_text = "".join(case_nodes)

    return f"""\\documentclass[preview,border=0pt]{{standalone}}
\\usepackage{{ctex}}
\\usepackage{{tikz}}
\\usepackage{{xcolor}}
{font_setup}

\\definecolor{{bg}}{{HTML}}{{{theme["background"]}}}
\\definecolor{{primary}}{{HTML}}{{{theme["primary"]}}}
\\definecolor{{secondary}}{{HTML}}{{{theme["secondary"]}}}
\\definecolor{{accent}}{{HTML}}{{FFB066}}

\\begin{{document}}
\\begin{{tikzpicture}}
  \\fill[bg] (0,0) rectangle (10.8cm,14.4cm);

  \\foreach \\x in {{0,0.6,...,10.8}} {{
    \\foreach \\y in {{0,0.6,...,14.4}} {{
      \\fill[white, opacity=0.16] (\\x,\\y) rectangle ++(0.28cm,0.28cm);
    }}
  }}

  \\node[font=\\fontsize{{28pt}}{{34pt}}\\selectfont\\bfseries,
        text=primary,
        align=center,
        text width=9.8cm]
    at (5.40cm,12.80cm) {{{title_text}}};

  \\fill[white, rounded corners=0.60cm] (0.45cm,0.50cm) rectangle (10.35cm,10.75cm);
  \\draw[primary, dashed, line width=1.1pt, rounded corners=0.60cm] (0.45cm,0.50cm) rectangle (10.35cm,10.75cm);

  \\node[anchor=west,
        fill=primary!10,
        rounded corners=4pt,
        inner xsep=10pt,
        inner ysep=5pt,
        font=\\fontsize{{12pt}}{{16pt}}\\selectfont\\bfseries,
        text=primary]
    at (0.90cm,10.10cm) {{{section_title_text}}};

{case_nodes_text}
\\end{{tikzpicture}}
\\end{{document}}
"""


def call_save_api(server: str, code: str, filename: str) -> str:
    url = server.rstrip("/") + "/api/save"
    payload = json.dumps({"code": code, "filename": filename, "save_pdf": False}).encode("utf-8")
    request = urllib.request.Request(
        url=url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"调用 latex_server 失败: {e}") from e

    if not result.get("success"):
        raise RuntimeError(f"latex_server 编译失败: {result.get('error') or result.get('message')}")
    png_path = result.get("png_path")
    if not png_path:
        raise RuntimeError("latex_server 未返回 png_path")
    return png_path


def resolve_server_output_path(api_path: str, scripts_dir: Path) -> Path:
    prefix = "/outputs/"
    if not api_path.startswith(prefix):
        raise ValueError(f"无法解析服务端输出路径: {api_path}")
    relative = api_path[len(prefix):]
    return scripts_dir / relative


def _ask(prompt: str, default: str = "") -> str:
    value = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return value or default


def _ask_int(prompt: str, default: int) -> int:
    raw = _ask(prompt, str(default))
    try:
        return int(raw)
    except ValueError:
        print(f"[warn] invalid integer '{raw}', fallback to {default}")
        return default


def _ask_yes_no(prompt: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = input(f"{prompt} ({hint}): ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes", "1", "true"}


def _ask_choice(prompt: str, choices: list[str], default: str) -> str:
    raw = _ask(f"{prompt} ({'/'.join(choices)})", default).lower()
    if raw not in choices:
        print(f"[warn] invalid choice '{raw}', fallback to {default}")
        return default
    return raw


def main() -> int:
    input_md_path = _ask("输入 Markdown 文件路径", "data/note_draft.md")
    keyword = _ask("关键词", "")
    analysis_report = _ask("趋势分析报告路径（留空跳过自动补充标签）", "")
    auto_tag_topk = _ask_int("从趋势报告提取标签上限", 5)
    max_tags = _ask_int("最终写入 manifest 的标签上限", 8)
    theme = _ask_choice("配色主题", list(THEMES.keys()), "classic")
    latex_server = _ask("latex_server 地址", "http://127.0.0.1:8000")
    output_dir = _ask("输出根目录", "images/notes")
    run_id = _ask("运行 ID（留空自动生成）", "")
    publish_mode = _ask_choice("发布模式", ["viewpoint", "checklist"], "checklist")
    body_template = _ask_choice("清单型正文模板", ["list", "case"], "list")
    title_check_passed = _ask_yes_no("标题检查是否通过", default=False)

    input_md = Path(input_md_path)
    if not input_md.exists():
        print(f"错误: 输入文件不存在: {input_md}")
        return 2

    parsed = parse_markdown(input_md)
    project_root = Path(__file__).resolve().parent.parent
    scripts_dir = project_root / "scripts"
    run_id_value = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = (project_root / output_dir / run_id_value).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    body1_sections = parse_body_sections(parsed["body1"])
    body2_sections = parse_body_sections(parsed["body2"])
    body3_sections = parse_body_sections(parsed["body3"])

    report_tags: list[str] = []
    report_path = None
    if analysis_report:
        report_path = (project_root / analysis_report).resolve()
        try:
            report_tags = extract_tags_from_report(
                report_path,
                max(auto_tag_topk, 0),
                keyword,
            )
        except FileNotFoundError as exc:
            print(f"错误: {exc}")
            return 2

    final_tags = merge_tags(parsed["tags"], report_tags, max(max_tags, 1))
    if not final_tags and keyword:
        final_tags = [normalize_tag(keyword)] if normalize_tag(keyword) else []

    pages = [("01_cover", "cover", parsed["title"], parsed["cover"], None)]

    if publish_mode == "checklist":
        if body_template == "list":
            pages.extend(
                [
                    ("02_body", "list", parsed["title"], "方法步骤", body1_sections),
                    ("03_body", "list", parsed["title"], "常见误区", body2_sections),
                    ("04_body", "list", parsed["title"], "执行复盘", body3_sections),
                ]
            )
        else:
            pages.extend(
                [
                    ("02_body", "case", parsed["title"], "案例拆解", body1_sections),
                    ("03_body", "case", parsed["title"], "误区修正", body2_sections),
                    ("04_body", "case", parsed["title"], "行动建议", body3_sections),
                ]
            )

    image_paths = []
    prefix = slugify(parsed["title"])[:24]

    for name, page_type, title, subtitle, payload in pages:
        if page_type == "cover":
            tex_code = build_cover_latex(theme, title, subtitle)
        elif page_type == "list":
            tex_code = build_body_list_latex(theme, title, subtitle, payload)
        else:
            tex_code = build_body_case_latex(theme, title, subtitle, payload)
        api_png = call_save_api(
            server=latex_server,
            code=tex_code,
            filename=f"{run_id_value}_{prefix}_{name}",
        )

        src_png = resolve_server_output_path(api_png, scripts_dir)
        dst_png = out_dir / f"{name}.png"
        shutil.copy2(src_png, dst_png)
        image_paths.append(str(dst_png))

    manifest = {
        "title": parsed["title"],
        "images": image_paths,
        "tags": final_tags,
        "keyword": keyword,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "title_check_passed": bool(title_check_passed),
        "publish_mode": publish_mode,
    }
    if report_path is not None:
        manifest["analysis_report"] = str(report_path)
        manifest["report_tags_added"] = report_tags
    if publish_mode == "checklist":
        manifest["body_template"] = body_template
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("图文渲染完成")
    print(f"- 输出目录: {out_dir}")
    print(f"- 图片数量: {len(image_paths)}")
    print(f"- Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
