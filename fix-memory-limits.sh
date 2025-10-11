#!/bin/bash
# Fix OOM errors by updating memory limits for all microservices

echo "Updating memory resources for all microservices..."

# Apply local resource files
kubectl apply -f auth/k8s/resource.yaml
kubectl apply -f events/k8s/resource.yaml
kubectl apply -f posts/k8s/resource.yaml
kubectl apply -f users/k8s/resource.yaml

# Patch services without local resource files
echo "Patching livestream memory..."
kubectl patch deployment microserv.livestream -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "microservices-livestream-1",
          "resources": {
            "requests": {
              "cpu": "250m",
              "memory": "512Mi"
            },
            "limits": {
              "memory": "1Gi"
            }
          }
        }]
      }
    }
  }
}'

echo "Patching payments memory..."
kubectl patch deployment microserv.payments -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "microservices-payments-1",
          "resources": {
            "requests": {
              "cpu": "250m",
              "memory": "512Mi"
            },
            "limits": {
              "memory": "1Gi"
            }
          }
        }]
      }
    }
  }
}'

echo "Patching r18e memory..."
kubectl patch deployment microserv.r18e -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "microservices-r18e-1",
          "resources": {
            "requests": {
              "cpu": "250m",
              "memory": "512Mi"
            },
            "limits": {
              "memory": "1Gi"
            }
          }
        }]
      }
    }
  }
}'

echo "Patching media memory..."
kubectl patch deployment microserv.media -p '{
  "spec": {
    "template": {
      "spec": {
        "containers": [{
          "name": "microservices-media-1",
          "resources": {
            "requests": {
              "cpu": "250m",
              "memory": "512Mi"
            },
            "limits": {
              "memory": "1Gi"
            }
          }
        }]
      }
    }
  }
}'

echo "Cleaning up OOM pods..."
kubectl delete pod -l app=microserv.events --field-selector=status.phase=Failed
kubectl delete pod -l app=microserv.livestream --field-selector=status.phase=Failed
kubectl delete pod -l app=microserv.payments --field-selector=status.phase=Failed
kubectl delete pod -l app=microserv.posts --field-selector=status.phase=Failed
kubectl delete pod -l app=microserv.r18e --field-selector=status.phase=Failed

echo "Done! Watch pods restart with: kubectl get pods -w"
