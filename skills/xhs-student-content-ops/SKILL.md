---
name: xhs-student-content-ops
description: "小红书研究生/学生赛道内容生产工作流。触发条件：趋势分析、AI直出TeX、标题合规检查、React图文渲染与发布素材准备。"
---

# XHS Student Content Ops

## Overview

小红书研究生/学生赛道的本地化内容生产工作流。基于 `xiaohongshu-mcp` + 本地脚本 + AI API + React 编辑页完成从选题到发布的图文生产。

## Execution Rules

- 所有命令必须从项目根目录运行: `/root/notebook_repo/xhs_note`
- API Key 默认从 `/root/notebook_repo/xhs_note/.claude/CLAUDE.md` 读取（`GLM_API_KEY` 或 `GLM_tokens`）
- 本地数据与产物只写仓库路径：`data/` 和 `images/notes/`
- 标题检查失败时，阻断渲染和发布准备
- 图文渲染只产出 PNG，不产出 PDF

## Workflow

### (0) 一键本地流程（推荐）

```bash
python skills/xhs-student-content-ops/scripts/run_local_workflow.py
```

该脚本会按提示输入参数，顺序执行：趋势分析 -> AI 定稿（含 TeX 编译守卫）-> 标题检查，并给出下一步 React 编辑命令。

### (1) 趋势分析（标题+正文，跳过视频）

```bash
python scripts/analyze_trending.py
```

输出报告: `data/reports/{YYYYMMDD_HHMMSS}_{keyword}_analysis.md`

### (2) AI 定稿（直接生成 LaTeX 模板）

```bash
python skills/xhs-student-content-ops/scripts/run_interactive_agent.py
```

无需手动 `export`，脚本默认读取 `.claude/CLAUDE.md` 中的 `GLM_API_KEY` 或 `GLM_tokens`。
默认会自动调用 `scripts/tex_compile_guard_agent.py` 逐页编译检查并修复不兼容 TeX。

### (3) 标题检查

```bash
python scripts/title_compliance_check.py
```

### (4) React 图文编辑与渲染

```bash
python scripts/start_tex_editor_session.py
```

打开返回的 `editor_url`，逐页执行：

1. 编辑左侧 TeX 文本
2. 点击“预览”查看右侧图片
3. 点击“保存并下一页”
4. 全部保存后自动生成 `images/notes/{run_id}/manifest.json`

### (5) 发布

使用生成的 `images/notes/{run_id}/manifest.json` 调用 `publish_content`。

**⚠️ Docker 路径映射**:

- 宿主机: `/root/notebook_repo/xhs_note/images/notes/{run_id}/01_cover.png`
- 容器: `/app/images/notes/{run_id}/01_cover.png`

发布时需将图片路径从宿主机路径转换为容器路径。

## References

| 文件 | 用途 |
|------|------|
| `references/prompts-viewpoint.md` | 观点表达型 prompt 模板 |
| `references/prompts-checklist.md` | 清单型 prompt 模板 |
| `references/project-map.md` | 项目文件映射 |

## Key Files

| 文件 | 用途 |
|------|------|
| `WORKFLOW.md` | 完整工作流说明 |
| `scripts/analyze_trending.py` | 热点分析（标题+正文，过滤视频） |
| `skills/xhs-student-content-ops/scripts/run_interactive_agent.py` | AI 定稿 Agent |
| `scripts/title_compliance_check.py` | 标题合规检查 |
| `scripts/start_tex_editor_session.py` | 创建 React 编辑会话 |
| `scripts/latex_server.py` | React 编辑页与编译 API |
| `scripts/tex_compile_guard_agent.py` | TeX 编译检查与自动修复 agent |
| `scripts/render_note_images.py` | 非交互式渲染（仅 PNG） |
| `data/policy/title_banned_words.yml` | 标题违禁词库 |

## Agent Metadata

- `agents/openai.yaml`: UI metadata and default prompt for invoking this skill
