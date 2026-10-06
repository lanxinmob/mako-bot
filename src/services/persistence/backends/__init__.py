"""Shared backend and explicit repository dependencies."""
from .redis import StorageBackend


class Repository:
    def __init__(self, backend: StorageBackend):
        self.backend = backend

    @property
    def redis(self):
        return self.backend.redis

    @property
    def settings(self):
        return self.backend.settings
