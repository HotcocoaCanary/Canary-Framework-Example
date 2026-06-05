from canary_framework import service
from canary_framework.core.service import ServiceBase

from app.module.db.repository.kb_chunk_repository import KbChunkRepository
from app.module.db.repository.kb_file_repository import KBFileRepository
from app.module.db.repository.knowledge_bases_repository import KnowledgeBaseRepository
from app.module.file.schema import CreateFileRequest, PatchFileRequest


@service()
class FileService(ServiceBase):
    knowledge_base_repo: KnowledgeBaseRepository
    kb_file_repo: KBFileRepository
    kb_chunk_repo: KbChunkRepository

    def _join_path(self, parent: str, name: str) -> str:
        parent = parent.rstrip("/")
        name = name.strip("/")
        if not parent:
            return "/" + name
        return parent + "/" + name

    def _parse_path(self, folder_path: str) -> tuple[str, str]:
        folder_path = folder_path.strip("/")
        if not folder_path:
            return "/", ""
        parts = folder_path.rsplit("/", 1)
        if len(parts) == 1:
            return "/", parts[0]
        return "/" + parts[0], parts[1]

    async def _ensure_folder_path(self, kb_id: str, folder_path: str, user_id: str) -> None:
        if not folder_path or folder_path == "/":
            return
        parts = folder_path.strip("/").split("/")
        current = ""
        for idx, part in enumerate(parts):
            current_path = "/" + part if not current else current + "/" + part
            parent_path = "/" + "/".join(parts[:idx]) if idx > 0 else "/"
            if idx == 0:
                parent_path = "/"
            existing = self.kb_file_repo.get_kb_file_by_path(kb_id, parent_path, part)
            if not existing:
                self.kb_file_repo.create_kb_file(
                    kb_id=kb_id,
                    name=part,
                    created_by=user_id,
                    file_type=None,
                    parent_path=parent_path
                )
            current = current_path

    def create(
            self,
            kb_id: str,
            folder_path: str,
            body: CreateFileRequest,
            user_id: str = "test_user"
    ) -> tuple[bool, dict | str]:
        try:
            kb = self.knowledge_base_repo.get_knowledge_base(kb_id)
            if not kb:
                return False, "知识库不存在"
            if kb.created_by != user_id:
                return False, "仅创建者可操作"

            parent_path, name = self._parse_path(folder_path)
            if not name:
                return False, "路径中缺少文件名"

            self._ensure_folder_path(kb_id, parent_path, user_id)

            unique_name = self.kb_file_repo.get_unique_name(kb_id, parent_path, name)
            file = self.kb_file_repo.create_kb_file(
                kb_id=kb_id,
                name=unique_name,
                created_by=user_id,
                file_type=body.file_type,
                parent_path=parent_path
            )

            return True, {"file_id": file.id, "name": unique_name, "file_type": body.file_type}
        except Exception as e:
            return False, str(e)

    def list_nodes(
            self,
            kb_id: str,
            folder_path: str,
            user_id: str = "test_user",
            page: int = 1,
            size: int = 20
    ) -> tuple[bool, dict | str]:
        try:
            kb = self.knowledge_base_repo.get_knowledge_base(kb_id)
            if not kb:
                return False, "知识库不存在"

            folder_path = "/" + folder_path.strip("/") if folder_path.strip("/") else "/"

            skip = (page - 1) * size
            files, total = self.kb_file_repo.list_children(kb_id, folder_path, skip=skip, limit=size)

            records = []
            for f in files:
                records.append({
                    "file_id": f.id,
                    "name": f.name,
                    "file_type": f.file_type,
                    "file_size": f.file_size if f.file_type else None,
                    "status": f.status,
                    "updated_at": f.updated_at.isoformat()
                })

            pages = (total + size - 1) // size if size > 0 else 0
            return True, {
                "records": records,
                "total": total,
                "size": size,
                "current": page,
                "pages": pages
            }
        except Exception as e:
            return False, str(e)

    def delete_by_path(
            self,
            kb_id: str,
            folder_path: str,
            user_id: str = "test_user"
    ) -> tuple[bool, str]:
        try:
            kb = self.knowledge_base_repo.get_knowledge_base(kb_id)
            if not kb:
                return False, "知识库不存在"
            if kb.created_by != user_id:
                return False, "仅创建者可操作"

            parent_path, name = self._parse_path(folder_path)
            if not name:
                return False, "路径中缺少文件名"

            parent_path = "/" + parent_path.strip("/") if parent_path.strip("/") else "/"

            f = self.kb_file_repo.get_kb_file_by_path(kb_id, parent_path, name)
            if not f:
                return False, "文件/文件夹不存在"

            if f.file_type is None:
                all_files = self.kb_file_repo.list_files_by_kb(kb_id)
                prefix = self._join_path(parent_path, name)
                for child in all_files:
                    if child.parent_path and (
                            child.parent_path == prefix or child.parent_path.startswith(prefix + "/")):
                        self.kb_chunk_repo.delete_chunks_by_file(child.id)
                        self.kb_file_repo.delete_kb_file(child.id)
                self.kb_file_repo.delete_kb_file_by_path(kb_id, parent_path, name)
            else:
                self.kb_chunk_repo.delete_chunks_by_file(f.id)
                self.kb_file_repo.delete_kb_file(f.id)

            return True, "删除成功"
        except Exception as e:
            return False, str(e)

    def update_by_path(
            self,
            kb_id: str,
            folder_path: str,
            body: PatchFileRequest,
            user_id: str = "test_user"
    ) -> tuple[bool, dict | str]:
        try:
            kb = self.knowledge_base_repo.get_knowledge_base(kb_id)
            if not kb:
                return False, "知识库不存在"
            if kb.created_by != user_id:
                return False, "仅创建者可操作"

            parent_path, name = self._parse_path(folder_path)
            if not name:
                return False, "路径中缺少文件名"

            parent_path = "/" + parent_path.strip("/") if parent_path.strip("/") else "/"

            f = self.kb_file_repo.get_kb_file_by_path(kb_id, parent_path, name)
            if not f:
                return False, "文件不存在"

            update_kwargs = {}
            if body.name is not None:
                update_kwargs["name"] = body.name
            if body.status is not None:
                update_kwargs["status"] = body.status

            if update_kwargs:
                updated = self.kb_file_repo.update_kb_file(f.id, **update_kwargs)
                if updated:
                    return True, {
                        "file_id": updated.id,
                        "name": updated.name,
                        "file_type": updated.file_type,
                        "status": updated.status,
                    }

            return True, {
                "file_id": f.id,
                "name": f.name,
                "file_type": f.file_type,
                "status": f.status,
            }
        except Exception as e:
            return False, str(e)
