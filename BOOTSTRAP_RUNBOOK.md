# Kubeflow ArgoCD Bootstrap Runbook

**Version:** 26.03 | **k3s + Flannel + Istio** | **Date:** 2026-06-04

---

## Phase 0: Pre-Flight Checks

**Run this verification before anything else:**

```bash
#!/bin/bash
set -e

echo "=== Pre-Flight Verification ==="

# Check Docker
if docker --version >/dev/null 2>&1; then
  echo "✓ Docker: $(docker --version)"
else
  echo "✗ Docker not found. Install: sudo apt install -y docker.io"
  exit 1
fi

# Check k3s NOT installed
if kubectl get nodes 2>&1 | grep -q "unable to connect\|connection refused"; then
  echo "✓ k3s: Not installed (good, ready for fresh install)"
else
  echo "✗ k3s appears to be running. Run cleanup first (see Cleanup section)"
  exit 1
fi

# Check git clone exists
if [ -d ".git" ]; then
  echo "✓ Workspace: Repo cloned"
else
  echo "✗ Not in repo directory. Run: git clone https://github.com/DurojaiyeAbisoye/kubeflow-argocd.git && cd kubeflow-argo-manifests"
  exit 1
fi

# Check for required tools (will be installed in Phase 1 if missing)
echo ""
echo "=== Tool Versions (to be confirmed in Phase 1) ==="
kubectl version --client 2>&1 | grep "Client Version" || echo "⚠ kubectl not found (will install)"
kustomize version 2>&1 || echo "⚠ kustomize not found (will install)"
argocd version --client 2>&1 | head -1 || echo "⚠ argocd not found (will install)"
yq --version 2>&1 || echo "⚠ yq not found (will install)"

echo ""
echo "✓ Pre-flight checks passed. Proceed to Phase 1."
```

**Expected versions (current environment):**
- kubectl: v1.36.0 (requirement: ≥ v1.28)
- Kustomize: v5.8.1 (requirement: ≥ v5.0)
- ArgoCD CLI: v3.3.9 (requirement: ≥ v2.8)
- yq: v4.53.2 (requirement: ≥ v4.4)
- Docker: 29.4.1 (requirement: installed and running)

---

## Phase 1: Tool Installation & Setup

### 1a: Verify/Install Required Tools

Run only if missing from pre-flight check:

**kubectl (v1.36.0+)**
```bash
# Check if installed
kubectl version --client || {
  echo "Installing kubectl v1.36.0..."
  curl -LO "https://dl.k8s.io/release/v1.36.0/bin/linux/amd64/kubectl"
  chmod +x kubectl && sudo mv kubectl /usr/local/bin/
  kubectl version --client
}
```

**Kustomize (v5.8.1+)**
```bash
# Check if installed
kustomize version | grep -q "5\.[4-9]\|6\." || {
  echo "Installing Kustomize v5.8.1..."
  curl -sLO https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv5.8.1/kustomize_v5.8.1_linux_amd64.tar.gz
  tar xzf kustomize_v5.8.1_linux_amd64.tar.gz
  sudo mv kustomize /usr/local/bin/
  rm kustomize_v5.8.1_linux_amd64.tar.gz
  kustomize version
}
```

**ArgoCD CLI (v3.3.9+)**
```bash
# Check if installed
argocd version --client 2>&1 | head -1 || {
  echo "Installing ArgoCD CLI..."
  curl -sSL -o argocd https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
  chmod +x argocd && sudo mv argocd /usr/local/bin/
  argocd version --client
}
```

**yq (v4.44.1+)**
```bash
# Check if installed
yq --version | grep -q "v4\." || {
  echo "Installing yq v4.53.2..."
  sudo wget https://github.com/mikefarah/yq/releases/download/v4.53.2/yq_linux_amd64 \
    -O /usr/local/bin/yq && sudo chmod +x /usr/local/bin/yq
  yq --version
}
```

---

