# Post-Install MLOps Stack Runbook

**Kubeflow + MLflow + Redis + Yatai + Evidently**
**Last updated:** 2026-06-09

After completing the Kubeflow bootstrap, use this runbook to add:
- **PostgreSQL** (shared backend store)
- **MLflow** (experiment tracking + model registry)
- **Redis** (online feature store for Feast)
- **BentoML/Yatai** (model serving on K8s)
- **Evidently UI** (data drift monitoring)

---

## Known Issues vs. Book

The book (Machine Learning Platform Engineering) was written against older versions of several tools. The following have changed:

| Tool | Book assumes | Reality |
|------|-------------|---------|
| `bentoml/yatai` Helm chart | Bundles postgres + redis internally | Chart expects external services; no bundled deps |
| Yatai secret name | `yatai-env` | `<release-name>-env` (e.g. `yatai-test-env`) |
| Yatai service name | `yatai` | `<release-name>` (e.g. `yatai-test`) |
| Evidently UI | Works out of the box | Requires `--workspace` flag and inotify kernel tuning |

---

## Prerequisites

- Kubeflow bootstrap complete (all pods Running)
- SeaweedFS running in `kubeflow` namespace (S3 endpoint: `seaweedfs.kubeflow.svc.cluster.local:8333`, credentials: `minio` / `minio123`)
- Helm installed

---

## Phase 0: Kernel Tuning (Single Node Only)

K3s on a single node exhausts inotify limits quickly. Apply before deploying anything:

```bash
sudo sysctl fs.inotify.max_user_instances=512
sudo sysctl fs.inotify.max_user_watches=524288

# Make permanent
echo "fs.inotify.max_user_instances=512" | sudo tee -a /etc/sysctl.conf
echo "fs.inotify.max_user_watches=524288" | sudo tee -a /etc/sysctl.conf
```

---

## Phase 1: PostgreSQL

### Install

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update bitnami

kubectl create namespace postgres

helm install postgres-release bitnami/postgresql \
  --namespace postgres

kubectl get pods -n postgres -w
# Wait for: postgres-release-postgresql-0   Running
```

### Get Password

```bash
export POSTGRES_PASSWORD=$(
  kubectl get secret \
    --namespace postgres \
    postgres-release-postgresql \
    -o jsonpath="{.data.postgres-password}" \
  | base64 -d
)
echo "Postgres password: $POSTGRES_PASSWORD"
```

**Connection string:**
```
postgresql+psycopg2://postgres:<password>@postgres-release-postgresql.postgres.svc.cluster.local:5432/postgres
```

---

## Phase 2: MLflow

### Create mlflow-artifacts bucket in SeaweedFS

SeaweedFS does not auto-create buckets. Use the weed shell:

```bash
echo "s3.bucket.create -name mlflow-artifacts" | \
  kubectl exec -i -n kubeflow deployment/seaweedfs -c seaweedfs -- \
  /usr/bin/weed shell -master=localhost:9333

# Verify
echo "s3.bucket.list" | \
  kubectl exec -i -n kubeflow deployment/seaweedfs -c seaweedfs -- \
  /usr/bin/weed shell -master=localhost:9333
```

### deployment.yaml

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mlflow-deployment
  namespace: mlflow
  labels:
    app: mlflow
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mlflow
  template:
    metadata:
      labels:
        app: mlflow
    spec:
      containers:
        - name: mlflow
          image: abisoye314/mlflow:v1
          imagePullPolicy: IfNotPresent
          env:
            - name: AWS_ACCESS_KEY_ID
              value: minio
            - name: AWS_SECRET_ACCESS_KEY
              value: minio123
            - name: AWS_ENDPOINT_URL
              value: http://seaweedfs.kubeflow.svc.cluster.local:8333
            - name: MLFLOW_S3_IGNORE_TLS
              value: "true"
          command: ["/bin/bash"]
          args:
            - "-c"
            - "mlflow server --host 0.0.0.0 --default-artifact-root s3://mlflow-artifacts --backend-store-uri postgresql+psycopg2://postgres:<POSTGRES_PASSWORD>@postgres-release-postgresql.postgres.svc.cluster.local:5432/postgres"
          ports:
            - containerPort: 5000
```

> **Note:** Replace `<POSTGRES_PASSWORD>` with the actual password from Phase 1.

### service.yaml

```yaml
apiVersion: v1
kind: Service
metadata:
  name: mlflow-service
  namespace: mlflow
spec:
  selector:
    app: mlflow
  ports:
    - protocol: TCP
      port: 5000
      targetPort: 5000
```

### Deploy

```bash
kubectl create namespace mlflow
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
kubectl get pods -n mlflow -w
```

### Access

```bash
kubectl port-forward svc/mlflow-service -n mlflow 5000:5000
# http://localhost:5000
```

> **Image pull slow?** Pull directly on the node:
> ```bash
> sudo ctr images pull docker.io/abisoye314/mlflow:v1
> ```

---

## Phase 3: Redis

### Install

```bash
kubectl create namespace redis

helm install redis-deployment bitnami/redis \
  --namespace redis

kubectl get pods -n redis -w
```

> If you get `release name check failed: cannot reuse a name that is still in use`:
> ```bash
> helm uninstall redis-deployment -n redis
> # Then re-run the install
> ```

### Get Password

