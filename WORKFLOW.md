# xhs_note 工作流（当前主流程）

本文档描述当前生效的本地生产链路，不包含趋势分析、TeX 渲染或标题合规流程。

## 1. 流程概览

统一流程：

1. 主题输入
2. 大纲生成与编辑（GLM-4.7）
3. 图片生成（GLM-Image）
4. 标题/文案/标签生成
5. 一键发布到小红书（xiaohongshu-mcp）

## 2. 环境约束

- Conda：`/root/soft/anaconda3/envs/videolingo`
- Python：`/root/soft/anaconda3/envs/videolingo/bin/python`

要求：所有后端运行、测试和脚本调用均使用该 Python。

## 3. 服务启动

### 3.1 启动 xiaohongshu-mcp

```bash
cd /root/notebook_repo/xhs_note
docker compose up -d
```

登录状态检查：

```bash
curl http://127.0.0.1:18060/api/v1/login/status
```

### 3.2 启动 RedInk 后端

```bash
cd /root/notebook_repo/xhs_note/RedInk
/root/soft/anaconda3/envs/videolingo/bin/python -m backend.app
```

默认地址：`http://127.0.0.1:12398`

### 3.3 启动 RedInk 前端

```bash
cd /root/notebook_repo/xhs_note/RedInk/frontend
npm install
npm run dev
```

默认地址：`http://127.0.0.1:5173`

## 4. 页面链路

1. 首页 `/`
- 输入主题（可附参考图）
- 提交后进入 `/outline`

2. 大纲页 `/outline`
- 编辑每页内容与顺序
- 点击“开始生成图片”进入 `/generate`

3. 生成页 `/generate`
- 并发生成图片
- 全部成功后自动跳转 `/result`
- 失败图片可单张或批量重试

4. 结果页 `/result`
- 预览和下载图片
- 生成标题/文案/标签
- 点击“发布到小红书”调用发布接口

5. 设置页 `/settings`
- 配置文本与图片 provider
- 默认模型：`glm-4.7`、`glm-image`

6. 历史记录页 `/history`（保留）
- 查看历史任务列表与详情
- 继续处理未完成任务
- 下载已生成图文

## 5. 发布链路（Phase 3 已接入）

### 5.1 后端发布接口

- `GET /api/publish/status`
- `POST /api/publish/from-result`

### 5.2 发布参数来源

`/api/publish/from-result` 由结果页自动组装：

- `task_id`
- `title`（默认取首选标题）
- `content`（文案正文）
- `tags`
- `image_filenames`

### 5.3 图片路径转换

后端会将 `RedInk/history/{task_id}/*.png` 复制到：

- 宿主机：`images/publish/{task_id_timestamp}/`
- 容器路径：`/app/images/publish/{task_id_timestamp}/`

然后调用 MCP 的 `publish_content` 工具发布。

## 6. API 检查清单

1. `POST /api/outline` 成功返回 `pages`
2. `POST /api/content` 成功返回 `titles/copywriting/tags`
3. `POST /api/generate` 成功产出图片
4. `GET /api/publish/status` 返回登录状态
5. `POST /api/publish/from-result` 返回发布结果或明确错误

## 7. 当前非目标（不接入主流程）

以下能力保留在仓库，但不作为当前主流程：

1. 趋势分析
2. TeX 生成
3. TeX 守卫编译
4. 标题合规检查
5. TeX 编辑渲染
