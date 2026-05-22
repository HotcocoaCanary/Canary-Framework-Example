class AppError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message


class NotFoundError(AppError):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(404, message)


class ForbiddenError(AppError):
    def __init__(self, message: str = "无权限"):
        super().__init__(403, message)


class InvalidStateError(AppError):
    def __init__(self, message: str = "状态冲突"):
        super().__init__(409, message)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "未登录"):
        super().__init__(401, message)
