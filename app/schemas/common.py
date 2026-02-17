from pydantic import BaseModel


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


class PaginatedResponse(BaseModel):
    data: list
    total: int
    limit: int
    offset: int
