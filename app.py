from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, Response
from checker import check_jobs, send_email, get_recipients, add_recipient, remove_recipient, update_recipient, send_telegram_message
import logging
import os
from dotenv import load_dotenv
import atexit
import codecs
import subprocess
import shutil
from pathlib import Path
import threading
import time
import json

def setup_onedrive_logs():
    """Setup real-time log copying to OneDrive"""
    try:
        # Get OneDrive path
        onedrive_path = Path.home() / "OneDrive"
        if not onedrive_path.exists():
            logger.error("OneDrive folder not found")
            return False
            
        # Create logs directory in OneDrive
        onedrive_logs = onedrive_path / "JobCheckerLogs"
        onedrive_logs.mkdir(exist_ok=True)
        
        # Setup log copying
        def copy_logs():
            while True:
                try:
                    # Copy job_checker.log
                    if os.path.exists('job_checker.log'):
                        shutil.copy2('job_checker.log', onedrive_logs / 'job_checker.log')
                    
                    # Copy app.log
                    if os.path.exists('app.log'):
                        shutil.copy2('app.log', onedrive_logs / 'app.log')
                        
                    time.sleep(5)  # Copy every 5 seconds
                except Exception as e:
                    logger.error(f"Error copying logs to OneDrive: {str(e)}")
                    time.sleep(30)  # Wait longer if there's an error
        
        # Start the copying thread
        copy_thread = threading.Thread(target=copy_logs, daemon=True)
        copy_thread.start()
        logger.info(f"Started copying logs to {onedrive_logs}")
        return True
    except Exception as e:
        logger.error(f"Failed to setup OneDrive logs: {str(e)}")
        return False

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log', mode='a', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Add a test log message
logger.info("Application started - Logging initialized")

# Setup OneDrive logs
setup_onedrive_logs()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-here')

# Global variable to store headless mode state
headless_mode = False  # Start with headless mode disabled

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/run_check')
def run_check():
    try:
        check_jobs(headless=headless_mode)
        flash('Job check completed successfully!')
    except Exception as e:
        flash(f'Error running job check: {str(e)}')
    return redirect(url_for('index'))

@app.route('/recipients')
def recipients():
    print("ROUTE /recipients CALLED")
    recs = get_recipients()
    print("DEBUG RECIPIENTS:", recs)
    return render_template('recipients2.html', recipients=recs)

