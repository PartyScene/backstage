# Fix OOM errors by updating memory limits for all microservices

Write-Host "Updating memory resources for all microservices..." -ForegroundColor Cyan


# Patch services without local resource files
Write-Host "`nPatching livestream memory..." -ForegroundColor Yellow
kubectl patch deployment microserv.livestream --type='json' -p='[
  {
    "op": "replace",
    "path": "/spec/template/spec/containers/0/resources",
    "value": {
      "requests": {
        "cpu": "250m",
        "memory": "512Mi"
      },
      "limits": {
        "memory": "1Gi"
      }
    }
  }
]'

Write-Host "`nPatching payments memory..." -ForegroundColor Yellow
kubectl patch deployment microserv.payments --type='json' -p='[
  {
    "op": "replace",
    "path": "/spec/template/spec/containers/0/resources",
    "value": {
      "requests": {
        "cpu": "250m",
        "memory": "512Mi"
      },
      "limits": {
        "memory": "1Gi"
      }
    }
  }
]'

Write-Host "`nPatching r18e memory..." -ForegroundColor Yellow
kubectl patch deployment microserv.r18e --type='json' -p='[
  {
    "op": "replace",
    "path": "/spec/template/spec/containers/0/resources",
    "value": {
      "requests": {
        "cpu": "250m",
        "memory": "512Mi"
      },
      "limits": {
        "memory": "1Gi"
      }
    }
  }
]'

Write-Host "`nPatching media memory..." -ForegroundColor Yellow
kubectl patch deployment microserv.media --type='json' -p='[
  {
    "op": "replace",
    "path": "/spec/template/spec/containers/0/resources",
    "value": {
      "requests": {
        "cpu": "250m",
        "memory": "512Mi"
      },
      "limits": {
        "memory": "1Gi"
      }
    }
  }
]'

Write-Host "`nCleaning up failed OOM pods..." -ForegroundColor Yellow
kubectl delete pod --field-selector=status.phase=Failed

Write-Host "`nDone! Watch pods restart with: kubectl get pods -w" -ForegroundColor Green