### 1b: Install Fresh k3s

**CRITICAL:** Traefik must be disabled or it will fight with Istio over ingress ports.

```bash
# Install k3s with traefik disabled
curl -sfL https://get.k3s.io | K3S_KUBECONFIG_MODE="644" sh -s - --disable traefik
```

**Verify:**
```bash
# Should show "Ready" status
kubectl get nodes

# Should return nothing (traefik must NOT be installed)
kubectl get deployment -n kube-system traefik 2>&1 | grep -i "notfound"
```

---

### 1c: (Optional) Configure Docker Hub Credentials

**Skip this unless you see `429 Too Many Requests` errors later.** Unauthenticated Docker Hub pulls are rate-limited. SeaweedFS, PostgreSQL, and Grafana pull from Docker Hub.

```bash
# Generate token at: hub.docker.com → Account Settings → Security → Access Tokens
# Use token (not your password)

sudo mkdir -p /etc/rancher/k3s
sudo tee /etc/rancher/k3s/registries.yaml << EOF
configs:
  "registry-1.docker.io":
    auth:
      username: YOUR_DOCKERHUB_USERNAME
      password: YOUR_DOCKERHUB_TOKEN
EOF

# Restart k3s to pick up the config
sudo systemctl restart k3s
kubectl rollout status deployment coredns -n kube-system --timeout=60s
```

---

### 1d: Fix kubeconfig Ownership

k3s writes kubeconfig owned by root. Fix to avoid needing sudo for every kubectl command.

```bash
# Copy to user's kubeconfig and fix permissions
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config
chmod 600 ~/.kube/config

# Verify
kubectl get nodes  # Should work WITHOUT sudo
```

---

### 1e: Fix CoreDNS for External Image Pulls

k3s CoreDNS may not resolve external hostnames for image pulls. Apply manual patch.

```bash
# Patch CoreDNS to use Google's nameserver
kubectl patch configmap coredns -n kube-system --type=merge -p '{
  "data": {
    "Corefile": ".:53 {\n    errors\n    health\n    ready\n    kubernetes cluster.local in-addr.arpa ip6.arpa {\n      pods insecure\n      fallthrough in-addr.arpa ip6.arpa\n    }\n    prometheus :9153\n    forward . 8.8.8.8\n    cache 30\n    loop\n    reload\n  }\n"
  }
}'

# Restart CoreDNS
kubectl rollout restart deployment coredns -n kube-system
kubectl rollout status deployment coredns -n kube-system

# Verify
kubectl get pod -n kube-system -l k8s-app=kube-dns  # Should be Running
```

---

## Phase 2: Deploy ArgoCD Control Plane

Build and deploy ArgoCD with custom Kustomize 5.8.1.

```bash
# Build and apply ArgoCD manifests (includes custom kustomize init container)
kustomize build argocd/ | kubectl apply -f -

# Wait for ArgoCD to reach Running state
kubectl wait --for=condition=Ready pod -n argocd -l app.kubernetes.io/name=argocd-server --timeout=300s
kubectl get pods -n argocd  # All pods should be Running

# Wait for ArgoCD API to be ready
sleep 5
kubectl -n argocd port-forward svc/argocd-server 8080:443 &
sleep 3
curl -k https://localhost:8080/api/version  # Should return JSON
kill %1 2>/dev/null
```

---

## Phase 3: Register Git Repository with ArgoCD

ArgoCD needs credentials to the repo before syncing Applications.

```bash
# Get initial ArgoCD admin password
ARGOCD_PASSWORD=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)

# Forward to ArgoCD API
kubectl -n argocd port-forward svc/argocd-server 8080:443 >/dev/null 2>&1 &
ARGOCD_PORT_FORWARD_PID=$!
sleep 2

# Register repository (public repo, no auth needed)
argocd repo add https://github.com/DurojaiyeAbisoye/kubeflow-argocd.git \
  --insecure-skip-server-verification \
  --server localhost:8080 \
  --username admin \
  --password "$ARGOCD_PASSWORD" \
  --grpc-web

# Verify repo is registered
argocd repo list --server localhost:8080 --grpc-web | grep "kubeflow-argocd"

# Cleanup port-forward
kill $ARGOCD_PORT_FORWARD_PID 2>/dev/null
```

