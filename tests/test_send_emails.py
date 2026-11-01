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
    def test_read_recipients_strips_headers_and_values(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "recipients.csv"
            csv_path.write_text(" email , name\n person@example.test , Ari \n", encoding="utf-8")
            self.assertEqual(
                send_emails.read_recipients(csv_path),
                [{"email": "person@example.test", "name": "Ari"}],
            )

    def test_load_env_sets_missing_values_without_overwriting_existing(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "# comment\nTEST_MAILFLOW_ENV=loaded\nTEST_MAILFLOW_EXISTING=file\ninvalid\n",
                encoding="utf-8",
            )
            with patch.dict(
                send_emails.os.environ,
                {"TEST_MAILFLOW_EXISTING": "existing"},
                clear=False,
            ):
                send_emails.load_env(env_path)
                self.assertEqual(send_emails.os.environ["TEST_MAILFLOW_ENV"], "loaded")
                self.assertEqual(send_emails.os.environ["TEST_MAILFLOW_EXISTING"], "existing")

    def test_log_sent_creates_header_and_appends_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "sent_log.csv"
            with patch.object(send_emails, "LOG_FILE", log_path), patch.object(
                send_emails.time, "strftime", return_value="2026-11-01 12:00:00"
            ):
                send_emails.log_sent("person@example.test", "sent")
                send_emails.log_sent("other@example.test", "failed: test")
            with log_path.open(newline="", encoding="utf-8") as file:
                rows = list(csv.reader(file))
            self.assertEqual(rows[0], ["email", "status", "time"])
            self.assertEqual(len(rows), 3)

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

    def test_invalid_template_placeholder_is_reported(self):
        subject, body, problem = send_emails.render_message(
            Template("Hello $"), Template("Body"), {}
        )
        self.assertIsNone(subject)
        self.assertIsNone(body)
        self.assertIn("invalid template placeholder", problem)

    def test_already_sent_returns_empty_set_when_log_does_not_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(send_emails, "LOG_FILE", Path(directory) / "missing.csv"):
                self.assertEqual(send_emails.already_sent(), set())

    def test_sent_today_returns_zero_when_log_does_not_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(send_emails.sent_today(Path(directory) / "missing.csv"), 0)

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
