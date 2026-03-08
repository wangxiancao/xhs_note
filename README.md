# xhs_note

研究生/学生赛道的小红书图文生产项目，采用“本地脚本 + `xiaohongshu-mcp` Docker + AI API + React 编辑页”。

核心能力：

- 热点分析：提取标题 + 正文文字，自动跳过视频类帖子
- AI 定稿：通过 API 直接生成 LaTeX 模板（无互动提问）
- 标题违禁词检查（仅标题，本地词库）
- React 图文编辑：左侧 TeX 可编辑，右侧预览，逐页保存进入下一步渲染
- 图文渲染仅产出 PNG（不产出 PDF）
- 产出 `manifest.json` 供 `publish_content` 直接调用

## 项目结构

```text
xhs_note/
├── WORKFLOW.md
├── docker-compose.yml
├── data/
│   ├── policy/title_banned_words.yml
│   ├── reports/
│   ├── compliance/
│   └── editor_sessions/
├── images/
│   └── notes/{run_id}/
├── scripts/
│   ├── analyze_trending.py
│   ├── title_compliance_check.py
│   ├── render_note_images.py
│   ├── start_tex_editor_session.py
│   ├── latex_server.py
│   ├── latex_compiler.py
│   ├── static/tex_editor.html
│   └── latex_templates/
└── skills/xhs-student-content-ops/
    ├── SKILL.md
    ├── agents/
    ├── scripts/
    └── references/
```

## 依赖与服务

1. `xiaohongshu-mcp`（Docker，默认 `http://127.0.0.1:18060`）
2. `latex_server`（FastAPI，默认 `http://127.0.0.1:8000`）
3. Python 3.10+，并安装运行脚本所需依赖
4. TeX Live（含 `xelatex`）
5. AI API（GLM-4.7，Z.ai）与 `GLM_API_KEY`

启动 LaTeX 服务：

```bash
cd scripts
python -m uvicorn latex_server:app --host 0.0.0.0 --port 8000
```

## 常用命令

趋势分析（提取标题+正文，跳过视频帖）：

```bash
python scripts/analyze_trending.py
```

AI 定稿（直接生成 TeX 模板）：

```bash
python skills/xhs-student-content-ops/scripts/run_interactive_agent.py
```

说明：按终端提示输入路径与参数。  
说明：如未设置环境变量，脚本会自动尝试读取 `.claude/CLAUDE.md` 中的 `GLM_API_KEY` 或 `GLM_tokens`。  
说明：脚本会自动调用 `scripts/tex_compile_guard_agent.py` 逐页编译检查并自动修复不兼容 TeX。

标题检查：

```bash
python scripts/title_compliance_check.py
```

创建 React 编辑会话（封面/正文同流程逐页编辑）：

```bash
python scripts/start_tex_editor_session.py
```

运行后打开返回的 `editor_url`，点击“预览”和“保存并下一页”，完成后自动生成：

- `images/notes/{run_id}/*.png`
- `images/notes/{run_id}/manifest.json`

## 说明

- 详细 SOP 见 `WORKFLOW.md`
- Skill 使用说明见 `skills/xhs-student-content-ops/SKILL.md`