**For private repos, add:**
```bash
  --username <github-username> \
  --password <github-token>
```

---

## Phase 4: Deploy Kubeflow Applications via ArgoCD

Apply the app-of-apps manifest. This triggers ArgoCD to read all 25 Applications and deploy them in wave order.

```bash
# Apply kubeflow.yaml (app-of-apps pattern)
kubectl apply -f kubeflow.yaml

# Monitor sync progress (waves 1-6 will deploy in order)
# Wave 1: cert-manager
# Wave 2: istio
# Wave 3: kubeflow-ns, kubeflow-roles, knative
# Wave 4: oauth2-proxy, metacontroller
# Wave 5: profiles, pipeline
# Wave 6: remaining applications

# Watch ArgoCD UI or CLI
kubectl -n argocd port-forward svc/argocd-server 8080:443 &
# Open browser to https://localhost:8080 (admin / <ARGOCD_PASSWORD>)

# Or use CLI
argocd app list  # Monitor Application status
argocd app sync  # Manually trigger sync if needed
```

---

## Phase 5: Wait for Wave Completion

Monitor critical pods to confirm each wave succeeds before moving to next.

```bash
# Wave 1: cert-manager (should reach Running after ~30s)
kubectl wait --for=condition=Ready pod -n cert-manager -l app=cert-manager --timeout=60s

# Wave 2: Istio (can take 2-3 minutes)
kubectl wait --for=condition=Ready pod -n istio-system -l app=istiod --timeout=180s

# Wave 3: Kubeflow namespace and labels
kubectl get ns kubeflow kubeflow-system
kubectl get ns kubeflow -o jsonpath='{.metadata.labels}' | grep -q 'istio-injection'

# Wave 4: Metacontroller (required before KFP)
kubectl wait --for=condition=Ready pod -n metacontroller -l app=metacontroller --timeout=60s

# Wave 6: KFP, KServe, other workloads
kubectl wait --for=condition=Ready pod -n kubeflow -l app=ml-pipeline --timeout=300s
```

---

## Phase 6: Create SeaweedFS mlpipeline Bucket

KFP expects this bucket to exist. SeaweedFS starts empty — this step creates it manually.

```bash
# Port-forward to SeaweedFS S3 gateway
kubectl port-forward -n kubeflow svc/seaweedfs-s3 9000:8333 &
S3_PID=$!
sleep 2

# Use AWS CLI to create bucket
aws s3api create-bucket \
  --bucket mlpipeline \
  --endpoint-url http://localhost:9000 \
  --access-key-id minio \
  --secret-access-key minio123 \
  --region us-east-1

# Verify
aws s3 ls --endpoint-url http://localhost:9000 \
  --access-key-id minio \
  --secret-access-key minio123

# Cleanup
kill $S3_PID 2>/dev/null
```

---

## Phase 7: Verify Platform Health

```bash
# Check all namespaces deployed
kubectl get ns | grep -E 'kubeflow|istio|knative|cert-manager'

# Check critical pods
kubectl get pods -n cert-manager
kubectl get pods -n istio-system
kubectl get pods -n kubeflow | head -20

# Test Kubeflow Dashboard access (requires Istio Ingress)
kubectl port-forward -n kubeflow svc/centraldashboard 8888:80 &
# Open browser to http://localhost:8888

# Test KFP API
kubectl port-forward -n kubeflow svc/ml-pipeline 3000:8888 &
# Open browser to http://localhost:3000
```

---

## Phase 8: Run Smoke Test Pipeline

Validates KFP can compile, execute, and store artifacts.

