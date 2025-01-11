# PartyScene Microservices Setup

## Prerequisites

- **Operating System**: Windows, macOS, or Linux
- **Required Tools**:
  - [Docker Desktop](https://www.docker.com/products/docker-desktop) (or Docker CLI for Linux)
  - Python 3.9+ with `pip`
  - GCP SDK (for media storage)

## Environment Setup

### 1. Clone the Repository

```bash
git clone https://github.com/scenes/partyscene.git
cd partyscene
```

### 2. Configure Environment Variables

Create a `.env` file in the root directory:

```env
DB_USER=root
DB_PASSWORD=your_secure_password
GCP_PROJECT_ID=your_project_id
GCP_BUCKET_NAME=your_bucket_name
```

### 3. Create Docker Network

```bash
docker network create \
  --subnet=172.20.0.0/16 \
  partyscene_network
```

### 4. Build and Start Services

```bash
docker-compose up --build
```

This will start:
- Users Service (Port 5500)
- Media Service (Port 5510)
- SurrealDB (Port 8000)
- Redis

The services are configured to use:
- SurrealDB at `ws://surrealdb:8000`
- Redis at `redis://redis`
as defined in shared settings.

### 5. Verify Installation

1. **Check SurrealDB**:
```bash
curl http://localhost:8000/sql -d "INFO FOR DB;"
```

2. **Test Users Service**:
```bash
curl http://localhost:5500/health
```

3. **Test Media Service**:
```bash
curl http://localhost:5510/health
```

## Service Architecture

### Users Service
- **Port**: 5500
- **Features**:
  - User Authentication
  - Profile Management
  - Friend Connections (up to 6 degrees)
  - Event Attendance

### Media Service
- **Port**: 5510
- **Features**:
  - File Upload to GCS
  - Media Management
  - Livestream Integration

### Database Schema
Key tables and relationships:
- `users`: Core user data
- `events`: Event information
- `friends`: Bidirectional friend relationships
- `attends`: User-Event relationships
- `media`: Media storage and metadata

## Development Guidelines

### Adding New Features
1. Update schema in `init/schema.surql`
2. Add corresponding endpoints in service
3. Update tests
4. Document in README

### Running Tests
```bash
# Run user service tests
cd users && python -m pytest

# Run media service tests
cd media && python -m pytest
```

## Troubleshooting

### Common Issues

1. **SurrealDB Connection Issues**:
   - Verify WebSocket connection at `ws://localhost:8000/rpc`
   - Check credentials in `.env`

2. **Friend Connections Not Working**:
   - Ensure bidirectional relationships in `friends` table
   - Check degree parameter (1-6 range)

3. **Media Upload Failures**:
   - Verify GCP credentials
   - Check bucket permissions

## Monitoring & Maintenance

- Use `docker-compose logs -f` for real-time logs
- Monitor SurrealDB with `surreal status`
- Check GCP Cloud Console for media storage metrics

## Security Notes

- Keep `.env` files secure and never commit them
- Regularly rotate JWT secrets
- Monitor GCP IAM permissions
- Keep SurrealDB credentials secure

---

For more details, check service-specific README files in each directory.