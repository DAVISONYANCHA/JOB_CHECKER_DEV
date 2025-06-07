import json
import os
import smtplib
import re
import logging
import time
import random
import hashlib
import msvcrt
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import traceback
from email.message import EmailMessage
import requests

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('job_checker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
USERNAME = os.getenv("ONSINCH_EMAIL")
PASSWORD = os.getenv("ONSINCH_PASSWORD")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
print("DEBUG ONSINCH_EMAIL:", USERNAME)
print("DEBUG ONSINCH_PASSWORD:", PASSWORD)
print("DEBUG EMAIL_SENDER:", EMAIL_SENDER)
print("DEBUG EMAIL_PASSWORD:", EMAIL_PASSWORD)
print("DEBUG TELEGRAM_BOT_TOKEN:", TELEGRAM_BOT_TOKEN)

JOBS_FILE = "jobs_seen.json"
RECIPIENTS_FILE = "recipients.json"
LOCK_FILE = "job_checker.lock"
STATE_FILE = "job_checker_state.json"
CHECK_INTERVAL = 300  # 5 minutes in seconds

# Add this function to send error emails
ERROR_EMAIL = "dalaw254@gmail.com"

def random_delay():
    """Add a random delay between actions."""
    time.sleep(random.uniform(2, 5))

def inspect_job_row(page, row):
    """Inspect a job row to find the best way to get its link."""
    try:
        # Get React props and event handlers
        react_info = page.evaluate("""
            (element) => {
                const info = {
                    props: {},
                    handlers: {},
                    reactKey: null,
                    reactProps: null
                };
                
                // Try to get React internal properties
                const key = Object.keys(element).find(key => key.startsWith('__reactProps$'));
                if (key) {
                    info.reactProps = element[key];
                }
                
                // Try to get React key
                const reactKey = Object.keys(element).find(key => key.startsWith('__reactKey$'));
                if (reactKey) {
                    info.reactKey = element[reactKey];
                }
                
                // Get all properties that might be React-related
                for (const prop of Object.getOwnPropertyNames(element)) {
                    if (prop.startsWith('__react') || prop.startsWith('_react')) {
                        info.props[prop] = element[prop];
                    }
                }
                
                // Try to get the click handler
                const clickHandler = element.onclick || element.getAttribute('onclick');
                if (clickHandler) {
                    info.handlers.click = clickHandler.toString();
                }
                
                // Try to get any data attributes that might contain job ID
                const dataAttrs = {};
                for (const attr of element.attributes) {
                    if (attr.name.startsWith('data-')) {
                        dataAttrs[attr.name] = attr.value;
                    }
                }
                info.dataAttrs = dataAttrs;
                
                return info;
            }
        """, row)
        logger.info("React inspection results:")
        logger.info(json.dumps(react_info, indent=2))

        # Also check the first cell specifically
        first_cell = row.query_selector('td')
        cell_info = page.evaluate("""
            (element) => {
                const info = {
                    props: {},
                    handlers: {},
                    reactKey: null,
                    reactProps: null
                };
                
                // Try to get React internal properties
                const key = Object.keys(element).find(key => key.startsWith('__reactProps$'));
                if (key) {
                    info.reactProps = element[key];
                }
                
                // Try to get React key
                const reactKey = Object.keys(element).find(key => key.startsWith('__reactKey$'));
                if (reactKey) {
                    info.reactKey = element[reactKey];
                }
                
                // Get all properties that might be React-related
                for (const prop of Object.getOwnPropertyNames(element)) {
                    if (prop.startsWith('__react') || prop.startsWith('_react')) {
                        info.props[prop] = element[prop];
                    }
                }
                
                // Try to get the click handler
                const clickHandler = element.onclick || element.getAttribute('onclick');
                if (clickHandler) {
                    info.handlers.click = clickHandler.toString();
                }
                
                // Try to get any data attributes that might contain job ID
                const dataAttrs = {};
                for (const attr of element.attributes) {
                    if (attr.name.startsWith('data-')) {
                        dataAttrs[attr.name] = attr.value;
                    }
                }
                info.dataAttrs = dataAttrs;
                
                return info;
            }
        """, first_cell)
        logger.info("First cell React inspection results:")
        logger.info(json.dumps(cell_info, indent=2))

        return {
            'row_info': react_info,
            'cell_info': cell_info
        }
    except Exception as e:
        logger.error(f"Error inspecting job row: {str(e)}")
        return None

def scrape_jobs_detailed(page=None, headless=True):
    """Scrape job details from the website including links."""
    jobs = {}
    try:
        if page is None:
            with sync_playwright() as p:
                # Launch browser with anti-detection measures
                logger.info(f"Launching browser in {'headless' if headless else 'visible'} mode...")
                browser = p.chromium.launch(
                    headless=headless,
                    args=[
                        '--disable-gpu',
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-blink-features=AutomationControlled'
                    ]
                )
                
                # Create a more realistic browser context
                context = browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    locale='en-GB',
                    timezone_id='Europe/London',
                    geolocation={'latitude': 51.5074, 'longitude': -0.1278},  # London coordinates
                    permissions=['geolocation']
                )
                
                # Add stealth scripts
                page = context.new_page()
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """)
                
                # Set longer timeouts
                page.set_default_timeout(90000)  # 90 seconds
                page.set_default_navigation_timeout(90000)
                
                try:
                    # Login with human-like behavior
                    logger.info("Attempting to log in...")
                    page.goto('https://splendid.onsinch.com/', wait_until='networkidle')
                    random_delay()
                    
                    # Fill email and password fields
                    page.fill('#UserEmail', USERNAME)
                    page.fill('#UserPassword', PASSWORD)
                    random_delay()

                    # Click the login button
                    page.click('[data-cy="sign-in-btn"]')
                    random_delay()
                    
                    page.wait_for_load_state('networkidle')
                    logger.info("Login successful")
                    random_delay()
                    
                    # Navigate to jobs page with human-like behavior
                    logger.info("Navigating to jobs page...")
                    page.goto('https://splendid.onsinch.com/react/position', wait_until='networkidle')
                    logger.info("Jobs page loaded")
                    random_delay()
                    
                    # Scroll the page like a human
                    page.evaluate("""
                        () => {
                            return new Promise((resolve) => {
                                let totalHeight = 0;
                                const distance = 100;
                                const timer = setInterval(() => {
                                    const scrollHeight = document.body.scrollHeight;
                                    window.scrollBy(0, distance);
                                    totalHeight += distance;
                                    
                                    if(totalHeight >= scrollHeight){
                                        clearInterval(timer);
                                        resolve();
                                    }
                                }, 100);
                            });
                        }
                    """)
                    random_delay()
                    
                    # Wait for job rows to be visible
                    logger.info("Waiting for job rows...")
                    page.wait_for_selector('tr.MuiTableRow-root.MuiTableRow-hover', timeout=90000)

                    # Get all job rows
                    job_rows = page.query_selector_all('tr.MuiTableRow-root.MuiTableRow-hover')
                    logger.info(f"Found {len(job_rows)} job rows")

                    for row in job_rows:
                        try:
                            cells = row.query_selector_all('td')
                            if len(cells) < 6:
                                continue  # skip if not enough columns

                            title = cells[0].inner_text().strip()
                            date = cells[1].inner_text().strip()
                            time_ = cells[2].inner_text().strip()
                            location = cells[3].inner_text().strip()
                            profession = cells[4].inner_text().strip()
                            occupancy = cells[5].inner_text().strip()

                            job_key = f"{title}\n{date}\n{time_}\n{location}\n{profession}\n{occupancy}"
                            jobs[job_key] = {
                                'title': title,
                                'date': date,
                                'time': time_,
                                'location': location,
                                'profession': profession,
                                'occupancy': occupancy,
                                'available': True
                            }
                        except Exception as e:
                            logger.error(f"Error processing job row: {str(e)}")
                            continue
                    
                except Exception as e:
                    logger.error(f"Error during page navigation: {str(e)}")
                    # Take a screenshot for debugging
                    try:
                        page.screenshot(path='error_screenshot.png')
                        logger.info("Error screenshot saved as error_screenshot.png")
                    except:
                        pass
                finally:
                    context.close()
                    browser.close()
        else:
            # Use existing page to get job details
            job_rows = page.query_selector_all('tr.MuiTableRow-root.MuiTableRow-hover')
            logger.info(f"Found {len(job_rows)} job rows")

            for row in job_rows:
                try:
                    cells = row.query_selector_all('td')
                    if len(cells) < 6:
                        continue  # skip if not enough columns

                    title = cells[0].inner_text().strip()
                    date = cells[1].inner_text().strip()
                    time_ = cells[2].inner_text().strip()
                    location = cells[3].inner_text().strip()
                    profession = cells[4].inner_text().strip()
                    occupancy = cells[5].inner_text().strip()

                    job_key = f"{title}\n{date}\n{time_}\n{location}\n{profession}\n{occupancy}"
                    jobs[job_key] = {
                        'title': title,
                        'date': date,
                        'time': time_,
                        'location': location,
                        'profession': profession,
                        'occupancy': occupancy,
                        'available': True
                    }
                except Exception as e:
                    logger.error(f"Error processing job row: {str(e)}")
                    continue
            
    except Exception as e:
        logger.error(f"Error during job scraping: {str(e)}")
    
    return jobs

def get_job_link(page, title_cell):
    """Get the link for a specific job by clicking its title."""
    try:
        # Click the title cell to get the link
        title_cell.click()
        random_delay()
        
        # Get the current URL after clicking
        link = page.url
        
        # Go back to the jobs page
        page.goto('https://splendid.onsinch.com/react/position', wait_until='networkidle')
        random_delay()
        
        # Wait for the table to be visible again
        page.wait_for_selector('tr.MuiTableRow-root.MuiTableRow-hover', timeout=90000)
        
        # Scroll back to where we were
        page.evaluate("""
            () => {
                return new Promise((resolve) => {
                    let totalHeight = 0;
                    const distance = 100;
                    const timer = setInterval(() => {
                        const scrollHeight = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        totalHeight += distance;
                        
                        if(totalHeight >= scrollHeight){
                            clearInterval(timer);
                            resolve();
                        }
                    }, 100);
                });
            }
        """)
        random_delay()
        
        return link
    except Exception as e:
        logger.error(f"Error getting job link: {str(e)}")
        return None

def get_job_link_via_api(page, job_id):
    """Get job link by making a direct API request."""
    try:
        # Make API request to get job details
        response = page.request.post(
            'https://splendid.onsinch.com/api',
            json={
                'id': job_id,
                'type': 'Position'
            }
        )
        
        if response.ok:
            data = response.json()
            # Construct job URL using the ID
            return f'https://splendid.onsinch.com/react/position/{job_id}'
        return None
    except Exception as e:
        logger.error(f"Error getting job link via API: {str(e)}")
        return None

def acquire_lock():
    """Acquire a Windows-compatible file lock."""
    try:
        if os.path.exists(LOCK_FILE):
            try:
                # Try to open existing lock file
                lock_file = open(LOCK_FILE, 'r+')
            except:
                # If can't open, assume stale and create new
                if os.path.exists(LOCK_FILE):
                    os.remove(LOCK_FILE)
                lock_file = open(LOCK_FILE, 'w')
        else:
            lock_file = open(LOCK_FILE, 'w')
        
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            return lock_file
        except:
            lock_file.close()
            return None
            
    except Exception as e:
        logger.error(f"Error acquiring lock: {str(e)}")
        return None

def release_lock(lock_file):
    """Release the Windows-compatible file lock."""
    if lock_file:
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        except:
            pass
        lock_file.close()
        try:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
        except:
            pass

def get_job_hash(job_info):
    """Create a unique hash for a job based on its key information."""
    job_str = f"{job_info.get('title', '')}{job_info.get('date', '')}{job_info.get('time', '')}{job_info.get('location', '')}"
    return hashlib.md5(job_str.encode()).hexdigest()

def load_state():
    """Load the current state of the job checker."""
    if not os.path.exists(STATE_FILE):
        return {
            "last_check_time": None,
            "processed_jobs": {},
            "last_run_id": None
        }
    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
            return state
    except Exception as e:
        logger.error(f"Error loading state: {str(e)}")
        return {
            "last_check_time": None,
            "processed_jobs": {},
            "last_run_id": None
        }

def save_state(state):
    """Save the current state of the job checker."""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving state: {str(e)}")

def load_seen_jobs():
    """Load the seen jobs."""
    if not os.path.exists(JOBS_FILE):
        return {}
    try:
        with open(JOBS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading seen jobs: {str(e)}")
        return {}

def save_seen_jobs(data):
    """Save the seen jobs."""
    try:
        with open(JOBS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving seen jobs: {str(e)}")

def get_recipients():
    """Load the list of email recipients."""
    if not os.path.exists(RECIPIENTS_FILE):
        return []
    try:
        with open(RECIPIENTS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading recipients: {str(e)}")
        return []

def add_recipient(email, telegram_chat_id='', delay=0, notify_new=True, notify_reopened=True, notify_spotfreed=True, use_telegram=False, use_email=True, receive_ngrok_url=True, receive_job_links=True):
    """Add a new recipient to the recipients list."""
    try:
        recipients = get_recipients()
        # Check if email already exists
        if any(r['email'] == email for r in recipients):
            logger.warning(f"Email {email} already exists in recipients")
            return False
        # Create new recipient with all fields
        new_recipient = {
            'email': email,
            'telegram_chat_id': telegram_chat_id,
            'delay': delay,
            'notify_new': notify_new,
            'notify_reopened': notify_reopened,
            'notify_spotfreed': notify_spotfreed,
            'use_telegram': use_telegram,
            'use_email': use_email,
            'receive_ngrok_url': receive_ngrok_url,
            'receive_job_links': receive_job_links
        }
        recipients.append(new_recipient)
        with open(RECIPIENTS_FILE, 'w') as f:
            json.dump(recipients, f, indent=2)
        logger.info(f"Added new recipient: {email}")
        return True
    except Exception as e:
        logger.error(f"Error adding recipient: {str(e)}")
        return False

def remove_recipient(email):
    """Remove a recipient."""
    recipients = get_recipients()
    recipients = [r for r in recipients if r["email"] != email]
    try:
        with open(RECIPIENTS_FILE, 'w') as f:
            json.dump(recipients, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving recipients: {str(e)}")

def update_recipient(email, telegram_chat_id='', delay=0, notify_new=True, notify_reopened=True, notify_spotfreed=True, use_telegram=False, use_email=True, receive_ngrok_url=True, receive_job_links=True):
    """Update an existing recipient's settings"""
    try:
        recipients = get_recipients()
        for recipient in recipients:
            if recipient['email'] == email:
                recipient.update({
                    'telegram_chat_id': telegram_chat_id,
                    'delay': delay,
                    'notify_new': notify_new,
                    'notify_reopened': notify_reopened,
                    'notify_spotfreed': notify_spotfreed,
                    'use_telegram': use_telegram,
                    'use_email': use_email,
                    'receive_ngrok_url': receive_ngrok_url,
                    'receive_job_links': receive_job_links
                })
                with open(RECIPIENTS_FILE, 'w') as f:
                    json.dump(recipients, f, indent=2)
                logger.info(f"Updated recipient: {email}")
                return True
        logger.warning(f"Recipient not found: {email}")
        return False
    except Exception as e:
        logger.error(f"Error updating recipient {email}: {str(e)}")
        return False

