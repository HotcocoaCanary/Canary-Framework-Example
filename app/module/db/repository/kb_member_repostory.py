from datetime import datetime
from typing import Optional, Any, Sequence

from canary_framework import after_config, after_init
from canary_framework.decorators import service
from sqlalchemy import create_engine
from sqlmodel import Session, select

from app.config import AppConfig
from app.module.db.models import KbMember


@service()
class KBMemberRepository:
    config: AppConfig

    def __init__(self):
        self.engine = None
        self.session = None
        self.database_url = None

    @after_config
    def after_config(self):
        self.database_url = self.config.database_url

    @after_init
    def after_init(self):
        self.engine = create_engine(self.database_url, echo=True)

    def get_session(self):
        return Session(self.engine)

    def add_member(self, kb_id: str, user_id: str, role: str = "member") -> KbMember:
        with self.get_session() as session:
            member = KbMember(
                kb_id=kb_id,
                user_id=user_id,
                role=role,
                joined_at=datetime.utcnow(),
            )
            session.add(member)
            session.commit()
            session.refresh(member)
            return member

    def get_member(self, kb_id: str, user_id: str) -> type[KbMember] | None:
        with self.get_session() as session:
            return session.get(KbMember, (kb_id, user_id))

    def update_member_role(self, kb_id: str, user_id: str, new_role: str) -> type[KbMember] | None:
        with self.get_session() as session:
            member = session.get(KbMember, (kb_id, user_id))
            if not member:
                return None
            member.role = new_role
            session.add(member)
            session.commit()
            session.refresh(member)
            return member

    def remove_member(self, kb_id: str, user_id: str) -> bool:
        with self.get_session() as session:
            member = session.get(KbMember, (kb_id, user_id))
            if not member:
                return False
            session.delete(member)
            session.commit()
            return True

    def remove_members_by_kb(self, kb_id: str) -> int:
        with self.get_session() as session:
            statement = select(KbMember).where(KbMember.kb_id == kb_id)
            members = session.exec(statement).all()
            count = 0
            for member in members:
                session.delete(member)
                count += 1
            session.commit()
            return count

    def list_kb_members(self, kb_id: str) -> Sequence[Any]:
        with self.get_session() as session:
            statement = select(KbMember).where(KbMember.kb_id == kb_id)
            return session.exec(statement).all()

    def list_user_kbs(self, user_id: str) -> Sequence[str]:
        with self.get_session() as session:
            statement = select(KbMember).where(KbMember.user_id == user_id)
            members = session.exec(statement).all()
            return [m.kb_id for m in members]
