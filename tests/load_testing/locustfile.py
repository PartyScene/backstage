import os
import json
import random
import string
from datetime import datetime, timedelta
from locust import HttpUser, task, between, events
from locust.contrib.fasthttp import FastHttpUser
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PartySceneUser(FastHttpUser):
    """Load test user simulating real PartyScene usage patterns"""
    
    wait_time = between(1, 5)  # Wait 1-5 seconds between requests
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.auth_token = None
        self.user_id = None
        self.event_id = None
        
    def on_start(self):
        """Called when a user starts - register and login"""
        self.register_user()
        self.login_user()
    
    def register_user(self):
        """Register a new test user"""
        email = f"loadtest_{self.generate_random_string(8)}@test.com"
        password = "TestPassword123!"
        
        user_data = {
            "email": email,
            "password": password,
            "first_name": f"Test{self.generate_random_string(5)}",
            "last_name": f"User{self.generate_random_string(5)}",
            "date_of_birth": "1990-01-01"
        }
        
        with self.client.post("/auth/register", 
                             json=user_data,
                             catch_response=True) as response:
            if response.status_code in [200, 201]:
                response.success()
                self.email = email
                self.password = password
                logger.info(f"User registered: {email}")
            else:
                response.failure(f"Registration failed: {response.text}")
    
    def login_user(self):
        """Login with registered user"""
        if not hasattr(self, 'email'):
            return
            
        login_data = {
            "email": self.email,
            "password": self.password
        }
        
        with self.client.post("/auth/login",
                             json=login_data,
                             catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                self.auth_token = data.get("data", {}).get("access_token")
                response.success()
                logger.info(f"User logged in: {self.email}")
            else:
                response.failure(f"Login failed: {response.text}")
    
    @property
    def headers(self):
        """Get headers with auth token"""
        if self.auth_token:
            return {"Authorization": f"Bearer {self.auth_token}"}
        return {}
    
    @task(3)
    def browse_events(self):
        """Browse available events - high frequency task"""
        with self.client.get("/events/browse",
                           headers=self.headers,
                           catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Browse events failed: {response.text}")
    
    @task(2)
    def search_events(self):
        """Search for events with various criteria"""
        search_params = {
            "location": random.choice(["New York", "Los Angeles", "Chicago", "Miami"]),
            "category": random.choice(["party", "concert", "festival", "club"]),
            "date_from": datetime.now().strftime("%Y-%m-%d"),
            "date_to": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        }
        
        with self.client.get("/events/search",
                           params=search_params,
                           headers=self.headers,
                           catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Search events failed: {response.text}")
    
    @task(1)
    def create_event(self):
        """Create a new event using multipart/form-data."""
        if not self.auth_token:
            return

        event_time = datetime.now() + timedelta(days=random.randint(1, 30))

        form_data = {
            "title": f"Load Test Event {self.generate_random_string(6)}",
            "description": "This is a load test event created by locust.",
            "location": "Test Location, 123 Test Street",
            "time": event_time.isoformat() + "Z",
            "coordinates[]": (str(random.uniform(-90, 90)), str(random.uniform(-180, 180))),
            "price": str(random.uniform(10.0, 100.0)),
            "categories[]": (random.choice(["party", "concert", "festival"])),
            "is_private": str(random.choice(["true", "false"])).lower(),
            "is_free": str(random.choice(["true", "false"])).lower(),
        }

        # Simulate file upload
        files = {
            'file1': ('test_image.jpg', b'fake_image_bytes', 'image/jpeg')
        }

        with self.client.post("/events", files=files, data=form_data, headers=self.headers, catch_response=True, name="/events/create") as response:
            if response.status_code in [200, 201]:
                response.success()
                try:
                    data = response.json()
                    if "data" in data and data["data"] and "id" in data["data"][0]:
                        self.event_id = data["data"][0]["id"]
                except json.JSONDecodeError:
                    response.failure(f"Create event returned non-JSON response: {response.text}")
            else:
                response.failure(f"Create event failed with {response.status_code}: {response.text}")
    
    @task(3)
    def get_my_profile(self):
        """Fetches the profile of the current logged-in user."""
        if not self.auth_token:
            return
        with self.client.get("/user", headers=self.headers, catch_response=True, name="/user/me") as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Get my profile failed with {response.status_code}: {response.text}")

    @task(1)
    def update_my_profile(self):
        """Updates the profile of the current logged-in user."""
        if not self.auth_token:
            return
        update_data = {
            "bio": f"This is a load test bio updated at {datetime.now().isoformat()}",
            "interests": random.sample(["music", "dancing", "tech", "art", "food"], k=3)
        }
        with self.client.patch("/user", json=update_data, headers=self.headers, catch_response=True, name="/user/update") as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Update my profile failed with {response.status_code}: {response.text}")

    @task(2)
    def view_another_user_profile(self):
        """Simulates viewing another user's public profile."""
        # In a real test, this ID would be discovered from browsing events, etc.
        # For now, we use a placeholder.
        user_id_placeholder = "user:k9d4g7f1h3j5l2m8"
        with self.client.get(f"/users/{user_id_placeholder}", headers=self.headers, catch_response=True, name="/users/[id]") as response:
            if response.status_code in [200, 404]: # 404 is a valid outcome
                response.success()
            else:
                response.failure(f"View user profile failed with {response.status_code}: {response.text}")

    @task(1)
    def manage_friends_flow(self):
        """A sequential task to simulate a full friend request and management flow."""
        if not self.auth_token:
            return

        # In a real scenario, this would be a discovered user ID.
        target_user_id = "user:a1b2c3d4e5f6g7h8"

        # Step 1: Send friend request
        connection_id = None
        with self.client.post("/friends", json={"target_id": target_user_id}, headers=self.headers, catch_response=True, name="/friends/add") as response:
            if response.status_code in [201, 400]: # 400 if request already exists
                response.success()
                try:
                    data = response.json()
                    if "data" in data and "id" in data["data"]:
                        connection_id = data["data"]["id"]
                except (json.JSONDecodeError, KeyError):
                    pass # It's okay if we don't get an ID back, e.g., on a 400
            else:
                response.failure(f"Send friend request failed with {response.status_code}: {response.text}")
                return

        if not connection_id:
            # Can't proceed without a connection ID
            return

        # Step 2: Update status (e.g., accept). In reality, the other user would do this.
        # We simulate it here to test the endpoint.
        with self.client.patch(f"/friends/{connection_id}", json={"status": "accepted"}, headers=self.headers, catch_response=True, name="/friends/[id]/update") as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Accept friend request failed with {response.status_code}: {response.text}")

        # Step 3: Delete the connection
        with self.client.delete(f"/friends/{connection_id}", headers=self.headers, catch_response=True, name="/friends/[id]/delete") as response:
            if response.status_code in [200, 404]: # 404 if already gone
                response.success()
            else:
                response.failure(f"Delete friend failed with {response.status_code}: {response.text}")

    @task(2)
    def get_my_tickets_and_events(self):
        """Fetches the user's tickets and their created/attended events."""
        if not self.auth_token:
            return
        
        # Fetch tickets
        with self.client.get("/user/tickets", headers=self.headers, catch_response=True, name="/user/tickets") as response:
            if response.status_code in [200, 404]:
                response.success()
            else:
                response.failure(f"Get tickets failed with {response.status_code}: {response.text}")

        # Fetch created events
        with self.client.get("/user/events?created=true", headers=self.headers, catch_response=True, name="/user/events/created") as response:
            if response.status_code in [200, 404]:
                response.success()
            else:
                response.failure(f"Get created events failed with {response.status_code}: {response.text}")
    
    # @task(1)
    # def upload_media(self):
    #     """Simulate media upload"""
    #     # Create fake image data
    #     fake_image_data = b"fake_image_data_" + self.generate_random_string(100).encode()
        
    #     files = {
    #         'file': ('test_image.jpg', fake_image_data, 'image/jpeg')
    #     }
        
    #     with self.client.post("/media/upload",
    #                         files=files,
    #                         headers=self.headers,
    #                         catch_response=True) as response:
    #         if response.status_code in [200, 201]:
    #             response.success()
    #         else:
    #             response.failure(f"Media upload failed: {response.text}")
    
    @task(1)
    def join_event(self):
        """Join an event if we have an event_id"""
        if not self.event_id:
            return
            
        with self.client.post(f"/events/{self.event_id}/attend",
                            headers=self.headers,
                            catch_response=True) as response:
            if response.status_code in [200, 201]:
                response.success()
            else:
                response.failure(f"Join event failed: {response.text}")
    
    @task(1)
    def get_event_details(self):
        """Get detailed event information"""
        if not self.event_id:
            return
            
        with self.client.get(f"/events/{self.event_id}",
                           headers=self.headers,
                           catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Get event details failed: {response.text}")
    
    def generate_random_string(self, length):
        """Generate random string for test data"""
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

class AuthServiceUser(FastHttpUser):
    """Focused load testing for authentication service"""

    wait_time = between(0.5, 2)

    def on_start(self):
        """Called when a user starts."""
        self.email = f"loadtest_{self.generate_random_string(10)}@test.com"
        self.password = "TestPassword123!"
        self.first_name = "Load"
        self.last_name = "Test"
        self.username = f"loadtest_{self.generate_random_string(8)}"

    @task(2)
    def register_and_verify(self):
        """Task sequence for user registration and OTP verification."""
        user_data = {
            "email": self.email,
            "password": self.password,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "username": self.username
        }

        # Step 1: Register user
        otp = None
        with self.client.post("/auth/register", json=user_data, catch_response=True, name="/auth/register") as response:
            if response.status_code in [200, 201]:
                response.success()
                # In test environment, OTP is returned in response
                if "data" in response.json() and "otp" in response.json()["data"]:
                    otp = response.json()["data"]["otp"]
            elif response.status_code == 409: # Conflict
                response.success() # It's okay if user already exists for this test
            else:
                response.failure(f"Registration failed with {response.status_code}: {response.text}")
                return

        if not otp:
            # If user already existed or something went wrong, we can't verify.
            # Let's try to log in instead as a fallback for the flow.
            self.login_existing_user()
            return

        # Step 2: Verify with OTP
        verify_data = {
            "email": self.email,
            "otp": otp,
            "context": "register"
        }
        with self.client.post("/auth/verify", json=verify_data, catch_response=True, name="/auth/verify") as response:
            if response.status_code == 200:
                response.success()
                data = response.json()
                self.auth_token = data.get("data", {}).get("access_token")
            else:
                response.failure(f"OTP verification failed with {response.status_code}: {response.text}")


    @task(5)
    def login_existing_user(self):
        """Test login with existing credentials"""
        login_data = {
            "email": self.email, # Use the user from this session
            "password": self.password
        }

        with self.client.post("/auth/login", json=login_data, catch_response=True, name="/auth/login") as response:
            if response.status_code == 200:
                response.success()
                data = response.json()
                self.auth_token = data.get("data", {}).get("access_token")
            elif response.status_code == 401:  # Unauthorized is an expected failure
                response.success()
            else:
                response.failure(f"Login test failed with {response.status_code}: {response.text}")

    @task(1)
    def forgot_password_flow(self):
        """Simulates the forgot password flow."""
        # Step 1: Request password reset
        forgot_data = {"email": self.email}
        otp = None
        with self.client.post("/auth/forgot-password", json=forgot_data, catch_response=True, name="/auth/forgot-password") as response:
            if response.status_code == 200:
                response.success()
                if "data" in response.json() and "otp" in response.json()["data"]:
                    otp = response.json()["data"]["otp"]
            elif response.status_code == 404:
                response.success() # User might not exist, that's fine.
            else:
                response.failure(f"Forgot password failed with {response.status_code}: {response.text}")
                return

        if not otp:
            return

        # Step 2: Reset password with OTP
        new_password = "NewPassword123!"
        reset_data = {
            "email": self.email,
            "otp": otp,
            "new_password": new_password
        }
        with self.client.post("/auth/reset-password", json=reset_data, catch_response=True, name="/auth/reset-password") as response:
            if response.status_code == 200:
                response.success()
                self.password = new_password # Update password for next login
            else:
                response.failure(f"Reset password failed with {response.status_code}: {response.text}")


    @task(1)
    def check_if_user_exists(self):
        """Checks if a user exists by email or username."""
        param_type = random.choice(["email", "username"])
        param = self.email if param_type == "email" else self.username
        
        with self.client.get(f"/auth/exists?type={param_type}&param={param}", catch_response=True, name="/auth/exists") as response:
            if response.status_code in [200, 409]: # OK or Conflict are valid
                response.success()
            else:
                response.failure(f"Exists check failed with {response.status_code}: {response.text}")


    def generate_random_string(self, length):
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

class EventServiceUser(FastHttpUser):
    """Focused load testing for events service with authenticated requests."""

    wait_time = between(0.5, 3)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.auth_token = None
        self.email = None
        self.password = None

    def on_start(self):
        """Called when a user starts - register and login"""
        self.register_and_login()

    def register_and_login(self):
        """Register a new user and login to get auth token"""
        self.email = f"eventuser_{self.generate_random_string(10)}@test.com"
        self.password = "TestPassword123!"
        username = f"eventuser_{self.generate_random_string(8)}"

        # Register user
        user_data = {
            "email": self.email,
            "password": self.password,
            "first_name": "Event",
            "last_name": "User",
            "username": username
        }

        with self.client.post("/auth/register", json=user_data, catch_response=True, name="/auth/register") as response:
            if response.status_code in [200, 201]:
                response.success()
                # Get OTP from response in test environment
                if "data" in response.json() and "otp" in response.json()["data"]:
                    otp = response.json()["data"]["otp"]
                    # Verify OTP
                    verify_data = {
                        "email": self.email,
                        "otp": otp,
                        "context": "register"
                    }
                    with self.client.post("/auth/verify", json=verify_data, catch_response=True, name="/auth/verify") as verify_response:
                        if verify_response.status_code == 200:
                            data = verify_response.json()
                            self.auth_token = data.get("data", {}).get("access_token")
                            verify_response.success()
                        else:
                            verify_response.failure(f"OTP verification failed: {verify_response.text}")
            elif response.status_code == 409:
                # User already exists, try to login
                self.login_existing_user()
            else:
                response.failure(f"Registration failed: {response.text}")

    def login_existing_user(self):
        """Login with existing credentials"""
        login_data = {
            "email": self.email,
            "password": self.password
        }

        with self.client.post("/auth/login", json=login_data, catch_response=True, name="/auth/login") as response:
            if response.status_code == 200:
                data = response.json()
                self.auth_token = data.get("data", {}).get("access_token")
                response.success()
            else:
                response.failure(f"Login failed: {response.text}")

    @property
    def headers(self):
        """Get headers with auth token"""
        if self.auth_token:
            return {"Authorization": f"Bearer {self.auth_token}"}
        return {}

    @task(10)
    def browse_all_events(self):
        """Simulates heavy browsing of all public events with authentication."""
        if not self.auth_token:
            return
            
        page = random.randint(1, 10)
        limit = random.randint(10, 50)
        with self.client.get(f"/events?page={page}&limit={limit}", headers=self.headers, catch_response=True, name="/events/browse_all") as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Browse all events failed with {response.status_code}: {response.text}")

    @task(5)
    def fetch_events_by_distance(self):
        """Simulates searching for events by location with authentication."""
        if not self.auth_token:
            return
            
        lat = random.uniform(-90, 90)
        lng = random.uniform(-180, 180)
        distance = random.choice([1000, 5000, 10000]) # meters

        with self.client.get(f"/events?lat={lat}&lng={lng}&distance={distance}", headers=self.headers, catch_response=True, name="/events/by_distance") as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Fetch by distance failed with {response.status_code}: {response.text}")

    @task(2)
    def fetch_specific_event(self):
        """Simulates viewing a specific event with authentication."""
        if not self.auth_token:
            return
            
        # This task would ideally get an event_id from a browse task.
        # For now, we'll simulate with a placeholder. A more advanced setup could share state.
        event_id_placeholder = "event:j7b2n4k9s8p3q5r6"
        with self.client.get(f"/events/{event_id_placeholder}", headers=self.headers, catch_response=True, name="/events/[id]") as response:
            # Expecting 404 if placeholder is not a real event, which is a valid scenario.
            if response.status_code == 200 or response.status_code == 404:
                response.success()
            else:
                response.failure(f"Fetch specific event failed with {response.status_code}: {response.text}")

    def generate_random_string(self, length):
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

# Event handlers for custom metrics
@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, context, **kwargs):
    """Log slow requests"""
    if response_time > 2000:  # Log requests slower than 2 seconds
        logger.warning(f"Slow request: {request_type} {name} took {response_time}ms")

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Called when test starts"""
    logger.info("Load test starting...")
    logger.info(f"Target host: {environment.host}")

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Called when test stops"""
    logger.info("Load test completed")
    
    # Print summary statistics
    stats = environment.stats
    logger.info(f"Total requests: {stats.total.num_requests}")
    logger.info(f"Total failures: {stats.total.num_failures}")
    logger.info(f"Average response time: {stats.total.avg_response_time:.2f}ms")
    logger.info(f"95th percentile: {stats.total.get_response_time_percentile(0.95):.2f}ms")