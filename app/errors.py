from sanic.exceptions import SanicException


class ApiError(SanicException):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        errors: list[dict] | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message, status_code=status_code)
        self.errors = errors
        self.headers = headers or {}
