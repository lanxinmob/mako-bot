"""Read-only control status and safe current-data projection."""
from src.services.memory.ledger.runtime import for_storage, repository, MemoryView
from src.services.persistence.ledger import LedgerUnavailable


def controls(storage, summary):
    users = {m.user_id for m in summary.relationship_memories}
    users.update(int(p['user_id']) for p in summary.profiles)
    repo = repository(storage)
    try:
        if repo:
            users.update(repo.users())
        return {user: for_storage(storage, [user]) for user in sorted(users)}
    except LedgerUnavailable:
        return {**{user: for_storage(storage, [user]) for user in sorted(users)}, None: MemoryView(repo, available=False)}


def status(view):
    return dict(mode='账本优先；旧画像暂停使用' if view.controlled else '原有记忆模式',
                persistence='Redis 已确认' if view.available and view.repo and view.repo.backend.redis else
                '内存合成验证' if view.available else '记忆控制读取失败')


def current_summary(summary, views):
    return summary.model_copy(update={
        'profiles': [dict(p, ledger=status(views[int(p['user_id'])]),
                          profile_state='历史档案，暂停使用' if views[int(p['user_id'])].controlled else '原有画像')
                     for p in summary.profiles],
        'relationship_memories': [m for m in summary.relationship_memories if views[m.user_id].available],
        'notes': [n for n in summary.notes if n.category != 'relationship' or
                  (n.user_id in views and views[n.user_id].available)],
    })


def annotate(people, views):
    for person in people:
        view = views[person['user_id']]
        person['ledger'] = status(view)
        if view.controlled:
            person['focus'] = '历史档案，暂停使用'
            person['preferences'] = []
            person['tags'] = ['历史档案，暂停使用']
    return people
