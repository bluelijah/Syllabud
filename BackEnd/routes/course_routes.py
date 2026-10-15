from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv
import os
import logging

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from database import get_db
from models import User, UserPreferences, Course, APIUsage
from auth import get_current_user
from course_creator import (
    CourseCreator,
    CourseCreatorError,
    CourseCreatorBusyError,
    UserProfile,
    CourseRequest,
    LearningStyle,
    EducationLevel,
    LearnerMotivation
)

router = APIRouter(prefix="/courses", tags=["courses"])

# Initialize CourseCreator (singleton pattern for efficiency)
_course_creator: Optional[CourseCreator] = None


def get_course_creator() -> CourseCreator:
    """Get or create the CourseCreator singleton."""
    global _course_creator
    if _course_creator is None:
        try:
            _course_creator = CourseCreator()
        except CourseCreatorError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to initialize course creator: {str(e)}"
            )
    return _course_creator


# ============================================================================
# Pydantic Schemas for API
# ============================================================================

class CourseCreateRequest(BaseModel):
    """Request body for creating a new course."""
    query: str = Field(..., min_length=1, max_length=500, description="The topic to learn")
    depth: int = Field(default=5, ge=1, le=10, description="Depth level 1-10")

    # Optional advanced options
    specific_goals: Optional[str] = Field(None, description="Specific learning goals")
    focus_areas: Optional[List[str]] = Field(None, description="Subtopics to emphasize")
    exclude_topics: Optional[List[str]] = Field(None, description="Topics to skip")
    time_constraint: Optional[str] = Field(None, description="Time constraint e.g., '2 weeks'")


class CourseResponse(BaseModel):
    """Response body for course operations."""
    id: int
    title: str
    query: str
    depth: int
    content: str
    created_at: str

    class Config:
        from_attributes = True


class CourseListItem(BaseModel):
    """Simplified course item for listing."""
    id: int
    title: str
    query: str
    depth: int
    created_at: str

    class Config:
        from_attributes = True


class CourseGenerationStats(BaseModel):
    """Statistics from course generation."""
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    model_used: str


class CourseCreateResponse(BaseModel):
    """Extended response including generation stats."""
    course: CourseResponse
    generation_stats: CourseGenerationStats


# ============================================================================
# Helper Functions
# ============================================================================

def build_user_profile(user: User, prefs: Optional[UserPreferences]) -> UserProfile:
    """
    Convert database User and UserPreferences to a UserProfile for course generation.
    """
    # Map learning style string to enum
    learning_style = None
    if prefs and prefs.learning_style:
        style_map = {
            "visual": LearningStyle.VISUAL,
            "auditory": LearningStyle.AUDITORY,
            "read_write": LearningStyle.READ_WRITE,
            "readwrite": LearningStyle.READ_WRITE,
            "kinesthetic": LearningStyle.KINESTHETIC,
        }
        learning_style = style_map.get(prefs.learning_style.lower())

    # Parse preferences text for additional info
    # The preferences_text may contain tags like "I like: Metaphors, Examples, ..."
    preferences_text = prefs.preferences_text if prefs else None
    preferred_formats = []

    if preferences_text:
        # Extract any format preferences mentioned
        format_keywords = {
            "video": "videos",
            "diagram": "diagrams",
            "visual": "visual aids",
            "interactive": "interactive tutorials",
            "hands-on": "hands-on exercises",
            "code": "code examples",
            "text": "textbooks",
            "audio": "audio content",
        }
        text_lower = preferences_text.lower()
        for keyword, format_name in format_keywords.items():
            if keyword in text_lower:
                preferred_formats.append(format_name)

    return UserProfile(
        user_id=user.id,
        username=user.username,
        learning_style=learning_style,
        preferred_formats=preferred_formats,
        preferences_text=preferences_text,
    )


def build_course_request(data: CourseCreateRequest) -> CourseRequest:
    """Convert API request to CourseRequest model."""
    return CourseRequest(
        topic=data.query,
        depth=data.depth,
        specific_goals=data.specific_goals,
        focus_areas=data.focus_areas or [],
        exclude_topics=data.exclude_topics or [],
        time_constraint=data.time_constraint,
    )


# ============================================================================
# API Endpoints
# ============================================================================

