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
    {
        "name": "Appointment Confirmation",
        "subject": "Your Appointment on {date}",
        "legacy_body": (
            "Hi {name},\n\nYour appointment is confirmed for {date} at "
            "{time}.\n\nLocation: {location}\n\nRegards,\n{sender_name}"
        ),
        "body": (
            "Hi {name},\n\n"
            "This is a confirmation of your appointment with us. Please keep "
            "the details below for reference:\n\n"
            "Date: {date}\n"
            "Time: {time}\n"
            "Location or meeting link: {location}\n"
            "Reason for visit: {appointment_type}\n\n"
            "If you need to change the time or have questions before the "
            "appointment, please reply to this message. We would appreciate "
            "as much notice as possible if you need to reschedule. We look "
            "forward to speaking with you.\n\n"
            "Kind regards,\n{sender_name}"
        ),
    },
    {
        "name": "Order Confirmation",
        "subject": "Order {order_number} Confirmation",
        "legacy_body": (
            "Hello {name},\n\nThank you for your order {order_number}. "
            "We are preparing it now.\n\nRegards,\n{sender_name}"
        ),
        "body": (
            "Hello {name},\n\n"
            "Thank you for placing an order with us. We have received your "
            "request and are preparing it for processing.\n\n"
            "Order number: {order_number}\n"
            "Order date: {order_date}\n"
            "Items: {items}\n"
            "Total: {total}\n"
            "Delivery details: {delivery_details}\n\n"
            "Please review the information and let us know promptly if "
            "anything needs to be corrected. We will send another update "
            "when the order status changes. If you have a question, reply "
            "to this email and include your order number.\n\n"
            "Thank you,\n{sender_name}"
        ),
    },
    {
        "name": "Payment Receipt",
        "subject": "Receipt for Payment {invoice_number}",
        "legacy_body": (
            "Dear {name},\n\nWe received your payment of {amount} on "
            "{payment_date}.\n\nThank you,\n{sender_name}"
        ),
        "body": (
            "Dear {name},\n\n"
            "This message confirms that we received your payment. Please "
            "retain these details for your records:\n\n"
            "Receipt or invoice number: {invoice_number}\n"
            "Amount paid: {amount}\n"
            "Payment date: {payment_date}\n"
            "Payment method: {payment_method}\n"
            "Description: {description}\n\n"
            "If you believe this receipt is incorrect or need a copy in "
            "another format, please reply and include the invoice number "
            "above. For your security, do not send full payment-card details "
            "by email.\n\n"
            "Thank you for your payment.\n\n"
            "Regards,\n{sender_name}"
        ),
    },
    {
        "name": "Follow-Up After Meeting",
        "subject": "Following Up on {meeting_topic}",
        "legacy_body": (
            "Hi {name},\n\nThank you for meeting about {meeting_topic}. "
            "Here are the next steps: {next_steps}\n\nBest,\n{sender_name}"
        ),
        "body": (
            "Hi {name},\n\n"
            "Thank you for taking the time to meet with me about "
            "{meeting_topic}. I appreciated the conversation and the "
            "perspective you shared.\n\n"
            "To keep things moving, here is a brief summary of the next "
            "steps we discussed:\n\n"
            "{next_steps}\n\n"
            "Please let me know if I missed anything or if you would like "
            "to adjust the plan. I will follow up again by {follow_up_date} "
            "with an update. In the meantime, feel free to reply with any "
            "questions or additional thoughts.\n\n"
            "Best regards,\n{sender_name}"
        ),
    },
    {
        "name": "Out of Office",
        "subject": "Out of Office: Returning {return_date}",
        "legacy_body": (
            "Hello,\n\nI am away until {return_date}. For urgent matters, "
            "contact {backup_contact}.\n\nRegards,\n{sender_name}"
        ),
        "body": (
            "Hello,\n\n"
            "Thank you for your message. I am currently away and expect to "
            "return on {return_date}. I may not be able to respond until "
            "then.\n\n"
            "For assistance while I am away, please contact "
            "{backup_contact} at {backup_email}. They can help with "
            "{coverage_details}.\n\n"
            "I will review your message after I return and respond as soon "
            "as I can. Thank you for your patience. If your message is "
            "time-sensitive, please contact the backup person rather than "
            "sending repeated follow-ups.\n\n"
            "Best,\n{sender_name}"
        ),
    },
    {
        "name": "Application Received",
        "subject": "We Received Your {application_type} Application",
        "legacy_body": (
            "Dear {name},\n\nWe received your application on {received_date}. "
            "We will review it and contact you.\n\nRegards,\n{sender_name}"
        ),
        "body": (
            "Dear {name},\n\n"
            "Thank you for submitting your {application_type} application. "
            "This message confirms that we received it on {received_date}.\n\n"
            "Reference number: {reference_number}\n"
            "Next step: {next_step}\n"
            "Expected update: {update_date}\n\n"
            "Our team will review the information provided and contact you "
            "when there is an update. If you need to add information or "
            "correct a detail, reply to this email and include your "
            "reference number. Please avoid sending sensitive documents "
            "unless we have specifically requested them through an "
            "appropriate channel.\n\n"
            "Thank you,\n{sender_name}"
        ),
    },
    {
        "name": "Service Maintenance Notice",
        "subject": "Planned Maintenance on {maintenance_date}",
        "legacy_body": (
            "Hello,\n\nWe will perform maintenance on {service} at "
            "{maintenance_time}. Some features may be unavailable.\n\n"
            "Regards,\n{sender_name}"
        ),
        "body": (
            "Hello,\n\n"
            "We are planning maintenance for {service} to improve "
            "reliability and performance. The work is scheduled for "
            "{maintenance_date}, beginning at {maintenance_time} "
            "({time_zone}).\n\n"
            "Expected duration: {duration}\n"
            "Possible impact: {service_impact}\n\n"
            "During this window, some features may be temporarily unavailable "
            "or respond more slowly. No action is required from you. We will "
            "share an update if the schedule changes or the work takes "
            "longer than expected. Thank you for planning around this "
            "maintenance window.\n\n"
            "Regards,\n{sender_name}"
        ),
    },
    {
        "name": "Event Invitation",
        "subject": "You Are Invited: {event_name}",
        "legacy_body": (
            "Hello {name},\n\nPlease join us for {event_name} on {date} "
            "at {time}. RSVP by {rsvp_date}.\n\nBest,\n{sender_name}"
        ),
        "body": (
            "Hello {name},\n\n"
            "We would be delighted if you could join us for {event_name}. "
            "We have planned time to connect, share updates, and hear from "
            "attendees.\n\n"
            "Date: {date}\n"
            "Time: {time}\n"
            "Location: {location}\n"
            "RSVP by: {rsvp_date}\n\n"
            "Please reply to let us know whether you can attend and mention "
            "any access or dietary requirements we should know about. If "
            "you cannot make it, you are welcome to send any questions in "
            "advance. We hope you can be there.\n\n"
            "Warm regards,\n{sender_name}"
        ),
    },
    {
        "name": "Project Kickoff",
        "subject": "Project Kickoff: {project_name}",
        "legacy_body": (
            "Hi {name},\n\nWe are starting {project_name} on {start_date}. "
            "Our first meeting is {meeting_time}.\n\nBest,\n{sender_name}"
        ),
        "body": (
            "Hi {name},\n\n"
            "We are ready to begin work on {project_name}, and I am looking "
            "forward to working together. The project is scheduled to start "
            "on {start_date}.\n\n"
            "Kickoff meeting: {meeting_time}\n"
            "Project goal: {project_goal}\n"
            "Initial milestone: {first_milestone}\n"
            "Shared workspace: {workspace_link}\n\n"
            "At the kickoff, we will confirm responsibilities, communication "
            "preferences, and the first set of priorities. Please review "
            "the available background material before the meeting and reply "
            "if there is anything important we should add to the agenda.\n\n"
            "Best,\n{sender_name}"
        ),
    },
    {
        "name": "Renewal Reminder",
        "subject": "A Reminder About Your Renewal on {renewal_date}",
        "legacy_body": (
            "Hello {name},\n\nYour {service_name} renewal is due on "
            "{renewal_date}. Contact us with questions.\n\nRegards,\n{sender_name}"
        ),
        "body": (
            "Hello {name},\n\n"
            "This is a friendly reminder that your {service_name} plan is "
            "scheduled for renewal on {renewal_date}.\n\n"
            "Plan: {plan_name}\n"
            "Renewal date: {renewal_date}\n"
            "Renewal amount: {renewal_amount}\n"
            "Account reference: {account_reference}\n\n"
            "If you would like to review your plan or have questions about "
            "the renewal, please contact us before that date at "
            "{support_contact}. No action is needed if you wish to continue "
            "with your current arrangement. We are happy to help you "
            "understand the available options.\n\n"
            "Kind regards,\n{sender_name}"
        ),
    },
]


def add_sample_templates():
    """Add or refresh the built-in sample templates for every account."""
    with app.app_context():
        users = User.query.order_by(User.id).all()
        if not users:
            print("No users found in database. Please create a user first.")
            return

        total_added = 0
        total_updated = 0
        total_unchanged = 0

        for user in users:
            added_count = 0
            updated_count = 0
            unchanged_count = 0
            existing_by_name = {
                template.name.casefold(): template
                for template in EmailTemplate.query.filter_by(user_id=user.id).all()
            }

            for template_data in SAMPLE_TEMPLATES:
                existing = existing_by_name.get(template_data["name"].casefold())

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

            total_added += added_count
            total_updated += updated_count
            total_unchanged += unchanged_count

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        print(
            "Sample templates complete: "
            f"{total_added} added, {total_updated} updated, "
            f"{total_unchanged} unchanged across {len(users)} user(s)."
        )


if __name__ == "__main__":
    add_sample_templates()
