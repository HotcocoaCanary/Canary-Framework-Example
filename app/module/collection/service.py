from canary_framework import service
from canary_framework.core.service import ServiceBase

from app.module.collection.schema import SubmitUrlRequest
from app.module.db.repository.collection_item_repository import CollectionItemRepository


@service()
class CollService(ServiceBase):
    collection_repo: CollectionItemRepository

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
