# Kung-Fu Chess — Kubernetes / K3s Deployment

## Directory layout

```
k8s/
  namespace.yaml     — kungfu-chess namespace
  secret.yaml        — PostgreSQL credentials (replace before deploying)
  configmap.yaml     — shared non-secret environment config
  postgres.yaml      — PostgreSQL StatefulSet + headless Service + PVC
  redis.yaml         — Redis Deployment + ClusterIP Service + PVC
  game-server.yaml   — Game Server StatefulSet + headless + lb Services
  gateway.yaml       — API Gateway Deployment + NodePort Service
```

## Prerequisites

- K3s or any CNCF-conformant Kubernetes cluster
- Images built and pushed (or available locally with `imagePullPolicy: Never`):

  ```bash
  docker build -f Dockerfile        -t kfc-server:latest  .
  docker build -f Dockerfile.gateway -t kfc-gateway:latest .
  ```

  For K3s with local images import them with:

  ```bash
  docker save kfc-server:latest  | sudo k3s ctr images import -
  docker save kfc-gateway:latest | sudo k3s ctr images import -
  ```

## Credentials

Before deploying, replace the placeholder base64 values in `secret.yaml`
with your own password:

```bash
echo -n 'your-password' | base64

# Then update postgres-password and postgres-dsn in secret.yaml,
# OR generate fresh:
kubectl create secret generic kfc-postgres-secret \
  --from-literal=postgres-password=<PASSWORD> \
  --from-literal=postgres-dsn="postgresql://kfc:<PASSWORD>@postgres:5432/kungfu_chess" \
  --namespace=kungfu-chess --dry-run=client -o yaml > k8s/secret.yaml
```

## Deploy

```bash
# Apply in dependency order
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/redis.yaml

# Wait for postgres and redis to be ready before game servers
kubectl wait --for=condition=ready pod -l app=postgres -n kungfu-chess --timeout=120s
kubectl wait --for=condition=ready pod -l app=redis    -n kungfu-chess --timeout=60s

kubectl apply -f k8s/game-server.yaml
kubectl apply -f k8s/gateway.yaml

# Watch all pods come up
kubectl get pods -n kungfu-chess -w
```

## Verify

```bash
# Get the NodePort the gateway is exposed on (default 30080)
NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[0].address}')

curl http://${NODE_IP}:30080/health
curl http://${NODE_IP}:30080/ready
curl http://${NODE_IP}:30080/metrics

curl -X POST http://${NODE_IP}:30080/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"secret"}'
```

## Scaling game servers

```bash
# Scale up to 4 replicas — each gets a unique KFC_SERVER_ID (game-server-0..3)
kubectl scale statefulset game-server --replicas=4 -n kungfu-chess
```

## Architecture notes

| Component     | Kind         | Replicas | Identity strategy                         |
|---------------|--------------|----------|-------------------------------------------|
| PostgreSQL    | StatefulSet  | 1        | Stable pod name; data on PVC              |
| Redis         | Deployment   | 1        | Ephemeral; PVC for short-term durability  |
| Game Server   | StatefulSet  | 2+       | Pod name → `KFC_SERVER_ID` (Downward API) |
| API Gateway   | Deployment   | 2+       | Stateless; rolling updates                |

### Why StatefulSet for Game Servers?

The existing `GameAllocator` registers each server in Redis under a stable
`server_id`.  StatefulSet pod names (`game-server-0`, `game-server-1`, …) are
stable across restarts, so a restarted pod re-registers under the same ID and
picks up rooms that were routed to it.  A Deployment would give random pod
names and break the room→server mapping in Redis on every restart.

### Docker Compose

The existing `docker-compose.yml` is unmodified and still works for local
development:

```bash
docker compose up --build
```

Kubernetes is an additional deployment target, not a replacement.
