# RedInk（xhs_note 本地改造版）

本目录是 `xhs_note` 使用的 RedInk 子项目，已按当前流程改造为：

1. 主题输入
2. 大纲与文案生成（GLM-4.7）
3. 图片生成（GLM-Image）
4. 结果确认
5. 通过 xiaohongshu-mcp 发布

## 运行要求

- Python 环境：`/root/soft/anaconda3/envs/videolingo`
- Node.js：18+
- Docker（用于 `xiaohongshu-mcp`）

## 本地启动

### 1. 启动发布服务依赖（在仓库根目录执行）

```bash
cd /root/notebook_repo/xhs_note
docker compose up -d
```

### 2. 启动后端

```bash
cd /root/notebook_repo/xhs_note/RedInk
/root/soft/anaconda3/envs/videolingo/bin/python -m backend.app
```

后端地址：`http://127.0.0.1:12398`

### 3. 启动前端

```bash
cd /root/notebook_repo/xhs_note/RedInk/frontend
npm install
npm run dev
```

前端地址：`http://127.0.0.1:5173`

## 关键接口

- `POST /api/outline`
- `POST /api/content`
- `POST /api/generate`
- `GET /api/publish/status`
- `POST /api/publish/from-result`

## 发布实现说明

- 发布使用 MCP 协议调用 `xiaohongshu-mcp` 的 `publish_content` 工具。
- 发布前会检查登录状态：`/api/v1/login/status`。
- 后端会把 `history/{task_id}` 图片复制到项目根目录 `images/publish/`，再映射为容器路径 `/app/images/publish/...` 进行发布。

## 配置说明

- 文本配置：`text_providers.yaml`
- 图片配置：`image_providers.yaml`

默认模型建议：

- 文本：`glm-4.7`
- 图片：`glm-image`

API Key 可通过设置页配置，或通过环境变量/`.claude/CLAUDE.md` 回退读取。
