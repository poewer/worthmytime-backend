from sanic.exceptions import SanicException


class ApiError(SanicException):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message, status_code=status_code)
