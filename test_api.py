import requests

# TODO: Replace with your actual session cookies after logging in via browser
cookies = {
    # Example: 'sessionid': 'your_session_id_here',
}

url = "https://splendid.onsinch.com/api"

# TODO: Replace with the actual payload you see in browser DevTools when clicking a job
payload = {
    # Example: 'id': 110790, 'type': 'Position'
}

response = requests.post(url, cookies=cookies, json=payload)

print("Status code:", response.status_code)
try:
    print("Response JSON:", response.json())
except Exception:
    print("Response text:", response.text) 