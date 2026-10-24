#!/usr/bin/env python3
"""
Script to check existing templates in the database.
"""

import os
import sys
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from app import app, db
from models import User
from template_models import EmailTemplate

with app.app_context():
    user = User.query.first()
    if user:
        print(f'User found: {user.email}')
        templates = EmailTemplate.query.filter_by(user_id=user.id).all()
        print(f'Templates found: {len(templates)}')
        for t in templates:
            print(f'- {t.name}')
    else:
        print('No users found in database')