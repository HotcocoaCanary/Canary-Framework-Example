from app.shared.pigx.config import PigXConfig
from app.shared.pigx.service.auth_service import AuthService
from canary_framework import module


@module(name="PigXModule", services=[AuthService], config=PigXConfig)
class PigXModule:
    pass
