# Study Companion

A Flask-based study tracker that helps students plan subjects, log study sessions, track progress, and stay consistent.

## Overview

Study Companion is designed to be used while studying and for reviewing progress afterward. It combines a study timer, session logging, a dashboard, streak tracking, XP-based motivation, and academic planning in one local web app.

## Features

- Study timer for focused sessions
- Session logging by subject, duration, and date
- Dashboard with daily totals, session counts, subject breakdowns, XP, level, and streaks
- Subject planning with priority, confidence, weekly goals, and notes
- Academic item tracking for assignments, exams, projects, quizzes, and reading
- SQLite storage for local use
- Optional Supabase authentication and remote data storage

## Tech Stack

- Python
- Flask
- SQLite
- Supabase, optional
- HTML, CSS, and JavaScript

## Project Structure

```text
StudyCompanion/
├── app.py                 # Flask routes and request handling
├── utils.py               # Database helpers, dashboard data, XP, and streak logic
├── supabase_client.py     # Optional Supabase client setup
├── database.db            # Local SQLite database
├── requirements.txt       # Python dependencies
├── supabase_schema.sql    # Supabase table schema
├── templates/
│   └── index.html         # Main page template
└── static/
    ├── app.js             # Frontend interactions and timer behavior
    ├── styles.css         # App styling
    └── study-companion-logo.svg
```

## Setup

1. Clone the repository:

```bash
git clone https://github.com/Turjoy-barua/StudyCompanion.git
cd StudyCompanion
```

2. Create and activate a virtual environment:

```bash
python3 -m venv env
source env/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Run the app:

```bash
flask --app app run
```

5. Open the local site:

```text
http://127.0.0.1:5000
```

You can also run the app directly:

```bash
python app.py
```

## Optional Supabase Setup

The app works locally with SQLite without any Supabase configuration. To enable Supabase authentication and remote storage, create a `.env` file with:

```env
SUPABASE_URL=your_supabase_project_url
SUPABASE_ANON_KEY=your_supabase_anon_key
SECRET_KEY=replace_with_a_secure_secret
APP_BASE_URL=http://127.0.0.1:5000
```

Then run the SQL in `supabase_schema.sql` in your Supabase project.

For account confirmation, password recovery, and Google login, configure Supabase Auth:

- Add `http://127.0.0.1:5000/auth/callback` and `http://127.0.0.1:5000/auth/reset-password` to Auth redirect URLs.
- Enable email confirmations if you want users to verify ownership before login.
- Enable the Google provider in Supabase Auth and add the Google OAuth client credentials there.
- In production, set `APP_BASE_URL` to your deployed app URL and add the matching callback/reset URLs in Supabase.

## Deployment

The included `vercel.json` is intended for deploying the Flask app on Vercel. Make sure required environment variables are configured in the deployment platform if Supabase is enabled.

## Future Improvements

- Smart study reminders
- More detailed analytics and charts
- Mobile-focused layout refinements
- Calendar integrations
- Exportable study reports

## Inspiration

Consistency beats intensity. Small study sessions, tracked over time, make progress easier to see and easier to repeat.
