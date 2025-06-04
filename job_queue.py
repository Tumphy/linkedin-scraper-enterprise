"""
Production Job Queue System

Redis-based job queue with Celery for distributed task processing.
Supports priority queues, job persistence, and progress tracking.
"""

import os
import json
import uuid
import redis
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Union
from enum import Enum
from dataclasses import dataclass, asdict
from celery import Celery
import logging

logger = logging.getLogger(__name__)

# Redis connection for job storage
redis_client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379"),
    decode_responses=True
)

# Celery app configuration
celery_app = Celery(
    'linkedin_scraper',
    broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
    backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
    include=['job_queue']
)

# Celery configuration
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_routes={
        'job_queue.scrape_linkedin_profiles': {'queue': 'scraping'},
        'job_queue.process_bulk_data': {'queue': 'processing'},
        'job_queue.send_notifications': {'queue': 'notifications'}
    },
    worker_prefetch_multiplier=1,  # One task at a time per worker
    task_acks_late=True,  # Acknowledge tasks after completion
    worker_disable_rate_limits=False
)

class JobStatus(Enum):
    """Job status enumeration"""
    PENDING = "pending"
    STARTED = "started"
    PROGRESS = "progress"
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    RETRY = "retry"

class JobPriority(Enum):
    """Job priority levels"""
    LOW = 1
    NORMAL = 5
    HIGH = 8
    URGENT = 10

@dataclass
class JobInfo:
    """Job information container"""
    job_id: str
    job_type: str
    status: str
    priority: int
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress: int = 0
    progress_message: str = ""
    parameters: Dict[str, Any] = None
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    user_id: Optional[str] = None

class JobQueue:
    """Production job queue manager"""
    
    def __init__(self):
        self.redis_client = redis_client
        self.celery_app = celery_app
    
    def create_job(
        self, 
        job_type: str, 
        parameters: Dict[str, Any], 
        priority: JobPriority = JobPriority.NORMAL,
        user_id: Optional[str] = None,
        max_retries: int = 3
    ) -> str:
        """Create a new job in the queue"""
        
        job_id = f"job_{uuid.uuid4().hex}"
        job_info = JobInfo(
            job_id=job_id,
            job_type=job_type,
            status=JobStatus.PENDING.value,
            priority=priority.value,
            created_at=datetime.utcnow().isoformat(),
            parameters=parameters or {},
            max_retries=max_retries,
            user_id=user_id
        )
        
        # Store job information in Redis
        job_key = f"job:{job_id}"
        self.redis_client.setex(
            job_key,
            timedelta(days=7),  # Keep job info for 7 days
            json.dumps(asdict(job_info))
        )
        
        # Add to priority queue
        priority_queue = f"queue:priority:{priority.value}"
        self.redis_client.lpush(priority_queue, job_id)
        
        # Add to user's job list if user_id provided
        if user_id:
            user_jobs_key = f"user_jobs:{user_id}"
            self.redis_client.lpush(user_jobs_key, job_id)
            self.redis_client.expire(user_jobs_key, 86400 * 30)  # 30 days
        
        # Dispatch to Celery based on job type
        self._dispatch_celery_task(job_id, job_type, parameters)
        
        logger.info(f"Created job {job_id} of type {job_type} with priority {priority.name}")