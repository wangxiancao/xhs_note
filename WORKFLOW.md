# 小红书专业自媒体工作流（研究生/学生赛道）

本工作流面向 **研究生、学生** 人群，基于 `xiaohongshu-mcp` + 本地脚本 + AI API + React 编辑页，完成从选题到发布的图文生产。

核心原则：

1. 赛道垂直：只做研究生/学生相关内容。
2. 产物结构化：每次产出分析报告、标题审核报告、图文产物目录。
3. 发布可复用：统一使用 `manifest.json` 对接 `publish_content`。
4. 渲染可编辑：封面与正文都先在 TeX 编辑页预览/保存，再进入下一页。

---

## 0. 当前运行基线（Docker）

已核实（2026-03-03）：

- `xiaohongshu-mcp` 容器 ID：`afeb5ff75e23`
- 容器状态：`Up`
- 端口映射：`18060:18060`
- 数据挂载：
  - `/root/notebook_repo/xhs_note/data -> /app/data`
  - `/root/notebook_repo/xhs_note/images -> /app/images`
- 登录状态接口可用：`GET /api/v1/login/status` 返回 `200`

说明：

- `GET /mcp` 需要 active session，当前返回行为正常。
- 当前容器未配置 `healthcheck`、日志轮转、资源限制。

---

## 1. 赛道与账号定位

### 1.1 目标人群

- 硕士/博士研究生
- 准研究生（考研/保研/申博）
- 在校本科生（学习方法、科研入门）

### 1.2 内容主线（固定四栏）

1. 学习效率：时间管理、复盘、高效学习流程
2. 科研方法：文献阅读、实验/数据分析、论文写作
3. 升学就业：申请策略、简历/面试、导师沟通
4. 研究生日常：情绪管理、作息、校园资源使用

### 1.3 内容边界

- 不发布医疗/法律/投资结论型建议
- 不承诺结果（如“包过”“必上岸”）
- 不做导流导私域表达（如“加微信”）

---

## 2. 热点采集与分析（标题+正文，跳过视频）

使用 `xiaohongshu-mcp` 获取热点样本，再用本地脚本生成分析报告。

### 2.1 推荐搜索模式

- 关键词：`博士生活`、`研究生学习`、`论文写作`、`考研经验`
- 筛选建议：
  - `sort_by`: `最多点赞`
  - `note_type`: `图文`
  - `publish_time`: `一周内`

### 2.2 分析命令（自动命名）

```bash
python scripts/analyze_trending.py
```

说明：脚本通过交互输入获取 JSON 路径、关键词、输出路径/目录等信息。

### 2.3 分析行为说明

- 自动提取：标题、正文文字、互动数据
- 自动跳过：视频类帖子（`video`/`视频` 标记）
- 自动保留：图文类帖子用于关键词与标题特征分析

### 2.4 报告命名规范

`data/reports/{YYYYMMDD_HHMMSS}_{keyword_slug}_analysis.md`

示例：`data/reports/20260303_095500_博士生活_analysis.md`

---

## 3. AI 定稿（直接生成 LaTeX 模板，无互动提问）

趋势报告生成后，调用 AI API 直接生成 LaTeX 页面模板（封面/正文），不再执行互动提问环节。

命令：

```bash
python skills/xhs-student-content-ops/scripts/run_interactive_agent.py
```

说明：按终端提示输入趋势报告路径、关键词、输出路径等信息。  
说明：未设置环境变量时，会回退读取 `.claude/CLAUDE.md` 中的 `GLM_API_KEY` 或 `GLM_tokens`。
说明：AI 生成后会自动触发 TeX 编译守卫 agent（逐页编译检查、自动修复不兼容语法）。

---

## 4. 标题合规检查（仅标题，本地词库）

> 本项目**不启用云审核**。  
> 审核对象仅为标题，不检查正文。

### 4.1 词库位置

`data/policy/title_banned_words.yml`

分类：

- `high_risk`
- `marketing_exaggeration`
- `diversion`
- `replacements`（替换建议）

### 4.2 检查命令

```bash
python scripts/title_compliance_check.py
```

输出报告（自动命名）：

`data/compliance/{YYYYMMDD_HHMMSS}_{keyword_slug}_title_check.md`

阻断规则：

- 命中任意违禁词 => 检查不通过（退出码 1）
- 标题长度 > 20 => 检查不通过（退出码 1）

---

## 5. React 图文渲染（左改 TeX，右看预览）

调用 `latex_server` 的编辑会话接口，进入 React 页面逐页编辑（封面与正文同流程）。

### 5.1 启动服务

```bash
cd scripts
python -m uvicorn latex_server:app --host 0.0.0.0 --port 8000
```

