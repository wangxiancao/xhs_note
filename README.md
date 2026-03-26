# RedInk-glm

本项目是基于 `RedInk` 改造的本地小红书图文生产工具，主链路为：

1. 输入主题
2. 生成大纲与文案
3. 生成封面与配图
4. 确认结果
5. 发布到小红书

同时支持一条轻量视频发布链路：

1. 首页进入视频发布页
2. 上传视频
3. 自动截取封面或手动上传封面
4. 填写文案
5. 一键发布视频到小红书

## 快速启动

推荐直接使用启动脚本：

```bash
cd /root/notebook_repo/RedInk-glm
bash scripts/start_local_stack.sh start
```

启动脚本路径：

`/root/notebook_repo/RedInk-glm/scripts/start_local_stack.sh`

## 启动前准备

1. 确认 `xiaohongshu-mcp` 已单独启动。
2. 确认前端依赖已安装过一次：

```bash
cd /root/notebook_repo/RedInk-glm/RedInk/frontend
npm install
```

3. 后端固定使用以下 Python：

```bash
/root/soft/anaconda3/envs/videolingo/bin/python
```

说明：当前脚本只管理 `RedInk` 前端和后端，不负责启动或停止 `xiaohongshu-mcp`。

## 常用命令

启动前后端：

```bash
bash scripts/start_local_stack.sh start
```

查看状态：

```bash
bash scripts/start_local_stack.sh status
```

查看最近日志：

```bash
bash scripts/start_local_stack.sh logs
```

停止前后端：

```bash
bash scripts/start_local_stack.sh stop
```

查看帮助：

```bash
bash scripts/start_local_stack.sh --help
```

## 服务地址

- 前端：`http://127.0.0.1:5173`
- 后端健康检查：`http://127.0.0.1:12398/health`
- MCP 登录状态：`http://127.0.0.1:18060/api/v1/login/status`

## 日志与 PID 文件

- 后端日志：`/tmp/redink-backend.log`
- 前端日志：`/tmp/redink-frontend.log`
- 后端 PID：`/tmp/redink-backend.pid`
- 前端 PID：`/tmp/redink-frontend.pid`

## 使用流程

1. 打开前端首页输入主题。
2. 在大纲页编辑内容。
3. 在封面页确认封面版本。
4. 进入生成页等待配图完成。
5. 在结果页确认标题、文案、标签并发布。

视频发布流程：

1. 在首页点击“视频发布”。
2. 上传视频并确认封面。
3. 填写标题（可选）和文案。
4. 点击“一键发布视频”。

## 相关目录

- 项目主代码：`RedInk/`
- 生成图片目录：`RedInk/history/{task_id}/`
- 发布中转目录：`images/publish/{task_id_timestamp}/`
