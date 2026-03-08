# Project Map

本 skill 对应项目根目录：`/root/notebook_repo/xhs_note`

## Key Files

- 工作流说明：`WORKFLOW.md`
- 热点分析脚本：`scripts/analyze_trending.py`
- AI 定稿脚本：`skills/xhs-student-content-ops/scripts/run_interactive_agent.py`
- TeX 编译守卫：`scripts/tex_compile_guard_agent.py`
- 标题合规脚本：`scripts/title_compliance_check.py`
- React 编辑会话脚本：`scripts/start_tex_editor_session.py`
- 图文渲染脚本（非交互式）：`scripts/render_note_images.py`
- LaTeX 服务（含 React 编辑页）：`scripts/latex_server.py`
- 标题词库：`data/policy/title_banned_words.yml`

## Output Directories

- 热点报告：`data/reports/`
- 标题审核报告：`data/compliance/`
- 编辑会话：`data/editor_sessions/`
- 渲染产物：`images/notes/{run_id}/`
- 发布参数清单：`images/notes/{run_id}/manifest.json`

## Common Commands

```bash
# 1) 趋势分析（标题+正文，跳过视频）
python scripts/analyze_trending.py

# 2) AI 定稿（直接生成 LaTeX 模板）
python skills/xhs-student-content-ops/scripts/run_interactive_agent.py

# 默认自动读取 .claude/CLAUDE.md 中的 GLM_API_KEY/GLM_tokens
# 默认自动运行 tex_compile_guard_agent，对每页做编译检查与修复

# 3) 标题检查
python scripts/title_compliance_check.py

# 4) 创建 React 编辑会话（封面与正文逐页编辑）
python scripts/start_tex_editor_session.py
```

运行第 4 步后，打开返回的 `editor_url`，逐页点击“预览”和“保存并下一页”，完成后自动生成 PNG 与 `manifest.json`。

## Local I/O Constraints

- 输入与中间产物：`data/`
- 渲染输出：`images/notes/{run_id}/`
- 不写入 skill 目录，不写入远程路径
