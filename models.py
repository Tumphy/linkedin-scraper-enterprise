#!/usr/bin/env python3
"""
Data Models and Database Schema
Defines the database structure and data models for the LinkedIn scraper
"""

import os
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, Float, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel, Field

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///linkedin_profiles.db")

# SQLAlchemy setup
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database Models
class LinkedInProfile(Base):
    """LinkedIn profile database model"""
    __tablename__ = "linkedin_profiles"
    
    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(String(255), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    
    # Profile Information
    full_name = Column(String(255), index=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    headline = Column(String(500))
    summary = Column(Text)
    
    # Current Position
    current_role = Column(String(255))
    current_company = Column(String(255), index=True)
    
    # Location
    location = Column(String(255), index=True)
    country = Column(String(100))
    city = Column(String(100))
    
    # Contact Information
    email = Column(String(255), index=True)
    phone = Column(String(50))
    linkedin_url = Column(String(500), unique=True, index=True)
    
    # Professional Details
    industry = Column(String(255))
    years_experience = Column(Integer)
    education = Column(JSON)  # Store as JSON
    skills = Column(JSON)     # Store as JSON
    languages = Column(JSON)  # Store as JSON
    
    # Additional Information
    profile_image_url = Column(String(500))
    connections_count = Column(Integer)
    followers_count = Column(Integer)
    
    # Scraping Metadata
    scraped_at = Column(DateTime, default=datetime.utcnow)
    source_url = Column(String(500))
    scrape_job_id = Column(String(100), index=True)
    data_quality_score = Column(Float, default=0.0)
    
    # Status
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ScrapingJob(Base):
    """Scraping job tracking model"""
    __tablename__ = "scraping_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(100), unique=True, index=True)
    
    # Job Details
    job_type = Column(String(50), default="linkedin_profile")
    status = Column(String(50), default="pending")  # pending, running, completed, failed
    priority = Column(String(20), default="normal")
    
    # URLs and Parameters
    target_urls = Column(JSON)  # List of URLs to scrape
    parameters = Column(JSON)   # Job parameters
    
    # Progress Tracking
    total_urls = Column(Integer, default=0)
    completed_urls = Column(Integer, default=0)
    failed_urls = Column(Integer, default=0)
    progress_percentage = Column(Float, default=0.0)
    
    # Results
    success_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    results = Column(JSON)  # Store results as JSON
    error_details = Column(JSON)  # Store errors as JSON
    
    # User and Scheduling
    user_id = Column(String(100), index=True)
    scheduled_at = Column(DateTime)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class User(Base):
    """User account model"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    
    # User Information
    email = Column(String(255), unique=True, index=True)
    username = Column(String(100), unique=True, index=True)
    full_name = Column(String(255))
    
    # Authentication
    password_hash = Column(String(255))
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    
    # Role and Permissions
    role = Column(String(50), default="user")  # user, admin, enterprise
    permissions = Column(JSON)  # Store permissions as JSON
    
    # API Usage
    api_calls_today = Column(Integer, default=0)
    api_calls_total = Column(Integer, default=0)
    last_api_call = Column(DateTime)
    
    # Subscription/Billing
    subscription_type = Column(String(50), default="free")
    subscription_expires = Column(DateTime)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime)

# Pydantic models for API
class ProfileCreate(BaseModel):
    """Model for creating a new profile"""
    full_name: str
    linkedin_url: str
    current_role: Optional[str] = None
    current_company: Optional[str] = None
    location: Optional[str] = None
    email: Optional[str] = None

class ProfileResponse(BaseModel):
    """Model for profile API response"""
    id: int
    profile_id: str
    full_name: Optional[str]
    current_role: Optional[str]
    current_company: Optional[str]
    location: Optional[str]
    linkedin_url: str
    scraped_at: datetime
    
    class Config:
        orm_mode = True

class JobCreate(BaseModel):
    """Model for creating a new scraping job"""
    job_type: str = "linkedin_profile"
    target_urls: List[str]
    priority: str = "normal"
    parameters: Optional[Dict[str, Any]] = {}

class JobResponse(BaseModel):
    """Model for job API response"""
    id: int
    job_id: str
    status: str
    progress_percentage: float
    total_urls: int
    completed_urls: int
    failed_urls: int
    created_at: datetime
    
    class Config:
        orm_mode = True

class UserCreate(BaseModel):
    """Model for creating a new user"""
    email: str = Field(..., description="User email address")
    username: str = Field(..., description="Username")
    full_name: str = Field(..., description="Full name")
    password: str = Field(..., min_length=8, description="Password (min 8 characters)")

class UserResponse(BaseModel):
    """Model for user API response"""
    id: int
    user_id: str
    email: str
    username: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
    
    class Config:
        orm_mode = True

# Database utility functions
def create_tables():
    """Create all database tables"""
    Base.metadata.create_all(bind=engine)

def get_db():
    """Dependency to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_database():
    """Initialize database with default data"""
    create_tables()
    
    # Create default admin user if not exists
    db = SessionLocal()
    try:
        admin_user = db.query(User).filter(User.email == "admin@yourcompany.com").first()
        if not admin_user:
            from security import SecurityManager
            security_manager = SecurityManager()
            
            admin_user = User(
                email="admin@yourcompany.com",
                username="admin",
                full_name="System Administrator",
                password_hash=security_manager.hash_password("secure_password123"),
                role="admin",
                is_active=True,
                is_verified=True
            )
            db.add(admin_user)
            db.commit()
            print("✅ Default admin user created")
    finally:
        db.close()

if __name__ == "__main__":
    print("🗄️ Initializing database...")
    init_database()
    print("✅ Database initialized successfully")