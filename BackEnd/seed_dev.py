"""
Seed a local SQLite database with synthetic development data.

Usage (from BackEnd/):
    python seed_dev.py

Creates the tables and a few obviously fake users, each with learning
preferences, plus a sample course. Safe to re-run: existing seed users are
skipped.

This script refuses to run if DATABASE_URL is set, so it can never write to
a production (Postgres) database.
"""
import os
import sys

from dotenv import load_dotenv

# Load .env first so a DATABASE_URL defined there is also caught by the guard
load_dotenv()

if os.getenv("DATABASE_URL"):
    sys.exit(
        "Refusing to seed: DATABASE_URL is set. seed_dev.py only runs against "
        "local SQLite. Unset DATABASE_URL (and remove it from .env) and retry."
    )

from database import SessionLocal, init_db, DATABASE_URL  # noqa: E402
from models import User, UserPreferences, Course  # noqa: E402
from auth import hash_password  # noqa: E402

# Shared password for all seed accounts. Local dev only.
DEV_PASSWORD = "devpassword123"

SEED_USERS = [
    {
        "username": "testuser1",
        "email": "testuser1@example.com",
        "learning_style": "visual",
        "preferences_text": "Fake profile: likes diagrams and short videos, about 30 minutes a day.",
    },
    {
        "username": "testuser2",
        "email": "testuser2@example.com",
        "learning_style": "read_write",
        "preferences_text": "Fake profile: prefers written tutorials and summaries, learns best on weekends.",
    },
    {
        "username": "testuser3",
        "email": "testuser3@example.com",
        "learning_style": "kinesthetic",
        "preferences_text": "Fake profile: wants hands-on exercises and small projects.",
    },
]

# Matches the section headers MainContent.jsx parses (PREREQUISITES, COURSE STRUCTURE, RESOURCES)
SAMPLE_COURSE_CONTENT = """COURSE: Introduction to Python (Sample Seed Course)

PREREQUISITES:
- Basic computer literacy
- A text editor and Python 3.11+ installed

COURSE STRUCTURE:
Module 1: Getting Started
├─ Unit 1.1: Variables and types → **Why here:** everything else builds on these
├─ Unit 1.2: Control flow
└─ Checkpoint: write a FizzBuzz script

Module 2: Functions and Data
├─ Unit 2.1: Defining functions
├─ Unit 2.2: Lists and dictionaries
└─ Checkpoint: build a small word-count tool

RESOURCES:
Required
- **Primary:** [The Python Tutorial](https://docs.python.org/3/tutorial/)
Recommended
- **Alternative:** [Python docs: Built-in Functions](https://docs.python.org/3/library/functions.html)
"""


def seed():
    init_db()
    db = SessionLocal()
    try:
        first_user = None
        for data in SEED_USERS:
            user = db.query(User).filter(User.email == data["email"]).first()
            if user:
                print(f"  exists:  {data['email']}")
            else:
                user = User(
                    username=data["username"],
                    email=data["email"],
                    password_hash=hash_password(DEV_PASSWORD),
                )
                db.add(user)
                db.flush()
                db.add(UserPreferences(
                    user_id=user.id,
                    learning_style=data["learning_style"],
                    preferences_text=data["preferences_text"],
                ))
                print(f"  created: {data['email']}")
            first_user = first_user or user

        if not db.query(Course).filter(Course.user_id == first_user.id).first():
            db.add(Course(
                user_id=first_user.id,
                title="Introduction to Python (Sample Seed Course)",
                query="Learn the basics of Python",
                depth=3,
                content=SAMPLE_COURSE_CONTENT,
            ))
            print(f"  created: sample course for {first_user.email}")

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    print(f"Seeding {DATABASE_URL}")
    seed()
    print(f"Done. Log in as testuser1 / testuser2 / testuser3 with password '{DEV_PASSWORD}'.")
