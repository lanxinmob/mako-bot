# F1a/F1c 群参与及集成独立评审（恢复）

## 结论

**不建议按“群参与及显式工具保护已完成”验收：发现 1 项 P1、4 项 P2。** 本评审未修改业务实现，问题均保留待修复。没有发现或证明实群自然度已达标。

## 开工记录与边界

- 读取时间：2026-09-14 19:04–19:10（Asia/Shanghai）；模块 F1a/F1c。
- 工作区：D:/vscode workplace/fun/bot/mako-bot-refactor。
- HEAD：8fdb8e542836bb616bfa5c426ca5ac9cf6dde7e9；存在大量先前重构及 F1 未提交改动，本结论针对当前工作树，不以 HEAD 代替当前代码。
- 已重新读取 AGENTS.md、docs/agent/project.md、docs/agent/development.md、docs/refactor/plan.md、modules.md、status.md；src/docs/test 中未检出下级 AGENTS.md。
- 授权：用户本次明确恢复独立只读评审。唯一写入文件为本报告；未更新状态、测试、业务代码。
- 检查范围：src/services/chat/group 全部模块；pipeline 的 participation/workflow/admission/execution 及输入契约；plugins/chat 的 ingress/delivery。为核实调用链只读查看注册入口、dispatcher、intent、rhythm、相关测试与配置源码。
- 保留契约：600 秒/60 条内存窗口、单群候选、显式工具与可丢弃闲聊隔离、锁和 guard、成功发送后提交；不改设置、提示词、概率、外部接口或持久化格式。
- 未读取 .env、真实聊天/画像/日志或其他真实数据；未启动应用、连接 Redis/模型、调用 QQ、安装依赖、提交或部署。
- 既有历史仅用于理解评审重点；以下缺陷依据当前源码及本轮受控探针独立确认。

## F1-G01 — P1：显式工具在取得保护前仍可被新请求覆盖

**位置：** src/services/chat/pipeline/participation.py:29–44；src/plugins/chat/ingress.py:20–29；src/services/chat/group/service.py:102–107。

observe 将消息一律记为默认 chat。prepare 先按当前群触发消息检查 target_message_id，并执行闲聊 debounce，随后才识别工具并设置 command。因此显式工具根本到不了不可丢弃分支。

**复现：** 同群依次观察 a（用户 7：“mako 翻译 hello”）和 b（用户 8：“mako 新问题”），再 prepare(a)。当前真实 decide_intents 能识别 a 为 language.translate，但 prepare(a) 返回 None。默认 0.8 秒 debounce 内到达 b，或 ingress.message_text 的异步成员查询期间到达 b，均可产生该交错。无需实际执行翻译或发送。

**影响：** 已明确调用的翻译、图片生成、笔记等任务可静默丢失；“显式工具不进入闲聊候选”的保证只在晚期分类成功以后成立。

**建议：** 在可覆盖群目标选择和等待之前，从原始事件识别已明确指向机器人的工具请求，创建按事件身份保留的工作项；让其绕过可丢弃闲聊目标选择，但保留治理、权限和工具预算检查。不能简单让所有含工具关键词的旁听消息执行工具。

**验证边界：** 探针执行真实规则与 prepare，未跑 NoneBot 并发分发；异步窗口由入口源码确认。补回归应包含默认 debounce、成员查询暂停和两个不同用户的显式请求，断言两个工具任务均保留且不重复执行。

## F1-G02 — P2：command 分类没有绕过普通聊天节奏拒绝/收束

**位置：** src/services/chat/pipeline/admission.py:57–76；src/services/chat/pipeline/workflow.py:94–129；关联 participation.py:40–44。

prepare 已把工具标为 command 并令 directed=True，但 admit 仍无条件调用 chat_rhythm.admit；同用户冷却会直接返回 None。即使 allowed=True，boundary=True 也会先发送闲聊收束语并 return，工具和提醒分支尚未执行。

**复现：** 先 prepare “mako 翻译 hello”，确认 category=command、is_current=None；用真实 ChatRhythmService、内存替身设置同会话 last_sender_id=7、last_reply_at=95、cooldown_until=150、clock=100，调用 admit。结果 None，工具未获执行入口。

**影响：** 用户在闲聊冷却期间发出明确功能请求仍被沉默丢弃；这与工具应独立于闲聊状态的契约冲突。

**建议：** 在 ChatInput/Admission 中显式携带工作类别；仅普通聊天应用闲聊冷却和 boundary，工具仍经过治理、权限、成本及 command 发送配额。避免靠 transport 的动态属性间接决定领域准入。

