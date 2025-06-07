from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_cors import CORS
import json
import os
import logging
from datetime import datetime
import threading
import time
import secrets
from checker import (
    check_jobs,
    get_recipients,
    add_recipient,
    remove_recipient,
    update_recipient,
    toggle_job_links,
    send_notifications,
    get_last_check_time,
    send_email,
    send_telegram_message
)
from remove_recent_jobs import remove_recent_jobs

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load secret key from environment variable or generate a new one
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY')
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    logger.warning("No FLASK_SECRET_KEY found in environment. Generated a new one. "
                  "For production, set FLASK_SECRET_KEY environment variable.")

app = Flask(__name__)
CORS(app)
app.secret_key = SECRET_KEY

# Global variables
is_checking = False
check_thread = None
last_check_time = None
last_check_status = None
last_check_error = None

def run_check():
    global is_checking, last_check_time, last_check_status, last_check_error
    try:
        is_checking = True
        last_check_time = datetime.now()
        last_check_status = "running"
        last_check_error = None
        
        # Run the check
        check_jobs()
        
        # Update status
        last_check_status = "success"
        logger.info("Job check completed successfully")
    except Exception as e:
        last_check_status = "error"
        last_check_error = str(e)
        logger.error(f"Error during job check: {str(e)}")
    finally:
        is_checking = False

def get_health_status():
    """Get the current health status of the application."""
    try:
        return {
            'status': 'healthy' if not is_checking else 'checking',
            'last_check': last_check_time,
            'last_status': last_check_status,
            'last_error': last_check_error
        }
    except Exception as e:
        logger.error(f"Error getting health status: {str(e)}")
        return {
            'status': 'error',
            'error': str(e)
        }

def get_active_recipients_count():
    """Get the count of active recipients."""
    try:
        recipients = get_recipients()
        return len([r for r in recipients if r.get('notify_new') or r.get('notify_reopened') or r.get('notify_spotfreed')])
    except Exception as e:
        logger.error(f"Error getting active recipients count: {str(e)}")
        return 0

@app.route('/')
def index():
    try:
        # Get all required data
        health_status = get_health_status()
        last_check = get_last_check_time()
        active_recipients = get_active_recipients_count()
        recipients = get_recipients()
        
        return render_template('index.html',
                             health_status=health_status,
                             last_check=last_check,
                             active_recipients=active_recipients,
                             recipients=recipients)
    except Exception as e:
        logger.error(f"Error in index route: {str(e)}")
        return render_template('500.html', error=str(e)), 500

@app.route('/recipients')
def recipients():
    """Display and manage recipients."""
    try:
        recipients_list = get_recipients()
        return render_template('recipients.html', recipients=recipients_list)
    except Exception as e:
        logger.error(f"Error in recipients route: {str(e)}")
        flash('Error loading recipients', 'error')
        return redirect(url_for('index'))

@app.route('/edit_recipient/<email>', methods=['GET', 'POST'])
def edit_recipient_route(email):
    try:
        if request.method == 'GET':
            # Get recipient details
            recipients = get_recipients()
            recipient = next((r for r in recipients if r['email'] == email), None)
            
            if not recipient:
                flash('Recipient not found.', 'error')
                return redirect(url_for('recipients'))
            
            return render_template('edit_recipient.html', recipient=recipient)
        
        # Handle POST request
        telegram_id = request.form.get('telegram_id')
        delay = int(request.form.get('delay', 0))
        notify_new = 'notify_new' in request.form
        notify_reopened = 'notify_reopened' in request.form
        notify_spotfreed = 'notify_spotfreed' in request.form

        success = update_recipient(
            email=email,
            telegram_id=telegram_id,
            delay=delay,
            notify_new=notify_new,
            notify_reopened=notify_reopened,
            notify_spotfreed=notify_spotfreed
        )

        if success:
            flash('Recipient updated successfully!', 'success')
        else:
            flash('Failed to update recipient.', 'error')

        return redirect(url_for('recipients'))

    except Exception as e:
        logger.error(f"Error in edit_recipient_route: {str(e)}")
        flash('An error occurred while updating the recipient.', 'error')
        return redirect(url_for('recipients'))

@app.route('/add_recipient', methods=['POST'])
def add_recipient_route():
    try:
        email = request.form.get('email')
        telegram_id = request.form.get('telegram_id')
        delay = int(request.form.get('delay', 0))
        notify_new = 'notify_new' in request.form
        notify_reopened = 'notify_reopened' in request.form
        notify_spotfreed = 'notify_spotfreed' in request.form

        success = add_recipient(
            email=email,
            telegram_id=telegram_id,
            delay=delay,
            notify_new=notify_new,
            notify_reopened=notify_reopened,
            notify_spotfreed=notify_spotfreed
        )

        if success:
            flash('Recipient added successfully!', 'success')
        else:
            flash('Failed to add recipient. Email might already exist.', 'error')

        return redirect(url_for('recipients'))

    except Exception as e:
        logger.error(f"Error in add_recipient_route: {str(e)}")
        flash('An error occurred while adding the recipient.', 'error')
        return redirect(url_for('recipients'))

