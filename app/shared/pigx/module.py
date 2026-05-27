from canary_framework import module

from app.shared.pigx.service.auth_service import AuthService


@module(name="PigXModule", services=[AuthService])
class PigXModule:
    pass
