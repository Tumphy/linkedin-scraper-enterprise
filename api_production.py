#!/usr/bin/env python3
"""
LinkedIn Scraper Production API

Enterprise-grade FastAPI server with:
- JWT authentication and RBAC
- Rate limiting and security
- Job queue integration
- Health monitoring
- Prometheus metrics
"""

import os
import logging
import asyncio
from datetime import datetime
from typing import List, Dict, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Request, status, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Import our production modules
from security import (
    auth_manager, get_current_user, User, UserRole, SecurityConfig,
    setup_security_middleware, limiter, rate_limit_manager,
    InputSanitizer, log_security_event
)
from job_queue import job_queue, JobPriority, JobStatus
from monitoring import (
    metrics_collector, health_monitor, alert_manager,
    setup_monitoring_endpoints
)
from database_service import ProfileDatabaseService, get_profile_statistics
from config import get_config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Pydantic models for API requests/responses
class LoginRequest(BaseModel):
    email: str = Field(..., description="User email address")
    password: str = Field(..., description="User password")

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400  # 24 hours
    user_role: str

class ScrapeProfilesRequest(BaseModel):
    urls: List[str] = Field(..., description="List of LinkedIn profile URLs to scrape")
    priority: str = Field(default="normal", description="Job priority: low, normal, high, urgent")
    
class JobResponse(BaseModel):
    job_id: str
    status: str
    message: str

class ProfileResponse(BaseModel):
    profiles: List[Dict[str, Any]]
    total_count: int
    page: int
    limit: int

class HealthResponse(BaseModel):
    overall_status: str
    timestamp: str
    checks: Dict[str, Any]

# Application lifespan management
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown"""
    # Startup
    logger.info("🚀 Starting LinkedIn Scraper Production API")
    
    # Initialize monitoring
    monitoring_thread = setup_monitoring_endpoints()
    
    # Log startup event
    log_security_event("api_startup", details={"version": "2.0.0"})
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down LinkedIn Scraper Production API")
    log_security_event("api_shutdown")

# Initialize FastAPI app
app = FastAPI(
    title="LinkedIn Scraper Enterprise API",
    description="Enterprise-grade LinkedIn profile scraper with authentication, rate limiting, and monitoring",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Setup security middleware
setup_security_middleware(app)

# Add rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security bearer
security = HTTPBearer()

# Database service
db_service = ProfileDatabaseService()

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for production"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    # Log security event for errors
    log_security_event("api_error", details={
        "error": str(exc),
        "endpoint": request.url.path,
        "method": request.method
    })
    
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error_id": datetime.utcnow().isoformat()}
    )

# Authentication endpoints
@app.post("/auth/login", response_model=LoginResponse, tags=["Authentication"])
@limiter.limit("5/minute")
async def login(request: Request, login_data: LoginRequest):
    """Login and get JWT access token"""
    try:
        # In production, validate against database
        # For demo, using hardcoded admin user
        if login_data.email == "admin@yourcompany.com" and login_data.password == "secure_password123":
            user = User("admin123", login_data.email, UserRole.ADMIN)
            token = auth_manager.generate_jwt_token(user)
            
            # Store session
            auth_manager.store_user_session(user, token)
            
            # Log successful login
            log_security_event("login_success", user_id=user.user_id, details={"email": login_data.email})
            
            return LoginResponse(
                access_token=token,
                user_role=user.role
            )
        else:
            # Log failed login attempt
            log_security_event("login_failed", details={"email": login_data.email})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
            
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login service unavailable"
        )

@app.post("/auth/logout", tags=["Authentication"])
@limiter.limit("10/minute")
async def logout(request: Request, current_user: User = Depends(get_current_user)):
    """Logout and invalidate session"""
    try:
        # Invalidate session
        auth_manager.invalidate_session(current_user.user_id)
        
        # Log logout
        log_security_event("logout", user_id=current_user.user_id)
        
        return {"message": "Successfully logged out"}
        
    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Logout service unavailable"
        )

# Job management endpoints
@app.post("/scrape/linkedin_profiles", response_model=JobResponse, tags=["Scraping"])
@limiter.limit("10/minute")
async def scrape_linkedin_profiles(
    request: Request,
    scrape_request: ScrapeProfilesRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """Start LinkedIn profile scraping job"""
    try:
        # Validate URLs
        validated_urls = []
        for url in scrape_request.urls:
            try:
                clean_url = InputSanitizer.sanitize_linkedin_url(url)
                validated_urls.append(clean_url)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid LinkedIn URL: {url} - {e}"
                )
        
        # Check rate limits
        if not rate_limit_manager.check_api_quota(current_user.user_id, "scraping"):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="API quota exceeded for scraping operations"
            )
        
        # Map priority
        priority_map = {
            "low": JobPriority.LOW,
            "normal": JobPriority.NORMAL,
            "high": JobPriority.HIGH,
            "urgent": JobPriority.URGENT
        }
        priority = priority_map.get(scrape_request.priority.lower(), JobPriority.NORMAL)
        
        # Create scraping job
        job_id = job_queue.create_job(
            job_type="linkedin_scraping",
            parameters={
                "urls": validated_urls,
                "user_id": current_user.user_id
            },
            priority=priority,
            user_id=current_user.user_id
        )
        
        # Increment API usage
        rate_limit_manager.increment_api_usage(current_user.user_id, "scraping")
        
        # Track metrics
        metrics_collector.track_api_request(
            method="POST",
            endpoint="/scrape/linkedin_profiles",
            status_code=200,
            response_time=0.1
        )
        
        # Log job creation
        log_security_event(
            "job_created",
            user_id=current_user.user_id,
            details={"job_id": job_id, "urls_count": len(validated_urls)}
        )
        
        return JobResponse(
            job_id=job_id,
            status="pending",
            message=f"Scraping job created for {len(validated_urls)} profiles"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating scraping job: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create scraping job"
        )

@app.get("/jobs/{job_id}", tags=["Jobs"])
@limiter.limit("30/minute")
async def get_job_status(
    request: Request,
    job_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get job status and progress"""
    try:
        job_info = job_queue.get_job_status(job_id)
        
        if not job_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found"
            )
        
        # Check if user owns this job (or is admin)
        if current_user.role != UserRole.ADMIN and job_info.user_id != current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this job"
            )
        
        return {
            "job_id": job_info.job_id,
            "status": job_info.status,
            "progress": job_info.progress,
            "progress_message": job_info.progress_message,
            "created_at": job_info.created_at,
            "started_at": job_info.started_at,
            "completed_at": job_info.completed_at,
            "result": job_info.result,
            "error_message": job_info.error_message
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get job status"
        )

