# Contributing to MailFlow Studio

Thanks for helping improve MailFlow Studio

## Development setup

1. Clone the repository.
2. Create and activate a virtual environment.
3. Install project dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env` and fill in the required values.
5. Run the app locally with the project startup script or `python app.py`.

## Code expectations

- Keep the project secure and privacy-focused.
- Avoid exposing secrets or user data in logs or templates.
- Validate email addresses and content before sending.
- Prefer scoped, readable changes over broad rewrites.
- Add or update tests when changing user-facing behavior.

## Testing

Run the project test suite before opening a pull request:

```bash
python -m unittest tests.test_application -q
```

## Pull requests

- Keep each pull request focused on one concern.
- Explain the problem, the fix, and any validation performed.
- Include screenshots or examples when the UI changes.
- Keep commit messages clear and action-oriented.