**验证边界：** 已实际确认真实 rhythm 的冷却拒绝；boundary 分支为静态调用链确认，未额外重复运行。应补同用户冷却与 boundary 两种工具回归。

## F1-G03 — P2：刷新候选令牌会放行未吸收新上下文的生成结果

**位置：** src/services/chat/pipeline/participation.py:50–59、73；src/services/chat/pipeline/execution.py:57–59、109–112、153–155。

current 在版本变化后重新做廉价规则选择，再刷新候选 revision/generation；但 incoming.group_context 是 prepare 时固定的字符串，已构建的 request 和 reply 也没有刷新。规则针对仍保留的旧 pending_target，无法评价后续补充对旧回答的影响。

**复现：** a：“mako 分析数字10”，prepare(a)；同一用户随后发 b：“更正：数字是20”（无 @、非结束语）。关闭 debounce 的确定性探针中，guard 返回 True，但 incoming.group_context 不含“数字是20”。默认 debounce 下等待安静间隔届满也会重新允许；若旧生成跨过该间隔，旧答案仍可发出。

**影响：** 候选的版本看似新鲜，实际答案仍基于旧事实。引用回答/“不用了”等硬取消有效，并不能覆盖补充和纠正场景。

**建议：** 区分“触发目标仍有效”和“生成所用上下文仍有效”。上下文变化时，保守丢弃旧生成，或明确判断不影响回答后允许继续；若需重生成，在原截止时间内刷新上下文和 request，不能只替换令牌。

**验证边界：** 运行确认 guard 与冻结上下文不一致；没有调用模型，不能声称已观测真实错误答案。修复测试需在生成挂起期间注入纠正，再确认不发送旧结果。

## F1-G04 — P2：失败/预算通知绕过候选 guard 与统一发送器

**位置：** src/plugins/chat/ingress.py:51–55；src/services/chat/pipeline/execution.py:99–107、178–183；关联 admission.py:49–54。

QQChatTransport.notice 直接 matcher.send，不检查 guard、不调用 dispatcher。普通聊天生成期间候选过期或被回答取消后，若生成抛错，异常分支仍会发送“累了”等通知；预算检查等待期间过期也会类似。extra 同样旁路，但附件是否应继续需按显式工具生命周期处理，不应机械绑定已经 mark_sent 的聊天候选。

**复现：** 提取并执行原 QQChatTransport 类，注入 AsyncMock matcher.send，把 guard 设为 False；await notice("synthetic failure") 后 send.await_count==1。

**影响：** 已取消候选仍可产生可见输出，多项错误绕开群间距/配额及通知合并，削弱实际沉默保证。

**建议：** 普通聊天失败通知进入 dispatcher，并携带候选有效性 guard；使用稳定原因码合并通知。显式工具的成功/失败通知按 command 生命周期和操作结果处理。附件也通过统一发送器，但不要复用已完成主回复的旧候选令牌。

**验证边界：** 实际确认 transport 旁路；执行异常到 notice 的连线通过源码核对，未调用真实生成服务或完整异常工作流。这也是 status 中已承认“通知/附件仍需收口”的具体可复现缺口，不将其包装为此前已完成模块的新回归。

## F1-G05 — P2：机器人已发送回复以空正文写入群上下文

**位置：** src/services/chat/pipeline/participation.py:61–68；src/plugins/chat/delivery.py:77–80。

send_reply 仅把发送回执传给 on_sent；sent 构造 GroupEvent 时没有 text，也没有 reply_to_message_id。窗口内只能留下空白机器人消息，丢失本轮机器人的回答正文及其引用对象。

**复现：** 为 a 创建候选后调用 transport.on_sent({"message_id":"bot1"})；读取 snapshot.events[-1]，text==""、reply_to_message_id is None。真实回复正文在 delivery 作用域中可用，但未传给回调。

**影响：** 近期群上下文并不完整。后续“你刚才这句话”与多人交错对话无法仅凭该窗口还原；长期历史可能保留部分内容，但不修复带消息身份和引用关系的群窗口缺失。

**建议：** 成功回调同时携带有界回复正文和源消息 ID，按真实出站消息 ID 记录；command 回复也按独立类别明确观察，不能打开普通闲聊租约。

**验证边界：** 已运行普通聊天成功回调探针；未验证协议端的发送回执延迟、重复回执或自身消息回推，不能假定 OneBot 一定会补齐丢失正文。

## 已核对有效部分与未覆盖项

