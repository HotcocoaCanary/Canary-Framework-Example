from canary_framework import module

from app.module.db_module.config import DBConfig
from app.module.db_module.service import DBService


@module(name="DBModule", services=[DBService], config=DBConfig)
class DBModule:
    pass
