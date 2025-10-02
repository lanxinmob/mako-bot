import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter


nonebot.init()

# 注册适配器
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

nonebot.load_plugin("src.plugins.chat")  
nonebot.load_plugin("src.plugins.scheduler")
nonebot.load_plugin("src.plugins.weather")
nonebot.load_plugin("src.plugins.what_to_eat")
nonebot.load_plugin("src.plugins.precipitate_knowledge")
nonebot.load_plugin("src.plugins.vector_db")

if __name__ == "__main__":
    nonebot.run()