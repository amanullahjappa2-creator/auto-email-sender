import csv
import tempfile
import unittest
from datetime import date
from email import message_from_bytes
from pathlib import Path
from string import Template
from unittest.mock import patch

import send_emails


class SendEmailsTests(unittest.TestCase):
    def test_attachment_uses_guessed_mime_type(self):
        with tempfile.TemporaryDirectory() as directory:
            attachment = Path(directory) / "report.csv"
            attachment.write_text("name,email\nA,person@example.test\n", encoding="utf-8")

            message = send_emails.build_message(
                "sender@example.test",
                "MailFlow",
                "person@example.test",
                "Report",
                "See attached.",
                attachment,
            )
            parsed = message_from_bytes(message.as_bytes())
            attachment_part = next(
                part for part in parsed.walk() if part.get_filename() == "report.csv"
            )

        self.assertEqual(attachment_part.get_content_type(), "text/csv")

    def test_unknown_attachment_type_uses_safe_binary_mime_type(self):
        with tempfile.TemporaryDirectory() as directory:
            attachment = Path(directory) / "archive.unknownext"
            attachment.write_bytes(b"data")

            message = send_emails.build_message(
                "sender@example.test",
                "",
                "person@example.test",
                "Archive",
                "See attached.",
                attachment,
            )
            parsed = message_from_bytes(message.as_bytes())
            attachment_part = next(
                part
                for part in parsed.walk()
                if part.get_filename() == "archive.unknownext"
            )

        self.assertEqual(attachment_part.get_content_type(), "application/octet-stream")

    def test_missing_template_column_is_reported_for_the_recipient(self):
        subject, body, problem = send_emails.render_message(
            Template("Hello $name"),
            Template("Your reference is $reference"),
            {"name": "Ari"},
        )

        self.assertIsNone(subject)
        self.assertIsNone(body)
        self.assertEqual(problem, "CSV column 'reference' is missing")

    def test_successful_send_log_only_skips_successes(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "sent_log.csv"
            with log_path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(["email", "status", "time"])
                writer.writerow(["sent@example.test", "sent", "2026-10-28 10:00:00"])
                writer.writerow(["retry@example.test", "failed: SMTP error", "2026-10-28 10:01:00"])

            with patch.object(send_emails, "LOG_FILE", log_path):
                skipped = send_emails.already_sent()

        self.assertEqual(skipped, {"sent@example.test"})

    def test_daily_counter_counts_only_successes_for_requested_day(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "sent_log.csv"
            with log_path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(["email", "status", "time"])
                writer.writerow(["today@example.test", "sent", "2026-10-28 10:00:00"])
                writer.writerow(["failed@example.test", "failed: SMTP error", "2026-10-28 10:01:00"])
                writer.writerow(["yesterday@example.test", "sent", "2026-10-27 23:59:00"])

            count = send_emails.sent_today(log_path, date(2026, 10, 28))

        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
