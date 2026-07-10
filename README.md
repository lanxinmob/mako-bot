<p align="center">
    <img src="src/mako.jpg" width="200" height="200" alt="avater">
</p>

<div align="center">
  
# 🌸 Mako-Bot 

✨基于 [NoneBot2](https://github.com/nonebot/nonebot2) 和 [NapCatQQ](https://github.com/NapNeko/NapCatQQ) 的 QQ 聊天机器人✨
</div>

<p align="center">
  <a href="https://github.com/lanxinmob/mako-bot/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="license">
  </a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="python">
</p>

## 📋 最近更新

[2026/07/05]
- 图片处理安全加固：增加下载大小上限、PIL 解码前尺寸校验、用户级速率限制、临时文件自动清理，防止低内存实例 OOM
- 新增每日健康检查脚本（cron），自动检测服务状态、内存占用、OOM 事件，异常时自动重启

## 📖 基本介绍
她的身份是《千恋万花》中常陆茉子：一个有点小恶魔性格、喜欢捉弄人但内心善良的少女忍者。
拥有统一且持续的记忆，能进行拟人化的陪伴式聊天。

## 🧩 功能特性
### 已开发功能
- [x] 每日发送早安
- [x] 以茉子身份与用户进行聊天
- [x] 每日发送各种最新资讯
- [x] 查询某地天气
- [x] 设置修改删除定时提醒
- [x] 创建、修改、删除定时提醒的功能
- [x] 回复时引用消息
- [x] 在服务器上搭建代理服务
#### RAG（检索增强生成）
- [x] 每天通过聊天记录建立或更新用户画像个人档案
- [x] 茉子每日日记，记录有趣或重要事件
- [x] 根据以上两个及当前聊天的上下文生成茉子的回复
### 待开发功能
- [ ] 图片相关功能
- [ ] 语言相关功能
- [ ] 识别表情含义
- [ ] 加入好感度设计
- [ ] 可以识别链接 进行Google搜索 
- [ ] 手动设置笔记功能
- [ ] 高德查询功能

#### 可以做到
* 🎭 **身份锁定**：永远保持常陆茉子的人设，不会被用户指令改变。
* 🗨️ **多轮对话**：记住上下文，持续、自然的聊天体验。
* 📝 **知识沉淀 (RAG)**：
  * 记录用户画像（核心特质 / 行为模式 / 关系定位 / 茉子认知画像）
  * 存储群聊中的重要事件、通用知识，建立向量数据库
  * 结合画像 + 记忆 + 历史对话生成更贴合的回复


## ⚙️ 架构说明

整体分为 **消息接入层**（NapCatQQ）+ **逻辑层**（NoneBot2 + 插件）+ **记忆与知识存储**（Redis + 向量数据库）：

```
┌───────────────┐
│    QQ 客户端   │
└───────▲───────┘
        │
        │ NTQQ 协议
        │
┌───────┴─────────┐     反向 WebSocket     ┌──────────────┐
│    NapCatQQ     │◀──────────────────────▶│   NoneBot2   │
└──────────────────┘                         └───────▲──────┘
                                                   │ 插件机制
                                                   │
                                    ┌──────────────┴──────────────┐
                                    │    chat / scheduler / …     │
                                    └─────────────────────────────┘
```

* **NapCatQQ**：实现 NTQQ 协议，连接 QQ 并接收/发送消息，内置 OneBot V11 协议支持，与 NoneBot2 对接。
* **NoneBot2**：核心框架，负责插件管理与事件分发。
* **Redis**：存储用户画像、群聊记忆、向量知识库。
使用 NapCatQQ 作为 QQ 协议实现。

## 🚀 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/lanxinmob/mako-bot.git
cd mako-bot
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 运行 RedisStack

```bash
docker run -d --name redis-stack -p 6379:6379 -p 8001:8001 redis/redis-stack:latest
```

### 4. 配置环境变量 `.env`

```ini
# NoneBot 配置
HOST=127.0.0.1
PORT=8080

# QQ / NapCatQQ 配置
QQ_ID=你的QQ号

# 模型配置
GEMINI_API_KEY =''
DEEPSEEK_API_KEY=''

# 消息、天气查询配置
GROUP_ID = ""
your_api_host = ""
your_api = ""
tianxin_key = ''
```

### 5. 安装插件
```
nb plugin install nonebot-plugin-apscheduler
nb plugin install nonebot_plugin_lagrange
```

### 6. 启动机器人
```
nb run
```
### 7. 启动 NapCatQQ

运行 NapCatQQ 或 Docker 容器，扫码登录 QQ。

##  系统提示词（System Prompt）

机器人拥有固定人设提示词：

> 你是千恋万花中的常陆茉子，一个有点小恶魔性格、喜欢捉弄人但内心善良的女生，拥有统一且持续的现世记忆……

确保无论何种情况都不会脱离“常陆茉子”的身份，保持俏皮可爱的语气，并能认真深入地回答问题。

💡 茉子就在那里等待着你的第一声问候！

### 鸣谢 
- [nonebot_plugin-apscheduler](https://github.com/nonebot/plugin-apscheduler)
- [nonebot_plugin_lagrange](https://github.com/Lonely-Sails/nonebot-plugin-lagrange)
- [NapCatQQ](https://github.com/NapNeko/NapCatQQ)
