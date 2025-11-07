# PartyScene Microservices Setup

## Prerequisites

- **Operating System**: Windows, macOS, or Linux
- **Required Tools**:
  - [Docker Desktop](https://www.docker.com/products/docker-desktop) (or Docker CLI for Linux)
  - Python 3.9+ with `pip`
  - [Google Cloud SDK](https://cloud.google.com/sdk/docs/install)
  - Git

## System Requirements

- **Minimum Specs**:
  - 8GB RAM
  - 20GB Disk Space
  - Multi-core CPU
- **Recommended**:
  - 16GB RAM
  - SSD Storage
  - Modern Multi-core Processor

## Project Overview

PartyScene is a microservices-based social platform with the following key services:
- Users Service
- Media Service
- Authentication Service
- Events Service
- Posts Service
- Livestream Service

## Microservices Architecture

### Core Technologies
- **Backend**: Python (Quart Framework)
- **Database**: SurrealDB v2.0
- **Caching**: Redis
- **API Gateway**: Kong
- **Containerization**: Docker
- **Cloud Storage**: Google Cloud Storage

## Prerequisites Installation

### 1. Install Dependencies

#### On Windows
```powershell
# Install Docker Desktop
winget install Docker.DockerDesktop

# Install Python 3.9+
winget install Python.Python.3.9

# Install Google Cloud SDK
winget install Google.CloudSDK
```

#### On macOS
```bash
# Install Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Docker Desktop
brew install --cask docker

# Install Python 3.9+
brew install python@3.9

# Install Google Cloud SDK
brew install google-cloud-sdk
```

#### On Linux (Ubuntu/Debian)
```bash
# Install Docker
sudo apt-get update
sudo apt-get install docker.io docker-compose

# Install Python 3.9+
sudo apt-get install python3.9 python3-pip

# Install Google Cloud SDK
sudo apt-get install apt-transport-https ca-certificates gnupg
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | sudo tee -a /etc/apt/sources.list.d/google-cloud-sdk.list
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key --keyring /usr/share/keyrings/cloud.google.gpg add -
sudo apt-get update && sudo apt-get install google-cloud-sdk
```

### 2. Configure Google Cloud

```bash
# Initialize Google Cloud
gcloud init

# Authenticate and set up application default credentials
gcloud auth application-default login

# Set your project
gcloud config set project partyscene-441317
```

## Repository Setup

### 1. Clone Repository

```bash
git clone https://github.com/scenes/backstage.git
cd backstage
```

### 2. Environment Configuration

Create a `.env` file in the root directory with the following template:

```env
# SurrealDB Credentials
DB_USER=root
DB_PASSWORD=your_secure_password

# Google Cloud Configuration
GCP_PROJECT_ID=partyscene-441317
GCP_BUCKET_NAME=partyscene-scenes
GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/credentials.json
GCLOUD_AUTH_DIR=C:/Users/YourUsername/.config/gcloud

# Cloudflare Stream API (for livestream service)
# Create token at: https://dash.cloudflare.com/profile/api-tokens
# Required permissions: Account > Stream > Edit
CLOUDFLARE_API_TOKEN=your_cloudflare_api_token
# Get account ID from: https://dash.cloudflare.com/ (in URL after login)
CLOUDFLARE_ACCOUNT_ID=your_cloudflare_account_id

# JWT and Security
JWT_SECRET_KEY=your_very_secure_random_key
```

### 3. Create Docker Network

```bash
docker network create \
  --subnet=11.0.0.0/24 \
  backstage_network
```

### 4. Build and Start Services

```bash
# Build all services
docker-compose build

# Start all services
docker-compose up -d
```

## Service Endpoints

| Service         | Port | Description                      |
|----------------|------|----------------------------------|
| Users          | 5500 | User management                 |
| Media          | 5510 | Media upload and management      |
| Auth           | 5520 | Authentication                  |
| Events         | 5530 | Event management                |
| Posts          | 5540 | Social posts                    |
| Livestream     | 5550 | Livestreaming                   |
| Kong Gateway   | 8002 | API Gateway                     |
| SurrealDB      | 8000 | Database                        |

## Verify Services
**Database Connection**:
```bash
# Test SurrealDB connection
curl http://localhost:8000/sql -d "INFO FOR DB;"
```

## Development Workflow

### Running Tests
```bash
# Run tests for a specific service
sudo docker compose -f docker-compose.test.yml up -d
```

### Adding New Features
1. Update schema in `init/schema.surql`
2. Add corresponding service endpoints
3. Write comprehensive tests
4. Update documentation

## Monitoring & Maintenance

```bash
# View real-time logs
docker compose logs -f

# Check service status
docker compose ps

# Monitor specific service
docker logs microservices.users
```

## Troubleshooting

- Ensure all environment variables are correctly set
- Check Docker network connectivity
- Verify Google Cloud credentials
- Validate SurrealDB connection parameters

## Security Recommendations

- Never commit `.env` files to version control
- Rotate credentials periodically
- Use strong, unique passwords
- Limit network access
- Keep all dependencies updated

## Performance Tuning

- Adjust Docker resource limits in `docker-compose.yml`
- Monitor service performance using Docker stats
- Scale services horizontally as needed

## Contributing

Please read `CONTRIBUTING.md` for details on our code of conduct and the process for submitting pull requests.

## License

This project is licensed under the MIT License - see the `LICENSE` file for details.

---

**Note**: This installation guide is for development setup. Production deployments require additional security and scalability configurations.