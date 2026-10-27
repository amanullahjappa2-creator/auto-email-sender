# Release Checklist

## Before release

- Confirm the environment variables are configured in `.env` and are not committed.
- Run the full project test suite.
- Validate `/healthz` and scheduler startup behavior.
- Review the changelog and deployment notes.

## After release

- Check logs for delivery issues or environment mismatches.
- Verify the app remains reachable on the expected host and port.
- Confirm scheduled jobs still process correctly.