@app.route('/add_recipient', methods=['POST'])
def add_recipient_route():
    try:
        email = request.form.get('email')
        telegram_chat_id = request.form.get('telegram_chat_id')
        notify_new = 'notify_new' in request.form
        notify_reopened = 'notify_reopened' in request.form
        notify_spotfreed = 'notify_spotfreed' in request.form
        use_telegram = 'use_telegram' in request.form
        use_email = 'use_email' in request.form
        delay = int(request.form.get('delay', 0))

        # Validate email
        if not email or '@' not in email:
            return jsonify({'status': 'error', 'message': 'Invalid email address'}), 400

        # Validate Telegram ID if using Telegram
        if use_telegram and not telegram_chat_id:
            return jsonify({'status': 'error', 'message': 'Telegram Chat ID is required when using Telegram'}), 400

        # Add recipient
        add_recipient(email, telegram_chat_id, notify_new, notify_reopened, notify_spotfreed, 
                     use_telegram, use_email, delay)
        
        return jsonify({'status': 'success', 'message': 'Recipient added successfully'})
    except Exception as e:
        logger.error(f"Error adding recipient: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/update_recipient', methods=['POST'])
def update_recipient_route():
    try:
        email = request.form.get('email')
        telegram_chat_id = request.form.get('telegram_chat_id')
        notify_new = 'notify_new' in request.form
        notify_reopened = 'notify_reopened' in request.form
        notify_spotfreed = 'notify_spotfreed' in request.form
        use_telegram = 'use_telegram' in request.form
        use_email = 'use_email' in request.form
        delay = int(request.form.get('delay', 0))

        # Validate email
        if not email or '@' not in email:
            return jsonify({'status': 'error', 'message': 'Invalid email address'}), 400

        # Validate Telegram ID if using Telegram
        if use_telegram and not telegram_chat_id:
            return jsonify({'status': 'error', 'message': 'Telegram Chat ID is required when using Telegram'}), 400

        # Update recipient
        update_recipient(email, telegram_chat_id, notify_new, notify_reopened, notify_spotfreed, 
                        use_telegram, use_email, delay)
        
        return jsonify({'status': 'success', 'message': 'Recipient updated successfully'})
    except Exception as e:
        logger.error(f"Error updating recipient: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/remove_recipient/<email>', methods=['GET'])
def remove_recipient_route(email):
    try:
        remove_recipient(email)
        return jsonify({'status': 'success', 'message': 'Recipient removed successfully'})
    except Exception as e:
        logger.error(f"Error removing recipient: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/edit_recipient/<email>', methods=['GET', 'POST'])
def edit_recipient_route(email):
    if request.method == 'POST':
        try:
            # Get all form fields with defaults
            telegram_chat_id = request.form.get('telegram_chat_id', '')
            delay = int(request.form.get('delay', 0))
            notify_new = 'notify_new' in request.form
            notify_reopened = 'notify_reopened' in request.form
            notify_spotfreed = 'notify_spotfreed' in request.form
            use_telegram = 'use_telegram' in request.form
            use_email = 'use_email' in request.form

            # Log the values for debugging
            logger.info(f"Updating recipient {email} with values:")
            logger.info(f"telegram_chat_id: {telegram_chat_id}")
            logger.info(f"delay: {delay}")
            logger.info(f"notify_new: {notify_new}")
            logger.info(f"notify_reopened: {notify_reopened}")
            logger.info(f"notify_spotfreed: {notify_spotfreed}")
            logger.info(f"use_telegram: {use_telegram}")
            logger.info(f"use_email: {use_email}")

            update_recipient(
                email=email,
                telegram_chat_id=telegram_chat_id,
                delay=delay,
                notify_new=notify_new,
                notify_reopened=notify_reopened,
                notify_spotfreed=notify_spotfreed,
                use_telegram=use_telegram,
                use_email=use_email
            )
            flash('Recipient updated successfully!')
            return redirect(url_for('recipients'))
        except Exception as e:
            logger.error(f"Error updating recipient {email}: {str(e)}")
            flash(f'Error updating recipient: {str(e)}')
    
    try:
        recipients = get_recipients()
        recipient = next((r for r in recipients if r['email'] == email), None)
        if recipient:
            # Ensure all required fields exist with defaults
            recipient.setdefault('notify_new', True)
            recipient.setdefault('notify_reopened', True)
            recipient.setdefault('notify_spotfreed', True)
            recipient.setdefault('use_telegram', False)
            recipient.setdefault('use_email', True)
            recipient.setdefault('delay', 0)
            recipient.setdefault('telegram_chat_id', '')
            
            return render_template('edit_recipient.html', recipient=recipient)
        flash('Recipient not found!')
        return redirect(url_for('recipients'))
    except Exception as e:
        logger.error(f"Error loading recipient {email}: {str(e)}")
        flash(f'Error loading recipient: {str(e)}')
        return redirect(url_for('recipients'))

@app.route('/test_email')
def test_email():
    try:
        recipients = get_recipients()
        if not recipients:
            flash('No recipients configured!')
            return redirect(url_for('index'))
        
        for recipient in recipients:
            logger.info(f"TEST EMAIL - Would send to: {recipient['email']}")
            send_email(
                recipient['email'],
                "Test Email from Job Checker",
                "This is a test email from the Job Checker application."
            )
        flash('Test emails sent successfully!')
    except Exception as e:
        flash(f'Error sending test emails: {str(e)}')
    return redirect(url_for('index'))

@app.route('/test_telegram')
def test_telegram():
    try:
        recipients = get_recipients()
        if not recipients:
            flash('No recipients configured!')
            return redirect(url_for('index'))
        
        for recipient in recipients:
            if recipient.get('use_telegram') and recipient.get('telegram_chat_id'):
                logger.info(f"TEST TELEGRAM - Would send to: {recipient['telegram_chat_id']}")
                send_telegram_message(
                    recipient['telegram_chat_id'],
                    "This is a test message from the Job Checker application."
                )
        flash('Test Telegram messages sent successfully!')
    except Exception as e:
        flash(f'Error sending test Telegram messages: {str(e)}')
    return redirect(url_for('index'))

@app.route('/toggle_headless', methods=['POST'])
def toggle_headless():
    global headless_mode
    headless_mode = not headless_mode
    logger.info(f"Headless mode {'enabled' if headless_mode else 'disabled'}")
    return jsonify({'status': 'success', 'headless': headless_mode})

@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': time.time()
    })

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/logs')
def view_logs():
    def read_log_file(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            return f"Error reading log file: {str(e)}"

    job_checker_log = read_log_file('job_checker.log')
    app_log = read_log_file('app.log')
    
    return render_template('logs.html', 
                         job_checker_log=job_checker_log,
                         app_log=app_log)

@app.route('/get_recipients')
def get_recipients_route():
    return jsonify(get_recipients())

def cleanup():
    logger.info("Application shutting down...")

atexit.register(cleanup)

if __name__ == '__main__':
    app.run(debug=True, port=5003)