```bash
# Port-forward KFP API
kubectl port-forward -n kubeflow svc/ml-pipeline 3000:8888 &
sleep 2

# Run test pipeline
cd scripts/
python3 hello-world-pipeline.py

# Check output:
# - Pipeline compiles without errors ✓
# - Execution succeeds ✓
# - KFP UI shows run ✓
# - Artifacts stored in mlpipeline bucket ✓
```

---

## Known Issues & Fixes

| Issue | Symptom | Fix |
|-------|---------|-----|
| **Traefik conflict** | Port 80/443 owned by both Traefik + Istio | `--disable traefik` at install time |
| **ArgoCD sync fails** | Kustomize errors or "version too old" | Custom init container installs v5.8.1 |
| **repo not registered** | All Applications show "Unknown" status | `argocd repo add` in Phase 5 |
| **cert-manager webhook timeout** | Wave 2 Istio install fails | Wait for cert-manager webhook Ready, manually sync wave 2 |
| **kubeconfig permission denied** | Every kubectl needs sudo | Phase 2 fixes ownership |
| **KFP artifacts missing** | Pipelines run but outputs lost | Phase 8 creates mlpipeline bucket |
| **Pods stuck in Pending** | PSS violation warnings | Check namespace labels have `pod-security.kubernetes.io/enforce: baseline` |
| **Istio sidecar injection not working** | Auth 403 errors | Verify kubeflow namespace has `istio-injection: enabled` label |
| **Istio CNI DaemonSet fails** | Istio CNI pod logs show socket not found | k3s overlay sets `CONTAINER_RUNTIME_ENDPOINT=/run/k3s/containerd/containerd.sock` |

---

## Cleanup (Uninstall)

```bash
# Remove all Kubeflow Applications
kubectl delete -f kubeflow.yaml

# Remove ArgoCD
kustomize build argocd/ | kubectl delete -f -

# Uninstall k3s
/usr/local/bin/k3s-uninstall.sh

# Clean system state
sudo rm -rf /etc/rancher /var/lib/rancher /run/k3s /run/flannel
sudo rm -rf /etc/cni /var/lib/cni /opt/cni
sudo ip link delete cni0 2>/dev/null || true
sudo ip link delete flannel.1 2>/dev/null || true
sudo ip link delete flannel-v6.1 2>/dev/null || true

# Verify cleanup
ls -la /etc/rancher 2>&1  # Should be "No such file or directory"
```

---

## Troubleshooting Checklist

```bash
# ArgoCD Applications stuck in Syncing?
kubectl get applications -n argocd  # Check status column
argocd app describe <app-name>     # Detailed error message
argocd app logs <app-name>         # Application logs

# Pod pending or CrashLoopBackOff?
kubectl describe pod <pod-name> -n <namespace>  # Check events
kubectl logs <pod-name> -n <namespace>          # Check logs
kubectl logs <pod-name> -n <namespace> --previous  # Previous crash

# Networking issues (pods can't communicate)?
kubectl get ns kubeflow -o yaml | grep istio-injection  # Must be "enabled"
kubectl get networkpolicies -n kubeflow  # Check policies exist

# Image pull errors?
kubectl get events -n kubeflow --sort-by='.lastTimestamp' | tail -20
# Check CoreDNS in Phase 3 is applied correctly

# Check if Kustomize 5.x installed in ArgoCD?
kubectl exec -it -n argocd deployment/argocd-repo-server -- which kustomize
# Should return /usr/local/bin/kustomize
```

---

## Success Criteria

✓ All 25 ArgoCD Applications show "Synced" status  
✓ All pods in kubeflow, istio-system, cert-manager, knative-serving are Running  
✓ Dashboard accessible at http://localhost:8888  
✓ KFP API accessible at http://localhost:3000  
✓ Smoke test pipeline completes successfully  
✓ Artifacts visible in KFP UI  
✓ No PSS or networking errors in pod events
