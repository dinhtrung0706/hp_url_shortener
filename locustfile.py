import random
import string
from locust import HttpUser, task, between

class URLShortenerUser(HttpUser):
    wait_time = between(1, 5)
    host = "http://localhost"  # Assuming the API is running on localhost:5000

    # Store generated short hashes to be used by the redirect task
    _short_url_hashes = []

    def on_start(self):
        """ on_start is called when a Locust user starts running """
        self.client.get("/", name="/ (Health Check)")
        self.client.get("/redis-check", name="/redis-check (Redis Connection Check)")

    @task(10)
    def create_and_redirect_url(self):
        long_url = f"http://example.com/{''.join(random.choices(string.ascii_lowercase + string.digits, k=10))}"
        response = self.client.post("/shorten", json={"url": long_url})
        if response.status_code == 200:
            short_url = response.json().get("short_url")
            if short_url:
                short_url_hash = short_url.split('/')[-1]
                self._short_url_hashes.append(short_url_hash)
                self.client.get(f"/{short_url_hash}", name=f"/{short_url_hash} (Redirect Short URL)")
        else:
            response.failure(f"Failed to shorten URL: {response.text}")

    @task(2)
    def redirect_existing_url(self):
        if self._short_url_hashes:
            short_url_hash = random.choice(self._short_url_hashes)
            self.client.get(f"/{short_url_hash}", name=f"/{short_url_hash} (Redirect Existing Short URL)")
        else:
            # If no short URLs exist yet, create one
            self.create_and_redirect_url()

    @task(1)
    def visit_health_check(self):
        self.client.get("/", name="/ (Health Check)")

    @task(1)
    def visit_redis_check(self):
        self.client.get("/redis-check", name="/redis-check (Redis Connection Check)")

# run with: locust -f locustfile.py --host=http://localhost:5000