@app.get("/jobs", tags=["Jobs"])
@limiter.limit("20/minute")
async def get_user_jobs(
    request: Request,
    limit: int = 20,
    current_user: User = Depends(get_current_user)
):
    """Get user's jobs"""
    try:
        jobs = job_queue.get_user_jobs(current_user.user_id, limit=limit)
        return {"jobs": jobs, "total": len(jobs)}
        
    except Exception as e:
        logger.error(f"Error getting user jobs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get user jobs"
        )

@app.delete("/jobs/{job_id}", tags=["Jobs"])
@limiter.limit("10/minute")
async def cancel_job(
    request: Request,
    job_id: str,
    current_user: User = Depends(get_current_user)
):
    """Cancel a job"""
    try:
        success = job_queue.cancel_job(job_id, current_user.user_id)
        
        if success:
            log_security_event("job_cancelled", user_id=current_user.user_id, details={"job_id": job_id})
            return {"message": "Job cancelled successfully"}
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found or cannot be cancelled"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling job: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel job"
        )

# Data access endpoints
@app.get("/profiles", response_model=ProfileResponse, tags=["Data"])
@limiter.limit("30/minute")
async def get_profiles(
    request: Request,
    limit: int = 50,
    page: int = 1,
    company: Optional[str] = None,
    location: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """Get scraped profiles with filtering"""
    try:
        profiles = db_service.get_profiles(
            limit=min(limit, 1000),  # Cap at 1000
            offset=(page - 1) * limit,
            filters={
                "company": company,
                "location": location
            }
        )
        
        total_count = db_service.get_profile_count(filters={
            "company": company,
            "location": location
        })
        
        return ProfileResponse(
            profiles=profiles,
            total_count=total_count,
            page=page,
            limit=limit
        )
        
    except Exception as e:
        logger.error(f"Error getting profiles: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get profiles"
        )

@app.get("/stats", tags=["Data"])
@limiter.limit("20/minute")
async def get_statistics(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Get scraping statistics"""
    try:
        stats = get_profile_statistics()
        return stats
        
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get statistics"
        )

# Health and monitoring endpoints
@app.get("/health", response_model=HealthResponse, tags=["Monitoring"])
async def health_check(request: Request):
    """System health check"""
    try:
        health_status = health_monitor.get_overall_health()
        return HealthResponse(
            overall_status=health_status["overall_status"],
            timestamp=datetime.utcnow().isoformat(),
            checks=health_status["checks"]
        )
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return HealthResponse(
            overall_status="unhealthy",
            timestamp=datetime.utcnow().isoformat(),
            checks={"error": str(e)}
        )

@app.get("/metrics", tags=["Monitoring"])
async def get_metrics(request: Request):
    """Get Prometheus metrics"""
    return metrics_collector.get_metrics_text()

@app.get("/alerts", tags=["Monitoring"])
@limiter.limit("10/minute")
async def get_alerts(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Get active alerts"""
    try:
        alerts = alert_manager.get_active_alerts()
        return {"alerts": alerts, "count": len(alerts)}
        
    except Exception as e:
        logger.error(f"Error getting alerts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get alerts"
        )

# Admin endpoints
@app.get("/admin/users", tags=["Admin"])
@limiter.limit("10/minute")
async def get_users(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Get all users (Admin only)"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    # Implementation would get users from database
    return {"users": [], "message": "User management endpoint"}

@app.get("/admin/system_health", tags=["Admin"])
@limiter.limit("10/minute")
async def get_detailed_system_health(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """Get detailed system health (Admin only)"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    try:
        detailed_health = health_monitor.get_detailed_health()
        return detailed_health
        
    except Exception as e:
        logger.error(f"Error getting detailed health: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get detailed system health"
        )

if __name__ == "__main__":
    import uvicorn
    
    config = get_config()
    
    logger.info("🚀 Starting LinkedIn Scraper Production API Server")
    logger.info(f"📊 Environment: {config.environment}")
    logger.info(f"🔐 Security: JWT + RBAC enabled")
    logger.info(f"📈 Monitoring: Prometheus metrics enabled")
    logger.info(f"⚡ Queue: Redis + Celery enabled")
    
    uvicorn.run(
        "api_production:app",
        host=config.api_host,
        port=config.api_port,
        workers=1,  # Use 1 worker for development, increase for production
        reload=config.environment == "development",
        log_level="info"
    )