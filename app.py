import os
import secrets
import string
import sqlalchemy
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse, RedirectResponse
from redis import Redis
from pydantic import BaseModel

class URLItem(BaseModel):
    url: str

app = FastAPI(
    title="URL Shortener API",
    description="API for shortening URLs and redirecting to original URLs.",
    version="1.0.0",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Database setup
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://user:password@localhost/shortener_db"
)
metadata = sqlalchemy.MetaData()

urls = sqlalchemy.Table(
    "urls",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("short_url", sqlalchemy.String, unique=True, index=True),
    sqlalchemy.Column("long_url", sqlalchemy.String),
)

engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)

# Localhost configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
DB_HOST = os.getenv("DB_HOST", "localhost")

# Initialize Redis client
redis_client = Redis(host=REDIS_HOST, port=6379, db=0)


@app.get("/", summary="Health Check", response_description="Status of the API")
async def health_check() -> JSONResponse:
    """
    Performs a health check on the API.
    Returns:
        JSONResponse: A JSON response indicating the API's status.
    """
    return JSONResponse(
        {
            "status": "running",
            "message": "URL Shortener API is active!",
            "pod_name": os.getenv("HOSTNAME", "localmachine"),
        }
    )


@app.get("/redis-check", summary="Redis Connection Check", response_description="Status of Redis connection")
async def redis_check() -> JSONResponse:
    """
    Checks the connection to the Redis server.
    Returns:
        JSONResponse: A JSON response indicating the Redis connection status.
    """
    try:
        redis_client.ping()
        return JSONResponse(
            {"status": "Redis connected", "message": "Successfully connected to Redis!"}
        )
    except Exception as e:
        return (
            JSONResponse({"status": "Redis connection error", "message": str(e)}),
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@app.post("/shorten", summary="Create Short URL", response_description="The newly created short URL")
async def create_short_url(url: URLItem) -> JSONResponse:
    """
    Creates a short URL for a given long URL.

    Args:
        url (URLItem): A Pydantic model containing the long URL to be shortened.

    Returns:
        JSONResponse: A JSON response containing the generated short URL.
    """
    long_url = url.url
    if not long_url:
        raise HTTPException(status_code=400, detail="URL not provided")

    short_url_hash = "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(7)
    )
    full_short_url = f"http://{os.getenv('SERVICE_IP', 'localhost')}/{short_url_hash}"
    # Save to PostgreSQL
    with engine.connect() as connection:
        query = urls.insert().values(short_url=short_url_hash, long_url=long_url)
        connection.execute(query)
        connection.commit()

    # Save to Redis
    redis_client.set(short_url_hash, long_url)

    return JSONResponse({"short_url": full_short_url})


@app.get("/{short_url_hash}", summary="Redirect to Long URL", response_description="Redirects to the original long URL")
async def redirect_to_long_url(short_url_hash: str) -> RedirectResponse:
    """
    Redirects to the original long URL associated with a given short URL hash.

    Args:
        short_url_hash (str): The hash of the short URL.

    Returns:
        RedirectResponse: A redirect response to the original long URL.
    """
    # Check Redis first
    long_url = redis_client.get(short_url_hash)
    if long_url:
        return RedirectResponse(url=long_url.decode("utf-8"))

    # If not in Redis, check PostgreSQL
    with engine.connect() as connection:
        query = urls.select().where(urls.c.short_url == short_url_hash)
        result = connection.execute(query).fetchone()
        if result:
            long_url = result.long_url
            # Save to Redis for next time
            redis_client.set(short_url_hash, long_url)
            return RedirectResponse(url=long_url)
        else:
            raise HTTPException(status_code=404, detail="Short URL not found")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5000)