- 实际正向探针：单调时钟恰到 25 秒时旧候选 guard=False；他人引用回答原问题后 guard=False。
- 静态检查：窗口按本地接收时间保留、60 条上限和有界清理；候选 revision/generation 及所有权比较防止旧取消清理后继；workflow 在会话锁前 prepare、锁内再查 current、finally 释放所属候选。
- 主回复在群成员渲染后交给 dispatcher，最终 guard 在发送器锁内执行；没有把“发送已开始后仍可撤回”当作保证。发送等待期间的新入站消息仍可能改变候选，网络已开始的发送无法撤销。
- 未发现上述静态项中的确定新增缺陷，不等于完整并发证明。未运行全套 pytest、编译、wheel、实群或外部联调，也未重新认证 B2/F1b/B4。
- 阅读了既有群候选/窗口/交错、pipeline、transport 测试；本轮只补缺口探针，不重复现有整套结果。原 F1a 57 passed/F1c 12 passed 等为状态文档历史记录，不作为本轮运行数。
- 配置入口、可选 classifier 接入及其体验仍属现有未完成集成边界；本报告不把未启用 classifier 本身定为额外缺陷。

## 实际验证方法与证据

使用 ../mako-bot/.venv/Scripts/python.exe -B -，通过标准输入执行内存探针。未落盘测试脚本或缓存。纯 group 包正常导入；其他目标以 AST 保留原定义、移除模块导入并显式注入依赖，避免注册插件或初始化配置/外部客户端。URL 提取替身返回空列表，样例不含 URL；matcher、storage、治理均为合成替身；rhythm、意图规则、prepare/admit/notice 方法本体为当前源码。

探针装配前两次分别缺少 Protocol、Literal 注入而失败，均在场景运行前停止；补齐标准库类型后第三次运行退出码 0。这两次为隔离探针错误，不计作业务缺陷。

最终输出：

```text
P1 tool superseded before prepare: dropped
P2 refreshed guard=True; generation context excludes correction
P2 outbound context: empty text and missing source message
P2 protected command still denied by ordinary chat cooldown
P2 stale notice guard=False: transport send invoked once
PASS expiry at 25s and quoted-answer invalidation
```

以下为本轮成功探针原文，可在项目根用上述解释器标准输入复现；不启动应用。AST 隔离仅证明定义本体及所列组合行为，不替代完整插件导入和真实传输验证。