def send_whatsapp_message(to_number, message):
    """Send a WhatsApp message using Callmebot."""
    if not CALLMEBOT_API_KEY:
        logger.error("Callmebot API key not configured")
        return False
    
    try:
        # Remove any '+' or spaces from the phone number
        to_number = to_number.replace('+', '').replace(' ', '')
        
        # Callmebot API endpoint
        url = f"https://api.callmebot.com/whatsapp.php?phone={to_number}&text={message}&apikey={CALLMEBOT_API_KEY}"
        
        # Send the message
        response = requests.get(url)
        
        if response.status_code == 200:
            logger.info(f"WhatsApp message sent to {to_number}")
            return True
        else:
            logger.error(f"Error sending WhatsApp message: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {str(e)}")
        return False

def send_telegram_message(chat_id, message):
    """Send a message using Telegram bot."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Telegram bot token not configured")
        return False
    
    try:
        # Clean up chat_id - remove any spaces or special characters
        chat_id = str(chat_id).strip()
        
        # Log the attempt
        logger.info(f"Attempting to send Telegram message to chat_id: {chat_id}")
        
        # Telegram API endpoint
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        
        # Prepare the message
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"  # Allows basic HTML formatting
        }
        
        # Send the message
        response = requests.post(url, json=data)
        response_data = response.json()
        
        if response.status_code == 200 and response_data.get('ok'):
            logger.info(f"Telegram message sent successfully to {chat_id}")
            return True
        else:
            error_msg = response_data.get('description', 'Unknown error')
            logger.error(f"Telegram API error: {error_msg}")
            
            # Provide helpful error messages for common issues
            if "chat not found" in error_msg.lower():
                logger.error("This usually means either:")
                logger.error("1. The user hasn't started the bot yet (they need to send a message to the bot first)")
                logger.error("2. The chat ID is incorrect")
                logger.error("Please ask the user to:")
                logger.error("1. Open Telegram and search for your bot")
                logger.error("2. Click 'Start' or send any message to the bot")
                logger.error("3. Verify the chat ID is correct")
            elif "bot was blocked" in error_msg.lower():
                logger.error("The user has blocked the bot. They need to unblock it first.")
            elif "chat_id is empty" in error_msg.lower():
                logger.error("The chat ID is empty. Please provide a valid chat ID.")
            
            return False
            
    except Exception as e:
        logger.error(f"Error sending Telegram message: {str(e)}")
        return False

def send_email(to_email, subject, message):
    """Send email using simple SMTP."""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        logger.error("Email sender or password not configured")
        return False

    try:
        logger.info(f"Preparing to send email to {to_email}")
        # Create message
        msg = MIMEText(message, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From'] = EMAIL_SENDER
        msg['To'] = to_email

        logger.info("Connecting to SMTP server...")
        # Send email
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            logger.info("Logging in to SMTP server...")
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            logger.info("Sending email message...")
            server.send_message(msg)
            logger.info(f"Email successfully sent to {to_email}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP Authentication Error: {str(e)}")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"SMTP Error: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Error sending email to {to_email}: {str(e)}")
        return False

def send_notifications(updates):
    """Send notifications to recipients."""
    recipients = get_recipients()
    logger.info(f"Found {len(recipients)} recipients to notify")
    
    for recipient in recipients:
        # Debug log to show recipient settings
        logger.info(f"Recipient settings for {recipient['email']}:")
        logger.info(f"  use_email: {recipient.get('use_email', True)}")
        logger.info(f"  use_telegram: {recipient.get('use_telegram', False)}")
        logger.info(f"  notify_new: {recipient.get('notify_new', True)}")
        logger.info(f"  notify_reopened: {recipient.get('notify_reopened', True)}")
        logger.info(f"  notify_spotfreed: {recipient.get('notify_spotfreed', True)}")
        
        # Check if any notification methods are enabled
        use_email = recipient.get('use_email', True)  # Default to True if not specified
        use_telegram = recipient.get('use_telegram', False)
        
        if not (use_email or use_telegram):
            logger.info(f"Skipping {recipient['email']} - no notification methods enabled")
            continue
        
        # Prepare messages based on preferences
        messages = {}
        if recipient.get('notify_new', True) and updates.get('new'):
            messages['new'] = updates['new']
        if recipient.get('notify_reopened', True) and updates.get('reopened'):
            messages['reopened'] = updates['reopened']
        if recipient.get('notify_spotfreed', True) and updates.get('spotfreed'):
            messages['spotfreed'] = updates['spotfreed']
        
        if not messages:
            logger.info(f"No messages to send to {recipient['email']}")
            continue
        
        logger.info(f"Preparing to send notifications to {recipient['email']}")
        
        # Build notification message
        message_parts = []
        
        # Add new jobs
        if messages.get('new'):
            emoji = random.choice(['🎉', '✨', '🌟', '🎊', '🎯'])
            message_parts.append(f"\n{emoji} New Jobs Available {emoji}")
            message_parts.extend(messages['new'])
        
        # Add reopened jobs
        if messages.get('reopened'):
            emoji = random.choice(['🔄', '📢', '🔔', '🎪', '🎭'])
            message_parts.append(f"\n{emoji} Reopened Jobs {emoji}")
            message_parts.extend(messages['reopened'])
        
        # Add freed spots
        if messages.get('spotfreed'):
            emoji = random.choice(['🎪', '🎭', '🎨', '🎬', '🎪'])
            message_parts.append(f"\n{emoji} Spots Freed Up {emoji}")
            message_parts.extend(messages['spotfreed'])
        
        # Add a random quote at the end
        quotes = [
            "The show must go on! 🎭",
            "Break a leg! 🎪",
            "Curtain up! 🎬",
            "Lights, camera, action! 🎥",
            "Time to shine! ✨",
            "Your stage awaits! 🎭",
            "Make it count! 🎯",
            "Show time! 🎪",
            "Ready for your close-up! 🎬",
            "Let's make some magic! ✨"
        ]
        message_parts.append(f"\n\n{random.choice(quotes)}")
        
        message_body = "\n".join(message_parts)
        
        # Apply delay if specified
        delay = recipient.get('delay', 0)
        if delay > 0:
            logger.info(f"Delaying notifications for {recipient['email']} by {delay} minutes")
            time.sleep(delay * 60)  # Convert minutes to seconds
        
        # Send email if enabled
        if use_email:
            logger.info(f"Attempting to send email to {recipient['email']}")
            email_sent = send_email(recipient['email'], "Job Updates", message_body)
            if not email_sent:
                logger.error(f"Failed to send email to {recipient['email']}")
        
        # Send Telegram if enabled and chat_id provided
        if use_telegram and recipient.get('telegram_chat_id'):
            logger.info(f"Attempting to send Telegram message to {recipient['telegram_chat_id']}")
            telegram_sent = send_telegram_message(recipient['telegram_chat_id'], message_body)
            if not telegram_sent:
                logger.error(f"Failed to send Telegram message to {recipient['telegram_chat_id']}")

def send_error_email(subject, message):
    """Send error notifications using direct SMTP sending."""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        logger.error("Email sender or password not configured for error emails")
        return
    try:
        email_content = f"""From: {EMAIL_SENDER}
