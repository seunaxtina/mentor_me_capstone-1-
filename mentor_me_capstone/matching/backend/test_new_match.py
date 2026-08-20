import requests
import sys

# Connect to running backend
API_URL = "http://127.0.0.1:8000/api/v1"

def test_new_user_matching():
    print("="*70)
    print("TESTING DYNAMIC MATCHING FOR NEW MENTEES AND NEW MENTORS")
    print("="*70)

    # 1. Register a new mentor
    mentor_email = "dynamic_mentor@example.com"
    mentor_password = "password123"
    print(f"\n1. Registering new mentor: {mentor_email}...")
    response = requests.post(f"{API_URL}/auth/signup", json={
        "email": mentor_email,
        "password": mentor_password,
        "role": "MENTOR"
    })
    if response.status_code not in [201, 400]:
        print(f"FAIL: Mentor registration failed: {response.text}")
        sys.exit(1)
        
    # Log in as the new mentor
    response = requests.post(f"{API_URL}/auth/token", data={
        "username": mentor_email,
        "password": mentor_password
    })
    mentor_token = response.json()["access_token"]
    mentor_headers = {"Authorization": f"Bearer {mentor_token}"}
    
    # Update mentor profile to unique specifications
    print("Updating new mentor profile details...")
    requests.put(f"{API_URL}/profile", json={
        "name": "Expert Mobile Mentor",
        "country": "Canada",
        "dev_type": "Developer, mobile;Engineering manager",
        "years_code_pro": 9.0,
        "job_factors": "Flex time or a flexible schedule;Remote work options",
        "org_size": "100 to 499 employees",
        "is_active": True,
        "max_mentees": 2
    }, headers=mentor_headers)

    # Fetch mentor profile to retrieve their user ID
    mentor_profile = requests.get(f"{API_URL}/users/me", headers=mentor_headers).json()
    mentor_id = mentor_profile["user"]["id"]
    print(f"PASS: Mentor profile set up. DB ID: {mentor_id}")

    # 2. Register a new mentee
    mentee_email = "dynamic_mentee@example.com"
    mentee_password = "password123"
    print(f"\n2. Registering new mentee: {mentee_email}...")
    response = requests.post(f"{API_URL}/auth/signup", json={
        "email": mentee_email,
        "password": mentee_password,
        "role": "MENTEE"
    })
    if response.status_code not in [201, 400]:
        print(f"FAIL: Mentee registration failed: {response.text}")
        sys.exit(1)
        
    # Log in as the new mentee
    response = requests.post(f"{API_URL}/auth/token", data={
        "username": mentee_email,
        "password": mentee_password
    })
    mentee_token = response.json()["access_token"]
    mentee_headers = {"Authorization": f"Bearer {mentee_token}"}
    
    # Update mentee profile to match the mentor's spec
    print("Updating new mentee profile details...")
    requests.put(f"{API_URL}/profile", json={
        "name": "Junior Mobile Mentee",
        "country": "Canada",
        "dev_type": "Developer, mobile",  # Role matches mentor's dev_type
        "years_code_pro": 1.0,            # Experience gap is 8 years (ideal)
        "job_factors": "Remote work options",  # Goal priority matches
        "org_size": "100 to 499 employees"   # Practical fit matches
    }, headers=mentee_headers)
    print("PASS: Mentee profile set up.")

    # 3. Fetch Matches
    print("\n3. Fetching matches for the new mentee...")
    response = requests.get(f"{API_URL}/matches?limit=1500", headers=mentee_headers)
    if response.status_code != 200:
        print(f"FAIL: Fetch matches failed: {response.text}")
        sys.exit(1)
        
    matches = response.json()
    
    # Find our new mentor in the matches
    matched_mentor = None
    for m in matches:
        if m["mentor_id"] == mentor_id:
            matched_mentor = m
            break
            
    if matched_mentor:
        print(f"PASS: Brand-new mentor '{matched_mentor['mentor_name']}' was found in matches!")
        print(f"  Match Score: {matched_mentor['total_score']} | Confidence: {matched_mentor['match_quality']}")
        print(f"  Breakdown: Role: {matched_mentor['role_score']}, Exp: {matched_mentor['experience_score']}, Goals: {matched_mentor['goals_score']}, Practical: {matched_mentor['practical_score']}")
        
        # Verify scores are correct
        # Role: intersection (Developer, mobile) / union (Developer, mobile, Engineering manager) = 1/2 = 0.5
        # Exp Gap: 9 - 1 = 8 yrs -> ideal (2-10y gap) = 1.0
        # Career-stage: mentee exp is 1.0 (tier '0-2y') = 1.0
        # Goals: intersection (Remote work options) / union (Flex time, Remote work options) = 1/2 = 0.5
        # Practical: org_size matches = 1.0
        # Weighted total = 0.5*0.3 + 1.0*0.25 + 1.0*0.2 + 0.5*0.15 + 1.0*0.1 = 0.775 -> Strong
        assert abs(matched_mentor['total_score'] - 0.775) < 1e-4, f"Expected score 0.775, got {matched_mentor['total_score']}"
        print("PASS: Match score matches the weighted scoring model calculations precisely!")
    else:
        print("FAIL: The newly registered mentor was not found in the match list.")
        sys.exit(1)
        
    # 4. Propose and accept match
    print("\n4. Proposing and accepting the connection...")
    match_id = matched_mentor["id"]
    response = requests.post(f"{API_URL}/matches/action", json={
        "match_id": match_id,
        "action": "ACCEPT"
    }, headers=mentee_headers)
    if response.status_code == 200:
        print("PASS: Mentee successfully accepted connection.")
    else:
        print(f"FAIL: Match acceptance failed: {response.text}")
        sys.exit(1)
        
    # 5. Check Mentor Requests Panel
    print("\n5. Checking requests history on the mentor's account...")
    response = requests.get(f"{API_URL}/matches/history", headers=mentor_headers)
    history = response.json()
    mentor_received = [h for h in history if h["id"] == match_id]
    if mentor_received and mentor_received[0]["status"] == "REQUESTED":
        print(f"PASS: Mentor successfully sees connection from '{mentor_received[0]['mentee_name']}' with status 'REQUESTED'.")
    else:
        print(f"FAIL: Mentor did not receive or see the requested connection correctly.")
        sys.exit(1)
        
    # 6. Mentor accepts request
    print("\n6. Mentor accepting the connection request...")
    response = requests.post(f"{API_URL}/matches/action", json={
        "match_id": match_id,
        "action": "ACCEPT",
        "availability_note": "UTC_DTS:2026-08-20T14:00/2026-08-20T14:30"
    }, headers=mentor_headers)
    if response.status_code == 200:
        print("PASS: Mentor successfully accepted connection request.")
    else:
        print(f"FAIL: Mentor match acceptance failed: {response.text}")
        sys.exit(1)
        
    # 7. Check final status
    response = requests.get(f"{API_URL}/matches/history", headers=mentee_headers)
    history = response.json()
    final_match = [h for h in history if h["id"] == match_id]
    if final_match and final_match[0]["status"] == "ACCEPTED":
        print("PASS: Connection is now fully ACCEPTED by both parties!")
    else:
        print("FAIL: Match status is not ACCEPTED.")
        sys.exit(1)
        
    print("\n" + "="*70)
    print("ALL DYNAMIC NEW USER MATCHING TESTS PASSED SUCCESSFULLY!")
    print("="*70)

if __name__ == '__main__':
    test_new_user_matching()