### 5.2 创建编辑会话

```bash
python scripts/start_tex_editor_session.py
```

脚本会返回 `editor_url`，打开后：

1. 左侧编辑 TeX 文本
2. 点击“预览”查看右侧渲染图
3. 点击“保存并下一页”进入下一张
4. 全部页面保存后自动生成 `manifest.json`

### 5.3 输出目录规范

`images/notes/{run_id}/`

产物：

- 观点表达型：`01_cover.png` + `manifest.json`
- 清单型：`01_cover.png` + `02_body.png` + `03_body.png` + `04_body.png` + `manifest.json`

说明：

- 图文渲染只产出 PNG，不产出 PDF 文件。

### 5.4 manifest.json 固定字段

- `title`
- `images[]`
- `tags[]`
- `keyword`
- `generated_at`
- `title_check_passed`
- `publish_mode`（`viewpoint` / `checklist`）
- `body_template`（仅清单型时存在）
- `analysis_report`（传入趋势报告时存在）
- `report_tags_added[]`（从趋势报告提取并追加的标签）

---

## 6. 发布（xiaohongshu-mcp）

图文发布使用 `publish_content`，支持一次提交多张图片（`images` 数组）。

### 6.1 Docker 路径映射 ⚠️

xiaohongshu-mcp 容器需要使用**容器内路径**发布图片：

| 宿主机路径 | 容器路径 |
|-----------|---------|
| `/root/notebook_repo/xhs_note/images/notes/{run_id}/01_cover.png` | `/app/images/notes/{run_id}/01_cover.png` |
| `/root/notebook_repo/xhs_note/data/` | `/app/data/` |

**发布时必须转换路径**:

```json
{
  "title": "标题",
  "images": ["/app/images/notes/{run_id}/01_cover.png", "/app/images/notes/{run_id}/02_body.png"],
  "tags": ["标签1", "标签2"]
}
```

### 6.2 发布参数建议

- `title`: 使用已通过标题审核的标题
- `content`: 简短正文（图文解释 + 互动引导）
- `images`: `manifest.json` 中图片路径
- `tags`: `manifest.json` 的标签数组
- `visibility`: 默认 `公开可见`

### 6.3 发布前检查清单

- [ ] 标题审核通过（仅标题）
- [ ] `manifest.json` 存在，且图片数量与模式一致
- [ ] 图片路径均存在、可读取
- [ ] 标题长度 <= 20
- [ ] 标签数量 3-8 个

---

## 7. Docker 推荐补充配置（建议）

以下配置写入 `docker-compose.yml` 的 `xiaohongshu-mcp` 服务（建议项）：

```yaml
services:
  xiaohongshu-mcp:
    image: xpzouying/xiaohongshu-mcp@sha256:23adcae5a7a7aebdb92aaddc21912101a2ef186b84deb152ddc5ead238d51b85
    ports:
      - "127.0.0.1:18060:18060"
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1:18060/api/v1/login/status >/dev/null || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    mem_limit: 2g
    cpus: "1.5"
```

说明：

- 单机场景建议仅监听 `127.0.0.1`。
- 镜像建议固定 digest，提高环境可复现性。

---

## 8. 测试与验收标准

1. 报告命名测试  
运行 `analyze_trending.py` 后，报告路径应符合 `时间+关键词` 命名规则，且报告中有“正文摘录”表。

2. 视频过滤测试  
混入视频帖子样本时，分析报告中的“跳过视频帖”数量应大于 0。

3. AI 定稿测试  
`run_interactive_agent.py` 可通过 API 生成草稿，标题满足“<=20 字且包含关键词”。

4. React 渲染测试  
编辑页可逐页“预览 + 保存并下一页”，最终生成 `manifest.json` 和 PNG 图片。

5. 发布参数测试  
`manifest.json` 中 `images` 路径必须真实存在，且数量与模式一致。

6. Docker 可用性测试  
`docker ps` 显示容器 `Up`，`/api/v1/login/status` 返回 200。

---

## 9. 目录结构（更新后）

```text
xhs_note/
├── WORKFLOW.md
├── data/
│   ├── policy/
│   │   └── title_banned_words.yml
│   ├── reports/                     # 趋势分析报告（自动命名）
│   ├── compliance/                  # 标题合规报告（自动命名）
│   ├── editor_sessions/             # React 编辑会话状态
│   ├── search_results.json
│   └── cookies.json
├── images/
│   └── notes/
│       └── {run_id}/                # PNG 产物 + manifest.json
└── scripts/
    ├── analyze_trending.py
    ├── title_compliance_check.py
    ├── render_note_images.py
    ├── start_tex_editor_session.py
    ├── latex_server.py
    └── latex_compiler.py
```
