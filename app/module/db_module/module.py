from app.module.db_module.config import DBConfig
from app.module.db_module.service import DBService
from cf import module


@module(name="DBModule", services=[DBService], config=DBConfig)
class DBModule:
    pass
