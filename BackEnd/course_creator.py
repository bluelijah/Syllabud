"""
Course Creator Module

This module contains the core logic for generating personalized courses using
the Google Gemini API with the AI Course Creator Constitution as the system prompt.
"""

import os
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone
from enum import Enum

import logging

import httpx
from google import genai
from google.genai import errors as genai_errors
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================

class LearningStyle(str, Enum):
    VISUAL = "visual"
    AUDITORY = "auditory"
    READ_WRITE = "read_write"
    KINESTHETIC = "kinesthetic"


class EducationLevel(str, Enum):
    HIGH_SCHOOL = "high_school"
    UNDERGRADUATE = "undergraduate"
    GRADUATE = "graduate"
    PROFESSIONAL = "professional"
    SELF_TAUGHT = "self_taught"


class LearnerMotivation(str, Enum):
    INSTRUMENTAL = "instrumental"  # Goal-driven (job skills, exam prep)
    EPISTEMIC = "epistemic"        # Curiosity-driven (understanding for its own sake)
    CREATIVE = "creative"          # Building/making-oriented


# ============================================================================
# Data Models
# ============================================================================

class UserProfile(BaseModel):
    """
    Persistent learner profile storing educational background and preferences.
    This is created once and used across all course requests.
    """
    # Core identity
    user_id: int
    username: str

    # Educational background
    education_level: Optional[EducationLevel] = None
    fields_of_expertise: List[str] = Field(default_factory=list)

    # Learning preferences
    learning_style: Optional[LearningStyle] = None
    preferred_formats: List[str] = Field(default_factory=list)  # e.g., ["videos", "textbooks", "interactive"]

    # Motivation and goals
    motivation: Optional[LearnerMotivation] = None
    learning_goals: Optional[str] = None

    # Additional context (free-form preferences text)
    preferences_text: Optional[str] = None

    # Constraints
    time_availability: Optional[str] = None  # e.g., "10 hours/week"

    def to_prompt_section(self) -> str:
        """Format the user profile as a clear section for the AI prompt."""
        lines = ["LEARNER PROFILE:", "=" * 40]

        if self.education_level:
            lines.append(f"Education Level: {self.education_level.value.replace('_', ' ').title()}")

        if self.fields_of_expertise:
            lines.append(f"Areas of Expertise: {', '.join(self.fields_of_expertise)}")

        if self.learning_style:
            lines.append(f"Primary Learning Style: {self.learning_style.value.replace('_', ' ').title()}")

        if self.preferred_formats:
            lines.append(f"Preferred Content Formats: {', '.join(self.preferred_formats)}")

        if self.motivation:
            motivation_descriptions = {
                LearnerMotivation.INSTRUMENTAL: "Goal-driven (focused on practical skills and outcomes)",
                LearnerMotivation.EPISTEMIC: "Curiosity-driven (learning for understanding)",
                LearnerMotivation.CREATIVE: "Building/making-oriented (wants to create things)"
            }
            lines.append(f"Learning Motivation: {motivation_descriptions.get(self.motivation, self.motivation.value)}")

        if self.learning_goals:
            lines.append(f"Learning Goals: {self.learning_goals}")

        if self.preferences_text:
            lines.append(f"Additional Preferences: {self.preferences_text}")

        if self.time_availability:
            lines.append(f"Time Availability: {self.time_availability}")

        return "\n".join(lines)


class CourseRequest(BaseModel):
    """
    Per-course parameters specifying what the learner wants to learn.
    """
    # Required fields
    topic: str = Field(..., min_length=1, max_length=500)
    depth: int = Field(default=5, ge=1, le=10)

    # Optional specifications
    specific_goals: Optional[str] = None  # What specifically they want to achieve
    time_constraint: Optional[str] = None  # e.g., "Complete in 2 weeks"
    focus_areas: List[str] = Field(default_factory=list)  # Specific subtopics to emphasize
    exclude_topics: List[str] = Field(default_factory=list)  # Topics to skip/minimize

    # Context
    prior_attempts: Optional[str] = None  # Previous learning attempts and what didn't work
    application_context: Optional[str] = None  # How they plan to use this knowledge

    @field_validator('depth')
    @classmethod
    def validate_depth(cls, v):
        if not 1 <= v <= 10:
            raise ValueError('Depth must be between 1 and 10')
        return v

    def to_prompt_section(self) -> str:
        """Format the course request as a clear section for the AI prompt."""
        lines = ["COURSE REQUEST:", "=" * 40]

        lines.append(f"Topic: {self.topic}")
        lines.append(f"Depth Level: {self.depth}/10")

        # Add depth interpretation
        depth_descriptions = {
            (1, 3): "Introductory - Focus on intuition, high-level structure, minimal formalism",
            (4, 6): "Intermediate - Core mechanisms, moderate formalism, practical competence",
            (7, 8): "Advanced - Formal frameworks, technical precision, edge cases",
            (9, 10): "Expert/Research - Primary literature, formal proofs, open problems"
        }
        for (low, high), desc in depth_descriptions.items():
            if low <= self.depth <= high:
                lines.append(f"Depth Interpretation: {desc}")
                break

        if self.specific_goals:
            lines.append(f"Specific Goals: {self.specific_goals}")

        if self.time_constraint:
            lines.append(f"Time Constraint: {self.time_constraint}")

        if self.focus_areas:
            lines.append(f"Focus Areas: {', '.join(self.focus_areas)}")

        if self.exclude_topics:
            lines.append(f"Topics to Minimize/Exclude: {', '.join(self.exclude_topics)}")

        if self.prior_attempts:
            lines.append(f"Previous Learning Attempts: {self.prior_attempts}")

        if self.application_context:
            lines.append(f"Intended Application: {self.application_context}")

        return "\n".join(lines)


