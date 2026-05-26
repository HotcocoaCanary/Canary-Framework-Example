from fastapi import Depends, Query

from app.common.depends import get_current_user
from app.module.knowledge_module.schema import (
    ViewParsedRequest,
    UpdateParsedRequest,
    ChunkRequest,
)
from canary_framework import (Context)
from canary_framework.web.fastapi import router, get, post, put


@router(prefix="/api/v1/knowledge-bases/file-op")
class ParseRouter:
    def __init__(self, ctx: Context):
        from app.module.knowledge_module.service.parse_service import ParseService
        self.svc = ctx.resolve(ParseService)

    @get("/{kb_id}/parse-tasks", tags=["解析任务"], summary="解析任务列表",
         description="获取知识库下所有解析任务及其关联文件的状态")
    async def list_tasks(
            self,
            kb_id: str,
            current: int = Query(1, description="页码"),
            size: int = Query(20, description="每页大小"),
            user=Depends(get_current_user),
    ):
        return await self.svc.list_tasks(kb_id, user, current, size)

    @post("/{kb_id}/parse-tasks/{task_id}/parsed", tags=["解析任务"], summary="查看解析文本")
    async def view_parsed(
            self,
            kb_id: str,
            task_id: str,
            req: ViewParsedRequest,
            user=Depends(get_current_user),
    ):
        return await self.svc.view_parsed(kb_id, task_id, user, req)

    @put("/{kb_id}/parse-tasks/{task_id}/parsed", tags=["解析任务"], summary="修改解析文本",
          description="仅 parsed 状态的文件可修改")
    async def update_parsed(
            self,
            kb_id: str,
            task_id: str,
            req: UpdateParsedRequest,
            user=Depends(get_current_user),
    ):
        return await self.svc.update_parsed(kb_id, task_id, user, req)

    @post("/{kb_id}/parse-tasks/{task_id}/chunk", tags=["解析任务"], summary="提交分块",
          description="仅 parsed 状态的文件可提交，提交后进入后台队列执行分块+embedding+入库")
    async def submit_chunk(
            self,
            kb_id: str,
            task_id: str,
            req: ChunkRequest,
            user=Depends(get_current_user),
    ):
        return await self.svc.submit_chunk(kb_id, task_id, user, req)
