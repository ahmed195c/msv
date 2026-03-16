# CLAUDE.md — MSV Project Guidelines

## Project Overview
Django web application for Sharjah Municipality (HCSD) — manages company permits, inspections, clearances, and waste disposal.

- **Stack**: Django 4.x, Python 3.12, SQLite/PostgreSQL, HTML/CSS templates (no JS framework)
- **Main app**: `msv/hcsd/`
- **Server**: Ubuntu, gunicorn + nginx, SSH `ahmed@192.168.50.74`

---

## Python / Django Rules

### Code Style
- Follow PEP 8 conventions
- Functions under 50 lines; files under 800 lines; nesting depth ≤ 4 levels
- No hardcoded values — use constants or settings
- No `print()` statements — use `logging` module instead
- Always handle errors explicitly; never silently suppress exceptions

### Django Patterns
- Use `get_object_or_404` for view lookups — never raw `.get()` without try/except
- Use `select_related` / `prefetch_related` to avoid N+1 queries
- Validate at system boundaries (user input, form data) — never trust raw POST data
- Use `update_fields` in `.save()` when only updating specific fields
- Model changes always require a migration — run `python manage.py makemigrations` after editing `models.py`

### Security
- Never expose raw exception messages to the user
- CSRF protection must be active on all POST forms (`{% csrf_token %}`)
- Use `@login_required` on all views that require authentication
- Never commit secrets, passwords, or API keys — use environment variables
- Sanitize all user input before rendering in templates (use `{{ var }}` not `{{ var|safe }}` unless explicitly needed)

### Templates
- Extend `hcsd/base.html` for all user-facing pages
- Use `{% load static %}` for static file references
- Print templates are standalone (no base.html) — use `@page { margin: 0 }` to suppress browser headers

---

## Git Workflow
- Commit format: `<type>: <description>` (types: feat, fix, refactor, docs, chore)
- Never commit `.pyc` files or `__pycache__/` — already in `.gitignore`
- Never commit `.env` or files with credentials
- Always pull before pushing to avoid conflicts on the server

---

## File Structure
```
msv/
  hcsd/
    models.py          # Data models — edit carefully, always migrate after
    views.py           # All views — large file, use Grep to find specific views
    urls.py            # URL patterns
    admin.py           # Django admin registration
    templates/hcsd/    # HTML templates
    static/hcsd/       # CSS, images, static assets
    migrations/        # Auto-generated — never edit manually
```

---

## Deployment
- Deploy: `ssh ahmed@192.168.50.74`, then `cd /home/ahmed/msv && git pull`
- Restart server: `sudo systemctl restart msv-gunicorn`
- If git conflicts on server: `git rebase --abort && git reset --hard origin/main`
- Gunicorn timeout: 120s (configured for large file uploads)