```python
import ast, asyncio, dataclasses, pathlib, sys, types, re, time, json, typing
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from src.services.chat.group import GroupEvent, GroupConversationService

def load(name, path, inject=None):
    tree=ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    tree.body=[n for n in tree.body if not isinstance(n,(ast.Import,ast.ImportFrom))]
    tree.body.insert(0,ast.ImportFrom(module="__future__",names=[ast.alias(name="annotations")],level=0))
    ast.fix_missing_locations(tree)
    mod=types.ModuleType(name); sys.modules[name]=mod
    mod.__dict__.update(dict(Protocol=typing.Protocol,Literal=typing.Literal,asyncio=asyncio,replace=dataclasses.replace,dataclass=dataclasses.dataclass,re=re,time=time,json=json))
    mod.__dict__.update(inject or {})
    exec(compile(tree,path,"exec"),mod.__dict__)
    return mod

intent=load("review_intent","src/services/tools/intent.py",dict(extract_urls=lambda _: []))
part=load("review_part","src/services/chat/pipeline/participation.py",dict(GroupEvent=GroupEvent,GroupConversationService=GroupConversationService,decide_intents=intent.decide_intents))
models=load("review_models","src/services/chat/pipeline/models.py")
policy=load("review_policy","src/services/chat/policy.py")
log=NS(info=lambda *a,**k:None,warning=lambda *a,**k:None,error=lambda *a,**k:None)
admission=load("review_admission","src/services/chat/pipeline/admission.py",dict(logger=log,Admission=models.Admission,should_reply=policy.should_reply))
rhythm=load("review_rhythm","src/services/chat/rhythm.py")

def setup():
    p=part.GroupParticipation(); s=p.service("99"); s.debounce_seconds=0; s.max_wait_seconds=0
    return p,s
def incoming(mid,text="mako 你好"):
    return models.ChatInput(policy.ChatAddress("group",7,1),"synthetic",text,NS(image_urls=[],audio_urls=[],face_ids=[]),True,False,0,"99",mid)

async def main():
    p,s=setup()
    s.observe(GroupEvent("1","a","7","mako 翻译 hello"))
    s.observe(GroupEvent("1","b","8","mako 新问题"))
    assert [x.name for x in intent.decide_intents("mako 翻译 hello",False,False)]==["language.translate"]
    assert await p.prepare(incoming("a","mako 翻译 hello"),NS()) is None
    print("P1 tool superseded before prepare: dropped")

    p,s=setup(); s.observe(GroupEvent("1","a","7","mako 分析数字10"))
    t=NS(); prepared=await p.prepare(incoming("a","mako 分析数字10"),t)
    s.observe(GroupEvent("1","b","7","更正：数字是20"))
    assert t.guard() is True
    assert "数字是20" not in prepared.group_context
    print("P2 refreshed guard=True; generation context excludes correction")

    p,s=setup(); s.observe(GroupEvent("1","a","7","mako 你好"))
    t=NS(); await p.prepare(incoming("a"),t); t.on_sent({"message_id":"bot1"})
    event=s.snapshot("1").events[-1]
    assert event.text=="" and event.reply_to_message_id is None
    print("P2 outbound context: empty text and missing source message")

    p,s=setup(); s.observe(GroupEvent("1","a","7","mako 翻译 hello"))
    t=NS(); prepared=await p.prepare(incoming("a","mako 翻译 hello"),t)
    settings=NS(chat_rhythm_enabled=True,known_bot_user_ids="",parse_int_list=lambda _:[],
        chat_rhythm_window_seconds=60,chat_rhythm_max_cooldown_seconds=300,
        llm_required=False,reply_random_chance=0)
    r=rhythm.ChatRhythmService(storage=NS(redis=None),settings=settings,clock=lambda:100)
    r._memory["group_1"]=rhythm.RhythmState(last_reply_at=95,last_sender_id=7,cooldown_until=150)
    services=NS(settings=settings,chat_rhythm=r,governance=NS(can_chat=lambda *a:NS(allowed=True)))
    assert t.category=="command"
    assert await admission.admit(services,prepared,t) is None
    print("P2 protected command still denied by ordinary chat cooldown")

    # Extract only the real transport class: no plugin registration/import.
    tree=ast.parse(pathlib.Path("src/plugins/chat/ingress.py").read_text(encoding="utf-8"))
    tree.body=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="QQChatTransport"]
    ns=dict(Message=lambda value:value,Matcher=object,MessageEvent=object,Bot=object)
    exec(compile(tree,"src/plugins/chat/ingress.py","exec"),ns)
    matcher=NS(send=AsyncMock())
    t=ns["QQChatTransport"](matcher,NS(),NS()); t.guard=lambda:False
    await t.notice("synthetic failure")
    assert matcher.send.await_count==1
    print("P2 stale notice guard=False: transport send invoked once")

    # Positive boundaries with the unmodified pure group modules.
    p,s=setup(); now=[100.]; s.clock=lambda:now[0]
    s.observe(GroupEvent("1","a","7","mako 你好"))
    t=NS(); await p.prepare(incoming("a"),t)
    now[0]=125.; assert t.guard() is False
    p,s=setup(); s.observe(GroupEvent("1","a","7","mako 你好"))
    t=NS(); await p.prepare(incoming("a"),t)
    s.observe(GroupEvent("1","b","8","回答",reply_to_message_id="a"))
    assert t.guard() is False
    print("PASS expiry at 25s and quoted-answer invalidation")
asyncio.run(main())
```

## 评审快照标识（SHA256，19:10 +08:00）

```text
src/services/chat/group/candidates.py 6CF44106A8C562DBB628577AA731E4CB39A961742BB3F83315A5CE027B13FB75
src/services/chat/group/models.py F9C6D98A9E88504C93E6A8549E3757D3D9435626E6A21B8BEED452675E001BA2
src/services/chat/group/policy.py 78CEB81DAD7612068FBE5FD624CFE3E8F329358117455DD9B9B3040B43663DF7
src/services/chat/group/service.py 4D1965AB79D8F5192D82516FDB859947EF411479EE15E02EB2679385D4492614
src/services/chat/group/window.py 39E2BDF892AD28854F121B4B8D47244D122792923855D7E3B24815F3006FBE9C
src/services/chat/pipeline/participation.py 2B305C34B3305B7EEC387A97F22A94ABA6775B26AFCAD57FA13A9603C3FD72E7
src/services/chat/pipeline/workflow.py 7091BD2E00CD7E56B239DE6052AD0D83543E36D453A35DBB3C518B220D79B23E
src/services/chat/pipeline/admission.py FBB9B2C664FAF1DDA3DD0702D57B0AAD6A7A7CB47A415489C0C6C1E7D1AAEC70
src/services/chat/pipeline/execution.py 49B18CCCC33F11A080A20886AD3987385D011D067DA46AD2CD561CDA5B00234C
src/plugins/chat/ingress.py 86BDF4CED821D0D5B3DDF6EC563E37EDD2AC383ABED9E161BCDDD14165C055F8
src/plugins/chat/delivery.py 058EF01CEE37285E316060D3573711CBE3E4694BA6A3AACADA462CFED30093F9
```
