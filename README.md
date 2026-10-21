# Auto Email Sender

A small Python command-line tool that sends personalized emails to a list of recipients from a CSV file. It was built to make the repetitive part of writing to many universities faster, while keeping every email individually addressed.

## Features

- Personalized emails: each message is filled from a text template using that row's CSV columns
- Dry-run mode to preview every email before anything is sent
- Optional PDF attachment, such as a CV
- Random delay between emails to avoid spam filters and provider limits
- Sent log, so re-running the script never emails the same address twice
- Credentials kept in a `.env` file, never in the code
- Standard library only, no extra packages to install

## Setup

1. Install Python 3.10 or newer.
2. Copy `.env.example` to `.env` and fill in your email address and a Gmail App Password (requires 2-Step Verification on the Google account).
3. Edit `recipients.csv` with your contacts and `template.txt` with your message.

## Usage

Preview first:

    python send_emails.py --dry-run

Send for real, with a CV attached and a 60 second base delay:

    python send_emails.py --attach cv.pdf --delay 60

## CSV format

The header row must contain `contact,email,university,program,reason`. Any column can be used in the template as `$column_name`.

## How it works

The script loads the settings from `.env`, reads the CSV, skips addresses already in `sent_log.csv`, fills the template for each row, connects to the SMTP server over SSL, and sends the messages one at a time while logging the result of each.

## Responsible use

Only email people who are reasonable recipients for your message, keep the list small and relevant, and write real, specific content for each contact. Bulk or generic mail can be treated as spam.

## License

MIT
