# xhs_note x RedInk 改造清单（简化版）

## 0. 执行环境约束（强制）

后续所有开发与测试统一使用：

1. Conda 环境：`/root/soft/anaconda3/envs/videolingo`
2. Python：`/root/soft/anaconda3/envs/videolingo/bin/python`

执行要求：

1. 脚本运行、接口测试、服务启动都必须使用该环境。
2. 缺失依赖只安装到该环境，不使用系统 Python。

---

## 1. 本轮目标

本轮只保留 RedInk 主业务链路：

1. 主题输入
2. 大纲/内容生成（GLM-4.7）
3. 图片生成（GLM-Image）
4. 结果确认
5. 通过 `xiaohongshu-mcp` 发布

---

## 2. 明确不做（Non-Goals）

以下能力不进入当前规划：

1. 趋势分析（`analyze_trending`）
2. TeX 生成
3. TeX 编译守卫
4. 标题合规检查
5. TeX 编辑渲染流程

说明：

1. 现有相关脚本可保留在仓库中，但不接入主流程、不作为验收项。

---

## 3. 目标流程（改造后）

统一流程为：

1. 前端输入主题（RedInk 首页）
2. 后端调用 GLM-4.7 生成大纲与文案
3. 后端调用 GLM-Image 生成图片
4. 前端展示结果并确认发布参数
5. 后端读取结果并调用 `xiaohongshu-mcp` 的发布接口

---

## 4. 分阶段改造计划

## Phase 1: 模型与配置统一（GLM）

目标：

1. 文本默认模型统一为 `glm-4.7`
2. 图片默认模型统一为 `glm-image`
3. API Key 支持配置、环境变量、`.claude/CLAUDE.md` 回退

涉及文件：

1. `RedInk/backend/services/outline.py`
2. `RedInk/backend/services/content.py`
3. `RedInk/backend/services/image.py`
4. `RedInk/backend/generators/image_api.py`
5. `RedInk/backend/config.py`
6. `RedInk/backend/routes/config_routes.py`
7. `RedInk/text_providers.yaml.example`
8. `RedInk/image_providers.yaml.example`

完成标准：

1. 设置页可测试通过文本与图片 provider
2. 未配置环境变量时可回退读取 `.claude/CLAUDE.md`

---

## Phase 2: 后端主链路收敛（去 TeX/趋势依赖）

目标：

1. 主流程只保留 `outline/content/image/result/publish`
2. 停止把趋势分析、TeX、守卫、标题检查接入主流程 API

涉及文件：

1. `RedInk/backend/routes/`（主流程路由）
2. `RedInk/backend/services/`（主流程服务）
3. `RedInk/frontend/src/api/index.ts`（移除不需要的调用入口）

完成标准：

1. 从主题输入到图片生成全链路无 TeX、无趋势、无标题检查依赖

---

## Phase 3: 发布能力接入 xiaohongshu-mcp

目标：

1. 新增统一发布 API
2. 直接从当前生成结果组装发布参数并调用 `publish_content`

涉及文件：

1. `RedInk/backend/services/publish_service.py`（新增）
2. `RedInk/backend/routes/publish_routes.py`（新增）
3. `RedInk/backend/routes/__init__.py`（注册）

完成标准：

1. 能从 RedInk 页面一键触发发布
2. 失败时返回明确错误原因（登录态、参数、图片路径）

---

## Phase 4: 前端流程简化与本地部署

目标：

1. 前端只展示主链路页面，不引导到 TeX 流程
2. 文档默认本地部署路径

涉及文件：

1. `RedInk/frontend/src/router/index.ts`
2. `RedInk/frontend/src/views/*.vue`（流程按钮与跳转）
3. `README.md`
4. `WORKFLOW.md`
5. `RedInk/README.md`

完成标准：

1. 本地启动后可完整跑通“生成并发布”
2. 文档中不再把趋势/TeX 流程作为主路径

---

## 5. 验收清单（必须全部通过）

1. 使用主题“论文阅读”可生成大纲与内容
2. 可成功生成图片（GLM-Image）
3. 可在结果页确认并触发发布
4. 发布调用 `xiaohongshu-mcp` 成功返回结果

---

## 6. 风险与回滚

主要风险：

1. GLM-Image 响应格式差异导致解析失败
2. MCP 登录态不稳定导致发布失败
3. 前后端旧流程并存导致调用混淆

回滚策略：

1. 保留旧路由但不在前端暴露
2. 以配置方式保留多 provider，可快速切换
3. 发布失败不影响本地图片产物留存

---

## 7. 增补：封面创作与修改接入主流程（2026-03-09）

说明：

1. 当前代码已支持封面单独生成与重绘，但还没有“封面专门编辑阶段”。
2. 本增补用于把封面创作和封面修改正式纳入端到端主流程。

当前状态（已具备）：

1. 封面在图片生成链路中单独处理（封面优先生成）。
2. 结果页支持按页重绘，封面可单独重绘。
3. 历史记录可保存任务与已生成图片。

缺口（待接入）：

1. 缺少封面专用编辑页面（标题/副标题/tag/hashtag/坐标）。
2. 缺少封面结构化数据模型（仅有页面文本）。
3. 缺少封面版本管理（多版封面对比与选用）。
4. 发布前无法显式确认“最终封面版本”。

接入目标流程（更新后）：

1. 输入主题
2. 生成大纲
3. 进入封面创作台（AI 草稿 + 手动修改 + 坐标编辑 + 预览）
4. 确认封面并保存版本
5. 生成正文配图
6. 结果页确认（封面可继续微调）
7. 发布到小红书

分阶段实施：

### Phase A: 数据与接口基础

目标：

1. 引入封面结构化字段 `cover_spec`（title/subtitle/tag/hashtags/top_badge/footer_words/positions/palette）。
2. 历史记录新增封面版本字段（`cover_versions`、`selected_cover_version`）。
3. 增加封面相关 API：
   - `POST /api/cover/preview`（基于 cover_spec 渲染预览）
   - `POST /api/cover/regenerate`（封面重生并保存版本）
   - `POST /api/cover/select`（选择发布封面版本）

完成标准：

1. 不改正文流程的前提下，后端可独立完成封面预览与版本保存。

### Phase B: 前端封面创作台

目标：

1. 在 `outline -> generating` 之间新增 `cover` 阶段页面。
2. 左侧表单可编辑封面文本与坐标，右侧实时预览。
3. 提供“AI 生成草稿 / 渲染预览 / 保存封面并继续”操作。

完成标准：

1. 用户可在不改代码的情况下，手动调标题位置并立即看到结果。
2. 退出后再次进入可恢复上次封面编辑状态。

### Phase C: 结果页与历史页联动

目标：

1. 结果页新增“编辑封面”入口，回到封面创作台。
2. 历史详情页支持查看封面历史版本并切换当前版本。

完成标准：

1. 任意历史任务都可以二次编辑封面并重新发布。

### Phase D: 发布链路封面锁定

目标：

1. 发布接口固定读取 `selected_cover_version` 作为第 1 张图。
2. 发布前校验封面是否存在且可访问。

完成标准：

1. 发布结果中的首图与用户在系统中确认的封面版本一致。

验收点（新增）：

1. 支持“只改封面不改正文”并重发。
2. 标题、tag、hashtag 坐标修改后，封面预览有明确变化。
3. 封面版本切换后，发布入参同步更新。