class GeneratedCourse(BaseModel):
    """
    The result of course generation.
    """
    title: str
    content: str
    depth: int
    topic: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_used: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


# ============================================================================
# Course Creator
# ============================================================================

class CourseCreatorError(Exception):
    """Custom exception for course creation errors."""
    pass


class CourseCreatorBusyError(CourseCreatorError):
    """Gemini is overloaded or timed out on every model tried; safe to retry later."""
    pass


# HTTP statuses from Gemini that mean "temporarily unavailable, try again"
RETRYABLE_STATUS_CODES = [429, 500, 502, 503, 504]


class CourseCreator:
    """
    Main class for generating personalized courses using the Google Gemini API.

    The constitution is loaded at initialization and used as the system instruction
    to guide course generation.
    """

    DEFAULT_MODEL = "gemini-2.5-flash"
    # Tried in order if the primary model stays overloaded after retries
    FALLBACK_MODELS = ["gemini-3.5-flash"]

    def __init__(
        self,
        constitution_path: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        Initialize the CourseCreator.

        Args:
            constitution_path: Path to the constitution markdown file.
                             Defaults to config/constitution.md relative to this file.
            api_key: Gemini API key. Defaults to GEMINI_API_KEY env var.
            model: Model to use. Defaults to DEFAULT_MODEL.
        """
        # Set up API client
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise CourseCreatorError(
                "Gemini API key not found. Set GEMINI_API_KEY environment variable "
                "or pass api_key parameter."
            )

        self.client = genai.Client(
            api_key=self.api_key,
            http_options={
                "timeout": 120_000,  # ms per attempt
                # SDK-level retries with exponential backoff for transient errors
                "retry_options": {
                    "attempts": 3,
                    "initial_delay": 2.0,
                    "max_delay": 10.0,
                    "http_status_codes": RETRYABLE_STATUS_CODES,
                },
            },
        )
        self.model = model or self.DEFAULT_MODEL
        self.fallback_models = [m for m in self.FALLBACK_MODELS if m != self.model]

        # Load constitution
        if constitution_path is None:
            # Default to config/constitution.md relative to this file
            base_dir = Path(__file__).parent
            constitution_path = base_dir / "config" / "constitution.md"

        self.constitution_path = Path(constitution_path)
        self.constitution = self._load_constitution()

    def _load_constitution(self) -> str:
        """Load the constitution from file."""
        if not self.constitution_path.exists():
            raise CourseCreatorError(
                f"Constitution file not found at: {self.constitution_path}"
            )

        with open(self.constitution_path, "r", encoding="utf-8") as f:
            return f.read()

    def reload_constitution(self) -> None:
        """Reload the constitution from file (useful if it's been updated)."""
        self.constitution = self._load_constitution()

    def _build_user_message(
        self,
        user_profile: UserProfile,
        course_request: CourseRequest
    ) -> str:
        """
        Build the user message combining profile and request.

        The message is structured clearly so the AI can parse the learner's
        context and requirements.
        """
        sections = [
            user_profile.to_prompt_section(),
            "",
            course_request.to_prompt_section(),
            "",
            "=" * 40,
            "Please design a complete course following your constitutional guidelines.",
            "",
            "Remember to:",
            "- Complete the Article 0 self-reflection before designing",
            "- Include the Designer's Note explaining your pedagogical reasoning",
            "- Provide explicit dependency mapping for depth 5+",
            "- Include assessment checkpoints and time estimates",
            "- Match resources to the learner's stated preferences",
            "- Follow the standard output format specified in your constitution"
        ]

        return "\n".join(sections)

    def create_course(
        self,
        user_profile: UserProfile,
        course_request: CourseRequest
    ) -> GeneratedCourse:
        """
        Generate a personalized course.

        Args:
            user_profile: The learner's persistent profile
            course_request: The specific course request parameters

        Returns:
            GeneratedCourse with the full course content and metadata

        Raises:
            CourseCreatorError: If course generation fails
        """
        # Build the user message
        user_message = self._build_user_message(user_profile, course_request)

        try:
            response, model_used = self._generate_with_fallback(user_message)

            # Extract content
            content = response.text

            # Extract title from the generated course
            title = self._extract_title(content, course_request.topic)

            # Build response with usage stats
            usage = getattr(response, 'usage_metadata', None)
            input_tokens = getattr(usage, 'prompt_token_count', 0) if usage else 0
            output_tokens = getattr(usage, 'candidates_token_count', 0) if usage else 0

            return GeneratedCourse(
                title=title,
                content=content,
                depth=course_request.depth,
                topic=course_request.topic,
                model_used=model_used,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=0,
                cache_creation_tokens=0
            )

        except CourseCreatorError:
            raise
        except Exception as e:
            raise CourseCreatorError(f"Failed to generate course: {str(e)}") from e

    def _generate_with_fallback(self, user_message: str):
        """
        Call Gemini, moving to the next model if one stays overloaded.

        Each model already gets SDK-level retries with backoff. Only
        transient errors (overload, rate limit, timeout) trigger a fallback;
        anything else (bad key, bad request) is raised immediately.

        Returns:
            (response, model_name) for the first model that succeeded
        """
        last_error = None
        for model in [self.model, *self.fallback_models]:
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=user_message,
                    config={"system_instruction": self.constitution},
                )
                return response, model
            except genai_errors.APIError as e:
                if e.code not in RETRYABLE_STATUS_CODES:
                    raise
                last_error = e
            except httpx.TimeoutException as e:
                last_error = e
            logger.warning("Gemini model %s unavailable after retries: %s", model, last_error)

        raise CourseCreatorBusyError(
            f"All Gemini models unavailable: {last_error}"
        ) from last_error

    def _extract_title(self, content: str, fallback_topic: str) -> str:
        """Extract the course title from generated content."""
        import re

        # Try to find "COURSE: [Title]" pattern
        match = re.search(r'COURSE:\s*(.+?)(?:\n|$)', content, re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            # Clean up any brackets or extra formatting
            title = re.sub(r'[\[\]]', '', title)
            if title and len(title) <= 100:
                return title

        # Try "Course Title:" pattern
        match = re.search(r'Course Title:\s*(.+?)(?:\n|$)', content, re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            if title and len(title) <= 100:
                return title

        # Fallback to truncated topic
        return fallback_topic[:50] if len(fallback_topic) > 50 else fallback_topic


# ============================================================================
# Factory function for easy instantiation
# ============================================================================

def create_course_creator(**kwargs) -> CourseCreator:
    """
    Factory function to create a CourseCreator instance.

    Handles common setup and provides sensible defaults.
    """
    return CourseCreator(**kwargs)


# ============================================================================
# Example usage (for testing/demonstration)
# ============================================================================

if __name__ == "__main__":
    # Example usage
    creator = CourseCreator()

    # Create a sample user profile
    profile = UserProfile(
        user_id=1,
        username="test_user",
        education_level=EducationLevel.UNDERGRADUATE,
        fields_of_expertise=["computer science", "mathematics"],
        learning_style=LearningStyle.VISUAL,
        preferred_formats=["videos", "interactive tutorials", "diagrams"],
        motivation=LearnerMotivation.EPISTEMIC,
        learning_goals="Understand the theoretical foundations",
        preferences_text="I like metaphors and real-world examples. I learn best with step-by-step explanations."
    )

    # Create a course request
    request = CourseRequest(
        topic="Category Theory",
        depth=6,
        specific_goals="Understand functors, natural transformations, and their applications in programming",
        focus_areas=["applications to functional programming"],
        application_context="Want to better understand Haskell and advanced type systems"
    )

    print("User Message Preview:")
    print("=" * 60)
    print(creator._build_user_message(profile, request))
    print("=" * 60)

    # Uncomment to actually generate a course:
    # course = creator.create_course(profile, request)
    # print(f"\nGenerated Course: {course.title}")
    # print(f"Tokens used: {course.input_tokens} input, {course.output_tokens} output")
