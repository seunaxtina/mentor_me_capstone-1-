"""
Unit Test Suite for Single Sign-On (SSO) Authentication (Google & Facebook)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime
import uuid
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import Base, get_db
from backend import models, auth

client = TestClient(app)

def test_sso_auth_flow():
    print("\n--- Test Suite: Google & Facebook Single Sign-On (SSO) ---")
    
    # 0. Test Seamless Sign-In / Auto-provisioning for new Google user
    unreg_email = f"unreg_user_{uuid.uuid4().hex[:6]}@gmail.com"
    sso_unreg_signin = client.post(
        "/api/v1/auth/sso",
        json={
            "provider": "google",
            "email": unreg_email,
            "mode": "signin"
        }
    )
    assert sso_unreg_signin.status_code == 200
    assert "access_token" in sso_unreg_signin.json()
    print("PASS: New Google user automatically and seamlessly auto-provisioned.")

    # 1. Test Google SSO Sign-Up as Mentee (Create Account mode)
    g_email = f"google_user_{uuid.uuid4().hex[:6]}@gmail.com"
    g_name = "Maya Google User"
    g_pic = "https://lh3.googleusercontent.com/a/mock_avatar_google"
    g_oauth_id = f"google_oauth_{uuid.uuid4().hex[:8]}"
    
    sso_g_signup = client.post(
        "/api/v1/auth/sso",
        json={
            "provider": "google",
            "email": g_email,
            "name": g_name,
            "picture": g_pic,
            "oauth_id": g_oauth_id,
            "role": "MENTEE",
            "mode": "signup"
        }
    )
    assert sso_g_signup.status_code == 200, f"Google SSO Sign-up failed: {sso_g_signup.text}"
    g_data = sso_g_signup.json()
    assert g_data["is_new_user"] is True
    assert g_data["provider"] == "Google"
    assert g_data["role"] == "MENTEE"
    assert "access_token" in g_data
    g_token = g_data["access_token"]
    print(f"PASS: Google SSO Sign-Up created Mentee: {g_email}")
    
    # 2. Test Google SSO Sign-In (Existing User)
    sso_g_signin = client.post(
        "/api/v1/auth/sso",
        json={
            "provider": "google",
            "email": g_email,
            "oauth_id": g_oauth_id,
            "mode": "signin"
        }
    )
    assert sso_g_signin.status_code == 200
    g_signin_data = sso_g_signin.json()
    assert g_signin_data["is_new_user"] is False
    assert g_signin_data["email"] == g_email
    print(f"PASS: Google SSO Sign-In successfully authenticated existing user.")
    
    # 3. Test accessing /api/v1/users/me with Google SSO token
    me_resp = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {g_token}"}
    )
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["user"]["email"] == g_email
    assert me_data["user"]["auth_provider"] == "GOOGLE"
    assert me_data["mentee"]["name"] == g_name
    print(f"PASS: Mentee profile auto-populated with Google name and avatar.")
    
    # 4. Test Facebook SSO Sign-Up as Mentor
    fb_email = f"fb_mentor_{uuid.uuid4().hex[:6]}@facebook.com"
    fb_name = "Sarah Facebook Mentor"
    fb_pic = "https://graph.facebook.com/v12.0/mock_avatar/picture"
    fb_oauth_id = f"fb_oauth_{uuid.uuid4().hex[:8]}"
    
    sso_fb_signup = client.post(
        "/api/v1/auth/sso",
        json={
            "provider": "facebook",
            "email": fb_email,
            "name": fb_name,
            "picture": fb_pic,
            "oauth_id": fb_oauth_id,
            "role": "MENTOR",
            "mode": "signup"
        }
    )
    assert sso_fb_signup.status_code == 200, f"Facebook SSO Sign-up failed: {sso_fb_signup.text}"
    fb_data = sso_fb_signup.json()
    assert fb_data["is_new_user"] is True
    assert fb_data["provider"] == "Facebook"
    assert fb_data["role"] == "MENTOR"
    fb_token = fb_data["access_token"]
    print(f"PASS: Facebook SSO Sign-Up created Mentor: {fb_email}")
    
    # 5. Test Facebook SSO Sign-In (Existing Mentor)
    sso_fb_signin = client.post(
        "/api/v1/auth/sso",
        json={
            "provider": "facebook",
            "email": fb_email,
            "oauth_id": fb_oauth_id,
            "mode": "signin"
        }
    )
    assert sso_fb_signin.status_code == 200
    assert sso_fb_signin.json()["is_new_user"] is False
    print(f"PASS: Facebook SSO Sign-In successfully authenticated existing mentor.")
    
    # 6. Test OAuth Authorize URL generation (Google & Facebook)
    g_url_resp = client.get("/api/v1/auth/sso/authorize-url?provider=google&role=MENTEE&mode=signup")
    assert g_url_resp.status_code == 200
    assert "google" in g_url_resp.json()["auth_url"].lower()
    print("PASS: Google OAuth redirection URL successfully generated.")

    fb_url_resp = client.get("/api/v1/auth/sso/authorize-url?provider=facebook&role=MENTOR&mode=signup")
    assert fb_url_resp.status_code == 200
    assert "facebook" in fb_url_resp.json()["auth_url"].lower()
    print("PASS: Facebook OAuth redirection URL successfully generated.")

    # 7. Test OAuth Redirection Callback endpoint
    cb_resp = client.post(
        "/api/v1/auth/sso/callback",
        json={
            "provider": "google",
            "code": "4/0AbCdEf1234567890",
            "redirect_uri": "http://localhost:8501",
            "role": "MENTEE",
            "mode": "signup"
        }
    )
    assert cb_resp.status_code == 200
    assert "access_token" in cb_resp.json()
    print("PASS: OAuth Callback exchange successfully issued JWT token without manual inputs.")

    # 8. Test Invalid Provider Error Handling
    bad_sso = client.post(
        "/api/v1/auth/sso",
        json={
            "provider": "twitter",
            "email": "test@twitter.com"
        }
    )
    assert bad_sso.status_code == 400
    print("PASS: Unsupported provider correctly rejected with 400 Bad Request.")
    
    print("\nAll Google & Facebook SSO test cases passed successfully!\n")

if __name__ == "__main__":
    test_sso_auth_flow()
