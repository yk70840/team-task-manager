from datetime import timedelta
from typing import Optional
import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import Request
from app.models import User


SESSION_NAME = "session_id"
SESSION_LIFETIME = timedelta(days=1)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


async def get_session_user(request: Request, db: AsyncSession) -> Optional[User]:
    session_token = request.cookies.get(SESSION_NAME)
    if not session_token:
        return None

    try:
        from itsdangerous import URLSafeTimedSerializer
        from app.config import SECRET_KEY

        serializer = URLSafeTimedSerializer(SECRET_KEY)
        session_data = serializer.loads(
            session_token, max_age=int(SESSION_LIFETIME.total_seconds())
        )
        user_id = session_data.get("user_id")

        if user_id:
            user = await db.get(User, user_id)
            if user and user.is_active is True:
                return user
    except Exception:
        return None

    return None


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalars().first()


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalars().first()
