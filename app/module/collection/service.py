

from canary_framework import service

from app.module.db.module import DBModule
from app.module.db.repository.collection_item_repository import CollectionItemRepository
from app.module.db.repository.kb_file_repository import KBFileRepository
from app.module.db.repository.knowledge_bases_repository import KnowledgeBaseRepository
from app.module.collection.schema import SubmitUrlRequest


@service()
class CollService:
    collection_repo: CollectionItemRepository
    knowledge_base_repo: KnowledgeBaseRepository
    kb_file_repo: KBFileRepository

    def submit_url(
        self,
        request: SubmitUrlRequest,
        user_id: str = "test_user"
    ) -> tuple[bool, dict | str]:
        try:
            item = self.collection_repo.create_item(
                user_id=user_id,
                url=request.url
            )
            
            return True, {
                "id": item.id,
                "url": request.url,
                "status": "pending"
            }
        except Exception as e:
            return False, str(e)

    def list_items(
        self,
        user_id: str = "test_user",
        page: int = 1,
        size: int = 20
    ) -> tuple[bool, dict | str]:
        try:
            skip = (page - 1) * size
            items = self.collection_repo.list_items_by_user(user_id, skip=skip, limit=size)
            
            records = []
            for item in items:
                records.append({
                    "id": item.id,
                    "url": item.url,
                    "title": item.title,
                    "status": item.status,
                    "is_imported": item.is_imported,
                    "created_at": item.created_at.isoformat()
                })
            
            all_items = self.collection_repo.list_items_by_user(user_id)
            total_count = len(all_items)
            pages = (total_count + size - 1) // size if size > 0 else 0
            
            return True, {
                "records": records,
                "total": total_count,
                "size": size,
                "current": page,
                "pages": pages
            }
        except Exception as e:
            return False, str(e)

    def get_item(
        self,
        item_id: str,
        user_id: str = "test_user"
    ) -> tuple[bool, dict | str]:
        try:
            item = self.collection_repo.get_item(item_id)
            if not item:
                return False, "采集记录不存在"
            if item.user_id != user_id:
                return False, "无权限"
            
            return True, {
                "id": item.id,
                "url": item.url,
                "title": item.title,
                "content": item.content,
                "status": item.status,
                "is_imported": item.is_imported,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat()
            }
        except Exception as e:
            return False, str(e)

    def delete_item(
        self,
        item_id: str,
        user_id: str = "test_user"
    ) -> tuple[bool, str]:
        try:
            item = self.collection_repo.get_item(item_id)
            if not item:
                return False, "采集记录不存在"
            if item.user_id != user_id:
                return False, "无权限"
            
            self.collection_repo.delete_item(item_id)
            
            return True, "删除成功"
        except Exception as e:
            return False, str(e)

    def import_to_kb(
        self,
        item_id: str,
        kb_id: str,
        user_id: str = "test_user"
    ) -> tuple[bool, dict | str]:
        try:
            item = self.collection_repo.get_item(item_id)
            if not item:
                return False, "采集记录不存在"
            if item.user_id != user_id:
                return False, "无权限"
            if item.status != "success":
                return False, "仅成功状态的采集可导入"
            if not item.content:
                return False, "采集无内容"
            if item.is_imported:
                return False, "已导入"
            
            kb = self.knowledge_base_repo.get_knowledge_base(kb_id)
            if not kb:
                return False, "知识库不存在"
            
            title = item.title or item.url.split("/")[-1] or "untitled"
            file_name = title.strip().replace("/", "_")[:200]
            unique_name = self.kb_file_repo.get_unique_name(kb_id, "/", file_name)
            
            file = self.kb_file_repo.create_kb_file(
                kb_id=kb_id,
                name=unique_name,
                created_by=user_id,
                file_type="txt",
                file_size=len(item.content.encode("utf-8")),
                parent_path="/",
                parsed_text=item.content,
                status="parsed"
            )
            
            self.collection_repo.update_item(item_id, is_imported=True)
            
            return True, {
                "file_id": file.id,
                "name": unique_name,
                "status": "parsed"
            }
        except Exception as e:
            return False, str(e)
