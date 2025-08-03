import websockets
import asyncio
import json

async def test():
    async with websockets.connect("ws://127.0.0.1:8080/onebot/v11/ws") as ws:
        print("连接成功！发送测试请求...")
        await ws.send(json.dumps({
            "action": "get_status",
            "params": {},
            "echo": "test"
        }))
        response = await ws.recv()
        print("收到响应:", response)

asyncio.run(test())