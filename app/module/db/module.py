from canary_framework import module
from canary_framework.core.module import ModuleBase

from app.module.db.repository.collection_item_repository import CollectionItemRepository
from app.module.db.repository.kb_chunk_repository import KbChunkRepository
from app.module.db.repository.kb_file_repository import KBFileRepository
from app.module.db.repository.kb_member_repostory import KBMemberRepository
from app.module.db.repository.knowledge_bases_repository import KnowledgeBaseRepository
from app.module.db.repository.message_repository import MessageRepository
from app.module.db.repository.session_repository import SessionRepository


@module(
    services=[
        SessionRepository,
        MessageRepository,
        KnowledgeBaseRepository,
        KBMemberRepository,
        KBFileRepository,
        KbChunkRepository,
        CollectionItemRepository,
    ]
)
class DBModule(ModuleBase):
    pass
