# Cloud Build Pipelines

## Commands

```bash
# Production deploy
gcloud builds submit .

# Run tests
gcloud builds submit --config=cloudbuild-test.yaml .

# Check status
gcloud builds list --limit=10
kubectl get pods
```

---

## Pipeline Comparison

| Aspect | `cloudbuild.yaml` | `cloudbuild-test.yaml` |
|--------|-------------------|------------------------|
| Purpose | Production deploy | Quality gates |
| Duration | 8-12 min | 12-15 min |
| Stages | Build → Push → Deploy | Lint → Test → Cleanup |
| Triggers | On merge to `main` | On pull request |

---

## CI/CD Workflow

```
Pull Request → Test Pipeline → Merge → Production Deploy
```

**Test Pipeline** (cloudbuild-test.yaml):
- Flake8 linting
- Bandit security scan  
- Integration tests (all services)

**Deploy Pipeline** (cloudbuild.yaml):
- Build 6 microservices (parallel)
- Push to Artifact Registry
- Rolling restart on GKE

---

## Configuration

**Machine**: E2_HIGHCPU_8 (8 vCPUs, ~$0.20/hr)  
**Location**: us-central1  
**Cluster**: backstage-cluster  
**Caching**: Enabled via `--cache-from`

---

## Troubleshooting

```bash
# Build single service
docker build --target prod -t IMAGE_NAME -f SERVICE/Dockerfile .

# Manual deploy
kubectl rollout restart deployment/microserv.auth

# View logs
kubectl logs deploy/microserv.auth --tail=100

# Rollback
kubectl rollout undo deployment/microserv.auth
```

---

## Monitoring

```bash
# Build history
gcloud builds list --limit=10

# Deployment status  
kubectl rollout status deployment/microserv.auth
kubectl get pods

# Image vulnerabilities
gcloud artifacts docker images scan IMAGE_PATH
```

**See TEST-PIPELINE-FIXES.md for detailed test configuration.**
