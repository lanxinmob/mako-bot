"""Read-only projections; paused storage never becomes an empty successful list."""
def snapshot(storage, limit=100):
    try:
        backend = getattr(storage, 'backend', None)
        if backend is None:
            raise RuntimeError('no companion persistence backend')
        from src.core.bootstrap import select_application_plugins
        from src.core.config import get_settings
        from src.services.companion.projection import project
        from src.services.persistence.companion.repository import CompanionRepository
        settings = get_settings()
        enabled = 'companion' in select_application_plugins(settings.parse_name_list(settings.plugin_enable_list))
        repo = CompanionRepository(backend)
        items = []
        for user in repo.users():
            items += [project(repo,p) for p in repo.list(user)]
        return dict(available=True, enabled=enabled, persistence='Redis 已确认',
                    reason='' if enabled else '插件未启用，自动动作暂停',items=items[:limit])
    except Exception:
        return dict(available=False,enabled=False,persistence='存储待确认',reason='计划读取失败或操作结果待确认',items=[])
