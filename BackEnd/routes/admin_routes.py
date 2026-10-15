from fastapi import APIRouter, Depends, HTTPException, status, Query, Header
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import secrets

from database import get_db
from models import APIUsage, User

router = APIRouter(prefix="/admin", tags=["admin"])

load_dotenv()

# Simple admin key auth - required ADMIN_API_KEY env variable, no fallback
ADMIN_API_KEY = os.environ["ADMIN_API_KEY"]


def verify_admin_key(api_key: str = Header(..., alias="X-Admin-Key")):
    """Verify admin API key from the X-Admin-Key request header."""
    if not secrets.compare_digest(api_key.encode("utf-8"), ADMIN_API_KEY.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin key"
        )
    return True


class UsageSummary(BaseModel):
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_combined_tokens: int
    total_cache_read_tokens: int
    total_cache_creation_tokens: int


class UsageRecord(BaseModel):
    id: int
    user_id: int
    username: Optional[str]
    course_id: Optional[int]
    model_used: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    created_at: str


class UsageByUser(BaseModel):
    user_id: int
    username: str
    request_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_combined_tokens: int


@router.get("/usage/summary", response_model=UsageSummary)
def get_usage_summary(
    days: int = Query(default=None, description="Filter to last N days"),
    _: bool = Depends(verify_admin_key),
    db: Session = Depends(get_db)
):
    """Get total token usage summary."""
    query = db.query(
        func.count(APIUsage.id).label("total_requests"),
        func.coalesce(func.sum(APIUsage.input_tokens), 0).label("total_input"),
        func.coalesce(func.sum(APIUsage.output_tokens), 0).label("total_output"),
        func.coalesce(func.sum(APIUsage.total_tokens), 0).label("total_combined"),
        func.coalesce(func.sum(APIUsage.cache_read_tokens), 0).label("cache_read"),
        func.coalesce(func.sum(APIUsage.cache_creation_tokens), 0).label("cache_create"),
    )

    if days:
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = query.filter(APIUsage.created_at >= cutoff)

    result = query.first()

    return UsageSummary(
        total_requests=result.total_requests or 0,
        total_input_tokens=result.total_input or 0,
        total_output_tokens=result.total_output or 0,
        total_combined_tokens=result.total_combined or 0,
        total_cache_read_tokens=result.cache_read or 0,
        total_cache_creation_tokens=result.cache_create or 0
    )


@router.get("/usage/records", response_model=List[UsageRecord])
def get_usage_records(
    limit: int = Query(default=50, le=500),
    days: int = Query(default=None, description="Filter to last N days"),
    user_id: int = Query(default=None, description="Filter by user ID"),
    _: bool = Depends(verify_admin_key),
    db: Session = Depends(get_db)
):
    """Get individual usage records."""
    query = db.query(APIUsage, User.username).outerjoin(User, APIUsage.user_id == User.id)

    if days:
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = query.filter(APIUsage.created_at >= cutoff)

    if user_id:
        query = query.filter(APIUsage.user_id == user_id)

    records = query.order_by(APIUsage.created_at.desc()).limit(limit).all()

    return [
        UsageRecord(
            id=usage.id,
            user_id=usage.user_id,
            username=username,
            course_id=usage.course_id,
            model_used=usage.model_used,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_creation_tokens=usage.cache_creation_tokens,
            created_at=usage.created_at.isoformat()
        )
        for usage, username in records
    ]


@router.get("/usage/by-user", response_model=List[UsageByUser])
def get_usage_by_user(
    days: int = Query(default=None, description="Filter to last N days"),
    _: bool = Depends(verify_admin_key),
    db: Session = Depends(get_db)
):
    """Get token usage grouped by user."""
    query = db.query(
        APIUsage.user_id,
        User.username,
        func.count(APIUsage.id).label("request_count"),
        func.coalesce(func.sum(APIUsage.input_tokens), 0).label("total_input"),
        func.coalesce(func.sum(APIUsage.output_tokens), 0).label("total_output"),
        func.coalesce(func.sum(APIUsage.total_tokens), 0).label("total_combined"),
    ).outerjoin(User, APIUsage.user_id == User.id).group_by(APIUsage.user_id, User.username)

    if days:
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = query.filter(APIUsage.created_at >= cutoff)

    results = query.order_by(func.sum(APIUsage.total_tokens).desc()).all()

    return [
        UsageByUser(
            user_id=r.user_id,
            username=r.username or "Unknown",
            request_count=r.request_count,
            total_input_tokens=r.total_input,
            total_output_tokens=r.total_output,
            total_combined_tokens=r.total_combined
        )
        for r in results
    ]
