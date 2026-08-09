# Minerva - Rental Scout

**Minerva - Rental Scout** is an autonomous LLM-driven browser agent that searches real rental listings (Craigslist, PadMapper) based on a natural-language goal. It streams its reasoning, actions, and a live browser view to the UI in real time, supports human-in-the-loop interventions (to pause, ask for input, or abort), and returns a structured final comparison enriched with nearby amenities (schools, groceries, gyms) and commute distances via LocationIQ.

## Architecture

The application is split into a Python backend and a React frontend, communicating seamlessly over a WebSocket connection.
- **Backend:** Built with Python, FastAPI, and WebSockets. It uses Playwright for headless browser automation (scraping listings from Craigslist and PadMapper) and Anthropic's Claude as the orchestration LLM to reason about user goals and dispatch tools.
- **Frontend:** Built with Next.js, React, and Tailwind CSS. It connects to the backend over WebSocket to receive a live stream of agent events (thoughts, actions, observations), screencast frames, and structured final results.

## Key Features

- **Live Agent Trace:** Watch the agent's thought process, tool calls, and observations stream into a collapsible, chronological UI in real time.
- **Live Browser View:** A real-time CDP screencast streams JPEG frames directly to the frontend so you can watch Playwright navigate and scrape.
- **Amenity & Commute Search:** Listings are automatically enriched with nearby points of interest (schools, gyms, grocery stores) or commute distances using the LocationIQ API (OpenStreetMap data).
- **Structured Final Findings:** The agent automatically synthesizes scraped listing data, photos, and amenities into a clean, comparative summary card UI.
- **Human-in-the-Loop:** The agent will pause and prompt the user if it gets stuck, encounters a CAPTCHA, or needs clarification, resuming automatically when the user replies.

## Tech Stack

**Backend:**
- Python
- `fastapi` & `uvicorn` (Server & WebSockets)
- `playwright` (Browser Automation)
- `anthropic` (LLM Orchestration)
- `python-dotenv` (Environment Config)

**Frontend:**
- Node.js
- `next` (16.2.12 - React Framework with Turbopack)
- `react` / `react-dom` (19.2.4)
- `tailwindcss` / `@tailwindcss/postcss` (v4 - Styling)
- `framer-motion` (Animations)
- `lucide-react` (Icons)
- `react-markdown` (Summary rendering)

## Setup Instructions

### Backend Setup
1. Navigate to the `backend` directory:
   ```bash
   cd backend
   ```
2. Create and activate a Python virtual environment:
   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Configure environment variables (copy the template and add your `ANTHROPIC_API_KEY` and `LOCATIONIQ_API_KEY`):
   ```bash
   cp .env.example .env
   ```
5. Start the backend server:
   ```bash
   python main.py
   ```

### Frontend Setup
1. Navigate to the `frontend` directory:
   ```bash
   cd frontend
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Configure environment variables (if applicable):
   ```bash
   cp .env.example .env.local
   ```
4. Start the development server:
   ```bash
   npm run dev
   ```
5. Open your browser to `http://localhost:3000` to interact with the scout.

---