@router.post("", response_model=CourseCreateResponse, status_code=status.HTTP_201_CREATED)
def create_course(
    course_data: CourseCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new personalized course.

    The course is generated using the AI Course Creator with the user's
    learning preferences taken into account.
    """
    # Get user preferences
    prefs = db.query(UserPreferences).filter(
        UserPreferences.user_id == current_user.id
    ).first()

    # Build the profile and request models
    user_profile = build_user_profile(current_user, prefs)
    course_request = build_course_request(course_data)

    try:
        # Get the course creator and generate
        creator = get_course_creator()
        generated = creator.create_course(user_profile, course_request)

        # Save course to database
        new_course = Course(
            user_id=current_user.id,
            title=generated.title,
            query=course_data.query,
            depth=course_data.depth,
            content=generated.content
        )
        db.add(new_course)
        db.commit()
        db.refresh(new_course)

        # Calculate total tokens
        total_tokens = generated.input_tokens + generated.output_tokens

        # Log token usage to console
        logger.info(
            f"TOKEN USAGE | user_id={current_user.id} | course_id={new_course.id} | "
            f"model={generated.model_used} | input={generated.input_tokens} | "
            f"output={generated.output_tokens} | total={total_tokens} | "
            f"cache_read={generated.cache_read_tokens} | cache_create={generated.cache_creation_tokens}"
        )

        # Save token usage to database
        usage_record = APIUsage(
            user_id=current_user.id,
            course_id=new_course.id,
            model_used=generated.model_used,
            input_tokens=generated.input_tokens,
            output_tokens=generated.output_tokens,
            total_tokens=total_tokens,
            cache_read_tokens=generated.cache_read_tokens,
            cache_creation_tokens=generated.cache_creation_tokens
        )
        db.add(usage_record)
        db.commit()

        return CourseCreateResponse(
            course=CourseResponse(
                id=new_course.id,
                title=new_course.title,
                query=new_course.query,
                depth=new_course.depth,
                content=new_course.content,
                created_at=new_course.created_at.isoformat()
            ),
            generation_stats=CourseGenerationStats(
                input_tokens=generated.input_tokens,
                output_tokens=generated.output_tokens,
                cache_read_tokens=generated.cache_read_tokens,
                cache_creation_tokens=generated.cache_creation_tokens,
                model_used=generated.model_used
            )
        )

    except CourseCreatorBusyError:
        logger.exception("Course generation failed: Gemini overloaded")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Course generation is busy right now. Please try again in a minute."
        )
    except CourseCreatorError:
        logger.exception("Course generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate course. Please try again."
        )
    except Exception:
        db.rollback()
        logger.exception("Course creation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create course. Please try again."
        )


@router.get("", response_model=List[CourseListItem])
def list_courses(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all courses for the current user."""
    courses = db.query(Course).filter(
        Course.user_id == current_user.id
    ).order_by(Course.created_at.desc()).all()

    return [
        CourseListItem(
            id=course.id,
            title=course.title,
            query=course.query,
            depth=course.depth,
            created_at=course.created_at.isoformat()
        )
        for course in courses
    ]


@router.get("/{course_id}", response_model=CourseResponse)
def get_course(
    course_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific course by ID."""
    course = db.query(Course).filter(
        Course.id == course_id,
        Course.user_id == current_user.id
    ).first()

    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )

    return CourseResponse(
        id=course.id,
        title=course.title,
        query=course.query,
        depth=course.depth,
        content=course.content,
        created_at=course.created_at.isoformat()
    )


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(
    course_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a course."""
    course = db.query(Course).filter(
        Course.id == course_id,
        Course.user_id == current_user.id
    ).first()

    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found"
        )

    db.delete(course)
    db.commit()


# ============================================================================
# Health/Status Endpoint
# ============================================================================

@router.get("/status/creator", tags=["status"])
def get_creator_status():
    """Check if the course creator is properly initialized."""
    try:
        creator = get_course_creator()
        return {
            "status": "ok",
            "model": creator.model,
            "constitution_loaded": len(creator.constitution) > 0,
            "constitution_length": len(creator.constitution)
        }
    except HTTPException as e:
        return {
            "status": "error",
            "detail": e.detail
        }
