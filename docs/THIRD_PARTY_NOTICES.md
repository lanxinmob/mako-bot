# 第三方许可说明

[返回README](../README.md) · [项目MIT许可证](../LICENSE)

本页保留依赖、服务、模型和素材的授权说明。依赖表沿用2026-10-08的上游核对；
NapCat、默认嵌入模型与Redis Stack的关键条款于2026-10-09再次核对。
授权以实际使用版本的上游全文为准，下面的摘要不替代原许可。

本仓库由作者提供的源码及原创文档沿用 **[MIT License](../LICENSE)**。
复制、修改或分发这些内容时，应保留 LICENSE 中的版权声明和许可全文。
MIT 是源码的授权，不替代第三方依赖、模型权重、外部服务和图片素材各自的许可。

### Python 依赖

| 依赖 | 上游许可证 |
| --- | --- |
| [NoneBot2](https://github.com/nonebot/nonebot2/blob/master/LICENSE)、[OneBot 适配器](https://github.com/nonebot/adapter-onebot/blob/master/LICENSE) | MIT |
| [nonebot-plugin-apscheduler](https://github.com/nonebot/plugin-apscheduler/blob/master/LICENSE)、[APScheduler](https://github.com/agronholm/apscheduler/blob/master/LICENSE.txt)、[nonebot-plugin-localstore](https://github.com/nonebot/plugin-localstore/blob/master/LICENSE) | MIT |
| [Pydantic](https://github.com/pydantic/pydantic/blob/main/LICENSE)、[pydantic-settings](https://github.com/pydantic/pydantic-settings/blob/main/LICENSE)、[FastAPI](https://github.com/fastapi/fastapi/blob/master/LICENSE)、[Loguru](https://github.com/Delgan/loguru/blob/master/LICENSE)、[redis-py](https://github.com/redis/redis-py/blob/master/LICENSE) | MIT |
| [OpenAI Python SDK](https://github.com/openai/openai-python/blob/main/LICENSE)、[google-generativeai](https://github.com/google-gemini/deprecated-generative-ai-python/blob/main/LICENSE)、[sentence-transformers](https://github.com/huggingface/sentence-transformers/blob/main/LICENSE) | Apache-2.0 |
| [HTTPX](https://github.com/encode/httpx/blob/master/LICENSE.md)、[Uvicorn](https://github.com/Kludex/uvicorn/blob/main/LICENSE.md)、[python-dotenv](https://github.com/theskumar/python-dotenv/blob/main/LICENSE)、[NumPy](https://github.com/numpy/numpy/blob/main/LICENSE.txt) | BSD-3-Clause；二进制包内附组件另遵各自许可 |
| [Pillow](https://github.com/python-pillow/Pillow/blob/11.3.0/LICENSE) | MIT-CMU（历史版本常标作 HPND） |
| [nonebot-plugin-lagrange](https://github.com/Lonely-Sails/nonebot-plugin-lagrange/blob/main/LICENSE) | GPL-3.0 |

上述 MIT、BSD 和 Apache 库允许本仓库源码保留 MIT，第三方代码仍按原许可分发。
`nonebot-plugin-lagrange` 已列入安装依赖及 NoneBot 配置，但当前应用入口未加载它。
仅声明或安装该依赖不等于将本仓库所有文件改为 GPL；如果启用它并形成同进程组合程序后分发，
组合程序须履行 GPLv3 的对应源码及许可义务，不能只用本仓库 MIT 声明代替。
这一判断取决于组合方式，参见 [GNU 关于主程序与插件的说明](https://www.gnu.org/licenses/gpl-faq.en.html#GPLPlugins)。

依赖表说明已核对的上游授权，不是完整的分发许可清单。仓库使用版本范围且没有锁定全部
传递依赖；发布安装包、容器或打包依赖时，须按实际包含的版本保留其 LICENSE、版权声明和
适用的 NOTICE，并满足相应许可要求。单纯调用远程 API 不会取得该服务内容的再授权权利。

### 外部服务、模型与素材

| 对象 | 使用及授权边界 |
| --- | --- |
| [NapCatQQ](https://github.com/NapNeko/NapCatQQ/blob/main/LICENSE) | 通过 OneBot V11 连接的独立程序；上游使用自定义 Limited Redistribution License，包含非商用及其他限制。本仓库 MIT 不覆盖 NapCat 的使用、修改或分发 |
| [Redis Stack](https://redis.io/legal/licenses/) | 部署文件使用 `redis/redis-stack-server:7.4.0-v3`；Redis Stack 按上游 RSALv2 或 SSPLv1 等适用条款使用与分发。它与 MIT 授权的 `redis-py` 客户端是不同组件 |
| [moka-ai/m3e-base](https://huggingface.co/moka-ai/m3e-base/blob/main/README.md#-license) | 默认嵌入模型，在运行时加载；上游声明限非商用、研究用途。商业部署须取得适当授权，或通过 `EMBEDDING_MODEL` 选择授权适用的模型；更换模型后需重新生成匹配的向量索引 |
| 角色与 `src/mako.jpg` | 《千恋万花》及常陆茉子的第三方角色、美术等权利归各自权利人。本仓库未附头像来源和再分发授权证明，MIT 不授予这些第三方权利 |
| 小鸟图片与在线资料 | 图片分别遵循输出中标明的 CC0、CC BY 或 CC BY-SA 等许可，保留作者、来源与许可链接；改编图片须遵守其对应条款。历史背景、期刊元数据和网页内容也不因被查询而改为 MIT |

因此，**Mako-Bot 源码使用 MIT，完整部署中的第三方组件和素材分别遵循原许可**；
不能据此把包含默认模型、协议端或第三方图片的部署整体标为无条件 MIT 商用授权。
