# AI Invoice & Expense Manager

A full-stack financial management starter for freelancers and small businesses.

## Stack
- Frontend: React, Vite, JavaScript, React Router, Axios, Lucide React, Recharts
- Backend: FastAPI, SQLAlchemy, Pydantic, SQLite, JWT authentication
- AI: Optional OpenAI integration for expense categorization and financial Q&A

## Requirements
- Python 3.11+
- Node.js 20+

## Run the backend (PowerShell)
```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```
API docs: http://127.0.0.1:8000/docs

## Run the frontend (second terminal)
```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```
Frontend: http://localhost:5173

Create an account in the app. Financial records are scoped to the authenticated user.
AI features require `OPENAI_API_KEY` in `backend/.env`; core expense categorization has a deterministic fallback and clearly indicates when AI is unavailable.

## Included
- Registration/login with hashed passwords and JWT bearer authentication
- Dashboard totals and recent records from SQLite
- Client CRUD
- Invoice CRUD with line items, calculated totals, payment recording and status
- Expense CRUD and AI-assisted category suggestion
- Financial assistant grounded in the current user's database totals
- CSV export for invoices and expenses
- Responsive dashboard UI

## Notes
This is a portfolio-ready MVP, not accounting or tax advice. Before production use, add migrations, refresh-token/session management, rate limiting, malware scanning for uploads, audit logs, backups, and jurisdiction-specific tax review. Never upload real financial records or `.env` files to GitHub.
