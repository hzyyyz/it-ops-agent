"""Single local administrator bearer-token boundary for data APIs."""

import os
from pathlib import Path
from secrets import compare_digest

from dotenv import load_dotenv
from fastapi import Header, HTTPException


def require_admin(authorization: str | None = Header(default=None)) -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    expected = os.getenv("AGENT_ADMIN_TOKEN", "")
    if len(expected) < 32 or expected.startswith("replace-with-"):
        raise HTTPException(status_code=503, detail="管理员口令未配置或长度不足 32 个字符。")
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="管理员口令无效。",
                            headers={"WWW-Authenticate": "Bearer"})
