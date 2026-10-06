from __future__ import annotations

import time
from datetime import datetime

from nonebot.adapters.onebot.v11 import Message
from nonebot.log import logger

from src.core.config import get_settings
from src.services.governance.service import GovernanceService
from src.services.memory.mako_context import MakoRuntimeContext
from src.services.delivery.dedup import OutboundDedupService
from src.services.persistence.backends.redis import get_redis
from src.services.persistence import StorageService

from src.services.autonomy.repository import AutonomyRepository
from src.services.autonomy.policy import AutonomyPolicy


settings = get_settings()
storage = StorageService()
governance = GovernanceService()
outbound_dedup = OutboundDedupService(storage)
runtime_context = MakoRuntimeContext(storage)
redis_client = get_redis()

repository = AutonomyRepository(settings, redis_client, storage, clock=time.time, datetime=datetime,
                                logger=logger, redis_provider=get_redis)
policy = AutonomyPolicy(settings, repository, logger=logger)
pending_memory = repository.pending_memory
cooldown_memory = repository.cooldown_memory
allowlist_memory = repository.allowlist_memory


from src.services.autonomy.context import AutonomyContext

context = AutonomyContext(settings, storage, governance, outbound_dedup, runtime_context, repository, policy, time.time, Message)
