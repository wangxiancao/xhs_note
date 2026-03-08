# xhs_note x RedInk 改造清单（优化版）

## 1. 改造目标（本轮范围）

本轮只做以下目标，不扩展额外功能：

1. 将本地工作流（`WORKFLOW.md`）并入 RedInk 全栈流程。
2. 大纲/内容生成统一切换为 `GLM-4.7`。
3. 画图统一切换为 `GLM-Image` 接口。
4. 部署主路径改为本地部署（不以 Docker 为主流程）。
5. 发布能力改为通过 `xiaohongshu-mcp` 完成。

## 2. 范围边界

### 2.1 In Scope

1. 打通 `趋势分析 -> AI 直出 TeX -> TeX 守卫 -> 标题检查 -> 编辑渲染 -> 发布` 的端到端链路。
2. 保持本地产物目录约束：`data/` 与 `images/notes/`。
3. API Key 支持从 `.claude/CLAUDE.md` 回退读取。
4. 图文渲染只产出 PNG（不产出 PDF）。

### 2.2 Out of Scope

1. 不做额外运营看板/复盘系统扩展。
2. 不重构 RedInk 的历史系统存储形态（仍按现有机制）。
3. 不引入新的第三方模型供应商抽象层重写。

## 3. 现状差异（改造依据）

1. 当前本地工作流核心脚本在仓库根目录：
   - `scripts/analyze_trending.py`
   - `skills/xhs-student-content-ops/scripts/run_interactive_agent.py`
   - `scripts/tex_compile_guard_agent.py`
   - `scripts/title_compliance_check.py`
   - `scripts/latex_server.py`
2. RedInk 已有完整前后端骨架与 provider 配置页面，但默认示例偏向 Gemini/OpenAI 文本与通用图像接口。
3. 发布环节目前仅到“产出图片/历史”，未内置 `xiaohongshu-mcp publish_content` 调用闭环。

## 4. 目标架构（改造后）

1. 前端（RedInk）新增“工作流执行入口”，触发后端工作流 API。
2. 后端（RedInk）编排本地脚本能力：
   - 趋势分析（跳过视频）
   - AI 直出 TeX（GLM-4.7）
   - TeX 编译守卫
   - 标题合规检查
   - 编辑会话创建
   - 发布（xiaohongshu-mcp）
3. 产物落盘：
   - 分析报告：`data/reports/`
   - 合规报告：`data/compliance/`
   - 渲染产物：`images/notes/{run_id}/`
   - 发布输入：`images/notes/{run_id}/manifest.json`

## 5. 分阶段改造清单（执行顺序）

## Phase 0: 基线冻结与分支准备

- [ ] `P0-1` 建立改造分支，冻结当前可运行基线。
- [ ] `P0-2` 固化验收主题：`论文阅读`（后续端到端统一用该主题验证）。

完成标准：

1. 能在现状下手工跑通最小流程并保留日志（作为回归基线）。

---

## Phase 1: 模型与密钥体系切换（GLM）

- [ ] `P1-1` 文本生成默认改为 GLM-4.7。
  - 目标文件：
    - `RedInk/backend/services/outline.py`
    - `RedInk/backend/services/content.py`
    - `RedInk/text_providers.yaml.example`
- [ ] `P1-2` 图片生成默认改为 GLM-Image。
  - 目标文件：
    - `RedInk/backend/services/image.py`
    - `RedInk/backend/generators/image_api.py`
    - `RedInk/image_providers.yaml.example`
- [ ] `P1-3` 增加 `.claude/CLAUDE.md` 回退读取能力（后端统一可用）。
  - 目标文件：
    - `RedInk/backend/utils/`（新增统一 key resolver，如 `secret_resolver.py`）
    - 调用方：文本/图片 service 初始化逻辑

完成标准：

1. 未设置环境变量时，文本与图片请求均可使用 `.claude/CLAUDE.md` 的 key 成功调用。
2. 设置页测试连接可通过（文本与图片至少各 1 个 provider）。

---

## Phase 2: 工作流能力后端化（从脚本到 API）

- [ ] `P2-1` 将趋势分析能力 API 化。
  - 目标能力：读取搜索结果 JSON，提取标题+正文，跳过视频帖。
  - 目标文件：
    - `scripts/analyze_trending.py`（复用核心函数）
    - `RedInk/backend/routes/`（新增 workflow 路由）
    - `RedInk/backend/services/`（新增 workflow orchestration service）
- [ ] `P2-2` 将 AI 直出 TeX + TeX 守卫 API 化。
  - 目标文件：
    - `skills/xhs-student-content-ops/scripts/run_interactive_agent.py`（复用 `run_ai_generation`）
    - `scripts/tex_compile_guard_agent.py`
    - `RedInk/backend/services/`（新增调用封装）
