# Rules

Application data should live outside the source code. The `clients` package contains the clients used by the application to connect to external services such as PostgreSQL, MongoDB, S3, Qdrant, model providers, etc.

The client handles the connection. The backend or agent uses that client to
read/write data and perform application logic.

## Example: PostgreSQL

Flow:

```text
PostgreSQL
    ↓
clients/postgres.py
    ↓
backend / agent
    ↓
application logic
```

## Example: Create PostgreSQL locally

For local development, PostgreSQL can run in Docker:

```bash
docker volume create agent-postgres-data

docker run \
  --name agent-postgres \
  -e POSTGRES_USER=agent \
  -e POSTGRES_PASSWORD=agent \
  -e POSTGRES_DB=app \
  -p 5432:5432 \
  -v agent-postgres-data:/var/lib/postgresql/data \
  -d postgres:16
```

The named Docker volume keeps the database persistent even if the container is
removed or recreated. The connection string would be `DATABASE_URL=postgresql://agent:agent@localhost:5432/app`. This should be stored in `.env`, not in source code.

I could also do `-v ./.data/postgres:/var/lib/postgresql/data` to do a *bind mount*, and then the files would actually live in this repo at `./data/postgres/`. 

### Then use the client from within the applicaiton

```python
from app.clients.postgres import get_connection

def get_user(user_id: str):
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM users WHERE id = %s",
                (user_id,),
            )
            return cursor.fetchone()
```

The data is retrieved into the running application process — it is never stored
inside the repository.

## Example Object Storage

PDFs, images and other application files should use object storage rather than being stored directly in the source repository. The goal is to keep local development and production as similar as possible. The application always talks to an S3-compatible API. Only the configuration changes between local development and production.

### Local object storage with MinIO

Use MinIO locally because it exposes an S3-compatible API.
Create a `docker-compose.yaml` file at the root of the repository. It could look like:

```yaml
services:
  minio:
    image: minio/minio
    command: server /data --console-address ":9001"

    ports:
      - "9000:9000"
      - "9001:9001"

    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin

    volumes:
      - ./.data/minio:/data
```

Then start MinIO with `docker compose up -d minio`. The S3 API will be available at `http://localhost:9000` and the MinIO web UI at `http://localhost:9001`.

Store the local config in your `.env`:
```env
S3_ENDPOINT_URL=http://localhost:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=app-files
S3_REGION=us-east-1
```

And the actual local files will be persisted under `.data/minio/` which should be gitignored. Do not access `.data/` directly from application code. The application should always interact with MinIO through `clients/s3.py`.

Running `docker compose up -d service1 service2` runs multiple services. With `docker compose start/stop` I can simply start and stop the containers. `docker compose down` will stop and remove the containers. `docker compose down -v` will also delete the (otherwise persistent) volumes from docker desktop.

# Production
Docker is useful for local development, and we use it to mimic production environments. In production, PostgreSQL would normally run as an external managed service, for example Railway PostgreSQL, AWS RDS, Supabase, Neon, etc. This lets *the application code to stay the same; only DATABASE_URL changes.*

# Docker vs Docker Compose

Dockerfile
→ defines how to build the application container

docker-compose.yaml
→ defines services needed for local development
  such as MinIO, PostgreSQL, Redis, etc.