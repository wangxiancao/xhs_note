# xhs_note

基于 `RedInk` 的本地小红书图文生产项目，主链路为：

1. 输入主题
2. 生成大纲与文案（GLM-4.7）
3. 生成图片（GLM-Image）
4. 结果确认
5. 通过 `xiaohongshu-mcp` 发布

## 执行环境（固定）

- Conda 环境：`/root/soft/anaconda3/envs/videolingo`
- Python：`/root/soft/anaconda3/envs/videolingo/bin/python`

说明：后端运行和测试统一使用上述 Python。

## 快速启动（本地部署）

### 1. 启动 xiaohongshu-mcp（外部独立服务）

仓库链接：<https://github.com/xpzouying/xiaohongshu-mcp>

说明：`xiaohongshu-mcp` 不由本项目管理，请按其仓库文档单独部署并启动。

检查登录状态：

```bash
curl http://127.0.0.1:18060/api/v1/login/status
```

### 2. 启动后端（Flask）

```bash
cd RedInk
/root/soft/anaconda3/envs/videolingo/bin/python -m backend.app
```

默认端口：`http://127.0.0.1:12398`

### 3. 启动前端（Vite）

```bash
cd RedInk/frontend
npm install
npm run dev
```

默认端口：`http://127.0.0.1:5173`

## 部署后快速命令行启动

前提：`xiaohongshu-mcp` 已在外部独立启动。

```bash
(cd RedInk && nohup /root/soft/anaconda3/envs/videolingo/bin/python -m backend.app >/tmp/redink-backend.log 2>&1 &)
(cd RedInk/frontend && nohup npm run dev -- --host 0.0.0.0 --port 5173 >/tmp/redink-frontend.log 2>&1 &)
```

快速检查：

```bash
curl http://127.0.0.1:12398/health
curl http://127.0.0.1:18060/api/v1/login/status
```

## 主流程使用

1. 打开首页输入主题。
2. 在大纲页编辑页面内容。
3. 进入生成页等待图片完成。
4. 在结果页生成标题/文案/标签并确认。
5. 点击“发布到小红书”触发发布。

补充：

- 历史记录页仍保留（`/history`），可查看、续跑和下载已生成任务。

## 核心接口

- `POST /api/outline` 生成大纲
- `POST /api/content` 生成标题/文案/标签
- `POST /api/generate` 生成图片（SSE）
- `GET/POST/PUT/DELETE /api/history*` 历史记录管理
- `GET /api/publish/status` 检查登录态
- `POST /api/publish/from-result` 从生成结果发布

## 输出目录

- 生成图片：`RedInk/history/{task_id}/`
- 发布中转图：`images/publish/{task_id_timestamp}/`

## 文档

- RedInk 子项目说明：`RedInk/README.md`
