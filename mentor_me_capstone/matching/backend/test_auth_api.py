import requests
import sys

API_URL = "http://127.0.0.1:8000/api/v1"

def test_api():
    print("="*60)
    print("RUNNING END-TO-END SECURITY AND PERSISTENCE API TESTS")
    print("="*60)
    
    # 1. Signup test
    email = "test_mentee_99@example.com"
    password = "securepassword123"
    print(f"\n1. Registering new mentee: {email}...")
    response = requests.post(f"{API_URL}/auth/signup", json={
        "email": email,
        "password": password,
        "role": "MENTEE"
    })
    if response.status_code == 201:
        print("PASS: User created successfully.")
    elif response.status_code == 400 and "already exists" in response.text:
        print("PASS: User already exists (continuing)...")
    else:
        print(f"FAIL: Signup returned status {response.status_code}: {response.text}")
        sys.exit(1)
        
    # 2. Login Failure test
    print("\n2. Testing login with incorrect credentials...")
    response = requests.post(f"{API_URL}/auth/token", data={
        "username": email,
        "password": "wrongpassword"
    })
    if response.status_code == 401:
        print("PASS: Login correctly rejected with 401.")
    else:
        print(f"FAIL: Invalid login returned status {response.status_code}: {response.text}")
        sys.exit(1)
        
    # 3. Login Success test
    print("\n3. Testing login with correct credentials...")
    response = requests.post(f"{API_URL}/auth/token", data={
        "username": email,
        "password": password
    })
    if response.status_code == 200:
        token_data = response.json()
        token = token_data["access_token"]
        print("PASS: Login succeeded. JWT retrieved.")
    else:
        print(f"FAIL: Login returned status {response.status_code}: {response.text}")
        sys.exit(1)
        
    headers = {"Authorization": f"Bearer {token}"}
    
    # 4. Fetch Profile
    print("\n4. Fetching current user profile...")
    response = requests.get(f"{API_URL}/users/me", headers=headers)
    if response.status_code == 200:
        profile = response.json()
        print(f"PASS: Profile loaded. Role: {profile['user']['role']}, Name: {profile['mentee']['name']}")
    else:
        print(f"FAIL: Fetch profile returned status {response.status_code}: {response.text}")
        sys.exit(1)
        
    # 5. Update Profile
    print("\n5. Updating profile details...")
    update_payload = {
        "name": "Jane Doe Updated",
        "country": "United Kingdom",
        "dev_type": "Developer, front-end;Developer, full-stack",
        "years_code_pro": 2.0,
        "job_factors": "Remote work options;Flex time or a flexible schedule",
        "org_size": "20 to 99 employees"
    }
    response = requests.put(f"{API_URL}/profile", json=update_payload, headers=headers)
    if response.status_code == 200:
        profile = response.json()
        assert profile["mentee"]["name"] == "Jane Doe Updated"
        assert profile["mentee"]["country"] == "United Kingdom"
        assert profile["mentee"]["years_code_pro"] == 2.0
        assert profile["mentee"]["exp_tier"] == "0-2y"
        print("PASS: Profile updated and experience tier correctly re-evaluated to 0-2y.")
    else:
        print(f"FAIL: Update profile returned status {response.status_code}: {response.text}")
        sys.exit(1)
        
    # 6. Fetch Matches
    print("\n6. Running matching algorithm via backend...")
    response = requests.get(f"{API_URL}/matches?limit=3", headers=headers)
    if response.status_code == 200:
        matches = response.json()
        print(f"PASS: Successfully retrieved {len(matches)} match recommendations.")
        for i, m in enumerate(matches):
            print(f"  Match {i+1}: {m['mentor_name']} | Score: {m['total_score']} | Confidence: {m['match_quality']}")
        match_id = matches[0]["id"]
        mentor_name = matches[0]["mentor_name"]
    else:
        print(f"FAIL: Matches search returned status {response.status_code}: {response.text}")
        sys.exit(1)
        
    # 7. Accept Match Action
    print(f"\n7. Accepting match proposal with {mentor_name}...")
    response = requests.post(f"{API_URL}/matches/action", json={
        "match_id": match_id,
        "action": "ACCEPT"
    }, headers=headers)
    if response.status_code == 200:
        match_record = response.json()
        assert match_record["status"] == "REQUESTED"
        print("PASS: Match successfully requested (mentee accepted).")
    else:
        print(f"FAIL: Match action returned status {response.status_code}: {response.text}")
        sys.exit(1)
        
    # 8. Check Match History
    print("\n8. Reviewing stored match history...")
    response = requests.get(f"{API_URL}/matches/history", headers=headers)
    if response.status_code == 200:
        history = response.json()
        requested_matches = [h for h in history if h["status"] == "REQUESTED"]
        assert len(requested_matches) > 0
        print(f"PASS: Verified {len(history)} match history records in DB. Requested match: {requested_matches[0]['mentor_name']}.")
    else:
        print(f"FAIL: History query returned status {response.status_code}: {response.text}")
        sys.exit(1)
        
    # 9. Test Role separation: Log in as a seeded Mentor
    mentor_email = "user_5@mentorme.demo"
    print(f"\n9. Logging in as seeded mentor: {mentor_email}...")
    response = requests.post(f"{API_URL}/auth/token", data={
        "username": mentor_email,
        "password": "password123"
    })
    if response.status_code == 200:
        m_token = response.json()["access_token"]
        print("PASS: Mentor login successful.")
    else:
        print(f"FAIL: Mentor login returned status {response.status_code}: {response.text}")
        sys.exit(1)
        
    m_headers = {"Authorization": f"Bearer {m_token}"}
    
    # 10. Access check: Mentor should not be allowed to run matching (Mentee role only)
    print("\n10. Testing role boundary (Mentor attempting to search matches)...")
    response = requests.get(f"{API_URL}/matches", headers=m_headers)
    if response.status_code == 403:
        print("PASS: API blocked mentor matching search with 403 Forbidden.")
    else:
        print(f"FAIL: Role boundary check failed. Status {response.status_code}: {response.text}")
        sys.exit(1)
        
    print("\n" + "="*60)
    print("ALL API END-TO-END SECURITY TESTS PASSED SUCCESSFULLY!")
    print("="*60)

if __name__ == '__main__':
    test_api()
