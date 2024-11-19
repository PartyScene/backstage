# Setting Up the Microservices Environment

## Prerequisites

- **Operating System**: Windows, macOS, or Linux

- **Required Tools**:
  - [Docker Desktop](https://www.docker.com/products/docker-desktop) (or Docker CLI for Linux)
  - Python 3.9+ installed with `pip`
  - GCP SDK installed and configured

## Environment Setup

### 1. Clone the Repository

git clone `backstage`

cd `backstage`

### 2. Configure `.env` Files

Create a `.env` file in the root directory with the following:

```env
DB_USER=root
DB_PASSWORD=supersecurepassword
```

### 3. Authenticate Google Cloud

Run the following to set up GCP credentials:

```bash
gcloud auth application-default login
```

Ensure the credentials are saved in the correct path as referenced in `docker-compose.yml`:

- Windows: `C:/Users/User/AppData/Roaming/gcloud`

- Linux/macOS: `~/.config/gcloud`

### 4. Create the Docker Network

```bash
docker network create \
  --subnet=10.0.0.0/24 \
  backstage_network
```

### 5. Build and Run the Services

Build and start all containers:

```bash
docker-compose up --build
```

### 6. Verify Services

- Access **SurrealDB**:

  ```bash
  curl http://localhost:8000/sql -d "INFO FOR DB;"
  ```

## Additional Notes

- Use `docker-compose logs -f` to monitor logs.
- Update the Kong Gateway configuration to manage routes for each service (e.g., `media`, `users`).
- Ensure all microservices work as intended before pushing to production.

---

### **Next Steps**

- Test the full stack locally with mocked clients to ensure all interactions (e.g., between `users` and `media`) function seamlessly.
- Implement error handling in services for missing JWT tokens, improper uploads, and invalid DB queries.
- Add scaling and monitoring (e.g., Docker Swarm, Prometheus) for production environments.