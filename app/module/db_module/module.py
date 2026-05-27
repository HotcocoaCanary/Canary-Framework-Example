from canary_framework import module

from app.module.db_module.service import DBService


@module(name="DBModule", services=[DBService])
class DBModule:
    pass
