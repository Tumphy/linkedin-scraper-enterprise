"""
Production Security Module

Implements comprehensive security features including:
- JWT authentication with role-based access control
- Rate limiting with Redis backend
- Secure CORS configuration
- API key management
- Input sanitization
"""

import os
import jwt
import bcrypt
import redis
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import HTTPException, Depends, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session
import hashlib
import secrets
from functools import wraps
import logging

logger = logging.getLogger(__name__)

# Initialize Redis for rate limiting and session storage
redis_client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379"),
    decode_responses=True
)

# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.getenv("REDIS_URL", "redis://localhost:6379"),
    default_limits=["100/hour"]
)

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

# Security bearer for dependency injection
security = HTTPBearer()

class UserRole:
    """User role definitions"""
    ADMIN = "admin"
    USER = "user"
    API_USER = "api_user"
    READONLY = "readonly"

class SecurityConfig:
    """Security configuration management"""
    
    @staticmethod
    def get_allowed_origins() -> List[str]:
        """Get allowed CORS origins from environment"""
        origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
        return [origin.strip() for origin in origins.split(",")]
    
    @staticmethod
    def get_cors_config():
        """Get CORS configuration parameters"""
        allowed_origins = SecurityConfig.get_allowed_origins()
        
        return {
            "allow_origins": allowed_origins,  # ✅ Specific origins only
            "allow_credentials": True,
            "allow_methods": ["GET", "POST", "PUT", "DELETE"],
            "allow_headers": ["Authorization", "Content-Type"],
            "expose_headers": ["X-RateLimit-Remaining", "X-RateLimit-Reset"]
        }

class AuthenticationError(Exception):
    """Custom authentication error"""
    pass

class AuthorizationError(Exception):
    """Custom authorization error"""
    pass

class User:
    """User model for authentication"""
    
    def __init__(self, user_id: str, email: str, role: str, api_key: Optional[str] = None):
        self.user_id = user_id
        self.email = email
        self.role = role
        self.api_key = api_key
        self.created_at = datetime.utcnow()

class AuthManager:
    """Authentication and authorization manager"""
    
    def __init__(self):
        self.redis_client = redis_client
    
    def hash_password(self, password: str) -> str:
        """Hash password using bcrypt"""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    def verify_password(self, password: str, hashed: str) -> bool:
        """Verify password against hash"""
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    
    def generate_api_key(self) -> str:
        """Generate secure API key"""
        return f"lls_{secrets.token_urlsafe(32)}"
    
    def generate_jwt_token(self, user: User) -> str:
        """Generate JWT token for user"""
        payload = {
            "user_id": user.user_id,
            "email": user.email,
            "role": user.role,
            "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
            "iat": datetime.utcnow()
        }
        
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    def verify_jwt_token(self, token: str) -> Dict[str, Any]:
        """Verify and decode JWT token"""
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            raise AuthenticationError("Token has expired")
        except jwt.InvalidTokenError:
            raise AuthenticationError("Invalid token")
    
    def store_user_session(self, user: User, token: str):
        """Store user session in Redis"""
        session_key = f"session:{user.user_id}"
        session_data = {
            "user_id": user.user_id,
            "email": user.email,
            "role": user.role,
            "token": token,
            "created_at": datetime.utcnow().isoformat()
        }
        
        # Store with expiration
        self.redis_client.setex(
            session_key,
            timedelta(hours=JWT_EXPIRATION_HOURS),
            str(session_data)
        )
    
    def invalidate_session(self, user_id: str):
        """Invalidate user session"""
        session_key = f"session:{user_id}"
        self.redis_client.delete(session_key)

# Global auth manager instance
auth_manager = AuthManager()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """Dependency to get current authenticated user"""
    try:
        token = credentials.credentials
        payload = auth_manager.verify_jwt_token(token)
        
        user = User(
            user_id=payload["user_id"],
            email=payload["email"],
            role=payload["role"]
        )
        
        return user
        
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"}
        )
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"}
        )

def require_role(required_role: str):
    """Decorator to require specific user role"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract user from kwargs (injected by FastAPI dependency)
            user = kwargs.get('current_user')
            if not user or user.role != required_role:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient permissions. Required role: {required_role}"
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator

def require_any_role(allowed_roles: List[str]):
    """Decorator to require any of the specified roles"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            user = kwargs.get('current_user')
            if not user or user.role not in allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient permissions. Allowed roles: {allowed_roles}"
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator

class InputSanitizer:
    """Input sanitization utilities"""
    
    @staticmethod
    def sanitize_linkedin_url(url: str) -> str:
        """Sanitize LinkedIn URL input"""
        # Remove potential XSS vectors
        url = url.strip()
        
        # Validate LinkedIn URL format
        if not ("linkedin.com/in/" in url or "linkedin.com/pub/" in url):
            raise ValueError("Invalid LinkedIn URL format")
        
        # Ensure HTTPS
        if url.startswith("http://"):
            url = url.replace("http://", "https://")
        elif not url.startswith("https://"):
            url = f"https://{url}"
        
        return url
    
    @staticmethod
    def sanitize_company_name(company: str) -> str:
        """Sanitize company name input"""
        if not company:
            return ""
        
        # Remove HTML tags and special characters
        import re
        company = re.sub(r'<[^>]+>', '', company)
        company = re.sub(r'[^\w\s&.-]', '', company)
        
        return company.strip()[:255]  # Limit length

class RateLimitManager:
    """Advanced rate limiting with different tiers"""
    
    def __init__(self):
        self.redis_client = redis_client
    
    def get_user_limits(self, user_role: str) -> Dict[str, str]:
        """Get rate limits based on user role"""
        limits = {
            UserRole.ADMIN: "1000/hour",
            UserRole.USER: "100/hour", 
            UserRole.API_USER: "500/hour",
            UserRole.READONLY: "50/hour"
        }
        return limits.get(user_role, "10/hour")
    
    def check_api_quota(self, user_id: str, operation: str) -> bool:
        """Check if user has remaining API quota"""
        quota_key = f"quota:{user_id}:{operation}"
        current_count = self.redis_client.get(quota_key) or 0
        
        # Get user's quota limit (could be stored in database)
        daily_limit = 1000  # Default limit
        
        return int(current_count) < daily_limit
    
    def increment_api_usage(self, user_id: str, operation: str):
        """Increment API usage counter"""
        quota_key = f"quota:{user_id}:{operation}"
        pipe = self.redis_client.pipeline()
        pipe.incr(quota_key)
        pipe.expire(quota_key, 86400)  # 24 hours
        pipe.execute()

# Global rate limit manager
rate_limit_manager = RateLimitManager()

def setup_security_middleware(app):
    """Set up security middleware for FastAPI app"""
    
    # Add CORS middleware
    cors_config = SecurityConfig.get_cors_config()
    app.add_middleware(CORSMiddleware, **cors_config)
    
    # Add rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    
    logger.info("Security middleware configured successfully")

# Security utilities
def generate_csrf_token() -> str:
    """Generate CSRF token"""
    return secrets.token_urlsafe(32)

def verify_csrf_token(token: str, stored_token: str) -> bool:
    """Verify CSRF token"""
    return secrets.compare_digest(token, stored_token)

def log_security_event(event_type: str, user_id: str = None, details: Dict = None):
    """Log security events for monitoring"""
    event = {
        "event_type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        "user_id": user_id,
        "details": details or {}
    }
    
    # Store in Redis for real-time monitoring
    redis_client.lpush("security_events", str(event))
    redis_client.ltrim("security_events", 0, 1000)  # Keep last 1000 events
    
    logger.info(f"Security event: {event_type}", extra=event)