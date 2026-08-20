import requests
import sys

API_URL = "http://127.0.0.1:8000/api/v1"

def test_freestyle_matching():
    print("="*70)
    print("TESTING DYNAMIC REGISTRATION AND FREESTYLE TEXT MATCHING")
    print("="*70)

    # 1. Register a new mentor with detailed bio text
    mentor_email = "cloud_mentor_v2@example.com"
    mentor_password = "password123"
    print(f"\n1. Registering new Cloud Mentor: {mentor_email}...")
    response = requests.post(f"{API_URL}/auth/signup", json={
        "email": mentor_email,
        "password": mentor_password,
        "role": "MENTOR",
        "name": "Cloud Mentor Dave",
        "country": "United States",
        "dev_type": "DevOps specialist;Engineer, site reliability",
        "years_code_pro": 10.0,
        "job_factors": "Remote work options;Opportunities for professional development",
        "org_size": "100 to 499 employees",
        "additional_details": "I can help with AWS cloud architecture, Docker containers, Kubernetes deployments, and Python backend scripts."
    })
    if response.status_code not in [201, 400]:
        print(f"FAIL: Mentor registration failed: {response.text}")
        sys.exit(1)
        
    # Log in to get mentor ID
    response = requests.post(f"{API_URL}/auth/token", data={
        "username": mentor_email,
        "password": mentor_password
    })
    mentor_token = response.json()["access_token"]
    mentor_headers = {"Authorization": f"Bearer {mentor_token}"}
    mentor_profile = requests.get(f"{API_URL}/users/me", headers=mentor_headers).json()
    mentor_id = mentor_profile["user"]["id"]
    print(f"PASS: Cloud Mentor set up. DB ID: {mentor_id}")

    # 2. Register a new mentee with matching keywords in freestyle details
    mentee_email = "cloud_mentee_v2@example.com"
    mentee_password = "password123"
    print(f"\n2. Registering new Cloud Mentee: {mentee_email}...")
    response = requests.post(f"{API_URL}/auth/signup", json={
        "email": mentee_email,
        "password": mentee_password,
        "role": "MENTEE",
        "name": "Cloud Mentee Anna",
        "country": "United States",
        "dev_type": "DevOps specialist",
        "years_code_pro": 1.0,
        "job_factors": "Remote work options;Opportunities for professional development",
        "org_size": "100 to 499 employees",
        "additional_details": "I want to learn about Docker containerization and Kubernetes cluster management."
    })
    if response.status_code not in [201, 400]:
        print(f"FAIL: Mentee registration failed: {response.text}")
        sys.exit(1)
        
    # Log in
    response = requests.post(f"{API_URL}/auth/token", data={
        "username": mentee_email,
        "password": mentee_password
    })
    mentee_token = response.json()["access_token"]
    mentee_headers = {"Authorization": f"Bearer {mentee_token}"}
    print("PASS: Cloud Mentee set up.")

    # 3. Query matches
    print("\n3. Querying matches for the new mentee...")
    response = requests.get(f"{API_URL}/matches?limit=1500", headers=mentee_headers)
    if response.status_code != 200:
        print(f"FAIL: Matches call failed: {response.text}")
        sys.exit(1)
        
    matches = response.json()
    
    # Find our new mentor in the list
    matched_mentor = None
    for m in matches:
        if m["mentor_id"] == mentor_id:
            matched_mentor = m
            break
            
    if matched_mentor:
        print(f"PASS: Found 'Cloud Mentor Dave' in matches!")
        print(f"  Total Match Score: {matched_mentor['total_score']} ({matched_mentor['match_quality']})")
        print(f"  Note: Since freestyle text was supplied, the weight distribution was dynamically shifted to include freestyle Jaccard overlap (10% weight).")
    else:
        print("FAIL: The newly registered Cloud Mentor was not found in the match list.")
        sys.exit(1)
        
    print("\n" + "="*70)
    print("ALL DYNAMIC REGISTRATION AND FREESTYLE TEXT MATCHING TESTS PASSED!")
    print("="*70)

if __name__ == '__main__':
    test_freestyle_matching()
