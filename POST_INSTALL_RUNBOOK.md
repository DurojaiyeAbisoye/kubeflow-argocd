# Post-Install MLOps Stack Runbook

**Version:** 26.03 | **Kubeflow + MLflow + Redis + Yatai + Evidently** | **Date:** 2026-06-04

After completing the Kubeflow bootstrap (see [BOOTSTRAP_RUNBOOK.md](BOOTSTRAP_RUNBOOK.md)), use this runbook to add:
- **MLflow** (experiment tracking + model registry)
- **Redis** (online feature store for Feast)
- **BentoML/Yatai** (model serving on K8s)
- **Evidently UI** (data drift monitoring)

---

## Prerequisites

✓ Kubeflow bootstrap complete (all pods Running)  
✓ SeaweedFS S3 gateway running in kubeflow namespace  
✓ Postgres will be deployed in this runbook  
✓ Helm 4+ installed (`helm version`)

---

## Phase 1: PostgreSQL Backend Store

MLflow and other components need Postgres for metadata storage. Deploy via Helm.

### 1a: Add Helm Repository

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update bitnami
```

### 1b: Create postgres namespace

```bash
kubectl create namespace postgres
```

### 1c: Install PostgreSQL

```bash
helm install postgres-release bitnami/postgresql \
  --namespace postgres \
  --set auth.password=kubeflow2026 \
  --wait

# Verify deployment
kubectl get deployment -n postgres
kubectl get pods -n postgres  # Should show postgres-release-postgresql-0 Running
```

### 1d: Store Postgres Password

```bash
# Capture the password for later use
export POSTGRES_PASSWORD="kubeflow2026"

# Or retrieve from secret if using Helm's auto-generated password:
export POSTGRES_PASSWORD=$(
  kubectl get secret \
    --namespace postgres \
    postgres-release-postgresql \
    -o jsonpath="{.data.postgres-password}" \
  | base64 -d
)

echo "Postgres Password: $POSTGRES_PASSWORD"
```

**Postgres connection details:**
```
Host: postgres-release-postgresql.postgres.svc.cluster.local
Port: 5432
User: postgres
Password: $POSTGRES_PASSWORD
```

---

## Phase 2: MLflow Deployment

MLflow serves as the experiment tracker and model registry. It uses Postgres for backend and SeaweedFS S3 gateway for artifact storage.

### 2a: Create mlflow namespace and secret

```bash
kubectl create namespace mlflow

# Store SeaweedFS S3 credentials as secret
kubectl create secret generic mlflow-s3-credentials \
  --from-literal=aws-access-key-id=minio \
  --from-literal=aws-secret-access-key=minio123 \
  -n mlflow
```

### 2b: Create mlflow-artifacts bucket in SeaweedFS

Port-forward to SeaweedFS S3 gateway and create the bucket:

```bash
# Port-forward SeaweedFS S3
kubectl port-forward -n kubeflow svc/seaweedfs-s3 9000:8333 &
S3_PID=$!
sleep 2

# Create mlflow-artifacts bucket (using AWS CLI)
# If AWS CLI not installed: pip install awscli-local or use s3cmd
aws s3api create-bucket \
  --bucket mlflow-artifacts \
  --endpoint-url http://localhost:9000 \
  --access-key-id minio \
  --secret-access-key minio123 \
  --region us-east-1

# Verify bucket exists
aws s3 ls --endpoint-url http://localhost:9000 \
  --access-key-id minio \
  --secret-access-key minio123

# Cleanup port-forward
kill $S3_PID 2>/dev/null
```

### 2c: Create MLflow Deployment

Save the following as `mlflow-deployment.yaml`:

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
          image: python:3.11-slim
          imagePullPolicy: IfNotPresent
          env:
            - name: AWS_ACCESS_KEY_ID
              value: "minio"
            - name: AWS_SECRET_ACCESS_KEY
              value: "minio123"
            - name: AWS_ENDPOINT_URL
              value: "http://seaweedfs-s3.kubeflow.svc.cluster.local:8333"
            - name: POSTGRES_PASSWORD
              value: "kubeflow2026"  # Update if different
          command: ["/bin/bash"]
          args:
            - "-c"
            - |
              pip install --upgrade pip &&
              pip install mlflow==3.12.0 boto3 psycopg2-binary &&
              mlflow server \
                --host 0.0.0.0 \
                --port 5000 \
                --default-artifact-root s3://mlflow-artifacts \
                --backend-store-uri postgresql+psycopg2://postgres:kubeflow2026@postgres-release-postgresql.postgres.svc.cluster.local:5432/postgres
          ports:
            - containerPort: 5000
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
```

Apply the deployment:

```bash
kubectl apply -f mlflow-deployment.yaml

# Wait for pod to start
kubectl wait --for=condition=Ready pod -n mlflow -l app=mlflow --timeout=120s
kubectl get pods -n mlflow
```

### 2d: Create MLflow Service

Save as `mlflow-service.yaml`:

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
  type: ClusterIP
