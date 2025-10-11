# OOM Fix - Memory Limit Updates

## Problem
Multiple pods experiencing OutOfMemory errors due to insufficient memory allocation.

**Affected Pods:**
- microserv.events
- microserv.livestream
- microserv.payments
- microserv.posts
- microserv.r18e

## Root Cause
All services configured with:
- **Memory request**: 128Mi (too low)
- **Memory limit**: None (pods can be killed anytime)
- **CPU**: 100m (insufficient)

Python/Quart apps with database connections need 256-512Mi minimum.

---

## Changes Applied

### Updated Resource Limits

| Resource | Before | After |
|----------|--------|-------|
| **Memory Request** | 128Mi | 512Mi |
| **Memory Limit** | None | 1Gi |
| **CPU Request** | 100m | 250m |

### Files Modified
- `auth/k8s/resource.yaml`
- `events/k8s/resource.yaml`
- `posts/k8s/resource.yaml`
- `users/k8s/resource.yaml`

---

## How to Apply

### PowerShell (Windows)
```powershell
.\fix-memory-limits.ps1
```

### Bash (Linux/Mac)
```bash
chmod +x fix-memory-limits.sh
./fix-memory-limits.sh
```

### Manual (per service)
```bash
# Apply local files
kubectl apply -f auth/k8s/resource.yaml
kubectl apply -f events/k8s/resource.yaml
kubectl apply -f posts/k8s/resource.yaml
kubectl apply -f users/k8s/resource.yaml

# Patch others
kubectl patch deployment microserv.livestream --type='json' -p='[
  {"op": "replace", "path": "/spec/template/spec/containers/0/resources", 
   "value": {"requests": {"cpu": "250m", "memory": "512Mi"}, "limits": {"memory": "1Gi"}}}
]'
```

---

## Verification

```bash
# Watch pods restart
kubectl get pods -w

# Check new resource limits
kubectl describe deployment microserv.auth | grep -A5 "Limits:"

# Clean up failed pods
kubectl delete pod --field-selector=status.phase=Failed
```

**Expected**: All pods running with 512Mi-1Gi memory, no OOM errors.

---

## Cost Impact

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Memory per pod | 128Mi | 512Mi | +300% |
| Total pods | 8 | 8 | 0 |
| **Total memory** | 1Gi | 4Gi | **+3Gi** |
| **Cost increase** | ~$15/mo | ~$60/mo | **+$45/mo** |

GKE Autopilot pricing: ~$15/GB/month for memory

---

## Prevention

### 1. Add to Dockerfile Health Checks
```dockerfile
# Monitor memory usage
HEALTHCHECK --interval=30s --timeout=3s \
  CMD ps aux | awk '{sum+=$6} END {if(sum/1024 > 400) exit 1}'
```

### 2. Set Resource Requests in Base Template
```yaml
# k8s/base-deployment.yaml
resources:
  requests:
    cpu: 250m
    memory: 512Mi
  limits:
    memory: 1Gi
```

### 3. Monitor Memory Usage
```bash
# Check actual memory usage
kubectl top pods

# View metrics over time
kubectl get --raw /apis/metrics.k8s.io/v1beta1/pods
```

---

## Troubleshooting

### If OOM still occurs:

**1. Check actual memory usage**
```bash
kubectl exec -it POD_NAME -- ps aux --sort=-%mem | head -10
```

**2. Increase limits further**
```yaml
limits:
  memory: 2Gi  # Double from 1Gi
```

**3. Check for memory leaks**
```bash
# Look for growing memory over time
kubectl top pod POD_NAME --use-protocol-buffers
```

**4. Enable memory profiling**
```python
# Add to app startup
import tracemalloc
tracemalloc.start()
```

---

## Related Issues

- Auth pods crashing rapidly: Likely due to startup probes failing before app ready
- Consider adding:
```yaml
startupProbe:
  httpGet:
    path: /health
    port: 8080
  failureThreshold: 30
  periodSeconds: 10
```
