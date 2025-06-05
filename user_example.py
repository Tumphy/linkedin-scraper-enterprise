#!/usr/bin/env python3
"""
LinkedIn Scraper Enterprise - User Example
Easy-to-use example script for scraping LinkedIn profiles
"""

import requests
import time
import json
from typing import List, Dict

class LinkedInScraperClient:
    """Easy-to-use client for the LinkedIn scraper API"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.token = None
        self.headers = {}
    
    def login(self, email: str, password: str) -> bool:
        """Login and get authentication token"""
        try:
            response = requests.post(f"{self.base_url}/auth/login", json={
                "email": email,
                "password": password
            })
            
            if response.status_code == 200:
                data = response.json()
                self.token = data["access_token"]
                self.headers = {"Authorization": f"Bearer {self.token}"}
                print(f"✅ Successfully logged in as {email}")
                return True
            else:
                print(f"❌ Login failed: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Error during login: {e}")
            return False
    
    def scrape_profiles(self, profile_urls: List[str], priority: str = "normal") -> str:
        """Start scraping LinkedIn profiles"""
        try:
            response = requests.post(
                f"{self.base_url}/scrape/linkedin_profiles",
                json={
                    "urls": profile_urls,
                    "priority": priority
                },
                headers=self.headers
            )
            
            if response.status_code == 200:
                job_data = response.json()
                job_id = job_data["job_id"]
                print(f"🚀 Scraping job started: {job_id}")
                print(f"📋 Scraping {len(profile_urls)} profiles...")
                return job_id
            else:
                print(f"❌ Failed to start scraping: {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ Error starting scraping job: {e}")
            return None
    
    def monitor_job(self, job_id: str) -> Dict:
        """Monitor job progress until completion"""
        print(f"⏳ Monitoring job {job_id}...")
        
        while True:
            try:
                response = requests.get(f"{self.base_url}/jobs/{job_id}", headers=self.headers)
                
                if response.status_code == 200:
                    job_info = response.json()
                    status = job_info.get('status', 'unknown')
                    progress = job_info.get('progress', 0)
                    
                    print(f"📊 Status: {status.upper()}, Progress: {progress}%")
                    
                    if status in ['success', 'failure', 'cancelled']:
                        print(f"🏁 Job completed with status: {status.upper()}")
                        return job_info
                    
                    time.sleep(5)  # Check every 5 seconds
                else:
                    print(f"❌ Error checking job status: {response.text}")
                    return None
                    
            except KeyboardInterrupt:
                print("⏹️ Monitoring interrupted by user")
                return None
            except Exception as e:
                print(f"❌ Error monitoring job: {e}")
                return None
    
    def get_scraped_profiles(self, limit: int = 50, company: str = None) -> List[Dict]:
        """Get scraped profiles from the database"""
        try:
            params = {"limit": limit}
            if company:
                params["company"] = company
            
            response = requests.get(
                f"{self.base_url}/profiles",
                params=params,
                headers=self.headers
            )
            
            if response.status_code == 200:
                profiles = response.json()
                print(f"📄 Retrieved {len(profiles)} profiles")
                return profiles
            else:
                print(f"❌ Failed to get profiles: {response.text}")
                return []
                
        except Exception as e:
            print(f"❌ Error getting profiles: {e}")
            return []
    
    def get_system_health(self) -> Dict:
        """Check system health"""
        try:
            response = requests.get(f"{self.base_url}/health")
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": "Health check failed"}
        except Exception as e:
            return {"error": str(e)}

def main():
    """Example usage of the LinkedIn scraper"""
    
    print("🚀 LinkedIn Scraper Enterprise - User Example")
    print("=" * 50)
    
    # Initialize client
    client = LinkedInScraperClient()
    
    # 1. Login
    if not client.login("admin@yourcompany.com", "secure_password123"):
        print("❌ Please set up your user account first")
        return
    
    # 2. Check system health
    health = client.get_system_health()
    print(f"💚 System Status: {health.get('overall_status', 'unknown')}")
    
    # 3. Example LinkedIn profiles to scrape
    linkedin_profiles = [
        "https://www.linkedin.com/in/williamhgates/",
        "https://www.linkedin.com/in/jeffweiner08/",
        "https://www.linkedin.com/in/satyanadella/",
        "https://www.linkedin.com/in/sherylsandberg/",
        "https://www.linkedin.com/in/melinda-french-gates/"
    ]
    
    print(f"\n📋 Profiles to scrape:")
    for i, url in enumerate(linkedin_profiles, 1):
        print(f"  {i}. {url}")
    
    # 4. Start scraping
    job_id = client.scrape_profiles(linkedin_profiles, priority="high")
    if not job_id:
        return
    
    # 5. Monitor progress
    job_result = client.monitor_job(job_id)
    if not job_result:
        return
    
    # 6. Get results
    print(f"\n📊 Retrieving scraped profiles...")
    profiles = client.get_scraped_profiles(limit=10)
    
    # 7. Display results
    if profiles:
        print(f"\n✅ Successfully scraped {len(profiles)} profiles!")
        for i, profile in enumerate(profiles[:3], 1):  # Show first 3
            print(f"\n👤 Profile {i}:")
            print(f"   Name: {profile.get('full_name', 'N/A')}")
            print(f"   Title: {profile.get('role', 'N/A')}")
            print(f"   Company: {profile.get('company', 'N/A')}")
            print(f"   Location: {profile.get('location', 'N/A')}")
    else:
        print("❌ No profiles were retrieved")
    
    print(f"\n🎉 Example completed successfully!")
    print(f"💡 You can now:")
    print(f"   • View all profiles at: http://localhost:8000/docs")
    print(f"   • Monitor system at: http://localhost:8000/health")
    print(f"   • Check metrics at: http://localhost:8000/metrics")

if __name__ == "__main__":
    main()