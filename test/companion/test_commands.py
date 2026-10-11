from datetime import datetime
import pytest
from src.services.companion.commands import invoked,parse,instant,ZONE


@pytest.mark.parametrize('text',[
    '创建考试计划 A | 考试=2026-10-09 15:00 | 提醒=2026-10-09 13:00 | 任务=a；',
    '创建考试计划 A | 考试=2026-10-09 15:00 | 提醒=2026-10-09 13:00 | 任务=a；b；c；d',
    '创建考试计划 A | 考试=2026-10-09 15:00 | 提醒=2026-10-09 13:00 | 任务=https://secret.invalid',
    '创建考试计划 A | 考试=2026-10-09 15:00 | 考试=2026-10-10 15:00 | 提醒=2026-10-09 13:00 | 任务=a',
    '同意回顾 123456abcdef 明天晚上', '提交回顾 123456abcdef 完成=4 | 感受=a | 下次=b',
    '修改计划 123456abcdef user_id=102','忘掉计划 123456abcdef 102',
    '创建考试计划 A | 考试=2026-10-09 15:00 | 提醒=2026-10-09 13:00 | 任务=token=secret',
    '创建考试计划 A | 考试=2026-10-09 15:00 | 提醒=2026-10-09 13:00 | 任务=a\nb',
])
def test_invalid_controls_never_fall_through_to_chat(text):
    assert invoked(text)
    with pytest.raises(ValueError):
        parse(text)


def test_fixed_zone_and_task_set_no_inference():
    assert instant('2026-10-09 15:00') == int(datetime(2026,10,9,15,tzinfo=ZONE).timestamp()*1000)
    command = parse('/提交回顾 123456abcdef 完成=2,1,2 | 感受=紧张 | 下次=提前复习')
    assert command.fields['completed'] == [1,2]
    assert parse('提交回顾 123456abcdef 完成=无 | 感受=一般 | 下次=复习').fields['completed'] == []
    assert parse('他说“同意回顾 123456abcdef 明天”') is None
