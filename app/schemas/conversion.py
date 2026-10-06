from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator, ConfigDict

VALID_OUTPUT_FORMATS = {"xlsx", "docx", "pptx"}


class ConversionCreateRequest(BaseModel):
    file_id: int
    output_format: str

    @field_validator("output_format")
    @classmethod
    def valid_format(cls, v: str) -> str:
        if v not in VALID_OUTPUT_FORMATS:
            raise ValueError(f"output_format must be one of {sorted(VALID_OUTPUT_FORMATS)}")
        return v


class ConversionJobOut(BaseModel):
    id: int
    file_id: Optional[int]
    input_format: str
    output_format: str
    page_count: Optional[int]
    status: str
    output_filename: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)
