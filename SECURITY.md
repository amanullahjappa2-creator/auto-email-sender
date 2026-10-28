# Security Policy

## Supported versions

MailFlow Studio is actively maintained for the current main branch.

## Reporting a vulnerability

Please do not open a public issue for security problems.

Report sensitive issues privately by emailing the project maintainer or using the repository's private security reporting flow if available.

Include:

- a clear description of the vulnerability
- the affected route, function, or data flow
- reproduction steps when possible
- the severity and impact you observed

We aim to respond quickly and keep reports confidential while the issue is reviewed and fixed.

## Security best practices

- Never commit real secrets or credentials.
- Keep local `.env` files private and out of source control.
- Prefer validated, user-scoped access checks before exposing admin features.
- Treat any SMTP credential or email content as sensitive data.