```

Apply:

```bash
kubectl apply -f mlflow-service.yaml
kubectl get svc -n mlflow
```

### 2e: Access MLflow UI

```bash
# Port-forward MLflow
kubectl port-forward -n mlflow svc/mlflow-service 5000:5000 &

# Open browser: http://localhost:5000
echo "MLflow UI: http://localhost:5000"
```

---

## Phase 3: Redis Online Feature Store

Redis serves as the online feature store for Feast. Deploy via Helm.

### 3a: Add Helm repo and create namespace

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update bitnami

kubectl create namespace redis
```

### 3b: Install Redis

```bash
helm install redis-deployment bitnami/redis \
  --namespace redis \
  --wait

# Verify
kubectl get deployment -n redis
kubectl get pods -n redis  # Should show redis-deployment-master-0 Running
```

### 3c: Retrieve Redis Password

```bash
export REDIS_PASSWORD=$(
  kubectl get secret \
    --namespace redis \
    redis-deployment \
    -o jsonpath="{.data.redis-password}" \
  | base64 -d
)

echo "Redis Password: $REDIS_PASSWORD"
```

**Redis connection details:**
```
Host: redis-deployment-master.redis.svc.cluster.local
Port: 6379
Password: $REDIS_PASSWORD
```

Use these in `feature_store.yaml` online store configuration for Feast.

---

## Phase 4: BentoML/Yatai Model Serving

Yatai is the deployment and operations platform for BentoML services on K8s.

### 4a: Add Helm repo and create namespace

```bash
helm repo add bentoml https://bentoml.github.io/helm-charts
helm repo update bentoml

kubectl create namespace yatai-system
```

### 4b: Install Yatai

```bash
helm install yatai bentoml/yatai \
  --namespace yatai-system \
  --set ingress.enabled=false \
  --set service.type=LoadBalancer \
  --create-namespace \
  --wait

# Verify
kubectl get pods -n yatai-system
```

### 4c: Get Yatai Initialization Token

On first install, you need to create an admin account:

```bash
# Get initialization token
export YATAI_INITIALIZATION_TOKEN=$(
  kubectl get secret yatai-env \
    --namespace yatai-system \
    -o jsonpath="{.data.YATAI_INITIALIZATION_TOKEN}" \
  | base64 --decode
)

# Get Yatai service IP/hostname
export SERVICE_IP=$(
  kubectl get svc \
    --namespace yatai-system \
    yatai \
    --template "{{ range (index .status.loadBalancer.ingress 0) }}{{.}}{{ end }}"
)

# If LoadBalancer not available, use port-forward instead:
kubectl port-forward -n yatai-system svc/yatai 5000:80 &
SERVICE_IP="localhost:5000"

echo "Create admin account at:"
echo "http://$SERVICE_IP/setup?token=$YATAI_INITIALIZATION_TOKEN"
```

### 4d: Create Admin Account

1. Open the URL from above in your browser
2. Enter Name, Email, Password
3. Create admin account

After login, you can deploy BentoML services to K8s via Yatai.

---

## Phase 5: Evidently UI Data Drift Monitoring

Evidently provides data drift detection and visualization. Set up custom Docker image.

### 5a: Create Evidently Docker Image

Create `Dockerfile.evidently`:

```dockerfile
FROM python:3.11-slim-bullseye
WORKDIR /app
RUN apt-get update && \
    apt-get install --no-install-recommends -y \
    build-essential \
    && apt-get clean && rm -rf /tmp/* /var/tmp/*

RUN pip install --upgrade pip && \
    pip install evidently==0.4.30

ENV PYTHONPATH "/app"
EXPOSE 8000

ENTRYPOINT ["evidently", "ui"]
```

Build and push to Docker Hub (or local registry):

```bash
# Build
docker build -f Dockerfile.evidently -t your-docker-hub/evidently-ui:latest .

# Push (optional, can use local image if testing)
docker push your-docker-hub/evidently-ui:latest
```

### 5b: Create Evidently Namespace and Deployment

Save as `evidently-namespace.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: evidently
```

Save as `evidently-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: evidently-ui
  namespace: evidently
  labels:
    app: evidently-ui
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
        - name: evidently-ui
          image: your-docker-hub/evidently-ui:latest  # Change to your image
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8000
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          volumeMounts:
            - name: evidently-data
              mountPath: /app/data
      volumes:
        - name: evidently-data
          emptyDir: {}
```

Apply:

```bash
kubectl apply -f evidently-namespace.yaml
kubectl apply -f evidently-deployment.yaml

# Wait for pod
kubectl wait --for=condition=Ready pod -n evidently -l app=evidently-ui --timeout=60s
kubectl get pods -n evidently
```

### 5c: Create Evidently Service

Save as `evidently-service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: evidently-ui
  namespace: evidently
  labels:
    app: evidently-ui
spec:
  ports:
    - name: "8000"
      port: 8000
      protocol: TCP
      targetPort: 8000
  selector:
    app: evidently-ui
  type: ClusterIP
```

Apply:

```bash
kubectl apply -f evidently-service.yaml
kubectl get svc -n evidently
```

### 5d: Access Evidently UI

