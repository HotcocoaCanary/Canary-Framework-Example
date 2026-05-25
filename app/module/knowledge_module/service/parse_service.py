import logging

from fastapi import HTTPException

from app.module.db_module.service import DBService
from app.module.knowledge_module.router.parse_router import ParseRouter
from app.module.knowledge_module.schema import (
    ParseTaskResponse,
    ParseTaskFileItem,
    ParsedFileResponse,
    ViewParsedRequest,
    UpdateParsedRequest,
    ChunkRequest,
    ChunkResultResponse,
    ChunkedFileItem,
)
from app.module.knowledge_module.state_machine import can_edit_parsed, can_chunk
from app.common.response import R
from app.common.types import UserContext
from app.shared.worker.chunk_worker import ChunkWorker
from app.shared.worker.parse_worker import ParseWorker
from canary_framework import service, on_init, Context
from canary_framework.web.fastapi import web

logger = logging.getLogger(__name__)


@web(routers=[ParseRouter])
@service(name="ParseService", deps=[DBService, ParseWorker, ChunkWorker])
class ParseService:
    @on_init
    def init(self, ctx: Context):
        pass

    async def list_tasks(self, kb_id: str, user: UserContext, current: int = 1, size: int = 20) -> R[dict]:
        async with self.db_service.transaction() as session:
            parse_repo = self.db_service.parse_repo(session)
            file_record_repo = self.db_service.file_record_repo(session)
            node_repo = self.db_service.node_repo(session)

            tasks, total = await parse_repo.list_by_kb(kb_id, current, size)

            records = []
            for task in tasks:
                file_records = await file_record_repo.get_by_parse_task(task.id)
                file_list = []
                for fr in file_records:
                    node = await node_repo.get_by_id(fr.file_id)
                    file_list.append(ParseTaskFileItem(
                        file_id=fr.file_id,
                        file_name=node.name if node else "",
                        file_type=node.node_type if node else None,
                        status=fr.status,
                        error_msg=fr.error_msg,
                    ))
                records.append(ParseTaskResponse(
                    parse_task_id=task.id,
                    file_list=file_list,
                    created_at=task.created_at,
                ))

            pages = (total + size - 1) // size if size > 0 else 0
            return R.ok({
                "records": [r.model_dump() for r in records],
                "total": total,
                "size": size,
                "current": current,
                "pages": pages,
            })

    async def view_parsed(self, kb_id: str, task_id: str, user: UserContext, req: ViewParsedRequest) -> R[
        list[ParsedFileResponse]]:
        async with self.db_service.transaction() as session:
            file_record_repo = self.db_service.file_record_repo(session)
            node_repo = self.db_service.node_repo(session)

            records = await file_record_repo.get_by_file_ids(req.file_ids)
            result = []
            for r in records:
                node = await node_repo.get_by_id(r.file_id)
                if node:
                    result.append(ParsedFileResponse(
                        file_id=r.file_id,
                        file_name=node.name,
                        file_type=node.node_type,
                        parsed_text=r.parsed_text,
                        status=r.status,
                        updated_at=r.updated_at,
                    ))
            return R.ok(result)

    async def update_parsed(self, kb_id: str, task_id: str, user: UserContext, req: UpdateParsedRequest) -> R[
        list[ParsedFileResponse]]:
        async with self.db_service.transaction() as session:
            file_record_repo = self.db_service.file_record_repo(session)
            node_repo = self.db_service.node_repo(session)

            result = []
            for file_item in req.files:
                record = await file_record_repo.get_by_file_id(file_item.file_id)
                if not record:
                    raise HTTPException(status_code=404, detail=f"文件 {file_item.file_id} 不存在")
                if not can_edit_parsed(record.status):
                    raise HTTPException(status_code=409,
                                        detail=f"文件 {file_item.file_id} 状态为 {record.status}，不允许修改解析文本")

                record.parsed_text = file_item.parsed_text
                await file_record_repo.update(record)

                node = await node_repo.get_by_id(record.file_id)
                result.append(ParsedFileResponse(
                    file_id=record.file_id,
                    file_name=node.name if node else "",
                    file_type=node.node_type if node else None,
                    parsed_text=record.parsed_text,
                    status=record.status,
                    updated_at=record.updated_at,
                ))

            logger.info(f"Parsed text updated for task {task_id}")
            return R.ok(result)

    async def submit_chunk(self, kb_id: str, task_id: str, user: UserContext, req: ChunkRequest) -> R[
        ChunkResultResponse]:
        async with self.db_service.transaction() as session:
            file_record_repo = self.db_service.file_record_repo(session)
            node_repo = self.db_service.node_repo(session)

            records = await file_record_repo.get_by_file_ids(req.file_ids)
            for r in records:
                if not can_chunk(r.status):
                    raise HTTPException(status_code=409,
                                        detail=f"文件 {r.file_id} 状态为 {r.status}，需要先解析再提交分块")

            self.chunk_worker.submit({
                "kb_id": kb_id,
                "task_id": task_id,
                "file_ids": req.file_ids,
            })

            chunked_files = []
            for r in records:
                r.status = "processing"
                await file_record_repo.update(r)
                chunked_files.append(ChunkedFileItem(
                    file_id=r.file_id,
                    chunk=[],
                    status="pending",
                ))

            logger.info(f"Chunk submitted for task {task_id}")
            return R.ok(ChunkResultResponse(
                task_id=task_id,
                chunked_files=chunked_files,
            ))
