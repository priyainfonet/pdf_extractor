from datetime import datetime
from pydantic import BaseModel, ConfigDict


class FileOut(BaseModel):
    id: int
    original_filename: str
    file_size: int
    mime_type: str
    page_count: int | None
    uploaded_at: datetime

    model_config = ConfigDict(from_attributes=True)
