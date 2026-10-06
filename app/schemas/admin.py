from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class AdminUserOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    is_active: bool
    is_verified: bool
    is_admin: bool
    created_at: datetime
    last_login_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class AdminUserUpdateRequest(BaseModel):
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None


class AdminConversionOut(BaseModel):
    id: int
    user_id: int
    user_email: str
    output_format: str
    status: str
    output_filename: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class AdminStatsOut(BaseModel):
    total_users: int
    active_users: int
    total_files: int
    total_conversions: int
    conversions_completed: int
    conversions_failed: int
    conversions_pending_or_processing: int
