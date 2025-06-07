import json
import os
import logging
import hashlib
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('job_removal.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
JOBS_FILE = "jobs_seen.json"
STATE_FILE = "job_checker_state.json"

def load_json_file(filename):
    """Load a JSON file safely."""
    try:
        if not os.path.exists(filename):
            logger.error(f"File {filename} does not exist")
            return None
        with open(filename, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading {filename}: {str(e)}")
        return None

def save_json_file(filename, data):
    """Save data to a JSON file safely."""
    try:
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving {filename}: {str(e)}")
        return False

def get_job_hash(job_key):
    """Create a hash for a job key using the same method as checker.py."""
    # Extract the first line which contains the title
    title = job_key.split('\n')[0]
    # Extract date and time from the key
    lines = job_key.split('\n')
    date = lines[1] if len(lines) > 1 else ""
    time = lines[2] if len(lines) > 2 else ""
    location = lines[3] if len(lines) > 3 else ""
    
    # Create the hash string in the same format as checker.py
    job_str = f"{title}{date}{time}{location}"
    return hashlib.md5(job_str.encode()).hexdigest()

def remove_recent_jobs(num_jobs):
    """Remove the specified number of most recent jobs from both tracking files."""
    # Load both files
    jobs_data = load_json_file(JOBS_FILE)
    state_data = load_json_file(STATE_FILE)
    
    if jobs_data is None or state_data is None:
        logger.error("Failed to load one or both files")
        return False
    
    # Get list of jobs and their hashes
    jobs_list = list(jobs_data.items())
    if not jobs_list:
        logger.info("No jobs found in jobs_seen.json")
        return False
    
    # Sort jobs by their key (which includes date and time)
    jobs_list.sort(key=lambda x: x[0], reverse=True)
    
    # Get the most recent jobs to remove
    jobs_to_remove = jobs_list[:num_jobs]
    
    # Create a backup of both files
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_jobs_file = f"jobs_seen_backup_{timestamp}.json"
    backup_state_file = f"job_checker_state_backup_{timestamp}.json"
    
    save_json_file(backup_jobs_file, jobs_data)
    save_json_file(backup_state_file, state_data)
    logger.info(f"Created backups: {backup_jobs_file} and {backup_state_file}")
    
    # Remove jobs from jobs_seen.json and track their hashes
    removed_hashes = set()
    for job_key, _ in jobs_to_remove:
        if job_key in jobs_data:
            # Generate the hash before removing the job
            job_hash = get_job_hash(job_key)
            removed_hashes.add(job_hash)
            del jobs_data[job_key]
            logger.info(f"Removed job from jobs_seen.json: {job_key}")
            logger.info(f"Generated hash for removal: {job_hash}")
    
    # Remove corresponding hashes from state.json
    jobs_removed = 0
    for hash_key in list(state_data.get("processed_jobs", {}).keys()):
        if hash_key in removed_hashes:
            del state_data["processed_jobs"][hash_key]
            jobs_removed += 1
            logger.info(f"Removed hash from state.json: {hash_key}")
    
    # Save the modified files
    if save_json_file(JOBS_FILE, jobs_data) and save_json_file(STATE_FILE, state_data):
        logger.info(f"Successfully removed {jobs_removed} jobs from both files")
        logger.info("Removed jobs:")
        for job_key, _ in jobs_to_remove:
            logger.info(f"- {job_key}")
        return True
    else:
        logger.error("Failed to save one or both files")
        return False

def main():
    """Main function to handle user input and job removal."""
    try:
        num_jobs = int(input("Enter the number of most recent jobs to remove: "))
        if num_jobs <= 0:
            logger.error("Please enter a positive number")
            return
        
        if remove_recent_jobs(num_jobs):
            logger.info("Job removal completed successfully")
        else:
            logger.error("Job removal failed")
    except ValueError:
        logger.error("Please enter a valid number")
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    main() 