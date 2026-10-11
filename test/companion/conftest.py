import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest
from test.autonomy.test_pending_atomic import isolated_redis
from src.services.persistence import StorageService
from src.services.persistence.backends import StorageBackend
from src.services.companion.commands import parse,ZONE
from src.services.companion.workflow import CompanionService

BASE = int(datetime(2026,10,9,12,tzinfo=ZONE).timestamp()*1000)


class ClockRedis:
    def __init__(self, client):
        self.client,self.ms = client,BASE
    def __getattr__(self, name):
        return getattr(self.client,name)
    def time(self):
        return self.ms//1000,self.ms%1000*1000
    def eval(self, script, nkeys, *args):
        seconds,micros = self.time()
        script = script.replace("redis.call('TIME')",f'{{{seconds},{micros}}}')
        return self.client.eval(script,nkeys,*args)


def source(message,user=101):
    return dict(bot_id='999',user_id=user,message_id=str(message),scene='private',quoted=False,
                occurred_at='2026-10-09T12:00:00+08:00',received_at='2026-10-09T12:00:01+08:00')


@pytest.fixture
def context(isolated_redis,monkeypatch):
    client = ClockRedis(isolated_redis)
    storage = StorageService.__new__(StorageService)
    storage._backend = StorageBackend(redis_provider=lambda:client)
    state = SimpleNamespace(client=client,storage=storage,service=CompanionService(storage),sends=[],allowed=True)
    from src.services.companion import delivery
    monkeypatch.setattr(delivery,'observe_plugin_output',lambda *args:None)
    return state


@pytest.fixture
def create(context):
    async def run(message=1,user=101):
        command = parse('创建考试计划 合成数学 | 考试=2026-10-09 15:00 | 提醒=2026-10-09 13:00 | 任务=复习章节；练习真题')
        result = await context.service.execute(user,command,source(message,user))
        return result.get('plan_id','')
    return run


async def execute(context,text,message,user=101):
    return await context.service.execute(user,parse(text),source(message,user))


async def immediate(target,user,callback,**kwargs):
    return await callback()


class Bot:
    self_id = '999'
    def __init__(self,context,*,ack=True,error=False):
        self.context,self.ack,self.error=context,ack,error
    async def send_private_msg(self,**kwargs):
        self.context.sends.append(kwargs)
        if self.error:
            raise TimeoutError('synthetic unconfirmed QQ receipt')
        return {'message_id':len(self.context.sends)} if self.ack else None
