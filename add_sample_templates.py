#!/usr/bin/env python3
"""
Script to add sample email templates to the database.
These are general templates covering various fields and use cases.
Credit: Created for MailFlow Studio by AI Assistant
"""

import os
import sys
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from app import app, db
from models import User
from template_models import EmailTemplate

# Sample templates covering various fields and use cases
# Credit: Created for MailFlow Studio by AI Assistant
SAMPLE_TEMPLATES = [
    {
        "name": "Welcome Message",
        "subject": "Welcome to Our Organization!",
        "body": "Dear {name},\n\nWelcome to our organization! We're excited to have you on board.\n\nBest regards,\n{sender_name}"
    },
    {
        "name": "Meeting Invitation",
        "subject": "Meeting Request - {meeting_topic}",
        "body": "Hi {name},\n\nWe'd like to invite you to a meeting about {meeting_topic}.\n\nDate: {date}\nTime: {time}\nLocation: {location}\n\nPlease confirm your attendance.\n\nThanks,\n{sender_name}"
    },
    {
        "name": "Feedback Request",
        "subject": "We Value Your Feedback",
        "body": "Dear {name},\n\nWe hope you're enjoying our services/products. We'd love to hear your feedback.\n\nYour opinion matters to us!\n\nBest regards,\n{sender_name}"
    },
    {
        "name": "Product Launch",
        "subject": "Exciting News: {product_name} is Here!",
        "body": "Hello {name},\n\nWe're thrilled to announce the launch of {product_name}!\n\nThis innovative solution will help you {benefit}.\n\nLearn more at: {url}\n\nCheers,\n{sender_name}"
    },
    {
        "name": "Newsletter Signup",
        "subject": "Thank You for Subscribing!",
        "body": "Hi {name},\n\nThank you for subscribing to our newsletter.\n\nYou'll receive regular updates about {topic}.\n\nStay tuned!\n\nWarm regards,\n{sender_name}"
    },
    {
        "name": "Event Reminder",
        "subject": "Reminder: {event_name} - {date}",
        "body": "Dear {name},\n\nJust a reminder about {event_name} scheduled for {date} at {time}.\n\nLocation: {location}\nDetails: {details}\n\nLooking forward to seeing you there!\n\nBest,\n{sender_name}"
    },
    {
        "name": "Training Session",
        "subject": "Training Session: {topic}",
        "body": "Hello {name},\n\nYou're invited to attend our training session on {topic}.\n\nDate: {date}\nTime: {time}\nVenue: {venue}\n\nPlease confirm your participation.\n\nThanks,\n{sender_name}"
    },
    {
        "name": "Project Update",
        "subject": "Project Update: {project_name}",
        "body": "Hi {name},\n\nHere's an update on {project_name}:\n\nStatus: {status}\nProgress: {progress}%\nNext Steps: {next_steps}\n\nFor more details, please contact {contact_person}.\n\nBest regards,\n{sender_name}"
    },
    {
        "name": "Customer Support",
        "subject": "Support Request - {ticket_number}",
        "body": "Dear {customer_name},\n\nThank you for contacting our support team.\n\nYour ticket #{ticket_number} has been received and is being processed.\n\nOur team will respond within 24 hours.\n\nTicket Details:\nSubject: {subject}\nPriority: {priority}\n\nBest regards,\n{support_team}"
    },
    {
        "name": "Thank You Note",
        "subject": "Thank You for Your Support",
        "body": "Dear {name},\n\nThank you for your continued support and trust in our services.\n\nYour business means a lot to us, and we're committed to providing excellent service.\n\nWe look forward to serving you in the coming year.\n\nWith gratitude,\n{sender_name}"
    }
]

def add_sample_templates():
    """Add sample templates to the database."""
    with app.app_context():
        # Find a test user (you might want to change this to a specific user)
        user = User.query.first()
        if not user:
            print("No users found in database. Please create a user first.")
            return
        
        print(f"Adding {len(SAMPLE_TEMPLATES)} sample templates for user: {user.email}")
        
        added_count = 0
        for template_data in SAMPLE_TEMPLATES:
            try:
                # Check if template already exists
                existing = EmailTemplate.query.filter_by(
                    user_id=user.id,
                    name=template_data['name']
                ).first()
                
                if not existing:
                    template = EmailTemplate(
                        user_id=user.id,
                        name=template_data['name'],
                        subject=template_data['subject'],
                        body=template_data['body']
                    )
                    db.session.add(template)
                    added_count += 1
                    print(f"Added template: {template_data['name']}")
                else:
                    print(f"Template already exists: {template_data['name']}")
                    
            except Exception as e:
                print(f"Error adding template '{template_data['name']}': {e}")
        
        try:
            db.session.commit()
            print(f"\nSuccessfully added {added_count} templates!")
        except Exception as e:
            db.session.rollback()
            print(f"Error committing changes: {e}")

if __name__ == "__main__":
    add_sample_templates()