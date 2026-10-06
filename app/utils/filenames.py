"""
Never trust the filename the browser sends. This generates a random,
collision-proof storage key while keeping a sanitized version of the
original name only for display purposes (shown to the user, never used
as a real filesystem path).
"""

import re
import uuid

SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_display_name(original_filename: str) -> str:
    """Strips path separators and weird characters for safe display/DB storage.
    This is NOT used to build a filesystem path — see generate_storage_key()."""
    name = original_filename.replace("\\", "/").split("/")[-1]  # strip any path components
    name = SAFE_CHARS.sub("_", name)
    return name[:255] or "file"


def generate_storage_key(user_id: int, subfolder: str, extension: str) -> str:
    """Returns a storage key like 'user_3/uploads/8f14e...c2.pdf' — fully
    server-generated, no user input, so there's no path-traversal risk."""
    extension = extension.lstrip(".").lower()
    extension = SAFE_CHARS.sub("", extension) or "bin"
    return f"user_{user_id}/{subfolder}/{uuid.uuid4().hex}.{extension}"