- [ ] `P2-3` 将标题检查 API 化。
  - 目标文件：
    - `scripts/title_compliance_check.py`
    - `RedInk/backend/routes/`（workflow 子路由）

建议新增 API（可按需调整命名）：

1. `POST /api/workflow/analyze`
2. `POST /api/workflow/ai-tex`
3. `POST /api/workflow/title-check`
4. `POST /api/workflow/editor-session`

完成标准：

1. 通过 API 能生成 `analysis.md`、`note_tex_draft.json`、`title_check.md`。
2. TeX 守卫失败时，API 返回阻断状态（不可进入下一步）。

---

## Phase 3: 前端流程改造（RedInk UI 接 WORKFLOW）

- [ ] `P3-1` 新增工作流入口与步骤页。
  - 目标文件：
    - `RedInk/frontend/src/router/index.ts`
    - `RedInk/frontend/src/views/`（新增 workflow 视图）
    - `RedInk/frontend/src/api/index.ts`（新增 workflow API 封装）
- [ ] `P3-2` 接入 TeX 编辑会话跳转（`latex_server`）。
  - 目标文件：
    - `scripts/start_tex_editor_session.py`（保留并可被后端调用）
    - 前端 workflow 页增加 `editor_url` 跳转
- [ ] `P3-3` 保持渲染产物协议不变（PNG + manifest）。
  - 目标文件：
    - `scripts/latex_server.py`

完成标准：

1. 用户在 RedInk 页面可顺序完成：分析 -> AI 定稿 -> 标题检查 -> 打开编辑器。
2. 编辑完成后产出 `images/notes/{run_id}/manifest.json`。

---

## Phase 4: 发布链路改造（xiaohongshu-mcp）

- [ ] `P4-1` 新增发布服务，读取 `manifest.json` 调用 `publish_content`。
  - 目标文件：
    - `RedInk/backend/services/`（新增 `publish_service.py`）
    - `RedInk/backend/routes/`（新增 `publish_routes.py`）
- [ ] `P4-2` 处理路径映射策略（宿主机路径 -> MCP 可识别路径）。
  - 目标文件：
    - 发布 service 内路径转换函数
- [ ] `P4-3` 发布前校验。
  - 校验项：标题长度、图片存在性、标签数量、manifest 字段完整性、MCP 登录状态

建议新增 API：

1. `POST /api/publish/from-manifest`

完成标准：

1. 传入 `manifest_path` 即可完成发布。
2. 发布失败时返回可定位错误（登录失效、路径错误、参数非法等）。

---

## Phase 5: 本地部署切换与文档收口

- [ ] `P5-1` 文档主路径切换为本地部署。
  - 目标文件：
    - `README.md`
    - `WORKFLOW.md`
    - `RedInk/README.md`
- [ ] `P5-2` 启动脚本统一本地流程（前端 + 后端 + latex_server）。
  - 目标文件：
    - `RedInk/scripts/start-linux.sh`
    - `RedInk/scripts/start-macos.command`
    - `RedInk/scripts/start-windows.bat`

完成标准：

1. 单机可执行一套本地启动步骤并完成端到端流程。
2. 文档中 Docker 保留为可选说明，不作为主推荐路径。

## 6. 端到端验收清单（必须全部通过）

- [ ] 主题 `论文阅读` 跑通全流程。
- [ ] 趋势分析报告生成且含“跳过视频帖”统计。
- [ ] AI 输出 TeX 通过守卫校验。
- [ ] 标题检查报告生成且通过。
- [ ] 编辑会话完成后产出 PNG 与 manifest。
- [ ] `publish_content` 调用成功并返回发布结果。

## 7. 风险与回滚

### 7.1 主要风险

1. GLM-Image 返回协议与现有 `image_api` 解析不一致。
2. MCP 登录态失效导致发布不稳定。
3. TeX 守卫调用链超时导致流程阻塞。

### 7.2 回滚策略

1. 保留 RedInk 原有 `/outline`、`/content`、`/generate` API 不移除，仅新增 workflow 路径。
2. provider 配置保留多服务商并允许手动切回旧 provider。
3. 发布功能失败不影响渲染产物落盘（保证可手工补发布）。

## 8. 建议实施顺序（最短路径）

1. 先做 `Phase 1`（模型与密钥），确保 GLM 通路稳定。
2. 再做 `Phase 2 + Phase 3`（后端编排 + 前端入口），形成可演示链路。
3. 最后做 `Phase 4 + Phase 5`（发布与部署文档切换），完成上线形态。