```bash
export REDIS_PASSWORD=$(
  kubectl get secret \
    --namespace redis \
    redis-deployment \
    -o jsonpath="{.data.redis-password}" \
  | base64 -d
)
echo "Redis password: $REDIS_PASSWORD"
```

> **Note:** The secret is named `redis-deployment` (not `redis-deployment-redis` as bitnami docs suggest for some versions).

**Connection details:**
```
Host: redis-deployment-master.redis.svc.cluster.local
Port: 6379
Password: $REDIS_PASSWORD
```

---

## Phase 4: Yatai

The book's install command no longer works. The current `bentoml/yatai` chart has no bundled postgres or redis — you must point it at external services explicitly.

### Create yatai bucket in SeaweedFS

```bash
echo "s3.bucket.create -name yatai" | \
  kubectl exec -i -n kubeflow deployment/seaweedfs -c seaweedfs -- \
  /usr/bin/weed shell -master=localhost:9333
```

### Create yatai database in PostgreSQL

```bash
kubectl exec -it -n postgres statefulset/postgres-release-postgresql -- \
  psql -U postgres -W -c "CREATE DATABASE yatai;"
# Enter $POSTGRES_PASSWORD when prompted
```

### Install

```bash
helm repo add bentoml https://bentoml.github.io/helm-charts
helm repo update bentoml

kubectl create namespace yatai-system

helm install yatai-test bentoml/yatai \
  --set ingress.enabled=false \
  --set service.type=ClusterIP \
  --set postgresql.host=postgres-release-postgresql.postgres.svc.cluster.local \
  --set postgresql.port=5432 \
  --set postgresql.user=postgres \
  --set postgresql.password=<POSTGRES_PASSWORD> \
  --set postgresql.database=yatai \
  --set s3.endpoint=seaweedfs.kubeflow.svc.cluster.local:8333 \
  --set s3.bucketName=yatai \
  --set s3.accessKey=minio \
  --set s3.secretKey=minio123 \
  --set s3.secure=false \
  -n yatai-system

kubectl get pods -n yatai-system -w
```

> If you get `release name check failed`:
> ```bash
> helm uninstall yatai-test -n yatai-system
> # Then re-run the install
> ```

### Get Initialization Token and Access

```bash
# Secret is named <release-name>-env, not yatai-env
export YATAI_INITIALIZATION_TOKEN=$(
  kubectl get secret yatai-test-env \
    --namespace yatai-system \
    -o jsonpath="{.data.YATAI_INITIALIZATION_TOKEN}" \
  | base64 --decode
)

kubectl port-forward svc/yatai-test -n yatai-system 8081:80 &

echo "http://localhost:8081/setup?token=$YATAI_INITIALIZATION_TOKEN"
```

Open the URL and create your admin account.

---

## Phase 5: Evidently UI

### deployment.yaml

The `--workspace` flag is required in 0.7.x — the UI will 500 on every request without it.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  labels:
    app: evidently-ui
  name: evidently-ui
  namespace: evidently
spec:
  replicas: 1
  selector:
    matchLabels:
      app: evidently-ui
  template:
    metadata:
      labels:
        app: evidently-ui
    spec:
      containers:
      - image: abisoye314/evidently-ui:latest
        name: evidently-ui
        command: ["evidently", "ui", "--host", "0.0.0.0", "--workspace", "/tmp/workspace"]
        ports:
        - containerPort: 8000
```

### namespace.yaml

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: evidently
```

### service.yaml

```yaml
apiVersion: v1
kind: Service
metadata:
  labels:
    app: evidently-ui
  name: evidently-ui
  namespace: evidently
spec:
  ports:
  - name: 8000-8000
    port: 8000
    protocol: TCP
    targetPort: 8000
  selector:
    app: evidently-ui
  type: ClusterIP
```

### Deploy

```bash
kubectl apply -f namespace.yaml
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
kubectl get pods -n evidently -w
```

### Access

```bash
kubectl port-forward svc/evidently-ui -n evidently 8000:8000
# http://localhost:8000
```

---

## Access URLs Summary

```bash
# MLflow
kubectl port-forward svc/mlflow-service -n mlflow 5000:5000
# http://localhost:5000

# Yatai
kubectl port-forward svc/yatai-test -n yatai-system 8081:80
# http://localhost:8081

# Evidently
kubectl port-forward svc/evidently-ui -n evidently 8000:8000
# http://localhost:8000
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Yatai: `dial tcp [::1]:5432 connection refused` | Chart not receiving postgres config | Use explicit `--set postgresql.*` flags as shown above |
| Yatai: `database "yatai" does not exist` | DB not created before install | `CREATE DATABASE yatai` in postgres first |
| Evidently UI: `500 Internal Server Error` on `/api/projects` | Missing `--workspace` flag or inotify limit | Add `--workspace /tmp/workspace` to command; increase inotify limits |
| Evidently UI: `inotify instance limit reached` | Single-node k3s exhausts kernel inotify | Run Phase 0 kernel tuning commands |
| Any pod: `ImagePullBackOff` with TLS timeout | Slow Docker Hub connection | `sudo ctr images pull docker.io/<image>:<tag>` directly on node |
| Helm: `cannot reuse a name that is still in use` | Previous failed install | `helm uninstall <name> -n <namespace>` then reinstall |
| Redis secret not found at `redis-deployment-redis` | Secret naming varies by chart version | Check actual name: `kubectl get secrets -n redis` |
