from pydantic import BaseModel


class UserUpdateRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
