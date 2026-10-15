# Syllabud - Your Personalized Course Creator

Syllabud is an intelligent course generation platform that creates personalized learning paths based on your learning style and preferences. Powered by Google's Gemini AI, it generates comprehensive courses tailored to how you learn best. Learn What Matters.

## Features

- **Personalized Learning Profiles** - Select your learning style (Visual, Auditory, Read/Write, Kinesthetic) and describe your preferences
- **AI-Generated Courses** - Get custom course content with prerequisites, curriculum, and curated resources
- **Depth Control** - Choose course complexity from beginner (1) to expert (10)
- **User Accounts** - Secure authentication with course history saved to your profile
- **Adaptive Resources** - Resource recommendations tailored to your learning style

## Tech Stack

**Frontend**
- React 19
- Vite
- React Router
- Styled Components

**Backend**
- FastAPI (Python)
- SQLAlchemy + SQLite
- JWT Authentication
- Google Gemini AI

## Getting Started

### Prerequisites

- Node.js 18+
- Python 3.11+
- Google Gemini API Key ([Get one here](https://aistudio.google.com/apikey))

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd Syllabud
   ```

2. **Set up the backend**
   ```bash
   cd BackEnd
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure environment variables**

   Copy the example file and fill in your own values:
   ```bash
   cp .env.example .env
   ```

   | Variable | Required | Purpose |
   |---|---|---|
   | `GEMINI_API_KEY` | Yes (to generate courses) | Google Gemini API key |
   | `JWT_SECRET_KEY` | Yes, the app won't start without it | Signs and verifies login tokens |
   | `ADMIN_API_KEY` | Yes, the app won't start without it | Key for `/admin` endpoints, sent as the `X-Admin-Key` header |
   | `FRONTEND_URL` | No | Extra frontend origin allowed through CORS |

   Generate random values for the two secrets with:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(64))"
   ```

   Leave `DATABASE_URL` unset locally. The backend then uses a local SQLite file (`BackEnd/syllabud.db`). Never commit `.env` or `*.db` files; both are in `.gitignore`.

4. **Seed synthetic dev data (optional)**

   From `BackEnd/`:
   ```bash
   python seed_dev.py
   ```
   This creates the SQLite tables, three fake users (`testuser1@example.com` through `testuser3@example.com`, password `devpassword123`) with learning preferences, and a sample course. It refuses to run if `DATABASE_URL` is set, so it can't touch a production database.

5. **Set up the frontend**
   ```bash
   cd FrontEnd
   npm install
   ```

### Running the Application

1. **Start the backend** (from `BackEnd/` directory)
   ```bash
   uvicorn main:backendApp --reload --port 8000
   ```

2. **Start the frontend** (from `FrontEnd/` directory)
   ```bash
   npm run dev
   ```

3. **Open the app**

   Navigate to `http://localhost:5173`

## Usage

1. **Create an account** - Register with username, email, and password
2. **Set preferences** - Choose your learning style and describe how you learn best
3. **Create a course** - Enter a topic and select depth level
4. **Learn** - View your personalized course with curated resources

## Project Structure

```
Syllabud/
├── BackEnd/
│   ├── main.py              # FastAPI application
│   ├── database.py          # SQLAlchemy setup
│   ├── models.py            # Database models
│   ├── auth.py              # Authentication utilities
│   ├── routes/
│   │   ├── auth_routes.py   # Auth endpoints
│   │   └── course_routes.py # Course CRUD + Gemini integration
│   ├── seed_dev.py          # Seeds local SQLite with fake dev data
│   ├── .env.example         # Template for environment variables
│   └── .env                 # Your local environment variables (create from .env.example, never commit)
├── FrontEnd/
│   ├── src/
│   │   ├── pages/           # Page components
│   │   ├── components/      # Reusable components
│   │   └── contexts/        # React contexts
│   └── package.json
└── TextFiles/
    └── structure.txt        # Course template
```

## API Endpoints

### Authentication
- `POST /auth/register` - Create account
- `POST /auth/login` - Get access token
- `GET /auth/me` - Get current user
- `PUT /auth/preferences` - Update learning preferences

### Courses
- `POST /courses` - Generate new course
- `GET /courses` - List user's courses
- `GET /courses/{id}` - Get course details
- `DELETE /courses/{id}` - Delete course

## License

MIT
