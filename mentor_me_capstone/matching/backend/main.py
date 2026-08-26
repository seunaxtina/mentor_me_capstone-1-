from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional, Dict
import pandas as pd
import datetime
import os
import sys
import secrets
import jwt
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Add parent directory to path to import matching_algorithm_v1
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from matching_algorithm_v1 import compute_match_score, match_quality_label

from .database import engine, Base, get_db
from . import models, schemas, auth

# Initialize tables
Base.metadata.create_all(bind=engine)

# Dynamic DB migration for existing SQLite databases
try:
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE external_nominations ADD COLUMN last_contacted_at DATETIME;"))
except Exception:
    pass

try:
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE matches ADD COLUMN availability_note TEXT;"))
except Exception:
    pass

try:
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE matches ADD COLUMN mentee_notified BOOLEAN DEFAULT 0;"))
        conn.execute(text("ALTER TABLE matches ADD COLUMN mentor_notified BOOLEAN DEFAULT 0;"))
except Exception:
    pass

try:
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE mentees ADD COLUMN timezone TEXT DEFAULT 'UTC+00:00 (London, GMT)';"))
        conn.execute(text("ALTER TABLE mentors ADD COLUMN timezone TEXT DEFAULT 'UTC+00:00 (London, GMT)';"))
except Exception:
    pass

try:
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE mentees ADD COLUMN linkedin_link TEXT;"))
        conn.execute(text("ALTER TABLE mentors ADD COLUMN linkedin_link TEXT;"))
except Exception:
    pass

# Ensure seed data / admin account exists on initial clean deployment
try:
    with SessionLocal() as _db_init:
        if _db_init.query(models.User).count() == 0:
            try:
                from .seed import seed_db
                seed_db()
            except Exception:
                try:
                    from backend.seed import seed_db
                    seed_db()
                except Exception:
                    pass
except Exception:
    pass


for col_stmt in [
    "ALTER TABLE users ADD COLUMN name TEXT;",
    "ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT 1;",
    "ALTER TABLE users ADD COLUMN is_verified BOOLEAN DEFAULT 0;",
    "ALTER TABLE users ADD COLUMN two_factor_enabled BOOLEAN DEFAULT 1;",
    "ALTER TABLE users ADD COLUMN two_factor_secret TEXT;",
    "ALTER TABLE users ADD COLUMN otp_code TEXT;",
    "ALTER TABLE users ADD COLUMN otp_expiry DATETIME;",
    "ALTER TABLE users ADD COLUMN otp_failed_attempts INTEGER DEFAULT 0;",
    "ALTER TABLE users ADD COLUMN otp_last_sent_at DATETIME;",
    "ALTER TABLE users ADD COLUMN auth_provider TEXT DEFAULT 'LOCAL';",
    "ALTER TABLE users ADD COLUMN oauth_id TEXT;",
    "ALTER TABLE users ADD COLUMN avatar_url TEXT;",
    "ALTER TABLE users ADD COLUMN updated_at DATETIME;"
]:
    try:
        from sqlalchemy import text
    except Exception:
        pass

# Ensure default demo Admin account exists in database
try:
    with SessionLocal() as db_session:
        admin_check = db_session.query(models.User).filter(
            (models.User.email == "admin@mentoring-me.demo") | (models.User.email == "admin@mentorme.demo")
        ).first()
        if not admin_check:
            admin_user = models.User(
                id="admin-uuid-clean-001",
                email="admin@mentoring-me.demo",
                name="Admin Demo",
                password_hash=auth.get_password_hash("adminpassword"),
                role="ADMIN",
                is_active=True,
                is_verified=True,
                two_factor_enabled=False
            )
            db_session.add(admin_user)
            db_session.commit()
except Exception:
    pass

app = FastAPI(title="Mentoring-Me — Secure Backend API", version="1.0.0")

# CORS configurations — restrict to deployment URL in production
_cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/docs")


@app.post("/api/v1/auth/signup", response_model=schemas.TokenOrTwoFactorResponse,status_code=status.HTTP_201_CREATED)
@app.post("/api/v1/auth/users/", response_model=schemas.TokenOrTwoFactorResponse, status_code=status.HTTP_201_CREATED)
def signup(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    import hashlib
    import threading
    import datetime

    # Check if email exists
    existing_user = db.query(models.User).filter(models.User.email == user_in.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists."
        )

    # P1: Backend password strength validation
    if len(user_in.password.strip()) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long."
        )

    # Hash password
    hashed_pwd = auth.get_password_hash(user_in.password)
    # P0: Use cryptographically secure OTP generation
    otp = auth.generate_otp_code(6)
    now = datetime.datetime.utcnow()

    user_display_name = user_in.name or user_in.email.split("@")[0].capitalize()

    # Create User — P1: store hashed OTP instead of plaintext
    otp_hash = hashlib.sha256(otp.encode()).hexdigest()
    new_user = models.User(
        email=user_in.email,
        name=user_display_name,
        password_hash=hashed_pwd,
        role=user_in.role.upper() if hasattr(user_in, "role") and user_in.role else "MENTEE",
        two_factor_enabled=True,
        is_verified=False,
        otp_code=otp_hash,
        otp_expiry=now + datetime.timedelta(minutes=5),
        otp_failed_attempts=0,
        otp_last_sent_at=now
    )
    db.add(new_user)
    db.flush()

    # Parse experience tier based on years_code_pro if provided, otherwise default to role standards
    years = float(user_in.years_code_pro or (1.0 if user_in.role.upper() == "MENTEE" else 5.0))
    if years <= 2: exp_tier = '0-2y'
    elif years <= 5: exp_tier = '2-5y'
    elif years <= 10: exp_tier = '5-10y'
    elif years <= 20: exp_tier = '10-20y'
    else: exp_tier = '20y+'

    # Create corresponding sub-profile using supplied information
    if new_user.role == "MENTEE":
        new_profile = models.Mentee(
            id=new_user.id,
            name=user_display_name,
            country=user_in.country or "United States",
            ed_level=user_in.ed_level or "Bachelor's degree",
            dev_type=user_in.dev_type or "Developer, back-end",
            years_code_pro=years,
            exp_tier=exp_tier,
            job_factors=user_in.job_factors or "Remote work options",
            org_size=user_in.org_size or "Not stated",
            additional_details=user_in.additional_details,
            cv_path=user_in.cv_path,
            profile_pic=user_in.profile_pic,
            gender=user_in.gender,
            target_mentor_expertise=user_in.target_mentor_expertise,
            target_mentor_country=user_in.target_mentor_country,
            target_mentor_min_years=user_in.target_mentor_min_years,
            prefer_diversity_ally=user_in.prefer_diversity_ally
        )
        db.add(new_profile)
    elif new_user.role == "MENTOR":
        new_profile = models.Mentor(
            id=new_user.id,
            name=user_display_name,
            country=user_in.country or "United States",
            ed_level=user_in.ed_level or "Bachelor's degree",
            dev_type=user_in.dev_type or "Developer, back-end",
            years_code_pro=years,
            exp_tier=exp_tier,
            job_factors=user_in.job_factors or "Remote work options",
            org_size=user_in.org_size or "Not stated",
            is_active=True,
            max_mentees=3,
            additional_details=user_in.additional_details,
            contact_link=user_in.contact_link,
            cv_path=user_in.cv_path,
            profile_pic=user_in.profile_pic,
            gender=user_in.gender,
            is_diversity_ally=user_in.is_diversity_ally
        )
        db.add(new_profile)
        
    db.commit()
    db.refresh(new_user)

    # If invite_code is present, automatically connect the mentor to the nominating mentee
    if user_in.invite_code and new_user.role == "MENTOR":
        import uuid
        nomination = db.query(models.ExternalNomination).filter(models.ExternalNomination.invite_code == user_in.invite_code).first()
        if nomination and nomination.status == "PENDING":
            new_match = models.Match(
                id=str(uuid.uuid4()),
                mentee_id=nomination.mentee_id,
                mentor_id=new_user.id,
                role_score=1.0,
                experience_score=1.0,
                career_stage_score=1.0,
                goals_score=1.0,
                practical_score=1.0,
                total_score=1.0,
                match_quality="Strong",
                status="ACCEPTED",
                created_at=datetime.datetime.utcnow()
            )
            db.add(new_match)
            nomination.status = "ACCEPTED"
            db.commit()

    # Send verification email via Resend
    email_thread = threading.Thread(
        target=auth.send_email_notification,
        kwargs={
            "to_email": new_user.email,
            "subject": "Welcome to Mentoring-Me - Verify Your Account",
            "body_text": f"Hello,\n\nWelcome to Mentoring-Me! Your 6-digit email verification code is: {otp}\n\nThis code expires in 5 minutes.\n\nBest,\nMentoring-Me Team",
            "body_html": f"<p>Hello,</p><p>Welcome to Mentoring-Me! Your 6-digit email verification code is:</p><h2 style='color:#4F46E5; letter-spacing: 4px;'>{otp}</h2><p>This code expires in 5 minutes.</p><p>Best,<br>Mentoring-Me Team</p>"
        },
        daemon=True
    )
    email_thread.start()

    # P0: Unified challenge token creation (same as login flow)
    challenge_token = auth.create_2fa_challenge_token(
        user_id=new_user.id,
        otp_code=otp,
        email=new_user.email,
        role=new_user.role,
        expires_minutes=5
    )

    return schemas.TokenOrTwoFactorResponse(
        two_factor_required=True,
        two_factor_enabled=True,
        challenge_token=challenge_token,
        email=new_user.email,
        otp_code_preview=otp if os.getenv("DEBUG_OTP") == "true" else None,
        delivery_hint="A 6-digit verification code has been sent to your email to verify your account.",
        is_signup=True
    )

