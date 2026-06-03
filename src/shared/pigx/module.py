from canary_framework import module

from app import AuthService


@module(name="PigXModule", services=[AuthService])
class PigXModule:
    pass