@app.route('/remove_recipient/<email>', methods=['POST'])
def remove_recipient_route(email):
    """Remove a recipient."""
    try:
        success = remove_recipient(email)
        if success:
            return jsonify({'status': 'success', 'message': 'Recipient removed successfully'})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to remove recipient'}), 400
    except Exception as e:
        logger.error(f"Error in remove_recipient_route: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/run_check')
def run_check_route():
    global check_thread
    try:
        if is_checking:
            return jsonify({
                'status': 'error',
                'message': 'A check is already running'
            }), 409

        check_thread = threading.Thread(target=run_check)
        check_thread.start()
        
        return jsonify({
            'status': 'success',
            'message': 'Job check started'
        })
    except Exception as e:
        logger.error(f"Error in run_check route: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/health_check')
def health_check():
    try:
        health_status = get_health_status()
        return jsonify(health_status)
    except Exception as e:
        logger.error(f"Error in health_check route: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/get_recipients')
def get_recipients_route():
    try:
        recipients = get_recipients()
        return jsonify(recipients)
    except Exception as e:
        logger.error(f"Error in get_recipients route: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/test_recipient/<email>', methods=['POST'])
def test_recipient_route(email):
    try:
        # Get recipient details
        recipients = get_recipients()
        recipient = next((r for r in recipients if r['email'] == email), None)
        
        if not recipient:
            return jsonify({
                'status': 'error',
                'message': 'Recipient not found'
            }), 404

        # Send test notification
        if recipient.get('use_telegram') and recipient.get('telegram_id'):
            send_telegram_message(
                recipient['telegram_id'],
                "🔔 Test notification from Job Checker\n\nThis is a test message to verify your notification settings."
            )
        
        if recipient.get('use_email'):
            send_email(
                recipient['email'],
                "Test Notification - Job Checker",
                "This is a test message to verify your notification settings."
            )

        return jsonify({
            'status': 'success',
            'message': 'Test notification sent successfully'
        })

    except Exception as e:
        logger.error(f"Error in test_recipient_route: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/test_notifications', methods=['POST'])
def test_notifications_route():
    try:
        success = test_all_notifications()
        if success:
            return jsonify({
                'status': 'success',
                'message': 'Test notifications sent successfully'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to send test notifications'
            }), 500
    except Exception as e:
        logger.error(f"Error in test_notifications route: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/toggle_job_links/<email>', methods=['POST'])
def toggle_job_links_route(email):
    try:
        should_receive = request.json.get('should_receive', True)
        success = toggle_job_links(email, should_receive)
        
        if success:
            return jsonify({
                'status': 'success',
                'message': 'Job links preference updated successfully'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to update job links preference'
            }), 400
    except Exception as e:
        logger.error(f"Error in toggle_job_links_route: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/remove_jobs', methods=['POST'])
def remove_jobs_route():
    try:
        num_jobs = int(request.form.get('num_jobs', 1))
        if num_jobs <= 0:
            flash('Please enter a positive number of jobs to remove.', 'error')
            return redirect(url_for('index'))
        
        success = remove_recent_jobs(num_jobs)
        if success:
            flash(f'Successfully removed {num_jobs} most recent jobs.', 'success')
        else:
            flash('Failed to remove jobs. Check the logs for details.', 'error')
        
        return redirect(url_for('index'))
    except ValueError:
        flash('Please enter a valid number.', 'error')
        return redirect(url_for('index'))
    except Exception as e:
        logger.error(f"Error in remove_jobs_route: {str(e)}")
        flash('An error occurred while removing jobs.', 'error')
        return redirect(url_for('index'))

@app.route('/test_telegram/<email>', methods=['POST'])
def test_telegram_route(email):
    """Test Telegram notifications for a specific recipient."""
    try:
        recipients = get_recipients()
        recipient = next((r for r in recipients if r['email'] == email), None)
        
        if not recipient:
            flash('Recipient not found', 'error')
            return jsonify({'status': 'error', 'message': 'Recipient not found'})
        
        if not recipient.get('use_telegram'):
            flash('Telegram notifications not enabled for this recipient', 'error')
            return jsonify({'status': 'error', 'message': 'Telegram notifications not enabled'})
        
        if not recipient.get('telegram_id'):
            flash('No Telegram ID configured for this recipient', 'error')
            return jsonify({'status': 'error', 'message': 'No Telegram ID configured'})
        
        # Send a test message
        test_message = "🔔 Test Notification\n\nThis is a test message from your Job Checker bot. If you receive this, your Telegram notifications are working correctly!"
        success = send_telegram_message(recipient['telegram_id'], test_message)
        
        if success:
            flash('Test Telegram message sent successfully', 'success')
            return jsonify({'status': 'success', 'message': 'Test message sent successfully'})
        else:
            flash('Failed to send test Telegram message', 'error')
            return jsonify({'status': 'error', 'message': 'Failed to send test message'})
            
    except Exception as e:
        logger.error(f"Error in test_telegram_route: {str(e)}")
        flash('Error sending test message', 'error')
        return jsonify({'status': 'error', 'message': str(e)})

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html', error=str(error)), 500

if __name__ == '__main__':
    app.run(debug=True, port=5003)