```bash
# Port-forward Evidently
kubectl port-forward -n evidently svc/evidently-ui 8000:8000 &

# Open browser: http://localhost:8000
echo "Evidently UI: http://localhost:8000"
```

---

## Verification Checklist

Run after all components are deployed:

```bash
#!/bin/bash
echo "=== Post-Install Verification ==="

# Check namespaces
echo ""
echo "✓ Namespaces created:"
kubectl get ns | grep -E "postgres|mlflow|redis|yatai-system|evidently"

# Check all pods running
echo ""
echo "✓ Pod status:"
kubectl get pods -n postgres
kubectl get pods -n mlflow
kubectl get pods -n redis
kubectl get pods -n yatai-system
kubectl get pods -n evidently

# Check services
echo ""
echo "✓ Services:"
kubectl get svc -n mlflow
kubectl get svc -n redis
kubectl get svc -n yatai-system
kubectl get svc -n evidently

# Test MLflow connectivity
echo ""
echo "✓ MLflow API test:"
kubectl port-forward -n mlflow svc/mlflow-service 5000:5000 >/dev/null 2>&1 &
sleep 2
curl -s http://localhost:5000/api/2.0/experiments/list | jq . && echo "✓ MLflow responsive" || echo "✗ MLflow not responding"
kill %1 2>/dev/null

echo ""
echo "=== All components deployed ==="
```

---

## Access URLs

After deployment, access components via port-forward:

```bash
# MLflow (experiment tracking + model registry)
kubectl port-forward -n mlflow svc/mlflow-service 5000:5000 &
# http://localhost:5000

# Yatai (model serving deployment)
kubectl port-forward -n yatai-system svc/yatai 8080:80 &
# http://localhost:8080

# Evidently (data drift monitoring)
kubectl port-forward -n evidently svc/evidently-ui 8000:8000 &
# http://localhost:8000

# Kubeflow (ML platform - from bootstrap)
kubectl port-forward -n kubeflow svc/centraldashboard 8888:80 &
# http://localhost:8888

# KFP (pipeline UI - from bootstrap)
kubectl port-forward -n kubeflow svc/ml-pipeline 3000:8888 &
# http://localhost:3000
```

---

## Configuration Reference

**Versions:**
- MLflow: 3.12.0
- Redis: Latest (Helm bitnami chart)
- BentoML/Yatai: Latest (Helm chart)
- Evidently: 0.4.30
- Helm: 4+

**Storage:**
- Postgres Backend: `postgres-release-postgresql.postgres.svc.cluster.local:5432`
- MLflow Artifacts: SeaweedFS S3 gateway at `seaweedfs-s3.kubeflow.svc.cluster.local:8333`
- Bucket: `mlpipeline` (created during Kubeflow bootstrap), `mlflow-artifacts` (created in Phase 2)

**Credentials:**
- Postgres User: postgres, Password: kubeflow2026 (set in Phase 1)
- SeaweedFS S3: Access Key: minio, Secret: minio123 (from Kubeflow deployment)
- Redis: Generated by Helm (retrieved in Phase 3)

---

## Troubleshooting

| Issue | Symptom | Fix |
|-------|---------|-----|
| **MLflow pod CrashLoopBackOff** | Logs show connection refused to Postgres | Verify Postgres is Running (`kubectl get pods -n postgres`), check password in deployment env vars |
| **MLflow can't write to S3** | 403 Forbidden when uploading artifacts | Verify mlflow-artifacts bucket exists, check S3 credentials (minio/minio123) |
| **Yatai initialization fails** | Token not found in secret | Wait longer for Yatai pods to stabilize (up to 2 minutes), then retry token retrieval |
| **Redis connection timeout** | Feast can't connect to Redis | Verify Redis pod Running, check hostname: `redis-deployment-master.redis.svc.cluster.local` |
| **Evidently UI blank** | Port-forward works but page empty | Check pod logs: `kubectl logs -n evidently -l app=evidently-ui` |
| **SeaweedFS bucket not accessible** | MLflow can't create objects | Verify bucket name is `mlflow-artifacts` (not `mlpipeline`), check S3 endpoint URL |

---

## Cleanup (Optional)

```bash
# Remove all post-install components
kubectl delete namespace postgres mlflow redis yatai-system evidently

# Or selectively:
kubectl delete -f mlflow-deployment.yaml -f mlflow-service.yaml -n mlflow
helm uninstall postgres-release -n postgres
helm uninstall redis-deployment -n redis
helm uninstall yatai -n yatai-system
```

---

## Next Steps

After all components are running:

1. **Configure MLflow Tracking** in your ML pipelines:
   ```python
   import mlflow
   mlflow.set_tracking_uri("http://localhost:5000")
   mlflow.set_experiment("my-experiment")
   ```

2. **Set up Feast** with Redis as online store (see book Chapter 9)

3. **Build BentoML services** and deploy via Yatai

4. **Configure Evidently** for production data drift monitoring (see book Chapter 10)

5. **Integrate with Kubeflow Pipelines** for end-to-end MLOps workflows
