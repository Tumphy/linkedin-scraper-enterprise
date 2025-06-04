#!/usr/bin/env python3
"""
LinkedIn Scraper Production Deployment Script

Comprehensive deployment and validation script for production environment.
Ensures all systems are properly configured and operational.
"""

import os
import sys
import time
import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import secrets
import psutil

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ProductionDeployment:
    """Production deployment manager"""
    
    def __init__(self):
        self.project_root = Path(__file__).parent
        self.env_file = self.project_root / ".env"
        self.checks_passed = []
        self.checks_failed = []
    
    def run_command(self, command: str, check_return_code: bool = True) -> Tuple[int, str, str]:
        """Run shell command and return result"""
        try:
            result = subprocess.run(
                command, 
                shell=True, 
                capture_output=True, 
                text=True,
                cwd=self.project_root
            )
            
            if check_return_code and result.returncode != 0:
                logger.error(f"Command failed: {command}")
                logger.error(f"Error output: {result.stderr}")
                return result.returncode, result.stdout, result.stderr
            
            return result.returncode, result.stdout, result.stderr
            
        except Exception as e:
            logger.error(f"Exception running command '{command}': {e}")
            return 1, "", str(e)
    
    def check_python_version(self) -> bool:
        """Check Python version compatibility"""
        logger.info("Checking Python version...")
        
        version = sys.version_info
        if version.major == 3 and version.minor >= 8:
            logger.info(f"✅ Python {version.major}.{version.minor}.{version.micro} is compatible")
            self.checks_passed.append("Python version")
            return True
        else:
            logger.error(f"❌ Python {version.major}.{version.minor}.{version.micro} is not supported. Need Python 3.8+")
            self.checks_failed.append("Python version")
            return False
    
    def check_system_requirements(self) -> bool:
        """Check system requirements"""
        logger.info("Checking system requirements...")
        
        # Check available memory
        memory = psutil.virtual_memory()
        memory_gb = memory.total / (1024**3)
        
        if memory_gb < 2:
            logger.warning(f"⚠️  System has {memory_gb:.1f}GB RAM. Recommended: 4GB+")
        else:
            logger.info(f"✅ System has {memory_gb:.1f}GB RAM")
        
        # Check available disk space
        disk = psutil.disk_usage('/')
        disk_gb = disk.free / (1024**3)
        
        if disk_gb < 5:
            logger.error(f"❌ Only {disk_gb:.1f}GB free disk space. Need at least 5GB")
            self.checks_failed.append("Disk space")
            return False
        else:
            logger.info(f"✅ {disk_gb:.1f}GB free disk space available")
        
        self.checks_passed.append("System requirements")
        return True
    
    def install_dependencies(self) -> bool:
        """Install production dependencies"""
        logger.info("Installing production dependencies...")
        
        # Install requirements
        requirements_file = self.project_root / "requirements_production.txt"
        if requirements_file.exists():
            logger.info("Installing requirements from requirements_production.txt...")
            ret_code, stdout, stderr = self.run_command("pip install -r requirements_production.txt")
            if ret_code != 0:
                logger.error(f"Failed to install requirements: {stderr}")
                self.checks_failed.append("Dependencies installation")
                return False
        
        logger.info("✅ Dependencies installed successfully")
        self.checks_passed.append("Dependencies")
        return True
    
    def setup_environment(self) -> bool:
        """Setup production environment file"""
        logger.info("Setting up environment configuration...")
        
        if self.env_file.exists():
            logger.info("✅ .env file already exists")
            self.checks_passed.append("Environment file")
            return True
        
        # Copy from template
        env_template = self.project_root / ".env.production"
        if env_template.exists():
            logger.info("Creating .env from .env.production template...")
            
            # Read template and generate secure values
            with open(env_template, 'r') as f:
                content = f.read()
            
            # Generate secure secrets
            jwt_secret = secrets.token_urlsafe(32)
            api_secret = secrets.token_urlsafe(32)
            
            # Replace placeholder values
            content = content.replace(
                "CHANGE_THIS_IN_PRODUCTION_TO_RANDOM_32_CHAR_STRING", 
                jwt_secret
            )
            content = content.replace(
                "CHANGE_THIS_TO_RANDOM_SECRET_KEY", 
                api_secret
            )
            
            # Write .env file
            with open(self.env_file, 'w') as f:
                f.write(content)
            
            logger.info("✅ .env file created with secure random secrets")
            logger.warning("⚠️  Please review and update .env file with your specific configuration")
            
        else:
            logger.error("❌ .env.production template not found")
            self.checks_failed.append("Environment template")
            return False
        
        self.checks_passed.append("Environment setup")
        return True
    
    def check_services(self) -> bool:
        """Check if required services are available"""
        logger.info("Checking required services...")
        
        services_status = {}
        
        # Check Redis
        try:
            import redis
            client = redis.Redis.from_url("redis://localhost:6379", decode_responses=True)
            client.ping()
            logger.info("✅ Redis is running and accessible")
            services_status["redis"] = True
        except Exception as e:
            logger.warning(f"⚠️  Redis not available: {e}")
            logger.info("You can start Redis with: docker run -d -p 6379:6379 redis:alpine")
            services_status["redis"] = False
        
        if services_status.get("redis", False):
            self.checks_passed.append("Redis service")
        else:
            self.checks_failed.append("Redis service")
        
        return True  # Services are optional for basic setup
    
    def validate_modules(self) -> bool:
        """Validate that our production modules can be imported"""
        logger.info("Validating production modules...")
        
        modules_to_test = [
            "security",
            "job_queue", 
            "monitoring",
            "config"
        ]
        
        for module_name in modules_to_test:
            try:
                __import__(module_name)
                logger.info(f"✅ {module_name} module imports successfully")
            except ImportError as e:
                logger.error(f"❌ Failed to import {module_name}: {e}")
                self.checks_failed.append(f"{module_name} module")
                return False
        
        self.checks_passed.append("Module validation")
        return True
    
    def run_basic_tests(self) -> bool:
        """Run basic functionality tests"""
        logger.info("Running basic functionality tests...")
        
        try:
            # Test security module
            from security import auth_manager, User, UserRole
            test_user = User("test-user", "test@example.com", UserRole.USER)
            token = auth_manager.generate_jwt_token(test_user)
            payload = auth_manager.verify_jwt_token(token)
            assert payload["user_id"] == "test-user"
            logger.info("✅ Security module test passed")
            
            # Test job queue module (basic)
            from job_queue import job_queue, JobPriority
            job_id = job_queue.create_job(
                "test_job",
                {"test": "data"},
                priority=JobPriority.LOW
            )
            job_info = job_queue.get_job_status(job_id)
            assert job_info is not None
            logger.info("✅ Job queue module test passed")
            
            # Test monitoring module
            from monitoring import metrics_collector, health_monitor
            metrics_collector.track_api_request("GET", "/test", 200, 0.1)
            health_status = health_monitor.check_database()
            logger.info("✅ Monitoring module test passed")
            
            self.checks_passed.append("Basic functionality tests")
            return True
            
        except Exception as e:
            logger.error(f"❌ Basic tests failed: {e}")
            self.checks_failed.append("Basic functionality tests")
            return False
    
    def generate_deployment_summary(self) -> None:
        """Generate deployment summary report"""
        logger.info("\n" + "="*60)
        logger.info("PRODUCTION DEPLOYMENT SUMMARY")
        logger.info("="*60)
        
        logger.info(f"\n✅ PASSED CHECKS ({len(self.checks_passed)}):")
        for check in self.checks_passed:
            logger.info(f"  • {check}")
        
        if self.checks_failed:
            logger.info(f"\n❌ FAILED CHECKS ({len(self.checks_failed)}):")
            for check in self.checks_failed:
                logger.info(f"  • {check}")
        
        total_checks = len(self.checks_passed) + len(self.checks_failed)
        success_rate = (len(self.checks_passed) / total_checks) * 100 if total_checks > 0 else 0
        
        logger.info(f"\nOverall Success Rate: {success_rate:.1f}%")
        
        if success_rate >= 90:
            logger.info("🎉 DEPLOYMENT STATUS: READY FOR PRODUCTION")
            self.print_next_steps()
        elif success_rate >= 70:
            logger.info("⚠️  DEPLOYMENT STATUS: NEEDS MINOR FIXES")
            self.print_fixes_needed()
        else:
            logger.info("❌ DEPLOYMENT STATUS: NEEDS MAJOR FIXES")
            self.print_fixes_needed()
    
    def print_next_steps(self) -> None:
        """Print next steps for production deployment"""
        logger.info("\n🚀 NEXT STEPS:")
        logger.info("1. Review and update .env file with your production values")
        logger.info("2. Start Redis: docker run -d -p 6379:6379 redis:alpine")
        logger.info("3. Set up PostgreSQL database (optional)")
        logger.info("4. Start the API: python api_production.py")
        logger.info("5. Start Celery workers: celery -A job_queue.celery_app worker --loglevel=info")
        logger.info("6. Access API docs: http://localhost:8000/docs")
        logger.info("7. Check health: http://localhost:8000/health")
        logger.info("8. Monitor metrics: http://localhost:8000/metrics")
    
    def print_fixes_needed(self) -> None:
        """Print fixes needed for failed checks"""
        logger.info("\n🔧 FIXES NEEDED:")
        for check in self.checks_failed:
            if "Redis" in check:
                logger.info("• Install and start Redis: docker run -d -p 6379:6379 redis:alpine")
            elif "Dependencies" in check:
                logger.info("• Install dependencies: pip install -r requirements_production.txt")
            elif "Python" in check:
                logger.info("• Upgrade to Python 3.8 or higher")
            elif "Disk space" in check:
                logger.info("• Free up disk space (need at least 5GB)")
            else:
                logger.info(f"• Fix issue with: {check}")
    
    def deploy(self) -> bool:
        """Run complete deployment process"""
        logger.info("🚀 Starting LinkedIn Scraper Production Deployment")
        logger.info("="*60)
        
        # Run all deployment checks
        checks = [
            self.check_python_version,
            self.check_system_requirements,
            self.install_dependencies,
            self.setup_environment,
            self.check_services,
            self.validate_modules,
            self.run_basic_tests
        ]
        
        for check in checks:
            try:
                success = check()
                if not success:
                    logger.warning(f"Check failed: {check.__name__}")
            except Exception as e:
                logger.error(f"Exception in {check.__name__}: {e}")
                self.checks_failed.append(check.__name__)
        
        # Generate summary
        self.generate_deployment_summary()
        
        # Return overall success
        total_checks = len(self.checks_passed) + len(self.checks_failed)
        success_rate = (len(self.checks_passed) / total_checks) * 100 if total_checks > 0 else 0
        
        return success_rate >= 80

def main():
    """Main deployment function"""
    try:
        deployment = ProductionDeployment()
        success = deployment.deploy()
        
        if success:
            logger.info("\n🎉 Deployment completed successfully!")
            return 0
        else:
            logger.error("\n❌ Deployment completed with issues. Please address the failed checks.")
            return 1
            
    except KeyboardInterrupt:
        logger.info("\n⚠️  Deployment interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"\n💥 Deployment failed with error: {e}")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)