To: {ERROR_EMAIL}
Subject: {subject}
Content-Type: text/plain; charset="utf-8"
MIME-Version: 1.0

{message}"""

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, ERROR_EMAIL, email_content.encode('utf-8'))
        logger.info(f"Error email sent to {ERROR_EMAIL}")
    except Exception as e:
        logger.error(f"Failed to send error email: {str(e)}")

# Custom logging handler for errors
class ErrorEmailHandler(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            subject = f"Job Checker Error: {record.getMessage()}"
            # Include traceback if present
            if record.exc_info:
                message = self.format(record) + "\n\n" + ''.join(traceback.format_exception(*record.exc_info))
            else:
                message = self.format(record)
            send_error_email(subject, message)

# Add the error email handler to the logger
error_email_handler = ErrorEmailHandler()
error_email_handler.setLevel(logging.ERROR)
error_email_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(error_email_handler)

def check_jobs(headless=True):
    """Check for new jobs and send notifications."""
    try:
        # Acquire lock to prevent multiple instances
        if not acquire_lock():
            logger.warning("Another instance is already running")
            return False

        try:
            # Load current state
            state = load_state()
            seen_jobs = load_seen_jobs()
            
            # Scrape jobs
            jobs = scrape_jobs_detailed(headless=headless)
            logger.info(f"Loaded {len(seen_jobs)} previously seen jobs")
            logger.info(f"Found {len(jobs)} current jobs on website")
            
            messages_by_type = {
                "new": [],
                "reopened": [],
                "spotfreed": []
            }

            current_time = datetime.now().isoformat()
            run_id = f"run_{current_time}"
            
            # Process jobs and get links
            new_jobs_count = 0
            for key, info in jobs.items():
                job_hash = get_job_hash(info)
                if not job_hash:
                    logger.warning(f"Could not generate hash for job: {info['title']}")
                    continue

                if job_hash in state["processed_jobs"]:
                    logger.debug(f"Skipping already processed job: {info['title']}")
                    continue

                if key not in seen_jobs:
                    logger.info(f"Found new job: {info['title']}")
                    new_jobs_count += 1
                    
                    # Get link for new jobs only
                    job_rows = page.query_selector_all('tr.MuiTableRow-root.MuiTableRow-hover')
                    for row in job_rows:
                        cells = row.query_selector_all('td')
                        if len(cells) >= 6:
                            row_title = cells[0].inner_text().strip()
                            if row_title == info['title']:
                                logger.info(f"Getting link for new job: {info['title']}")
                                link = get_job_link(page, cells[0])
                                info['link'] = link
                                logger.info(f"Got link for job {info['title']}: {link}")
                                break
                    
                    msg = f"New shift/job: {key}"
                    if info.get('link'):
                        msg += f"\nLink: {info['link']}"
                    messages_by_type["new"].append(msg)
                    state["processed_jobs"][job_hash] = run_id
                else:
                    prev = seen_jobs[key]
                    if prev.get('locked') and not info['locked']:
                        logger.info(f"Found reopened job: {info['title']}")
                        msg = f"Re-opened: {key}"
                        if info.get('link'):
                            msg += f"\nLink: {info['link']}"
                        messages_by_type["reopened"].append(msg)
                        state["processed_jobs"][job_hash] = run_id
                    if (prev.get('filled') is not None and info['filled'] is not None
                            and info['filled'] < prev['filled'] and not info['locked']):
                        logger.info(f"Found job with freed spot: {info['title']}")
                        msg = (f"Spot freed: {key} (was {prev['filled']}/{prev['capacity']}, now {info['filled']}/{info['capacity']})")
                        if info.get('link'):
                            msg += f"\nLink: {info['link']}"
                        messages_by_type["spotfreed"].append(msg)
                        state["processed_jobs"][job_hash] = run_id
            
            logger.info(f"Found {new_jobs_count} new jobs in this cycle")

            if any(messages_by_type.values()):
                logger.info("Sending notifications for:")
                if messages_by_type["new"]:
                    logger.info(f"- {len(messages_by_type['new'])} new jobs")
                if messages_by_type["reopened"]:
                    logger.info(f"- {len(messages_by_type['reopened'])} reopened jobs")
                if messages_by_type["spotfreed"]:
                    logger.info(f"- {len(messages_by_type['spotfreed'])} jobs with freed spots")
                send_notifications(messages_by_type)
            else:
                logger.info("No updates to send")

            # Update state
            state["last_check_time"] = current_time
            state["last_run_id"] = run_id
            save_state(state)
            save_seen_jobs(jobs)
            logger.info("Job check cycle completed successfully")
        except Exception as e:
            logger.error(f"Error during job check cycle: {str(e)}")
            # Send error email
            error_message = f"Error during job check cycle: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            send_error_email("Job Checker Error", error_message)
        finally:
            release_lock(lock_file)
    except Exception as e:
        logger.error(f"Error in check_jobs: {str(e)}")
        return False

def run_scheduled_checks():
    """Run job checks on a schedule."""
    while True:
        try:
            check_jobs()
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Scheduled checks stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in scheduled check: {str(e)}")
            time.sleep(60)  # Wait a minute before retrying on error

def resend_last_update(force_all=False):
    """Resend the last job update to all recipients.
    
    Args:
        force_all (bool): If True, will send all current jobs regardless of whether they're new or not.
    """
    try:
        # Load the last seen jobs
        old = load_seen_jobs()
        new = scrape_jobs_detailed()
        
        messages_by_type = {
            "new": [],
            "reopened": [],
            "spotfreed": []
        }

        if force_all:
            # Force all current jobs to be sent as "new"
            for key, info in new.items():
                msg = f"Current job: {key}"
                if info.get('link'):
                    msg += f"\nLink: {info['link']}"
                messages_by_type["new"].append(msg)
        else:
            # Process the jobs to generate messages
            for key, info in new.items():
                job_hash = get_job_hash(info)
                if not job_hash:
                    continue

                if key not in old:
                    msg = f"New shift/job: {key}"
                    if info.get('link'):
                        msg += f"\nLink: {info['link']}"
                    messages_by_type["new"].append(msg)
                else:
                    prev = old[key]
                    if prev.get('locked') and not info['locked']:
                        msg = f"Re-opened: {key}"
                        if info.get('link'):
                            msg += f"\nLink: {info['link']}"
                        messages_by_type["reopened"].append(msg)
                    if (prev.get('filled') is not None and info['filled'] is not None
                            and info['filled'] < prev['filled'] and not info['locked']):
                        msg = (f"Spot freed: {key} (was {prev['filled']}/{prev['capacity']}, now {info['filled']}/{info['capacity']})")
                        if info.get('link'):
                            msg += f"\nLink: {info['link']}"
                        messages_by_type["spotfreed"].append(msg)

        if any(messages_by_type.values()):
            logger.info("Resending job updates to all recipients")
            send_notifications(messages_by_type)
            return True
        else:
            logger.info("No updates to resend")
            return False

    except Exception as e:
        logger.error(f"Error resending last update: {str(e)}")
        return False

def test_job_notifications():
    """Test function to simulate finding new jobs and sending notifications."""
    logger.info("Starting test job notification")
    
    # Simulate finding new jobs
    test_jobs = {
        "Test Job 1\n2024-05-10\n10:00-18:00\nLondon\nActor\nFull": {
            'title': 'Test Job 1',
            'date': '2024-05-10',
            'time': '10:00-18:00',
            'location': 'London',
            'profession': 'Actor',
            'occupancy': 'Full',
            'available': True
        },
        "Test Job 2\n2024-05-11\n14:00-22:00\nManchester\nDancer\nPart": {
            'title': 'Test Job 2',
            'date': '2024-05-11',
            'time': '14:00-22:00',
            'location': 'Manchester',
            'profession': 'Dancer',
            'occupancy': 'Part',
            'available': True
        }
    }
    
    # Create test messages
    messages_by_type = {
        "new": [],
        "reopened": [],
        "spotfreed": []
    }
    
    # Add test jobs to new messages
    for key, info in test_jobs.items():
        msg = f"New shift/job: {key}"
        messages_by_type["new"].append(msg)
        logger.info(f"Test job added: {key}")
    
    # Send notifications using the same function as the real job checker
    if any(messages_by_type.values()):
        logger.info("Sending test notifications")
        send_notifications(messages_by_type)
        logger.info("Test notifications sent")
    else:
        logger.info("No test messages to send")

if __name__ == "__main__":
    try:
        # Add command line argument handling
        import sys
        if len(sys.argv) > 1 and sys.argv[1] == "--test":
            test_job_notifications()
        else:
            # Uncomment the next line to test resending the last update
            # resend_last_update(force_all=True)  # Set to True to force resend all current jobs
            run_scheduled_checks()
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
    finally:
        # Clean up any remaining lock files
        try:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
        except:
            pass