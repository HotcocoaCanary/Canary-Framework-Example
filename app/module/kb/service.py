from canary_framework import service

from app.module.db.module import DBModule


@service(deps=[DBModule])
class KbService:
    pass