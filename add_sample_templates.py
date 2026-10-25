#!/usr/bin/env python3
"""Add or refresh the built-in sample email templates."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app import app, db
from models import User
from template_models import EmailTemplate


SAMPLE_TEMPLATES = [
    {
        "name": "Welcome Message",
        "subject": "Welcome to Our Organization!",
        "legacy_body": (
            "Dear {name},\n\nWelcome to our organization! We're excited to have "
            "you on board.\n\nBest regards,\n{sender_name}"
        ),
        "body": (
            "Dear {name},\n\n"
            "Welcome to our organization! We are delighted to have you with us "
            "and look forward to helping you get started. Whether you are here "
            "to explore our services, collaborate with our team, or learn more "
            "about what we do, we are glad you joined us.\n\n"
            "If you have questions or need help finding the right resources, "
            "please reply to this email and we will be happy to assist. We will "
            "also share useful updates and information as you get settled in.\n\n"
            "Thanks again for joining us. We look forward to working with you!\n\n"
            "Best regards,\n{sender_name}"
        ),
    },
    {
        "name": "Meeting Invitation",
        "subject": "Meeting Request - {meeting_topic}",
        "legacy_body": (
            "Hi {name},\n\nWe'd like to invite you to a meeting about "
            "{meeting_topic}.\n\nDate: {date}\nTime: {time}\nLocation: {location}"
            "\n\nPlease confirm your attendance.\n\nThanks,\n{sender_name}"
        ),
        "body": (
            "Hi {name},\n\n"
            "I would like to invite you to a meeting to discuss {meeting_topic}. "
            "Your perspective would be valuable, and we will leave time for "
            "questions and next steps.\n\n"
            "Date: {date}\n"
            "Time: {time}\n"
            "Location: {location}\n\n"
            "Please reply to let me know whether you can attend. If this time "
            "does not work for you, feel free to suggest an alternative. If "
            "there is anything you would like us to add to the agenda, please "
            "send it along in advance.\n\n"
            "Thank you, and I hope you can join us.\n\n"
            "Best,\n{sender_name}"
        ),
    },
    {
        "name": "Feedback Request",
        "subject": "We Value Your Feedback",
        "legacy_body": (
            "Dear {name},\n\nWe hope you're enjoying our services/products. "
            "We'd love to hear your feedback.\n\nYour opinion matters to us!"
            "\n\nBest regards,\n{sender_name}"
        ),
        "body": (
            "Dear {name},\n\n"
            "Thank you for choosing our services. We are always looking for "
            "ways to make your experience more useful and straightforward, and "
            "your feedback can help us understand what is working well and "
            "where we should improve.\n\n"
            "When you have a moment, please reply and share what you liked, "
            "anything that could have gone better, or a feature you would like "
            "to see in the future. Honest feedback is welcome, and there is no "
            "need for a lengthy response.\n\n"
            "We appreciate your time and the opportunity to serve you.\n\n"
            "Kind regards,\n{sender_name}"
        ),
    },
    {
        "name": "Product Launch",
        "subject": "Exciting News: {product_name} is Here!",
        "legacy_body": (
            "Hello {name},\n\nWe're thrilled to announce the launch of "
            "{product_name}!\n\nThis innovative solution will help you "
            "{benefit}.\n\nLearn more at: {url}\n\nCheers,\n{sender_name}"
        ),
        "body": (
            "Hello {name},\n\n"
            "We are pleased to introduce {product_name}, created to help you "
            "{benefit}. It is now available, and we would love for you to take "
            "a closer look.\n\n"
            "The product is designed to make everyday work simpler, with "
            "practical features and a straightforward experience. Visit the "
            "link below to explore the details, see how it works, and decide "
            "whether it is a good fit for you:\n\n"
            "{url}\n\n"
            "If you have questions or would like more information, just reply "
            "to this message. We would be glad to hear what you think.\n\n"
            "Best,\n{sender_name}"
        ),
    },
    {
        "name": "Newsletter Signup",
        "subject": "Thank You for Subscribing!",
        "legacy_body": (
            "Hi {name},\n\nThank you for subscribing to our newsletter."
            "\n\nYou'll receive regular updates about {topic}.\n\nStay tuned!"
            "\n\nWarm regards,\n{sender_name}"
        ),
        "body": (
            "Hi {name},\n\n"
            "Thank you for subscribing to our newsletter. We are glad to have "
            "you with us and look forward to sharing useful updates about "
            "{topic}.\n\n"
            "Our emails may include recent news, practical tips, upcoming "
            "announcements, and highlights we think you will find relevant. "
            "We will aim to keep each update clear and worthwhile, so you can "
            "quickly find the information that matters to you.\n\n"
            "If there is a topic you would especially like us to cover, reply "
            "and let us know. We appreciate your interest.\n\n"
            "Warm regards,\n{sender_name}"
        ),
    },
    {
        "name": "Event Reminder",
        "subject": "Reminder: {event_name} - {date}",
        "legacy_body": (
            "Dear {name},\n\nJust a reminder about {event_name} scheduled "
            "for {date} at {time}.\n\nLocation: {location}\nDetails: {details}"
            "\n\nLooking forward to seeing you there!\n\nBest,\n{sender_name}"
        ),
        "body": (
            "Dear {name},\n\n"
            "This is a friendly reminder that {event_name} is coming up on "
            "{date} at {time}.\n\n"
            "Location: {location}\n"
            "Event details: {details}\n\n"
            "Please review the details above and allow enough time to arrive "
            "or get connected. If you need to make any arrangements or "
            "have a question before the event, reply to this email and "
            "we will do our best to help.\n\n"
            "We look forward to seeing you there.\n\n"
            "Best regards,\n{sender_name}"
        ),
    },
    {
        "name": "Training Session",
        "subject": "Training Session: {topic}",
        "legacy_body": (
            "Hello {name},\n\nYou're invited to attend our training session "
            "on {topic}.\n\nDate: {date}\nTime: {time}\nVenue: {venue}"
            "\n\nPlease confirm your participation.\n\nThanks,\n{sender_name}"
        ),
        "body": (
            "Hello {name},\n\n"
            "You are invited to join our training session on {topic}. The "
            "session will provide a practical overview, time to work through "
            "key ideas, and an opportunity to ask questions.\n\n"
            "Date: {date}\n"
            "Time: {time}\n"
            "Venue: {venue}\n\n"
            "Please reply to confirm whether you can attend. If there is "
            "something specific you would like covered, let us know ahead of "
            "time so we can prepare. Bring any relevant questions or materials "
            "you would like to discuss.\n\n"
            "We look forward to learning with you.\n\n"
            "Best,\n{sender_name}"
        ),
    },
    {
        "name": "Project Update",
        "subject": "Project Update: {project_name}",
        "legacy_body": (
            "Hi {name},\n\nHere's an update on {project_name}:\n\nStatus: "
            "{status}\nProgress: {progress}%\nNext Steps: {next_steps}"
            "\n\nFor more details, please contact {contact_person}."
            "\n\nBest regards,\n{sender_name}"
        ),
        "body": (
            "Hi {name},\n\n"
            "Here is the latest update on {project_name}. The summary below "
            "covers the current status, progress to date, and the work planned "
            "next.\n\n"
            "Status: {status}\n"
            "Progress: {progress}%\n"
            "Next steps: {next_steps}\n\n"
            "We will continue to share updates as the project moves forward. "
            "If you have questions, see a risk we should consider, or need "
            "more detail about any item, please contact {contact_person}.\n\n"
            "Thank you for your continued collaboration.\n\n"
            "Best regards,\n{sender_name}"
        ),
    },
    {
        "name": "Customer Support",
        "subject": "Support Request - {ticket_number}",
        "legacy_body": (
            "Dear {customer_name},\n\nThank you for contacting our support "
            "team.\n\nYour ticket #{ticket_number} has been received and is "
            "being processed.\n\nOur team will respond within 24 hours."
            "\n\nTicket Details:\nSubject: {subject}\nPriority: {priority}"
            "\n\nBest regards,\n{support_team}"
        ),
        "body": (
            "Dear {customer_name},\n\n"
            "Thank you for contacting our support team. We have received "
            "your request and recorded it as ticket #{ticket_number}. Our "
            "team will review the information and follow up with you as soon "
            "as we can.\n\n"
            "Ticket details:\n"
            "Subject: {subject}\n"
            "Priority: {priority}\n\n"
            "If you have additional details, screenshots, or steps that may "
            "help us understand the issue, please reply to this email and "
            "include them. Please keep the ticket number in your reply so we "
            "can match the information to your request.\n\n"
            "Thank you for your patience.\n\n"
            "Regards,\n{support_team}"
        ),
    },
    {
        "name": "Thank You Note",
        "subject": "Thank You for Your Support",
        "legacy_body": (
            "Dear {name},\n\nThank you for your continued support and trust "
            "in our services.\n\nYour business means a lot to us, and we're "
            "committed to providing excellent service.\n\nWe look forward to "
            "serving you in the coming year.\n\nWith gratitude,\n{sender_name}"
        ),
        "body": (
            "Dear {name},\n\n"
            "Thank you for your continued support and for placing your trust "
            "in us. We truly value the time you have spent working with our "
            "team and the opportunity to support your goals.\n\n"
            "We remain committed to providing thoughtful, dependable service "
            "and to making each interaction a positive one. If there is "
            "anything we could do better or any way we can help, please feel "
            "free to get in touch.\n\n"
            "We appreciate your partnership and look forward to staying in "
            "touch.\n\n"
            "With gratitude,\n{sender_name}"
        ),
    },
]


def add_sample_templates():
    """Add missing samples and refresh the built-in sample copy."""
    with app.app_context():
        user = User.query.first()
        if not user:
            print("No users found in database. Please create a user first.")
            return

        added_count = 0
        updated_count = 0
        unchanged_count = 0

        for template_data in SAMPLE_TEMPLATES:
            existing = EmailTemplate.query.filter_by(
                user_id=user.id,
                name=template_data["name"],
            ).first()

            if existing is None:
                db.session.add(
                    EmailTemplate(
                        user_id=user.id,
                        name=template_data["name"],
                        subject=template_data["subject"],
                        body=template_data["body"],
                    )
                )
                added_count += 1
            elif (
                existing.subject == template_data["subject"]
                and existing.body == template_data["legacy_body"]
            ):
                existing.subject = template_data["subject"]
                existing.body = template_data["body"]
                updated_count += 1
            else:
                unchanged_count += 1

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        print(
            "Sample templates complete: "
            f"{added_count} added, {updated_count} updated, "
            f"{unchanged_count} unchanged."
        )


if __name__ == "__main__":
    add_sample_templates()
