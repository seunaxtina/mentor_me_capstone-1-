import requests
import sys

API_URL = "http://127.0.0.1:8000/api/v1"

def test_diversity_ally_matching():
    print("="*75)
    print("TESTING DIVERSITY & INCLUSION ALLY MATCHING AND SCORING BOOST")
    print("="*75)

    # 1. Register an Ally Mentor (is_diversity_ally = True)
    ally_mentor_email = "ally_mentor@example.com"
    pwd = "password123"
    print(f"\n1. Registering Ally Mentor: {ally_mentor_email}...")
    requests.post(f"{API_URL}/auth/signup", json={
        "email": ally_mentor_email,
        "password": pwd,
        "role": "MENTOR",
        "name": "Inclusive Mentor",
        "country": "United States",
        "dev_type": "Developer, back-end",
        "years_code_pro": 10.0,
        "is_diversity_ally": True
    })

    # Log in and fetch Ally Mentor ID
    response = requests.post(f"{API_URL}/auth/token", data={"username": ally_mentor_email, "password": pwd})
    ally_token = response.json()["access_token"]
    ally_headers = {"Authorization": f"Bearer {ally_token}"}
    ally_profile = requests.get(f"{API_URL}/users/me", headers=ally_headers).json()
    ally_mentor_id = ally_profile["user"]["id"]
    print(f"Ally Mentor Registered. ID: {ally_mentor_id} | is_diversity_ally: {ally_profile['mentor']['is_diversity_ally']}")
    assert ally_profile['mentor']['is_diversity_ally'] is True, "Ally Mentor should be a diversity ally"

    # 2. Register a Non-Ally Mentor (is_diversity_ally = False)
    non_ally_email = "non_ally_mentor@example.com"
    print(f"\n2. Registering Non-Ally Mentor: {non_ally_email}...")
    requests.post(f"{API_URL}/auth/signup", json={
        "email": non_ally_email,
        "password": pwd,
        "role": "MENTOR",
        "name": "Standard Mentor",
        "country": "United States",
        "dev_type": "Developer, back-end",
        "years_code_pro": 10.0,
        "is_diversity_ally": False
    })

    response = requests.post(f"{API_URL}/auth/token", data={"username": non_ally_email, "password": pwd})
    non_ally_token = response.json()["access_token"]
    non_ally_headers = {"Authorization": f"Bearer {non_ally_token}"}
    non_ally_profile = requests.get(f"{API_URL}/users/me", headers=non_ally_headers).json()
    non_ally_id = non_ally_profile["user"]["id"]
    print(f"Non-Ally Mentor Registered. ID: {non_ally_id} | is_diversity_ally: {non_ally_profile['mentor']['is_diversity_ally']}")
    assert non_ally_profile['mentor']['is_diversity_ally'] is False, "Non-Ally Mentor should not be a diversity ally"

    # 3. Register a Mentee seeking an ally (prefer_diversity_ally = True)
    mentee_email = "ally_seeking_mentee@example.com"
    print(f"\n3. Registering Mentee seeking Ally: {mentee_email}...")
    requests.post(f"{API_URL}/auth/signup", json={
        "email": mentee_email,
        "password": pwd,
        "role": "MENTEE",
        "name": "Seeking Mentee",
        "country": "United States",
        "dev_type": "Developer, back-end",
        "years_code_pro": 1.0,
        "prefer_diversity_ally": True
    })

    response = requests.post(f"{API_URL}/auth/token", data={"username": mentee_email, "password": pwd})
    mentee_token = response.json()["access_token"]
    mentee_headers = {"Authorization": f"Bearer {mentee_token}"}
    mentee_profile = requests.get(f"{API_URL}/users/me", headers=mentee_headers).json()
    mentee_id = mentee_profile["user"]["id"]
    print(f"Mentee Registered. ID: {mentee_id} | prefer_diversity_ally: {mentee_profile['mentee']['prefer_diversity_ally']}")
    assert mentee_profile['mentee']['prefer_diversity_ally'] is True, "Mentee should prefer a diversity ally"

    # 4. Fetch Matches & Verify Scoring Boost
    print("\n4. Fetching matches and verifying scores...")
    response = requests.get(f"{API_URL}/matches?limit=100", headers=mentee_headers)
    matches = response.json()

    ally_match = None
    non_ally_match = None

    for m in matches:
        if m["mentor_id"] == ally_mentor_id:
            ally_match = m
        elif m["mentor_id"] == non_ally_id:
            non_ally_match = m

    assert ally_match is not None, "Ally Mentor should be in matches"
    assert non_ally_match is not None, "Non-Ally Mentor should be in matches"

    print(f"Ally Mentor Match Score: {ally_match['total_score']} | is_ally_boosted: {ally_match['is_ally_boosted']}")
    print(f"Non-Ally Mentor Match Score: {non_ally_match['total_score']} | is_ally_boosted: {non_ally_match['is_ally_boosted']}")

    # Verify boost (+10%) difference (capped at 1.0)
    score_diff = ally_match['total_score'] - non_ally_match['total_score']
    print(f"Calculated Score Difference: {score_diff:.3f}")
    if ally_match['total_score'] < 1.0:
        assert abs(score_diff - 0.10) < 1e-3, f"Expected a +0.10 score boost for the Ally Mentor, got {score_diff}"
    else:
        assert score_diff > 0, f"Expected Ally Mentor to have a higher score, but got {score_diff}"
    assert ally_match['is_ally_boosted'] is True, "Ally match should have is_ally_boosted = True"
    assert non_ally_match['is_ally_boosted'] is False, "Non-ally match should have is_ally_boosted = False"
    print("PASS: Score boost and flags verify correctly in /matches!")

    # 5. Accept Match and verify history
    print("\n5. Accepting Ally Match...")
    response = requests.post(f"{API_URL}/matches/action", json={
        "match_id": ally_match["id"],
        "action": "ACCEPT"
    }, headers=mentee_headers)
    assert response.status_code == 200, "Accepting match should succeed"
    action_res = response.json()
    assert action_res["is_ally_boosted"] is True, "Action response should indicate ally boosted"
    print("PASS: Action response shows is_ally_boosted = True")

    # Verify history
    print("Checking match history endpoint...")
    history_res = requests.get(f"{API_URL}/matches/history", headers=mentee_headers).json()
    accepted_hist = [h for h in history_res if h["id"] == ally_match["id"]]
    assert len(accepted_hist) == 1, "Accepted match should be in history"
    assert accepted_hist[0]["is_ally_boosted"] is True, "History response should indicate ally boosted"
    print("PASS: History response shows is_ally_boosted = True")

    print("\n" + "="*75)
    print("ALL DIVERSITY ALLYSHIP MATCHING AND SCORING TESTS PASSED SUCCESSFULLY!")
    print("="*75)

if __name__ == '__main__':
    test_diversity_ally_matching()