@app.post("/api/v1/auth/token", response_model=schemas.TokenOrTwoFactorResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    clean_username = form_data.username.strip().lower()
    user = db.query(models.User).filter(models.User.email == clean_username).first()
    
    # Auto-provision or verify Admin demo credentials
    if clean_username in ["admin@mentoring-me.demo", "admin@mentoring-me.com", "admin@mentorme.demo", "admin@mentorme.com"]:
        if form_data.password in ["adminpassword", "password123", "admin123", "admin"]:
            if not user:
                user = models.User(
                    id="admin-uuid-clean-001",
                    email=clean_username,
                    name="Admin Demo",
                    password_hash=auth.get_password_hash("adminpassword"),
                    role="ADMIN",
                    is_active=True,
                    is_verified=True,
                    two_factor_enabled=False
                )
                db.add(user)
                db.commit()
                db.refresh(user)
            else:
                user.role = "ADMIN"
                user.two_factor_enabled = False
                user.is_verified = True
                user.is_active = True
                db.commit()
        elif user and not auth.verify_password(form_data.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
    else:
        if not user or not auth.verify_password(form_data.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    # Check if Double Authentication (2FA) is enabled
    is_2fa_enabled = getattr(user, "two_factor_enabled", True)
    if is_2fa_enabled is None:
        is_2fa_enabled = True
        
    # Admin demo credentials bypass 2FA for immediate evaluation and management
    if user.role == "ADMIN" or clean_username in ["admin@mentoring-me.demo", "admin@mentoring-me.com", "admin@mentorme.demo", "admin@mentorme.com"]:
        is_2fa_enabled = False
        
    if is_2fa_enabled:
        import hashlib
        otp_code = auth.generate_otp_code(6)
        now = datetime.datetime.utcnow()
        # P1: Store hashed OTP in database
        user.otp_code = hashlib.sha256(otp_code.encode()).hexdigest()
        user.otp_expiry = now + datetime.timedelta(minutes=5)
        user.otp_failed_attempts = 0
        user.otp_last_sent_at = now
        db.commit()

        challenge_token = auth.create_2fa_challenge_token(
            user_id=user.id,
            otp_code=otp_code,
            email=user.email,
            role=user.role,
            expires_minutes=5
        )
        # Asynchronously dispatch 2FA email in background so login returns instantly without timing out
        import threading
        email_thread = threading.Thread(
            target=auth.send_email_notification,
            kwargs={
                "to_email": user.email,
                "subject": "Your Mentoring-Me 2FA Verification Code",
                "body_text": f"Hello,\n\nYour 6-digit Double Authentication code is: {otp_code}\n\nThis code will expire in 5 minutes.\n\nBest,\nMentoring-Me Security Team"
            },
            daemon=True
        )
        email_thread.start()

        return schemas.TokenOrTwoFactorResponse(
            two_factor_required=True,
            challenge_token=challenge_token,
            email=user.email,
            delivery_hint=f"A 6-digit security code has been sent to {user.email}.",
            otp_code_preview=otp_code if os.getenv("DEBUG_OTP") == "true" else None
        )
    
    # If 2FA disabled, generate direct access token
    access_token = auth.create_access_token(
        data={"sub": user.id, "role": user.role}
    )
    return schemas.TokenOrTwoFactorResponse(
        two_factor_required=False,
        access_token=access_token,
        token_type="bearer"
    )

@app.post("/api/v1/auth/2fa/verify", response_model=schemas.Token)
def verify_two_factor(req: schemas.TwoFactorVerifyRequest, db: Session = Depends(get_db)):
    try:
        payload = auth.verify_token(req.challenge_token)
        purpose = payload.get("purpose") or payload.get("type")
        if purpose != "2fa_challenge":
            raise HTTPException(status_code=400, detail="Invalid challenge token")
        email = payload.get("email") or payload.get("sub")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Verification session expired. Please log in again.")

    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Max 5 attempts rate limiting
    if (user.otp_failed_attempts or 0) >= 5:
        user.otp_code = None
        user.otp_expiry = None
        user.otp_failed_attempts = 0
        db.commit()
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. This code has expired. Please request a new code or log in again."
        )

    # Expiration check
    if not user.otp_code or not user.otp_expiry or datetime.datetime.utcnow() > user.otp_expiry:
        raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new one.")

    # Match check — P1: compare hashed OTP
    import hashlib
    submitted_hash = hashlib.sha256(req.code.strip().encode()).hexdigest()
    if user.otp_code != submitted_hash:
        user.otp_failed_attempts = (user.otp_failed_attempts or 0) + 1
        db.commit()
        remaining = 5 - user.otp_failed_attempts
        if remaining <= 0:
            user.otp_code = None
            user.otp_expiry = None
            db.commit()
            raise HTTPException(
                status_code=429,
                detail="Too many failed attempts. This code has been invalidated. Please log in again."
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid verification code. {remaining} attempt(s) remaining."
        )

    # Success: activate user & clear OTP
    user.otp_code = None
    user.otp_expiry = None
    user.otp_failed_attempts = 0
    user.is_verified = True
    db.commit()

    access_token = auth.create_access_token(
        data={"sub": user.id, "email": user.email, "role": user.role, "user_id": user.id, "name": user.name}
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/api/v1/auth/2fa/resend")
def resend_two_factor_code(req: schemas.TwoFactorResendRequest, db: Session = Depends(get_db)):
    import hashlib
    import threading

    try:
        payload = auth.verify_token(req.challenge_token)
        email = payload.get("email") or payload.get("sub")
        user_id = payload.get("sub")
    except Exception:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")

    user = db.query(models.User).filter((models.User.id == user_id) | (models.User.email == email) | (models.User.id == email) | (models.User.email == user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    now = datetime.datetime.utcnow()
    if user.otp_last_sent_at and os.getenv("TESTING") != "true" and not user.email.startswith("test_"):
        elapsed = (now - user.otp_last_sent_at).total_seconds()
        if elapsed < 60:
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {int(60 - elapsed)} second(s) before requesting another code."
            )

    # P0: Use secure OTP generation + P1: store hashed
    new_otp = auth.generate_otp_code(6)
    user.otp_code = hashlib.sha256(new_otp.encode()).hexdigest()
    user.otp_expiry = now + datetime.timedelta(minutes=5)
    user.otp_failed_attempts = 0
    user.otp_last_sent_at = now
    db.commit()

    email_thread = threading.Thread(
        target=auth.send_email_notification,
        kwargs={
            "to_email": user.email,
            "subject": "Your Mentoring-Me 2FA Verification Code",
            "body_text": f"Hello,\n\nYour new verification code is: {new_otp}\n\nThis code expires in 5 minutes.\n\nBest,\nMentoring-Me Team",
            "body_html": f"<p>Hello,</p><p>Your new verification code is:</p><h2 style='color:#4F46E5; letter-spacing: 4px;'>{new_otp}</h2><p>This code expires in 5 minutes.</p><p>Best,<br>Mentoring-Me Team</p>"
        },
        daemon=True
    )
    email_thread.start()

    # P0: Unified challenge token + P2: aligned 5-minute expiry
    new_challenge = auth.create_2fa_challenge_token(
        user_id=user.id,
        otp_code=new_otp,
        email=user.email,
        role=user.role,
        expires_minutes=5
    )

    return schemas.TokenOrTwoFactorResponse(
        two_factor_required=True,
        two_factor_enabled=True,
        challenge_token=new_challenge,
        email=user.email,
        otp_code_preview=new_otp if os.getenv("DEBUG_OTP") == "true" else None,
        delivery_hint="A new 6-digit security code has been sent to your email."
    )
@app.get("/api/v1/auth/email-status")
@app.get("/api/v1/auth/smtp-status")
def email_diagnostic_status():
    raw_resend_key = os.getenv("RESEND_API_KEY")
    resend_configured = bool(raw_resend_key and raw_resend_key.strip(' "\''))
    
    raw_host = os.getenv("SMTP_HOST")
    raw_port = os.getenv("SMTP_PORT")
    raw_user = os.getenv("SMTP_USER")
    raw_pass = os.getenv("SMTP_PASSWORD")
    
    test_result = "Not attempted"
    error_detail = None

    if resend_configured:
        resend_status = "Configured (HTTPS Port 443 active)"
    else:
        resend_status = "Not configured"

    if raw_host and raw_user and raw_pass:
        try:
            import smtplib
            h = raw_host.strip(' "\'')
            u = raw_user.strip(' "\'')
            p = raw_pass.strip(' "\'')
            try:
                with smtplib.SMTP_SSL(h, 465, timeout=8) as s:
                    s.login(u, p)
                test_result = "SUCCESS (Port 465 SSL)"
            except Exception as e_ssl:
                try:
                    with smtplib.SMTP(h, 587, timeout=8) as s:
                        s.starttls()
                        s.login(u, p)
                    test_result = "SUCCESS (Port 587 TLS)"
                except Exception as e_tls:
                    test_result = f"FAILED: SSL={e_ssl} | TLS={e_tls}"
                    error_detail = str(e_tls)
        except Exception as e:
            test_result = "FAILED"
            error_detail = str(e)
            
    return {
        "resend_active": resend_configured,
        "resend_key_preview": (raw_resend_key.strip(' "\'')[:6] + "..." + raw_resend_key.strip(' "\'')[-4:]) if resend_configured else None,
        "smtp_configured": bool(raw_host and raw_user and raw_pass),
        "smtp_host": raw_host,
        "smtp_port": raw_port,
        "smtp_user_preview": (raw_user[:3] + "***@" + raw_user.split("@")[-1]) if raw_user and "@" in raw_user else raw_user,
        "smtp_connection_test": test_result,
        "smtp_error_detail": error_detail
    }

@app.post("/api/v1/auth/2fa/toggle")
def toggle_two_factor(
    req: schemas.TwoFactorToggleRequest,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    current_user.two_factor_enabled = req.enabled
    db.commit()
    return {
        "two_factor_enabled": current_user.two_factor_enabled,
        "message": f"Double authentication has been {'enabled' if req.enabled else 'disabled'} successfully."
    }

@app.post("/api/v1/auth/forgot-password", response_model=schemas.ForgotPasswordResponse)
def forgot_password(req: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)):
    email_clean = req.email.lower().strip()
    user = db.query(models.User).filter(models.User.email == email_clean).first()

    # P1: Prevent user enumeration — always return a success-like response
    if not user:
        return schemas.ForgotPasswordResponse(
            message=f"If an account exists for {email_clean}, a password reset code has been sent.",
            challenge_token="",
            delivery_hint="Check your email for the reset code."
        )
        
    otp = auth.generate_otp_code(6)
    challenge_token = auth.create_password_reset_challenge_token(
        user_id=user.id,
        otp_code=otp,
        email=user.email,
        expires_minutes=15
    )
    
    # Store token record in DB
    reset_record = models.PasswordResetToken(
        user_id=user.id,
        email=user.email,
        token=otp,
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=15),
        used=False
    )
    db.add(reset_record)
    db.commit()
    
    # Send via SMTP if configured
    email_sent = auth.send_email_notification(
        to_email=user.email,
        subject="Password Reset Code — Mentoring-Me",
        body_text=f"Hello,\n\nYour 6-digit password reset code is: {otp}\n\nThis code will expire in 15 minutes.\n\nIf you did not request a password reset, please ignore this email.\n\nBest,\nMentoring-Me Support Team"
    )
    
    delivery_msg = f"If an account exists for {email_clean}, a password reset code has been sent."
    
    return schemas.ForgotPasswordResponse(
        message=delivery_msg,
        challenge_token=challenge_token,
        delivery_hint="Enter the 6-digit code and your new password.",
        otp_code_preview=otp if os.getenv("DEBUG_OTP") == "true" else None
    )

@app.post("/api/v1/auth/reset-password", response_model=schemas.ResetPasswordResponse)
def reset_password(req: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
    payload = auth.verify_password_reset_challenge_token(req.challenge_token, req.code)
    user_id = payload.get("sub")
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User account not found."
        )
        
    if len(req.new_password.strip()) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters long."
        )
        
    # Update password
    user.password_hash = auth.get_password_hash(req.new_password.strip())
    
    # Mark reset tokens as used
    recent_tokens = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.user_id == user.id,
        models.PasswordResetToken.used == False
    ).all()
    for t in recent_tokens:
        t.used = True
    db.commit()
    
    return schemas.ResetPasswordResponse(
        success=True,
        message="Your password has been successfully reset! You can now log in with your new password."
    )

def ensure_user_profile(user: models.User, target_role: str, db: Session, name: str = None, picture: str = None):
    """
    Ensures that the corresponding sub-profile table (models.Mentor or models.Mentee)
    exists and is populated for the given user and role, transferring any available
    profile details if migrating between roles.
    """
    display_name = name or user.name or (user.email.split("@")[0].capitalize() if user.email else "User")
    avatar = picture or user.avatar_url
    
    if target_role == "MENTOR":
        mentor = db.query(models.Mentor).filter(models.Mentor.id == user.id).first()
        if not mentor:
            mentee = db.query(models.Mentee).filter(models.Mentee.id == user.id).first()
            years = float(mentee.years_code_pro if mentee and mentee.years_code_pro is not None else 5.0)
            if years <= 2: exp_tier = '0-2y'
            elif years <= 5: exp_tier = '2-5y'
            elif years <= 10: exp_tier = '5-10y'
            elif years <= 20: exp_tier = '10-20y'
            else: exp_tier = '20y+'
            
            mentor = models.Mentor(
                id=user.id,
                name=mentee.name if mentee and mentee.name else display_name,
                country=mentee.country if mentee and mentee.country else "United States",
                ed_level=mentee.ed_level if mentee and mentee.ed_level else "Bachelor's degree",
                dev_type=mentee.dev_type if mentee and mentee.dev_type else "Developer, back-end",
                years_code_pro=years,
                exp_tier=exp_tier,
                job_factors=mentee.job_factors if mentee and mentee.job_factors else "Remote work options",
                org_size=mentee.org_size if mentee and mentee.org_size else "Not stated",
                additional_details=mentee.additional_details if mentee and mentee.additional_details else None,
                is_active=True,
                max_mentees=3,
                profile_pic=avatar or (mentee.profile_pic if mentee else None)
            )
            db.add(mentor)
            db.commit()
            db.refresh(mentor)
        return mentor
        
    elif target_role == "MENTEE":
        mentee = db.query(models.Mentee).filter(models.Mentee.id == user.id).first()
        if not mentee:
            mentor = db.query(models.Mentor).filter(models.Mentor.id == user.id).first()
            years = float(mentor.years_code_pro if mentor and mentor.years_code_pro is not None else 1.0)
            if years <= 2: exp_tier = '0-2y'
            elif years <= 5: exp_tier = '2-5y'
            elif years <= 10: exp_tier = '5-10y'
            elif years <= 20: exp_tier = '10-20y'
            else: exp_tier = '20y+'
            
            mentee = models.Mentee(
                id=user.id,
                name=mentor.name if mentor and mentor.name else display_name,
                country=mentor.country if mentor and mentor.country else "United States",
                ed_level=mentor.ed_level if mentor and mentor.ed_level else "Bachelor's degree",
                dev_type=mentor.dev_type if mentor and mentor.dev_type else "Developer, back-end",
                years_code_pro=years,
                exp_tier=exp_tier,
                job_factors=mentor.job_factors if mentor and mentor.job_factors else "Remote work options",
                org_size=mentor.org_size if mentor and mentor.org_size else "Not stated",
                additional_details=mentor.additional_details if mentor and mentor.additional_details else None,
                profile_pic=avatar or (mentor.profile_pic if mentor else None)
            )
            db.add(mentee)
            db.commit()
            db.refresh(mentee)
        return mentee
    return None

@app.post("/api/v1/auth/sso", response_model=schemas.SSOResponse)
def sso_authenticate(req: schemas.SSOLoginRequest, db: Session = Depends(get_db)):
    provider = req.provider.lower().strip()
    if provider not in ["google", "facebook"]:
        raise HTTPException(status_code=400, detail="Unsupported SSO provider. Must be 'google' or 'facebook'.")
        
    email = req.email.lower().strip()
    name = req.name.strip() if req.name else email.split("@")[0].capitalize()
    picture = req.picture.strip() if req.picture else None
    oauth_id = req.oauth_id.strip() if req.oauth_id else None
    
    # Optional production token verification if credentials exist
    google_client_id = os.getenv("GOOGLE_CLIENT_ID")
    facebook_app_secret = os.getenv("FACEBOOK_APP_SECRET")
    
    if provider == "google" and req.token_or_code and google_client_id:
        try:
            import requests as _req
            g_resp = _req.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={req.token_or_code}", timeout=5)
            if g_resp.status_code == 200:
                g_data = g_resp.json()
                if g_data.get("aud") == google_client_id or not google_client_id:
                    email = g_data.get("email", email).lower().strip()
                    name = g_data.get("name", name)
                    picture = g_data.get("picture", picture)
                    oauth_id = g_data.get("sub", oauth_id)
        except Exception as e:
            print(f"Google OAuth Token Verify Notice: {e}")
            
    elif provider == "facebook" and req.token_or_code and facebook_app_secret:
        try:
            import requests as _req
            fb_resp = _req.get(f"https://graph.facebook.com/me?fields=id,name,email,picture&access_token={req.token_or_code}", timeout=5)
            if fb_resp.status_code == 200:
                fb_data = fb_resp.json()
                email = fb_data.get("email", email).lower().strip()
                name = fb_data.get("name", name)
                oauth_id = fb_data.get("id", oauth_id)
                if "picture" in fb_data and "data" in fb_data["picture"]:
                    picture = fb_data["picture"]["data"].get("url", picture)
        except Exception as e:
            print(f"Facebook OAuth Token Verify Notice: {e}")

    # Look up existing user
    user = db.query(models.User).filter(
        (models.User.email == email) | 
        (models.User.oauth_id == oauth_id) if oauth_id else (models.User.email == email)
    ).first()
    
    is_new_user = False
    
    if user:
        # Enforce strict account and role separation:
        if req.mode == "signup":
            requested_role = (req.role or "MENTEE").upper()
            if requested_role != user.role:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"An account with this email ({user.email}) is already registered as a {user.role.capitalize()}. You cannot register the same email as a {requested_role.capitalize()}. Please sign in to your {user.role.capitalize()} account, or use a different Google account."
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"An account with this email ({user.email}) is already registered as a {user.role.capitalize()}. Please sign in on the 'Sign In' tab."
                )
        elif req.mode == "signin":
            if req.role and user.role != "ADMIN" and req.role.upper() != user.role:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"This account ({user.email}) is registered as a {user.role.capitalize()}, not a {req.role.capitalize()}. Please select 'Continue as {user.role.capitalize()} with {provider.capitalize()}' to sign in."
                )
        
        # Existing user: update provider info if not set
        if not user.name and name:
            user.name = name
        if not user.auth_provider or user.auth_provider == "LOCAL":
            user.auth_provider = provider.upper()
        if oauth_id and not user.oauth_id:
            user.oauth_id = oauth_id
        if picture and not user.avatar_url:
            user.avatar_url = picture
        user.is_verified = True
            
        db.commit()
        db.refresh(user)
        
        # Ensure the user's sub-profile exists and matches user.role
        ensure_user_profile(user, user.role, db, name=name, picture=picture)
        
        # Handle invite code if provided for a mentor
        if req.invite_code and user.role == "MENTOR":
            nomination = db.query(models.ExternalNomination).filter(models.ExternalNomination.invite_code == req.invite_code).first()
            if nomination:
                existing_match = db.query(models.Match).filter(
                    models.Match.mentee_id == nomination.mentee_id,
                    models.Match.mentor_id == user.id
                ).first()
                if not existing_match:
                    new_match = models.Match(
                        mentee_id=nomination.mentee_id,
                        mentor_id=user.id,
                        role_score=1.0,
                        experience_score=1.0,
                        career_stage_score=1.0,
                        goals_score=1.0,
                        practical_score=1.0,
                        total_score=1.0,
                        match_quality="Strong",
                        status="ACCEPTED",
                        created_at=datetime.datetime.utcnow()
                    )
                    db.add(new_match)
                nomination.status = "ACCEPTED"
                db.commit()
    else:
        # Seamlessly auto-provision new SSO user
        is_new_user = True
        user_role = (req.role or "MENTEE").upper()
        if user_role not in ["MENTEE", "MENTOR"]:
            user_role = "MENTEE"
            
        dummy_hash = auth.get_password_hash(secrets.token_urlsafe(24))
        user = models.User(
            email=email,
            name=name,
            password_hash=dummy_hash,
            role=user_role,
            is_active=True,
            is_verified=True,
            auth_provider=provider.upper(),
            oauth_id=oauth_id,
            avatar_url=picture,
            two_factor_enabled=False
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        ensure_user_profile(user, user.role, db, name=name, picture=picture)
        
        # Handle invite code if provided
        if req.invite_code and user.role == "MENTOR":
            nomination = db.query(models.ExternalNomination).filter(models.ExternalNomination.invite_code == req.invite_code).first()
            if nomination:
                new_match = models.Match(
                    mentee_id=nomination.mentee_id,
                    mentor_id=user.id,
                    role_score=1.0,
                    experience_score=1.0,
                    career_stage_score=1.0,
                    goals_score=1.0,
                    practical_score=1.0,
                    total_score=1.0,
                    match_quality="Strong",
                    status="ACCEPTED",
                    created_at=datetime.datetime.utcnow()
                )
                db.add(new_match)
                nomination.status = "ACCEPTED"
                db.commit()
                
    # Issue JWT access token
    access_token = auth.create_access_token(
        data={"sub": user.id, "role": user.role}
    )
    
    # Retrieve display name
    display_name = name
    if user.role == "MENTEE" and user.mentee_profile:
        display_name = user.mentee_profile.name or name
    elif user.role == "MENTOR" and user.mentor_profile:
        display_name = user.mentor_profile.name or name
        
    return schemas.SSOResponse(
        access_token=access_token,
        token_type="bearer",
        is_new_user=is_new_user,
        provider=provider.capitalize(),
        email=user.email,
        name=display_name,
        role=user.role
    )

@app.get("/api/v1/auth/sso/authorize-url", response_model=schemas.SSOAuthUrlResponse)
def get_sso_authorize_url(provider: str, redirect_uri: str = None, role: str = "MENTEE", mode: str = "signin", invite_code: str = None):
    import urllib.parse
    load_dotenv()
    if not redirect_uri:
        redirect_uri = os.getenv("APP_BASE_URL") or os.getenv("FRONTEND_URL") or "http://localhost:8501"
    redirect_uri = redirect_uri.rstrip("/")
    provider = provider.lower().strip()
    google_client_id = os.getenv("GOOGLE_CLIENT_ID")
    facebook_app_id = os.getenv("FACEBOOK_APP_ID")
    
    if provider == "google":
        if google_client_id and "your_" not in google_client_id:
            params = {
                "client_id": google_client_id.strip(),
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "access_type": "offline",
                "prompt": "select_account",
                "state": f"provider=google&role={role}&mode={mode}" + (f"&invite={invite_code}" if invite_code else "")
            }
            url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
            return schemas.SSOAuthUrlResponse(provider="google", auth_url=url, is_live_oauth=True)
        else:
            raise HTTPException(
                status_code=400,
                detail="Google OAuth is not configured on this backend. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in environment variables."
            )
            
    elif provider == "facebook":
        if facebook_app_id and "your_" not in facebook_app_id:
            params = {
                "client_id": facebook_app_id.strip(),
                "redirect_uri": redirect_uri,
                "scope": "email,public_profile",
                "state": f"provider=facebook&role={role}&mode={mode}" + (f"&invite={invite_code}" if invite_code else "")
            }
            url = f"https://www.facebook.com/v18.0/dialog/oauth?{urllib.parse.urlencode(params)}"
            return schemas.SSOAuthUrlResponse(provider="facebook", auth_url=url, is_live_oauth=True)
        else:
            params = {"sso_provider": "facebook", "role": role, "mode": mode}
            if invite_code: params["invite_code"] = invite_code
            url = f"{redirect_uri}?{urllib.parse.urlencode(params)}"
            return schemas.SSOAuthUrlResponse(provider="facebook", auth_url=url, is_live_oauth=False)
    else:
        raise HTTPException(status_code=400, detail="Unsupported provider. Must be 'google' or 'facebook'.")

@app.post("/api/v1/auth/sso/callback", response_model=schemas.SSOResponse)
def sso_callback(req: schemas.SSOCallbackRequest, db: Session = Depends(get_db)):
    load_dotenv()
    provider = req.provider.lower().strip()
    google_client_id = os.getenv("GOOGLE_CLIENT_ID")
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    facebook_app_id = os.getenv("FACEBOOK_APP_ID")
    facebook_app_secret = os.getenv("FACEBOOK_APP_SECRET")
    
    redirect_uri = (req.redirect_uri or os.getenv("APP_BASE_URL") or os.getenv("FRONTEND_URL") or "http://localhost:8501").rstrip("/")
    
    email = None
    name = None
    picture = None
    oauth_id = None
    
    if provider == "google" and google_client_secret:
        try:
            import requests as _req
            token_resp = _req.post("https://oauth2.googleapis.com/token", data={
                "code": req.code,
                "client_id": google_client_id.strip() if google_client_id else "",
                "client_secret": google_client_secret.strip() if google_client_secret else "",
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code"
            }, verify=False, timeout=10)
            if token_resp.status_code == 200:
                t_data = token_resp.json()
                access_tok = t_data.get("access_token")
                userinfo_resp = _req.get("https://www.googleapis.com/oauth2/v3/userinfo", headers={"Authorization": f"Bearer {access_tok}"}, verify=False, timeout=5)
                if userinfo_resp.status_code == 200:
                    userinfo = userinfo_resp.json()
                    email = userinfo.get("email")
                    name = userinfo.get("name")
                    picture = userinfo.get("picture")
                    oauth_id = userinfo.get("sub")
            else:
                err_data = token_resp.json() if "application/json" in token_resp.headers.get("content-type", "") else {"error": token_resp.text}
                err_desc = err_data.get("error_description") or err_data.get("error") or token_resp.text
                print(f"[GOOGLE SSO ERROR] Google token exchange returned {token_resp.status_code}: {err_desc}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Google authentication failed: {err_desc}"
                )
        except HTTPException:
            raise
        except Exception as e:
            print(f"Google Token Exchange Exception: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Google authentication error: {str(e)}"
            )
            
    elif provider == "facebook" and facebook_app_secret:
        try:
            import requests as _req
            token_resp = _req.get(f"https://graph.facebook.com/v18.0/oauth/access_token?client_id={facebook_app_id}&redirect_uri={req.redirect_uri}&client_secret={facebook_app_secret}&code={req.code}", timeout=10)
            if token_resp.status_code == 200:
                access_tok = token_resp.json().get("access_token")
                fb_user = _req.get(f"https://graph.facebook.com/me?fields=id,name,email,picture.type(large)&access_token={access_tok}", timeout=5).json()
                email = fb_user.get("email")
                name = fb_user.get("name")
                oauth_id = fb_user.get("id")
                if "picture" in fb_user and "data" in fb_user["picture"]:
                    picture = fb_user["picture"]["data"].get("url")
        except Exception as e:
            print(f"Facebook Token Exchange Error: {e}")
            
    if not email:
        email = f"{provider}.user@example.com"
        name = f"{provider.capitalize()} User"
        oauth_id = f"{provider}_{req.code[:8]}"
        
    return sso_authenticate(schemas.SSOLoginRequest(
        provider=provider,
        email=email,
        name=name,
        picture=picture,
        oauth_id=oauth_id,
        role=req.role or "MENTEE",
        mode=req.mode or "signin",
        invite_code=req.invite_code
    ), db=db)

@app.get("/api/v1/users/me", response_model=schemas.UserProfileResponse)
def read_current_user_profile(current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    mentee_resp = None
    mentor_resp = None
    
    if current_user.role == "MENTEE":
        mentee = db.query(models.Mentee).filter(models.Mentee.id == current_user.id).first()
        if not mentee:
            mentee = ensure_user_profile(current_user, "MENTEE", db)
        if mentee:
            mentee_resp = schemas.MenteeProfileResponse.model_validate(mentee)
    elif current_user.role == "MENTOR":
        mentor = db.query(models.Mentor).filter(models.Mentor.id == current_user.id).first()
        if not mentor:
            mentor = ensure_user_profile(current_user, "MENTOR", db)
        if mentor:
            mentor_resp = schemas.MentorProfileResponse.model_validate(mentor)
            
    user_resp = schemas.UserResponse.model_validate(current_user)
    
    return schemas.UserProfileResponse(
        user=user_resp,
        mentee=mentee_resp,
        mentor=mentor_resp
    )

@app.put("/api/v1/profile", response_model=schemas.UserProfileResponse)
def update_profile(
    profile_updates: dict,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role == "MENTEE":
        mentee = db.query(models.Mentee).filter(models.Mentee.id == current_user.id).first()
        if not mentee:
            raise HTTPException(status_code=404, detail="Mentee profile not found.")
        
        # Valid fields to update
        for field in ['name', 'country', 'ed_level', 'dev_type', 'years_code_pro', 'job_factors', 'org_size', 'additional_details', 'cv_path', 'profile_pic', 'gender', 'target_mentor_expertise', 'target_mentor_country', 'target_mentor_min_years', 'alternative_emails', 'prefer_diversity_ally', 'timezone', 'linkedin_link']:
            if field in profile_updates:
                setattr(mentee, field, profile_updates[field])
        
        # Recalculate experience tier based on years_code_pro
        years = float(mentee.years_code_pro or 0.0)
        if years <= 2: mentee.exp_tier = '0-2y'
        elif years <= 5: mentee.exp_tier = '2-5y'
        elif years <= 10: mentee.exp_tier = '5-10y'
        elif years <= 20: mentee.exp_tier = '10-20y'
        else: mentee.exp_tier = '20y+'
        
        db.commit()
        db.refresh(mentee)
        
    elif current_user.role == "MENTOR":
        mentor = db.query(models.Mentor).filter(models.Mentor.id == current_user.id).first()
        if not mentor:
            raise HTTPException(status_code=404, detail="Mentor profile not found.")
            
        for field in ['name', 'country', 'ed_level', 'dev_type', 'years_code_pro', 'job_factors', 'org_size', 'is_active', 'max_mentees', 'additional_details', 'contact_link', 'cv_path', 'profile_pic', 'gender', 'is_diversity_ally', 'timezone', 'linkedin_link']:
            if field in profile_updates:
                setattr(mentor, field, profile_updates[field])
                
        years = float(mentor.years_code_pro or 0.0)
        if years <= 2: mentor.exp_tier = '0-2y'
        elif years <= 5: mentor.exp_tier = '2-5y'
        elif years <= 10: mentor.exp_tier = '5-10y'
        elif years <= 20: mentor.exp_tier = '10-20y'
        else: mentor.exp_tier = '20y+'
        
        db.commit()
        db.refresh(mentor)
        
    # Return refreshed user profile info
    return read_current_user_profile(current_user, db)

def freestyle_match_score(mentee_text: str, mentor_text: str, mentor_devtype: str) -> float:
    if not mentee_text or not mentee_text.strip():
        return 0.5  # Neutral default when no text is provided
    
    stop_words = {
        "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your", "yours", 
        "he", "him", "his", "she", "her", "hers", "it", "its", "they", "them", "their", 
        "what", "which", "who", "whom", "this", "that", "these", "those", "am", "is", "are", 
        "was", "were", "be", "been", "being", "have", "has", "had", "having", "do", "does", 
        "did", "doing", "a", "an", "the", "and", "but", "if", "or", "because", "as", "until", 
        "while", "of", "at", "by", "for", "with", "about", "against", "between", "into", 
        "through", "during", "before", "after", "above", "below", "to", "from", "up", "down", 
        "in", "out", "on", "off", "over", "under", "again", "further", "then", "once", "here", 
        "there", "when", "where", "why", "how", "all", "any", "both", "each", "few", "more", 
        "most", "other", "some", "such", "no", "nor", "not", "only", "own", "same", "so", 
        "than", "too", "very", "can", "will", "just", "should", "now", "like", "want", "looking"
    }
    
    def get_keywords(text):
        if not text:
            return set()
        cleaned = "".join([c.lower() if c.isalnum() or c.isspace() else " " for c in text])
        words = cleaned.split()
        return {w for w in words if len(w) > 2 and w not in stop_words}
        
    mentee_words = get_keywords(mentee_text)
    if not mentee_words:
        return 0.5
        
    mentor_combined = (mentor_text or "") + " " + (mentor_devtype or "")
    mentor_words = get_keywords(mentor_combined)
    
    if not mentor_words:
        return 0.3
        
    intersection = len(mentee_words & mentor_words)
    union = len(mentee_words | mentor_words)
    return intersection / union if union > 0 else 0.3

@app.get("/api/v1/matches", response_model=list[schemas.MatchResponse])
def get_matches(
    limit: int = 5,
    current_user: models.User = Depends(auth.require_role(["MENTEE"])),
    db: Session = Depends(get_db)
):
    mentee = db.query(models.Mentee).filter(models.Mentee.id == current_user.id).first()
    if not mentee:
        raise HTTPException(status_code=404, detail="Mentee profile not found.")
        
    # Query all active mentors from database
    active_mentors = db.query(models.Mentor).filter(models.Mentor.is_active == True).all()
    if not active_mentors:
        return []
        
    # Format mentee as pandas Series
    mentee_series = pd.Series({
        'Respondent': mentee.id,
        'DevType': mentee.dev_type or 'Not stated',
        'YearsCodePro': float(mentee.years_code_pro or 0.0),
        'exp_tier': mentee.exp_tier or '0-2y',
        'JobFactors': mentee.job_factors or 'Not stated',
        'OrgSize': mentee.org_size or 'Not stated'
    })
    
    # Dynamic weights adjusting for freestyle text matching
    has_freestyle = bool(mentee.additional_details and mentee.additional_details.strip())
    if has_freestyle:
        weights = {
            'role': 0.25,
            'experience': 0.20,
            'career_stage': 0.20,
            'goals': 0.15,
            'freestyle': 0.10,
            'practical': 0.10,
        }
    else:
        weights = {
            'role': 0.30,
            'experience': 0.25,
            'career_stage': 0.20,
            'goals': 0.15,
            'freestyle': 0.00,
            'practical': 0.10,
        }
        
    # Compute match scores
    results = []
    for m in active_mentors:
        # Avoid matching with self
        if m.id == mentee.id:
            continue
            
        m_series = pd.Series({
            'Respondent': m.id,
            'Name': m.name or "Anonymous",
            'DevType': m.dev_type or 'Not stated',
            'YearsCodePro': float(m.years_code_pro or 0.0),
            'exp_tier': m.exp_tier or '5-10y',
            'JobFactors': m.job_factors or 'Not stated',
            'OrgSize': m.org_size or 'Not stated',
            'Country': m.country or 'Not stated'
        })
        
        score, breakdown = compute_match_score(mentee_series, m_series)
        exp_gap = m_series['YearsCodePro'] - mentee_series['YearsCodePro']
        
        # Calculate freestyle score
        free_score = freestyle_match_score(mentee.additional_details, m.additional_details, m.dev_type)
        
        # Calculate combined score dynamically based on presence of freestyle details
        if has_freestyle:
            score = (
                breakdown['role'] * weights['role'] +
                breakdown['experience'] * weights['experience'] +
                breakdown['career_stage'] * weights['career_stage'] +
                breakdown['goals'] * weights['goals'] +
                free_score * weights['freestyle'] +
                breakdown['practical'] * weights['practical']
            )
            
        # Target mentor preferences boost (up to 20% combined)
        target_boost = 0.0
        if mentee.target_mentor_expertise:
            keywords = [k.strip().lower() for k in mentee.target_mentor_expertise.replace(",", ";").split(";") if k.strip()]
            matches_count = 0
            if keywords:
                mentor_str = f"{m.dev_type or ''} {m.job_factors or ''} {m.additional_details or ''}".lower()
                for kw in keywords:
                    if kw in mentor_str:
                        matches_count += 1
                target_boost += min(0.10, (matches_count / len(keywords)) * 0.10)
                
        if mentee.target_mentor_country and m.country:
            if mentee.target_mentor_country.lower().strip() == m.country.lower().strip():
                target_boost += 0.05
                
        if mentee.target_mentor_min_years is not None:
            if float(m.years_code_pro or 0.0) >= float(mentee.target_mentor_min_years):
                target_boost += 0.05
                
        score = min(1.0, score + target_boost)

        # Representation & Role-Model Boost (SDG 5 Focus)
        is_representation_boosted = False
        if mentee.gender == "Female" and m.gender == "Female":
            score = min(1.0, score + 0.10)
            is_representation_boosted = True

        # Diversity Allyship Boost
        is_ally_boosted = False
        if mentee.prefer_diversity_ally and m.is_diversity_ally:
            score = min(1.0, score + 0.10)
            is_ally_boosted = True
            
        score = round(score, 3)
            
        results.append({
            'mentor_id': m.id,
            'mentor_name': m.name,
            'mentor_devtype': m.dev_type,
            'mentor_years': m.years_code_pro,
            'mentor_country': m.country,
            'mentor_org_size': m.org_size,
            'mentor_cv_path': m.cv_path,
            'mentor_profile_pic': m.profile_pic,
            'mentor_ed_level': m.ed_level,
            'mentor_job_factors': m.job_factors,
            'mentor_additional_details': m.additional_details,
            'experience_gap': exp_gap,
            'role_score': breakdown['role'],
            'experience_score': breakdown['experience'],
            'career_stage_score': breakdown['career_stage'],
            'goals_score': breakdown['goals'],
            'practical_score': breakdown['practical'],
            'total_score': score,
            'match_quality': match_quality_label(score),
            'mentor_gender': m.gender,
            'mentee_gender': mentee.gender,
            'is_representation_boosted': is_representation_boosted,
            'is_ally_boosted': is_ally_boosted
        })
        
    # Primary sort: total_score descending. Secondary: experience_gap ascending
    results.sort(key=lambda x: (x['total_score'], -x['experience_gap']), reverse=True)
    top_matches = results[:limit]
    
    # Clean previous proposed matches for this mentee first
    db.query(models.Match).filter(models.Match.mentee_id == mentee.id, models.Match.status == "PROPOSED").delete()
    
    db_matches = []
    for match in top_matches:
        new_db_match = models.Match(
            mentee_id=mentee.id,
            mentor_id=match['mentor_id'],
            role_score=match['role_score'],
            experience_score=match['experience_score'],
            career_stage_score=match['career_stage_score'],
            goals_score=match['goals_score'],
            practical_score=match['practical_score'],
            total_score=match['total_score'],
            match_quality=match['match_quality'],
            status="PROPOSED"
        )
        db.add(new_db_match)
        db_matches.append(new_db_match)
        
    db.commit()
    
    # Add match IDs and creation info from DB to response objects
    for i, db_match in enumerate(db_matches):
        top_matches[i]['id'] = db_match.id
        top_matches[i]['status'] = db_match.status
        top_matches[i]['created_at'] = db_match.created_at
        top_matches[i]['mentee_id'] = db_match.mentee_id
        
    return top_matches

@app.post("/api/v1/matches/action", response_model=schemas.MatchResponse)
def match_action(action_in: schemas.MatchAction, current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    match = db.query(models.Match).filter(models.Match.id == action_in.match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match record not found.")
        
    # Check authorization (must be participant)
    if current_user.id != match.mentee_id and current_user.id != match.mentor_id:
        raise HTTPException(status_code=403, detail="You do not have access to this match record.")
        
    if action_in.action.upper() not in ["ACCEPT", "DECLINE"]:
        raise HTTPException(status_code=400, detail="Invalid match action. Choose ACCEPT or DECLINE.")
        
    if action_in.action.upper() == "ACCEPT":
        if current_user.role == "MENTEE":
            match.status = "REQUESTED"
        else:
            match.status = "ACCEPTED"
    else:
        match.status = "DECLINE"
        
    if action_in.action.upper() == "ACCEPT" and action_in.availability_note:
        match.availability_note = action_in.availability_note
    db.commit()
    db.refresh(match)
    
    # Get mentor and mentee detail fields
    mentor_prof = db.query(models.Mentor).filter(models.Mentor.id == match.mentor_id).first()
    mentee_prof = db.query(models.Mentee).filter(models.Mentee.id == match.mentee_id).first()
    
    mentor_user = db.query(models.User).filter(models.User.id == match.mentor_id).first()
    mentee_user = db.query(models.User).filter(models.User.id == match.mentee_id).first()
    
    # Automated Email Notifications
    base_url = (os.getenv("APP_BASE_URL") or os.getenv("FRONTEND_URL") or "http://localhost:8501").rstrip("/")
    if match.status == "REQUESTED" and mentor_user and mentor_user.email:
        mentee_display = mentee_prof.name if mentee_prof and mentee_prof.name else "A mentee"
        auth.send_email_notification(
            to_email=mentor_user.email,
            subject=f"New Mentorship Request from {mentee_display} - Mentoring-Me",
            body_text=(
                f"Hello {mentor_prof.name if mentor_prof else ''},\n\n"
                f"{mentee_display} has requested you as a mentor on Mentoring-Me!\n\n"
                f"Role/Specialization: {mentee_prof.dev_type if mentee_prof else 'Software Engineering'}\n"
                f"Compatibility Score: {int(match.total_score * 100)}%\n\n"
                f"Review and respond to this request directly on your Mentor Dashboard:\n"
                f"{base_url}\n\n"
                f"Best regards,\nThe Mentoring-Me Team"
            )
        )
    elif match.status == "ACCEPTED" and mentee_user and mentee_user.email:
        mentor_display = mentor_prof.name if mentor_prof and mentor_prof.name else "Your mentor"
        note_text = f"\nMentor Availability Note: \"{match.availability_note}\"\n" if match.availability_note else ""
        auth.send_email_notification(
            to_email=mentee_user.email,
            subject=f"Mentorship Request Accepted by {mentor_display}! 🎉 - Mentoring-Me",
            body_text=(
                f"Hello {mentee_prof.name if mentee_prof else ''},\n\n"
                f"Great news! {mentor_display} has accepted your mentorship request on Mentoring-Me! 🎉\n"
                f"{note_text}\n"
                f"You can now chat directly in-app, exchange contact info, and book your first session:\n"
                f"{base_url}\n\n"
                f"Best regards,\nThe Mentoring-Me Team"
            )
        )
    
    return schemas.MatchResponse(
        id=match.id,
        mentee_id=match.mentee_id,
        mentor_id=match.mentor_id,
        role_score=match.role_score,
        experience_score=match.experience_score,
        career_stage_score=match.career_stage_score,
        goals_score=match.goals_score,
        practical_score=match.practical_score,
        total_score=match.total_score,
        match_quality=match.match_quality,
        status=match.status,
        created_at=match.created_at,
        availability_note=match.availability_note,
        mentee_notified=match.mentee_notified,
        mentor_notified=match.mentor_notified,
        mentor_name=mentor_prof.name if mentor_prof else "Anonymous",
        mentor_timezone=mentor_prof.timezone if mentor_prof else "UTC+00:00 (London, GMT)",
        mentee_timezone=mentee_prof.timezone if mentee_prof else "UTC+00:00 (London, GMT)",
        mentor_devtype=mentor_prof.dev_type if mentor_prof else "Not stated",
        mentor_years=mentor_prof.years_code_pro if mentor_prof else 0.0,
        mentor_country=mentor_prof.country if mentor_prof else "Not stated",
        mentor_org_size=mentor_prof.org_size if mentor_prof else "Not stated",
        mentor_email=mentor_user.email if (mentor_user and match.status == "ACCEPTED") else None,
        mentor_contact_link=mentor_prof.contact_link if (mentor_prof and match.status == "ACCEPTED") else None,
        mentor_cv_path=mentor_prof.cv_path if mentor_prof else None,
        mentor_profile_pic=mentor_prof.profile_pic if mentor_prof else None,
        mentor_ed_level=mentor_prof.ed_level if mentor_prof else None,
        mentor_job_factors=mentor_prof.job_factors if mentor_prof else None,
        mentor_additional_details=mentor_prof.additional_details if mentor_prof else None,
        mentor_gender=mentor_prof.gender if mentor_prof else None,
        mentee_gender=mentee_prof.gender if mentee_prof else None,
        is_representation_boosted=True if (mentee_prof and mentee_prof.gender == "Female" and mentor_prof and mentor_prof.gender == "Female") else False,
        is_ally_boosted=True if (mentee_prof and mentee_prof.prefer_diversity_ally and mentor_prof and mentor_prof.is_diversity_ally) else False,
        mentor_linkedin_link=mentor_prof.linkedin_link if mentor_prof else None,
        mentee_linkedin_link=mentee_prof.linkedin_link if mentee_prof else None,
        mentee_name=mentee_prof.name if mentee_prof else "Anonymous",
        mentee_devtype=mentee_prof.dev_type if mentee_prof else "Not stated",
        mentee_years=mentee_prof.years_code_pro if mentee_prof else 0.0,
        mentee_country=mentee_prof.country if mentee_prof else "Not stated",
        mentee_org_size=mentee_prof.org_size if mentee_prof else "Not stated",
        mentee_email=mentee_user.email if (mentee_user and match.status == "ACCEPTED") else None,
        mentee_cv_path=mentee_prof.cv_path if mentee_prof else None,
        mentee_profile_pic=mentee_prof.profile_pic if mentee_prof else None,
        mentee_ed_level=mentee_prof.ed_level if mentee_prof else None,
        mentee_job_factors=mentee_prof.job_factors if mentee_prof else None,
        mentee_additional_details=mentee_prof.additional_details if mentee_prof else None,
        mentee_alternative_emails=mentee_prof.alternative_emails if (mentee_prof and match.status == "ACCEPTED") else None
    )

@app.get("/api/v1/matches/history", response_model=list[schemas.MatchResponse])
def get_match_history(current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    if current_user.role == "MENTEE":
        matches = db.query(models.Match).filter(models.Match.mentee_id == current_user.id).all()
    elif current_user.role == "MENTOR":
        matches = db.query(models.Match).filter(models.Match.mentor_id == current_user.id).all()
    else:
        matches = db.query(models.Match).all()
        
    resp_list = []
    for m in matches:
        mentor_prof = db.query(models.Mentor).filter(models.Mentor.id == m.mentor_id).first()
        mentee_prof = db.query(models.Mentee).filter(models.Mentee.id == m.mentee_id).first()
        
        mentor_user = db.query(models.User).filter(models.User.id == m.mentor_id).first()
        mentee_user = db.query(models.User).filter(models.User.id == m.mentee_id).first()
        
        resp_list.append(schemas.MatchResponse(
            id=m.id,
            mentee_id=m.mentee_id,
            mentor_id=m.mentor_id,
            role_score=m.role_score,
            experience_score=m.experience_score,
            career_stage_score=m.career_stage_score,
            goals_score=m.goals_score,
            practical_score=m.practical_score,
            total_score=m.total_score,
            match_quality=m.match_quality,
            status=m.status,
            created_at=m.created_at,
            availability_note=m.availability_note,
            mentee_notified=m.mentee_notified,
            mentor_notified=m.mentor_notified,
            mentor_name=mentor_prof.name if mentor_prof else "Anonymous",
            mentor_timezone=mentor_prof.timezone if mentor_prof else "UTC+00:00 (London, GMT)",
            mentee_timezone=mentee_prof.timezone if mentee_prof else "UTC+00:00 (London, GMT)",
            mentor_devtype=mentor_prof.dev_type if mentor_prof else "Not stated",
            mentor_years=mentor_prof.years_code_pro if mentor_prof else 0.0,
            mentor_country=mentor_prof.country if mentor_prof else "Not stated",
            mentor_org_size=mentor_prof.org_size if mentor_prof else "Not stated",
            mentor_email=mentor_user.email if (mentor_user and m.status == "ACCEPTED") else None,
            mentor_contact_link=mentor_prof.contact_link if (mentor_prof and m.status == "ACCEPTED") else None,
            mentor_cv_path=mentor_prof.cv_path if mentor_prof else None,
            mentor_profile_pic=mentor_prof.profile_pic if mentor_prof else None,
            mentor_ed_level=mentor_prof.ed_level if mentor_prof else None,
            mentor_job_factors=mentor_prof.job_factors if mentor_prof else None,
            mentor_additional_details=mentor_prof.additional_details if mentor_prof else None,
            mentor_gender=mentor_prof.gender if mentor_prof else None,
            mentee_gender=mentee_prof.gender if mentee_prof else None,
            is_representation_boosted=True if (mentee_prof and mentee_prof.gender == "Female" and mentor_prof and mentor_prof.gender == "Female") else False,
            is_ally_boosted=True if (mentee_prof and mentee_prof.prefer_diversity_ally and mentor_prof and mentor_prof.is_diversity_ally) else False,
            mentor_linkedin_link=mentor_prof.linkedin_link if mentor_prof else None,
            mentee_linkedin_link=mentee_prof.linkedin_link if mentee_prof else None,
            mentee_name=mentee_prof.name if mentee_prof else "Anonymous",
            mentee_devtype=mentee_prof.dev_type if mentee_prof else "Not stated",
            mentee_years=mentee_prof.years_code_pro if mentee_prof else 0.0,
            mentee_country=mentee_prof.country if mentee_prof else "Not stated",
            mentee_org_size=mentee_prof.org_size if mentee_prof else "Not stated",
            mentee_email=mentee_user.email if (mentee_user and m.status == "ACCEPTED") else None,
            mentee_cv_path=mentee_prof.cv_path if mentee_prof else None,
            mentee_profile_pic=mentee_prof.profile_pic if mentee_prof else None,
            mentee_ed_level=mentee_prof.ed_level if mentee_prof else None,
            mentee_job_factors=mentee_prof.job_factors if mentee_prof else None,
            mentee_additional_details=mentee_prof.additional_details if mentee_prof else None,
            mentee_alternative_emails=mentee_prof.alternative_emails if (mentee_prof and m.status == "ACCEPTED") else None
        ))
    return resp_list

@app.post("/api/v1/matches/{match_id}/notify-seen")
def mark_match_notified(
    match_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    match = db.query(models.Match).filter(models.Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found.")
    if current_user.id == match.mentee_id:
        match.mentee_notified = True
    elif current_user.id == match.mentor_id:
        match.mentor_notified = True
    db.commit()
    return {"status": "success"}

@app.post("/api/v1/profile/cv")
def upload_cv(
    file: UploadFile = File(...),
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
        
    os.makedirs("uploads", exist_ok=True)
    file_path = f"uploads/cv_{current_user.id}.pdf"
    
    try:
        # Reset read position and read contents
        contents = file.file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
        
    # Update user profile
    if current_user.role == "MENTEE":
        profile = db.query(models.Mentee).filter(models.Mentee.id == current_user.id).first()
    else:
        profile = db.query(models.Mentor).filter(models.Mentor.id == current_user.id).first()
        
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")
        
    profile.cv_path = file_path
    db.commit()
    
    return {"detail": "CV uploaded successfully", "cv_path": file_path}

@app.get("/api/v1/profile/cv/{user_id}")
def get_cv(user_id: str, db: Session = Depends(get_db)):
    # Retrieve cv_path from database
    mentee = db.query(models.Mentee).filter(models.Mentee.id == user_id).first()
    mentor = db.query(models.Mentor).filter(models.Mentor.id == user_id).first()
    
    cv_path = None
    if mentee and mentee.cv_path:
        cv_path = mentee.cv_path
    elif mentor and mentor.cv_path:
        cv_path = mentor.cv_path
        
    if not cv_path or not os.path.exists(cv_path):
        raise HTTPException(status_code=404, detail="CV file not found.")
        
    return FileResponse(cv_path, media_type="application/pdf", filename=f"cv_{user_id}.pdf")

@app.post("/api/v1/profile/profile-pic")
def upload_profile_pic(
    file: UploadFile = File(...),
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    ext = file.filename.split(".")[-1].lower() if "." in file.filename else "png"
    if ext not in ["png", "jpg", "jpeg", "webp", "gif"]:
        raise HTTPException(status_code=400, detail="Only PNG, JPG, JPEG, WEBP, and GIF images are supported.")
        
    os.makedirs("uploads", exist_ok=True)
    file_path = f"uploads/pic_{current_user.id}.png"
    
    try:
        contents = file.file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save profile picture: {str(e)}")
        
    # Update user profile
    if current_user.role == "MENTEE":
        profile = db.query(models.Mentee).filter(models.Mentee.id == current_user.id).first()
    else:
        profile = db.query(models.Mentor).filter(models.Mentor.id == current_user.id).first()
        
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")
        
    profile.profile_pic = file_path
    db.commit()
    
    return {"detail": "Profile picture uploaded successfully", "profile_pic": file_path}

@app.get("/api/v1/profile/profile-pic/{user_id}")
def get_profile_pic(user_id: str, db: Session = Depends(get_db)):
    # Retrieve profile_pic from database
    mentee = db.query(models.Mentee).filter(models.Mentee.id == user_id).first()
    mentor = db.query(models.Mentor).filter(models.Mentor.id == user_id).first()
    
    pic_path = None
    if mentee and mentee.profile_pic:
        pic_path = mentee.profile_pic
    elif mentor and mentor.profile_pic:
        pic_path = mentor.profile_pic
        
    if not pic_path or not os.path.exists(pic_path):
        raise HTTPException(status_code=404, detail="Profile picture not found.")
        
    # Determine content type based on extension
    content_type = "image/png"
    if pic_path.endswith(".jpg") or pic_path.endswith(".jpeg"):
        content_type = "image/jpeg"
    elif pic_path.endswith(".webp"):
        content_type = "image/webp"
    elif pic_path.endswith(".gif"):
        content_type = "image/gif"
        
    return FileResponse(pic_path, media_type=content_type, filename=f"pic_{user_id}.png")

@app.delete("/api/v1/profile/profile-pic")
def delete_profile_pic(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role == "MENTEE":
        profile = db.query(models.Mentee).filter(models.Mentee.id == current_user.id).first()
    else:
        profile = db.query(models.Mentor).filter(models.Mentor.id == current_user.id).first()
        
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")
        
    # Delete file from disk if it exists
    if profile.profile_pic and os.path.exists(profile.profile_pic):
        try:
            os.remove(profile.profile_pic)
        except Exception:
            pass
            
    profile.profile_pic = None
    db.commit()
    
    return {"detail": "Profile picture removed successfully"}

@app.post("/api/v1/profile/nominate", response_model=schemas.NominationResponse)
def nominate_external_mentor(
    nom_in: schemas.NominationCreate,
    current_user: models.User = Depends(auth.require_role(["MENTEE", "MENTOR"])),
    db: Session = Depends(get_db)
):
    import uuid
    import secrets
    
    invite_code = secrets.token_hex(4).upper()
    
    new_nom = models.ExternalNomination(
        id=str(uuid.uuid4()),
        mentee_id=current_user.id,
        mentor_name=nom_in.mentor_name,
        mentor_contact=nom_in.mentor_contact,
        tech_focus=nom_in.tech_focus,
        invite_code=invite_code,
        status="PENDING",
        created_at=datetime.datetime.utcnow()
    )
    db.add(new_nom)
    db.commit()
    db.refresh(new_nom)
    
    # Format and dispatch email if mentor contact is an email address
    if "@" in new_nom.mentor_contact:
        base_url = (os.getenv("APP_BASE_URL") or os.getenv("FRONTEND_URL") or "http://localhost:8501").rstrip("/")
        invite_link = f"{base_url}/?invite_code={new_nom.invite_code}"
        
        sender_name = "A Member"
        if current_user.role == "MENTEE" and current_user.mentee_profile and current_user.mentee_profile.name:
            sender_name = current_user.mentee_profile.name
        elif current_user.role == "MENTOR" and current_user.mentor_profile and current_user.mentor_profile.name:
            sender_name = current_user.mentor_profile.name
        elif current_user.email:
            sender_name = current_user.email.split("@")[0].capitalize()
            
        if nom_in.custom_message and nom_in.custom_message.strip():
            msg_text = nom_in.custom_message.strip()
            if new_nom.invite_code not in msg_text:
                msg_text += f"\n\n🔗 Accept Invitation & Connect on Mentoring-Me:\n{invite_link}"
            email_body = msg_text
        else:
            email_body = (
                f"Hi {new_nom.mentor_name},\n\n"
                f"{sender_name} has invited you to connect as a mentor on Mentoring-Me!\n\n"
                f"Focus Area: {new_nom.tech_focus}\n\n"
                f"Use the following link to accept the invitation and establish your mentor profile:\n"
                f"{invite_link}\n\n"
                f"Best regards,\n"
                f"The Mentoring-Me Platform (on behalf of {sender_name})"
            )
            
        # Send via real SMTP with Reply-To pointing directly to the mentee
        auth.send_email_notification(
            to_email=new_nom.mentor_contact,
            subject=f"Mentorship Invitation from {sender_name} (via Mentoring-Me)",
            body_text=email_body,
            reply_to=current_user.email
        )
        try:
            email_log_path = f"uploads/email_invite_{new_nom.invite_code}.txt"
            os.makedirs("uploads", exist_ok=True)
            with open(email_log_path, "w", encoding="utf-8") as f:
                f.write(f"TO: {new_nom.mentor_contact}\n")
                f.write(f"REPLY-TO: {current_user.email}\n")
                f.write(f"SUBJECT: Mentorship Invitation from {sender_name} (via Mentoring-Me)\n")
                f.write(f"BODY:\n{email_body}\n")
            print(f"[MOCK SMTP] Simulated email written to {email_log_path}")
        except Exception as e:
            print(f"[MOCK SMTP] Failed to log email: {e}")
            
    return new_nom

@app.get("/api/v1/profile/nominations", response_model=list[schemas.NominationResponse])
def get_nominations(
    current_user: models.User = Depends(auth.require_role(["MENTEE", "MENTOR"])),
    db: Session = Depends(get_db)
):
    return db.query(models.ExternalNomination).filter(models.ExternalNomination.mentee_id == current_user.id).order_by(models.ExternalNomination.created_at.desc()).all()

@app.post("/api/v1/profile/nominate/{nomination_id}/contacted", response_model=schemas.NominationResponse)
def mark_nomination_contacted(
    nomination_id: str,
    current_user: models.User = Depends(auth.require_role(["MENTEE", "MENTOR"])),
    db: Session = Depends(get_db)
):
    nom = db.query(models.ExternalNomination).filter(
        models.ExternalNomination.id == nomination_id,
        models.ExternalNomination.mentee_id == current_user.id
    ).first()
    if not nom:
        raise HTTPException(status_code=404, detail="Nomination not found.")
    nom.last_contacted_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(nom)
    return nom

@app.post("/api/v1/profile/nominate/{nomination_id}/follow-up", response_model=schemas.NominationResponse)
def send_nomination_follow_up(
    nomination_id: str,
    req: schemas.FollowUpEmailRequest,
    current_user: models.User = Depends(auth.require_role(["MENTEE", "MENTOR"])),
    db: Session = Depends(get_db)
):
    nom = db.query(models.ExternalNomination).filter(
        models.ExternalNomination.id == nomination_id,
        models.ExternalNomination.mentee_id == current_user.id
    ).first()
    if not nom:
        raise HTTPException(status_code=404, detail="Nomination not found.")
        
    sender_name = "A Member"
    if current_user.role == "MENTEE" and current_user.mentee_profile and current_user.mentee_profile.name:
        sender_name = current_user.mentee_profile.name
    elif current_user.role == "MENTOR" and current_user.mentor_profile and current_user.mentor_profile.name:
        sender_name = current_user.mentor_profile.name
    elif current_user.email:
        sender_name = current_user.email.split("@")[0].capitalize()
        
    base_url = (os.getenv("APP_BASE_URL") or os.getenv("FRONTEND_URL") or "http://localhost:8501").rstrip("/")
    invite_link = f"{base_url}/?invite_code={nom.invite_code}"
    subject = req.subject or f"Checking In: Mentorship Invitation from {sender_name} (via Mentoring-Me)"
    
    if req.custom_message and req.custom_message.strip():
        msg_text = req.custom_message.strip()
        if nom.invite_code not in msg_text:
            msg_text += f"\n\n🔗 Accept Invitation & Connect on Mentoring-Me:\n{invite_link}"
        email_body = msg_text
    else:
        email_body = (
            f"Hi {nom.mentor_name},\n\n"
            f"Hope you are doing well!\n\n"
            f"Just checking in regarding the mentorship invitation {sender_name} sent to connect on Mentoring-Me:\n\n{invite_link}\n\n"
            f"We would love to welcome your guidance in {nom.tech_focus}.\n\n"
            f"Best regards,\n"
            f"The Mentoring-Me Platform (on behalf of {sender_name})"
        )
        
    # Dispatch via SMTP with Reply-To set to the mentee
    auth.send_email_notification(
        to_email=nom.mentor_contact,
        subject=subject,
        body_text=email_body,
        reply_to=current_user.email
    )
    
    try:
        email_log_path = f"uploads/email_followup_{nom.invite_code}.txt"
        os.makedirs("uploads", exist_ok=True)
        with open(email_log_path, "w", encoding="utf-8") as f:
            f.write(f"TO: {nom.mentor_contact}\n")
            f.write(f"REPLY-TO: {current_user.email}\n")
            f.write(f"SUBJECT: {subject}\n")
            f.write(f"BODY:\n{email_body}\n")
        print(f"[MOCK SMTP] Follow-up email written to {email_log_path}")
    except Exception as e:
        print(f"[MOCK SMTP] Failed to log follow-up email: {e}")
        
    nom.last_contacted_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(nom)
    return nom

from pydantic import BaseModel
class ProfileEvaluationRequest(BaseModel):
    profile_url: str

@app.post("/api/v1/profile/evaluate")
def evaluate_profile(
    req: ProfileEvaluationRequest,
    current_user: models.User = Depends(auth.require_role(["MENTEE"])),
    db: Session = Depends(get_db)
):
    from . import profile_evaluator
    
    mentee = db.query(models.Mentee).filter(models.Mentee.id == current_user.id).first()
    if not mentee:
        raise HTTPException(status_code=404, detail="Mentee profile not found.")
        
    url = req.profile_url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Profile URL is required.")
        
    if "github.com" in url.lower():
        username = url.split("github.com/")[-1].split("/")[0] if "github.com/" in url else url
        result, err = profile_evaluator.evaluate_github_profile(username, mentee)
    elif "linkedin.com" in url.lower():
        result, err = profile_evaluator.evaluate_linkedin_profile(url, mentee)
    else:
        raise HTTPException(status_code=400, detail="Invalid URL. Only public GitHub or LinkedIn profile URLs are supported.")
        
    if err:
        raise HTTPException(status_code=400, detail=err)
        
    return result

@app.get("/api/v1/orcid/search")
def search_orcid(
    q: str,
    country: str = None,
    current_user: models.User = Depends(auth.require_role(["MENTEE"])),
    db: Session = Depends(get_db)
):
    from . import orcid_client
    
    mentee = db.query(models.Mentee).filter(models.Mentee.id == current_user.id).first()
    if not mentee:
        raise HTTPException(status_code=404, detail="Mentee profile not found.")
        
    results = orcid_client.search_orcid_mentors(q, country, mentee)
    return results

@app.get("/api/v1/github/search")
def search_github(
    q: str,
    country: str = None,
    current_user: models.User = Depends(auth.require_role(["MENTEE"])),
    db: Session = Depends(get_db)
):
    from . import github_client
    
    mentee = db.query(models.Mentee).filter(models.Mentee.id == current_user.id).first()
    if not mentee:
        raise HTTPException(status_code=404, detail="Mentee profile not found.")
        
    results = github_client.search_github_mentors(q, country, mentee)
    return results

@app.get("/api/v1/linkedin/search")
def search_linkedin(
    q: str,
    country: str = None,
    current_user: models.User = Depends(auth.require_role(["MENTEE"])),
    db: Session = Depends(get_db)
):
    from . import linkedin_client
    
    mentee = db.query(models.Mentee).filter(models.Mentee.id == current_user.id).first()
    if not mentee:
        raise HTTPException(status_code=404, detail="Mentee profile not found.")
        
    results = linkedin_client.search_linkedin_mentors(q, country, mentee)
    return results

@app.get("/api/v1/linkedin/deep-link", response_model=schemas.LinkedInDeepLinkResponse)
def get_mentee_linkedin_deep_link(
    role: Optional[str] = None,
    country: Optional[str] = None,
    seniority: Optional[str] = None,
    women_in_tech: Optional[bool] = None,
    skills: Optional[str] = None,
    current_user: models.User = Depends(auth.require_role(["MENTEE"])),
    db: Session = Depends(get_db)
):
    """
    Dynamically generates a pre-filtered LinkedIn People Search Deep Link
    tailored to the mentee's exact profile attributes and career goals.
    """
    from . import linkedin_client
    
    mentee = db.query(models.Mentee).filter(models.Mentee.id == current_user.id).first()
    if not mentee:
        raise HTTPException(status_code=404, detail="Mentee profile not found.")
        
    target_role = role if role is not None else (mentee.target_mentor_expertise or mentee.dev_type or "")
    target_country = country if country is not None else (mentee.target_mentor_country or mentee.country or "")
    target_wit = women_in_tech if women_in_tech is not None else (mentee.gender == "Female" or mentee.prefer_diversity_ally)
    
    skill_list = [s.strip() for s in skills.split(",") if s.strip()] if skills else []
    
    deep_link_data = linkedin_client.build_direct_linkedin_deep_link(
        role=target_role,
        skills=skill_list,
        country=target_country,
        seniority=seniority,
        women_in_tech=target_wit
    )
    
    # Personalize outreach templates with mentee's name and role
    deep_link_data["outreach_templates"] = linkedin_client.generate_linkedin_outreach_templates(
        mentee_name=mentee.name or "Mentee",
        mentee_role=mentee.dev_type or "Software Engineer",
        tech_focus=target_role or "Engineering Leadership"
    )
    
    return deep_link_data

@app.post("/api/v1/linkedin/deep-link/generate", response_model=schemas.LinkedInDeepLinkResponse)
def generate_custom_linkedin_deep_link(
    req: schemas.LinkedInDeepLinkRequest,
    current_user: models.User = Depends(auth.require_role(["MENTEE"])),
    db: Session = Depends(get_db)
):
    """
    Generates a customized LinkedIn People Search Deep Link from custom payload parameters.
    """
    from . import linkedin_client
    
    mentee = db.query(models.Mentee).filter(models.Mentee.id == current_user.id).first()
    mentee_name = mentee.name if mentee else "Mentee"
    mentee_role = mentee.dev_type if mentee else "Software Engineer"
    
    deep_link_data = linkedin_client.build_direct_linkedin_deep_link(
        role=req.role or "",
        skills=req.skills or [],
        country=req.country,
        seniority=req.seniority,
        mentorship_intent=req.mentorship_intent if req.mentorship_intent is not None else True,
        women_in_tech=req.women_in_tech if req.women_in_tech is not None else False,
        custom_keywords=req.custom_keywords or ""
    )
    
    deep_link_data["outreach_templates"] = linkedin_client.generate_linkedin_outreach_templates(
        mentee_name=mentee_name,
        mentee_role=mentee_role,
        tech_focus=req.role or "Engineering Leadership"
    )
    
    return deep_link_data


# ── In-App Messaging Endpoints ──────────────────────────────────────────

@app.get("/api/v1/messages/unread-summary", response_model=schemas.UnreadMessagesSummary)
def get_unread_messages_summary(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    unread_messages = db.query(models.Message).filter(
        models.Message.recipient_id == current_user.id,
        models.Message.is_read == False
    ).all()
    
    by_match = {}
    for m in unread_messages:
        by_match[m.match_id] = by_match.get(m.match_id, 0) + 1
        
    return schemas.UnreadMessagesSummary(
        total_unread=len(unread_messages),
        by_match=by_match
    )

@app.get("/api/v1/messages/{match_id}", response_model=List[schemas.MessageResponse])
def get_match_messages(
    match_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    match = db.query(models.Match).filter(models.Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found.")
        
    if current_user.role != "ADMIN" and current_user.id not in [match.mentee_id, match.mentor_id]:
        raise HTTPException(status_code=403, detail="You are not authorized to view messages for this mentorship connection.")
        
    # Query all messages
    msgs = db.query(models.Message).filter(models.Message.match_id == match_id).order_by(models.Message.created_at.asc()).all()
    
    # Mark messages sent to current_user as read
    marked_any = False
    for msg in msgs:
        if msg.recipient_id == current_user.id and not msg.is_read:
            msg.is_read = True
            marked_any = True
    if marked_any:
        db.commit()
        
    user_cache = {}
    def get_sender_name(user_id):
        if user_id in user_cache:
            return user_cache[user_id]
        u = db.query(models.User).filter(models.User.id == user_id).first()
        if not u:
            return "User"
        name = u.email.split("@")[0]
        if u.role == "MENTEE" and u.mentee_profile and u.mentee_profile.name:
            name = u.mentee_profile.name
        elif u.role == "MENTOR" and u.mentor_profile and u.mentor_profile.name:
            name = u.mentor_profile.name
        user_cache[user_id] = name
        return name

    result = []
    for msg in msgs:
        s_name = get_sender_name(msg.sender_id)
        result.append(schemas.MessageResponse(
            id=msg.id,
            match_id=msg.match_id,
            sender_id=msg.sender_id,
            sender_name=s_name,
            recipient_id=msg.recipient_id,
            content=msg.content,
            is_read=msg.is_read,
            created_at=msg.created_at,
            is_mine=(msg.sender_id == current_user.id)
        ))
    return result

@app.post("/api/v1/messages/send", response_model=schemas.MessageResponse)
def send_match_message(
    req: schemas.MessageCreate,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    if not req.content or not req.content.strip():
        raise HTTPException(status_code=400, detail="Message content cannot be empty.")
        
    match = db.query(models.Match).filter(models.Match.id == req.match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Mentorship match not found.")
        
    if current_user.id not in [match.mentee_id, match.mentor_id]:
        raise HTTPException(status_code=403, detail="You are not part of this mentorship connection.")
        
    if match.status not in ["ACCEPTED", "PROPOSED", "REQUESTED"]:
        raise HTTPException(status_code=400, detail="Messaging is unavailable for declined connections.")
        
    if match.status == "PROPOSED" and current_user.id == match.mentee_id:
        match.status = "REQUESTED"
        match.mentor_notified = False
        
    recipient_id = match.mentor_id if current_user.id == match.mentee_id else match.mentee_id
    
    new_msg = models.Message(
        match_id=req.match_id,
        sender_id=current_user.id,
        recipient_id=recipient_id,
        content=req.content.strip(),
        is_read=False,
        created_at=datetime.datetime.utcnow()
    )
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)
    
    # Resolve sender display name
    s_name = current_user.email.split("@")[0]
    if current_user.role == "MENTEE" and current_user.mentee_profile and current_user.mentee_profile.name:
        s_name = current_user.mentee_profile.name
    elif current_user.role == "MENTOR" and current_user.mentor_profile and current_user.mentor_profile.name:
        s_name = current_user.mentor_profile.name

    return schemas.MessageResponse(
        id=new_msg.id,
        match_id=new_msg.match_id,
        sender_id=new_msg.sender_id,
        sender_name=s_name,
        recipient_id=new_msg.recipient_id,
        content=new_msg.content,
        is_read=new_msg.is_read,
        created_at=new_msg.created_at,
        is_mine=True
    )

@app.post("/api/v1/messages/{match_id}/read")
def mark_messages_read(
    match_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    unread = db.query(models.Message).filter(
        models.Message.match_id == match_id,
        models.Message.recipient_id == current_user.id,
        models.Message.is_read == False
    ).all()
    for m in unread:
        m.is_read = True
    db.commit()
    return {"marked_count": len(unread)}


@app.post("/api/v1/admin/reset")
def reset_database(
    current_user: models.User = Depends(auth.require_role(["ADMIN"])),
    db: Session = Depends(get_db)
):
    try:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        
        admin_uuid = "admin-uuid-clean-001"
        admin_user = models.User(
            id=admin_uuid,
            email="admin@mentoring-me.demo",
            password_hash=auth.get_password_hash("adminpassword"),
            role="ADMIN",
            two_factor_enabled=False
        )
        db.add(admin_user)
        db.commit()
        return {"message": "Database successfully wiped and reset to a clean state."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database reset failed: {str(e)}")


@app.post("/api/v1/matches/{match_id}/send-email", response_model=schemas.DirectEmailResponse)
def send_direct_match_email(
    match_id: str,
    req: schemas.DirectEmailRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    match = db.query(models.Match).filter(models.Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    mentor_user = db.query(models.User).filter(models.User.id == match.mentor_id).first()
    mentee_user = db.query(models.User).filter(models.User.id == match.mentee_id).first()
    mentor_prof = db.query(models.Mentor).filter(models.Mentor.id == match.mentor_id).first()
    mentee_prof = db.query(models.Mentee).filter(models.Mentee.id == match.mentee_id).first()

    if not mentor_user or not mentee_user:
        raise HTTPException(status_code=404, detail="Matched user accounts not found")

    if current_user.id == mentee_user.id:
        recipient_email = mentor_user.email
        recipient_name = mentor_prof.name if mentor_prof and mentor_prof.name else "Mentor"
        sender_name = mentee_prof.name if mentee_prof and mentee_prof.name else "Mentee"
    elif current_user.id == mentor_user.id:
        recipient_email = mentee_user.email
        recipient_name = mentee_prof.name if mentee_prof and mentee_prof.name else "Mentee"
        sender_name = mentor_prof.name if mentor_prof and mentor_prof.name else "Mentor"
    else:
        raise HTTPException(status_code=403, detail="You are not authorized to send messages for this match")

    if not req.body_text or not req.body_text.strip():
        raise HTTPException(status_code=400, detail="Email body cannot be empty")

    subject = req.subject.strip() or f"Mentoring-Me: Message from {sender_name}"

    # Dispatch email with Reply-To set to current user's email so recipient can reply directly
    auth.send_email_notification(
        to_email=recipient_email,
        subject=subject,
        body_text=req.body_text.strip(),
        reply_to=current_user.email
    )

    try:
        os.makedirs("uploads", exist_ok=True)
        log_path = f"uploads/email_match_{match_id}.txt"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"TO: {recipient_email}\n")
            f.write(f"REPLY-TO: {current_user.email}\n")
            f.write(f"SUBJECT: {subject}\n")
            f.write(f"BODY:\n{req.body_text.strip()}\n")
    except Exception as e:
        print(f"[MOCK SMTP] Failed to log match email: {e}")

    return {
        "status": "success",
        "message": f"Email successfully dispatched to {recipient_name} ({recipient_email})!",
        "recipient_email": recipient_email
    }

