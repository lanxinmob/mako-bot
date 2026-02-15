# Mako-Bot

基于 `NoneBot2 + NapCat(OneBot V11)` 的拟人化 QQ 机器人，采用“自然对话自动调用能力”模式。

## 重构结果

- 分层架构
- `src/core`：配置、日志、错误、系统提示词
- `src/services`：LLM、Redis、向量库、图片、语言、搜索、地图、笔记、工具执行器
- `src/models`：统一数据模型
- `src/plugins`：聊天入口、调度、天气、知识沉淀、辅助插件

## 已实现能力（自然触发）

- 图片能力：看图理解、文生图、灰度/模糊/缩放处理
- 语言能力：翻译、语种检测、语音转文字、文字转语音
- 表情识别：识别 `face` 表情与文本情绪并影响互动
- 好感度系统：按互动情绪动态变化，影响回复风格
- Google 搜索：联网检索与链接摘要
- 笔记系统：自然语言新增/查询/修改/删除笔记
- 高德地图：地点解析、周边搜索、路线规划

说明：除保留少量命令入口外，主流程已支持在普通聊天中自动判定并调用能力。

## 快速启动

```bash
pip install -r requirements.txt
nb run
```

或：

```bash
python bot.py
```

## NapCat 接入

1. 启动 NapCat 并登录 QQ。
2. 在 NapCat 中开启 OneBot V11 反向 WebSocket，上报地址指向本机 NoneBot：
   - `ws://127.0.0.1:8080/onebot/v11/ws`
3. 如配置了访问令牌，令牌与 `.env` 中 `ONEBOT_ACCESS_TOKEN` 保持一致。

## 环境变量

建议复制 `.env.example` 到 `.env` 后填写。

核心项：

- `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY`
- `REDIS_URL`（可选，默认本地 Redis）
- `QWEATHER_HOST` `QWEATHER_KEY`
- `GOOGLE_API_KEY` `GOOGLE_CX`
- `AMAP_KEY`
- 非文本识别（图片）可选：
- `IMAGE_PROVIDER=gemini` + `GEMINI_API_KEY`（推荐）

## 典型自然对话示例

- “这张图里有什么？”
- “把这张图改成黑白，再缩放到 800x800”
- “把这句话翻译成英文：今天很开心”
- “帮我记一下：周六 9 点开组会”
- “查一下上海明天天气”
- “从人民广场到虹桥火车站怎么去”
- “帮我搜索今天 OpenAI 的最新消息”

## 已知约束

- 部分能力依赖第三方 API Key。
- 图片和语音能力需要 OneBot 消息段可访问到资源 URL。
- 向量检索依赖 Redis Stack（RediSearch）。
