from celery import Celery
import os

class Config:
    # Celery configuration
    broker_url = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
    result_backend = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
    task_serializer = 'json'
    accept_content = ['json']
    timezone = 'UTC'
    enable_utc = True

app = Celery('tasks')
app.config_from_object(Config)

# Sample task for sending WhatsApp messages
@app.task
def send_whatsapp_message(to, message):
    # Logic to send WhatsApp message
    print(f'Sending message to {to}: {message}')

# Sample task for vendor notifications
@app.task
def notify_vendor(vendor_id, message):
    # Logic to notify vendor
    print(f'Notifying vendor {vendor_id}: {message}')

# Sample task for audit logging
@app.task
def log_audit(action, user_id):
    # Logic for logging audit
    print(f'Audit log - Action: {action}, User ID: {user_id}')