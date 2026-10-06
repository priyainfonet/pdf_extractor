"""
One-off CLI to grant admin rights to an existing user, since the API
can't do this for the very first admin (require_admin needs an admin to
already exist to call it).

Usage (from the backend/ directory, venv active):
    python -m app.scripts.make_admin someone@example.com
"""

import sys

from app.core.database import SessionLocal
from app.models.user import User


def make_admin(email: str) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email.lower().strip()).first()
        if not user:
            print(f"No user found with email: {email}")
            sys.exit(1)

        if user.is_admin:
            print(f"{email} is already an admin.")
            return

        user.is_admin = True
        db.commit()
        print(f"{email} is now an admin.")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m app.scripts.make_admin <email>")
        sys.exit(1)
    make_admin(sys.argv[1])
