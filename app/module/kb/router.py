from canary_framework import post, get, delete, patch
from canary_framework.decorators import router

from app.module.kb.schema import CreateKbRequest, KbResponse, UpdateKbRequest
from app.common.response import R, PageR
from app.module.kb.service import KbService


@router(prefix='/kb', deps=[KbService], tags=["kb"])
class KBRouter:

    # CRUD
    @post(
        path='/op',
        summary="创建知识库",
        description="传入必要参数，为当前用户创建知识库",
        request_model=CreateKbRequest,
        response_model=R[str],
        responses={
            "200": R[str],
            "400": R[str],
            "401": R[str],
            "500": R[str],
        }
    )
    def op_create(self, request: CreateKbRequest):
        states, res = self.kb_service.create_kb(request)
        return R.ok(res) if states else R.fail(res)

    @get(
        path='/op?page={page}#count={count}',
        summary="查询知识库列表",
        description="传入分页参数，获取知识库列表，已经过滤当前用户权限",
        response_model=PageR[KbResponse],
        responses={
            "200": PageR[KbResponse],
            "400": R[str],
            "401": R[str],
            "500": R[str],
        }
    )
    def op_get(self, page: int, count: int):
        pass

    @delete(
        path='/op/{kb_id}',
        summary="删除知识库",
        description="根据kb_id删除知识库",
        response_model=R[str],
        responses={
            "200": R[str],
            "400": R[str],
            "401": R[str],
            "500": R[str],
        }
    )
    def op_delete(self, kb_id):
        pass

    @patch(
        path='/op/{kb_id}',
        summary="更新知识库",
        description="根据kb_id更新知识库",
        request_model=UpdateKbRequest,
        response_model=R[str],
        responses={
            "200": R[str],
            "400": R[str],
            "401": R[str],
            "500": R[str],
        }
    )
    def op_patch(self, request: UpdateKbRequest):
        pass
