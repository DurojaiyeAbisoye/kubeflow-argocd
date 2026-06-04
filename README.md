# Kubeflow ArgoCD MLOps Platform

A complete, production-ready MLOps stack deployed on k3s using GitOps with ArgoCD.

## Overview

This repository contains Kubernetes manifests for deploying a comprehensive machine learning platform on k3s. It uses ArgoCD as the GitOps orchestrator to manage 25 applications across 6 deployment waves, ensuring proper sequencing and dependency management.

**Platform includes:**
- **Kubeflow** — ML model development, training, and serving
- **Istio** — Service mesh with mTLS and authorization policies
- **KFP (Kubeflow Pipelines)** — ML workflow orchestration with artifact storage
- **KServe** — Model inference serving with raw deployment support
- **Jupyter** — Interactive notebooks for data exploration
- **Katib** — Hyperparameter tuning
- **TensorBoard** — Model visualization
- **Spark** — Distributed data processing
- **Knative** — Serverless workloads
- **Cert-Manager** — Automatic certificate management
- **SeaweedFS** — Distributed artifact storage with S3 gateway
- **MLflow** (post-install) — Experiment tracking and model registry
- **Redis** (post-install) — Feature store online layer
- **BentoML/Yatai** (post-install) — Model serving deployment platform
- **Evidently** (post-install) — Data drift monitoring

---

## Quick Start

### Prerequisites

- Linux or Mac system
- Docker installed and running
- 4+ CPU cores, 12+ GB RAM, 50+ GB disk space (100 GB recommended)
- k3s will be installed fresh (with traefik disabled)

### Installation Steps

**1. Bootstrap Kubeflow on k3s**

Follow [BOOTSTRAP_RUNBOOK.md](BOOTSTRAP_RUNBOOK.md) for complete step-by-step instructions (Phases 0-8):

```bash
# Phase 0: Pre-flight checks
# Phase 1: Install k3s, tools, and fix configuration
# Phase 2: Deploy ArgoCD control plane
# Phase 3: Register Git repository
# Phase 4-8: Deploy Kubeflow applications via ArgoCD
```

Expected time: **30-45 minutes**

**2. (Optional) Deploy MLOps Components**

After Kubeflow is stable, follow [POST_INSTALL_RUNBOOK.md](POST_INSTALL_RUNBOOK.md) to add:
- PostgreSQL backend
- MLflow (experiment tracking)
- Redis (feature store)
- Yatai (model serving platform)
- Evidently UI (drift monitoring)

Expected time: **15-20 minutes**

---

## Repository Structure

```
kubeflow-argo-manifests/
├── README.md                          # This file
├── BOOTSTRAP_RUNBOOK.md               # Step-by-step Kubeflow installation
├── POST_INSTALL_RUNBOOK.md            # MLflow, Redis, Yatai, Evidently setup
├── kubeflow.yaml                      # App-of-apps: triggers all 25 ArgoCD Applications
├── kustomization.yaml                 # Root kustomization for the repo
│
├── argocd/                            # ArgoCD control plane
│   ├── kustomization.yaml
│   ├── namespace.yaml
│   └── configmap-patch.yaml          # Kustomize v5.8.1 path configuration
│
├── argocd-apps/                       # 25 ArgoCD Application manifests
│   ├── cert-manager.yaml              # Wave 1: Certificate generation
│   ├── istio.yaml                     # Wave 2: Service mesh
│   ├── kubeflow-ns.yaml               # Wave 3: Namespaces + labels
│   ├── knative.yaml                   # Wave 3: Serverless
│   ├── oauth2-proxy.yaml              # Wave 4: Authentication
│   ├── metacontroller.yaml            # Wave 4: Required for KFP
│   ├── profiles.yaml                  # Wave 5: User namespaces
│   ├── pipeline.yaml                  # Wave 5: KFP with SeaweedFS
│   ├── kserve.yaml                    # Wave 6: Model serving
│   ├── jupyter.yaml                   # Wave 6: Notebooks
│   ├── katib.yaml                     # Wave 6: Hyperparameter tuning
│   ├── tensorboard.yaml               # Wave 6: Visualization
│   ├── trainer.yaml                   # Wave 6: Distributed training
│   ├── training-operator.yaml         # Wave 6: PyTorch/TF training jobs
│   └── ... (13 more applications)
│
├── applications/                      # Individual component configs
│   ├── admission-webhook/
│   ├── centraldashboard/
│   ├── jupyter/
│   ├── katib/
│   ├── kserve/
│   │   └── kustomization.yaml        # KServe with deployDefaults: deployRaw=true
│   ├── pipeline/                      # KFP with SeaweedFS S3 backend
│   ├── profiles/
│   ├── spark/
│   ├── tensorboard/
│   ├── trainer/
│   ├── training-operator/
│   └── ... (more components)
│
├── common/                            # Shared platform components
│   ├── cert-manager/
│   ├── dex/                           # OIDC provider
│   ├── istio/
│   │   └── istio-install/overlays/k3s/    # k3s-specific CNI patch
│   ├── knative/
│   ├── kubeflow-namespace/            # Namespace with PSS labels
│   ├── kubeflow-roles/
│   ├── oauth2-proxy/
│   └── user-namespace/
│
└── scripts/
    ├── hello-world-pipeline.py        # KFP v2 smoke test
    └── README.md
```

---

## Architecture

### Deployment Waves

ArgoCD synchronizes applications in 6 sequential waves to handle dependencies:

```
Wave 1 (Dependencies)
├── cert-manager          ← Generates TLS certificates

Wave 2 (Networking)
├── istio                 ← Service mesh with mTLS

Wave 3 (Platform)
├── kubeflow-ns          ← Namespaces with PSS labels + RBAC
├── kubeflow-roles
├── knative              ← Serverless foundation

Wave 4 (Authentication)
├── oauth2-proxy         ← OIDC integration
├── metacontroller       ← Required by KFP profile controller

Wave 5 (Core Services)
├── profiles             ← User namespaces
├── pipeline             ← KFP with SeaweedFS S3 artifacts

Wave 6 (Applications)
├── admission-webhook, centraldashboard, jupyter
├── katib, kserve, model-registry, models-web-app
├── notebook-controller, tensorboard, tensorboards-web-app
├── trainer, training-operator, volumes-web-app
└── spark-operator, pvcviewer-controller
```

### Key Technologies

| Component | Role | k3s Integration |
|-----------|------|-----------------|
| **k3s** | Lightweight K8s distribution | Flannel CNI, traefik disabled, containerd at `/run/k3s/containerd/containerd.sock` |
| **ArgoCD** | GitOps orchestration | Repo-server with Kustomize 5.8.1 init container |
| **Istio** | Service mesh + ingress | CNI patch for k3s containerd socket path |
| **Kustomize** | Configuration management | v5.8.1 pinned in ArgoCD, supports remote base overlays |
| **Kubeflow** | ML platform | Baseline PSS enforcement, SeaweedFS S3 backend |
| **SeaweedFS** | Object storage | S3 API gateway for MLOps artifact storage |

---

## Critical Configuration

### Pod Security Standards

**kubeflow namespace:** Baseline (allows Kubeflow workloads)  
**cert-manager, istio-system, knative-serving:** Restricted (security hardened)  
**user namespaces:** Baseline with network policies

Apply via namespace labels (see [common/kubeflow-namespace/base](common/kubeflow-namespace/base)):

```yaml
pod-security.kubernetes.io/enforce: baseline
pod-security.kubernetes.io/warn: baseline
```

### KServe RawDeployment Mode

KServe is configured for raw (direct) deployment instead of serverless:

```yaml
# applications/kserve/kserve/kustomization.yaml
deployDefaults: |-
  {
    "deployRaw": true
  }
```

This allows Knative Serving to be optional while supporting model inference.

### Istio CNI Socket Path (k3s-specific)

k3s uses non-standard containerd socket: `/run/k3s/containerd/containerd.sock`

Configured in [common/istio/istio-install/overlays/k3s/kustomization.yaml](common/istio/istio-install/overlays/k3s/kustomization.yaml):

```yaml
env:
  - name: CONTAINER_RUNTIME_ENDPOINT
    value: unix:///run/k3s/containerd/containerd.sock
```

---

## Known Pitfalls & Fixes

See [BOOTSTRAP_RUNBOOK.md](BOOTSTRAP_RUNBOOK.md#known-issues--fixes) for complete troubleshooting guide.

**Most critical:**
- ❌ **Traefik + Istio conflict** → Use `--disable traefik` at install time
- ❌ **ArgoCD repo not registered** → Run `argocd repo add` before applying kubeflow.yaml
- ❌ **cert-manager webhook timeout** → Wave timing handles this; if issues, manually retry wave 2
- ❌ **kubeconfig owned by root** → Fix permissions in Phase 1 (Phase 2 in bootstrap runbook)

---

## Testing

### Smoke Test

After Kubeflow bootstrap (Phase 8 complete):

```bash
# 1. Port-forward KFP
kubectl port-forward -n kubeflow svc/ml-pipeline 3000:8888 &

# 2. Run smoke test pipeline
cd scripts/
python3 hello-world-pipeline.py

# 3. Verify in KFP UI: http://localhost:3000
```

See [scripts/README.md](scripts/README.md) for details.

### Health Checks

```bash
# All namespaces deployed?
kubectl get ns | grep -E 'kubeflow|istio|knative|cert-manager'

# Critical pods Running?
kubectl get pods -n kubeflow | grep -E 'ml-pipeline|centraldashboard'
kubectl get pods -n istio-system
kubectl get pods -n cert-manager

# ArgoCD showing all apps Synced?
kubectl -n argocd port-forward svc/argocd-server 8080:443 &
# Open https://localhost:8080 (admin / password from bootstrap)
```

---

## Configuration Customization

### Change Repository URL

Update all 24 argocd-apps/*.yaml files:

```bash
# Option 1: Global search-replace
grep -r "https://github.com/DurojaiyeAbisoye/kubeflow-argocd.git" argocd-apps/ \
  | sed 's/:.*//g' | xargs -I {} sed -i 's|YOUR_URL|https://github.com/your-org/your-repo.git|g' {}

# Option 2: Manual edit key files
# argocd-apps/{cert-manager,istio,kubeflow-ns,etc.}.yaml
# Change: repoURL: https://github.com/YOUR_REPO/kubeflow-argocd.git
```

### Adjust Resource Limits

Edit individual application manifests in `applications/*/`:

```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
    cpu: "500m"
```

### Extend with Custom Applications

Add new ArgoCD Application in `argocd-apps/`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-custom-app
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "6"  # After core apps
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/your-repo.git
    targetRevision: main
    path: path/to/manifests
  destination:
    server: https://kubernetes.default.svc
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

---

## Uninstall & Cleanup

```bash
# Remove all Kubeflow Applications
kubectl delete -f kubeflow.yaml

# Remove ArgoCD
kustomize build argocd/ | kubectl delete -f -

# Uninstall k3s
/usr/local/bin/k3s-uninstall.sh

# Clean system state (including CNI, cgroup configuration)
sudo rm -rf /etc/rancher /var/lib/rancher /run/k3s /run/flannel
sudo rm -rf /etc/cni /var/lib/cni /opt/cni
sudo ip link delete cni0 2>/dev/null || true
sudo ip link delete flannel.1 2>/dev/null || true

# Verify cleanup
ls -la /etc/rancher 2>&1  # Should be "No such file or directory"
```

---

## Versions

- **Kubeflow**: 1.7+ manifests (26.03 release)
- **k3s**: Latest stable with traefik disabled
- **ArgoCD**: v3.3.9+ (with Kustomize 5.8.1 init container)
- **Istio**: Latest (service mesh)
- **Kubernetes**: 1.28+ (via k3s)
- **Kustomize**: v5.8.1+ (required for manifest patching)
- **kubectl**: v1.36.0+ (tested)
- **yq**: v4.53.2+ (YAML processing)

**Post-install (optional):**
- **MLflow**: 3.12.0
- **Redis**: Latest (Helm bitnami/redis chart)
- **BentoML/Yatai**: Latest (Helm bentoml/yatai chart)
- **Evidently**: 0.4.30

---

## Documentation

- **[BOOTSTRAP_RUNBOOK.md](BOOTSTRAP_RUNBOOK.md)** — Step-by-step Kubeflow installation (Phases 0-8)
- **[POST_INSTALL_RUNBOOK.md](POST_INSTALL_RUNBOOK.md)** — MLflow, Redis, Yatai, Evidently setup
- **[scripts/README.md](scripts/README.md)** — KFP smoke test pipeline instructions

---

## Support & Troubleshooting

### Common Issues

1. **kubectl: connection refused** → k3s not running or not installed
2. **ArgoCD applications stuck in Syncing** → Check repo is registered (`argocd repo list`)
3. **Pods pending/CrashLoopBackOff** → Check namespace PSS labels, events (`kubectl describe pod`)
4. **Istio sidecar not injected** → Verify `istio-injection: enabled` label on namespace
5. **MLflow can't write artifacts** → Check SeaweedFS bucket exists and S3 credentials

See full troubleshooting in [BOOTSTRAP_RUNBOOK.md](BOOTSTRAP_RUNBOOK.md#troubleshooting-checklist).

---

## Contributing

To extend or customize this platform:

1. Fork or clone this repository
2. Create feature branch: `git checkout -b feature/my-feature`
3. Update manifests in `applications/` or `common/`
4. Add new ArgoCD Application in `argocd-apps/`
5. Test: `kustomize build <path>` (all manifests must validate)
6. Commit with clear message referencing the change
7. Push and create PR

---

## License

These manifests are based on the Kubeflow 2026 03 release and provided based on a similar repo in the O'Reilly "Machine Learning Platform Engineering" book.
---

## References

- **Kubeflow Docs**: https://www.kubeflow.org/docs/
- **ArgoCD Docs**: https://argo-cd.readthedocs.io/
- **k3s Docs**: https://docs.k3s.io/
- **Istio Docs**: https://istio.io/latest/docs/
- **Kustomize Docs**: https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/

---

## Quick Links

**After bootstrap completes, access:**

| Component | URL | Command |
|-----------|-----|---------|
| Kubeflow Dashboard | http://localhost:8888 | `kubectl port-forward -n kubeflow svc/centraldashboard 8888:80` |
| KFP Pipelines UI | http://localhost:3000 | `kubectl port-forward -n kubeflow svc/ml-pipeline 3000:8888` |
| ArgoCD | https://localhost:8080 | `kubectl port-forward -n argocd svc/argocd-server 8080:443` |
| MLflow (post-install) | http://localhost:5000 | `kubectl port-forward -n mlflow svc/mlflow-service 5000:5000` |
| Yatai (post-install) | http://localhost:8080 | `kubectl port-forward -n yatai-system svc/yatai 8080:80` |
| Evidently (post-install) | http://localhost:8000 | `kubectl port-forward -n evidently svc/evidently-ui 8000:8000` |

Default credentials:
- **Kubeflow UI**: user@kubeflow.org / 12341234
- **ArgoCD**: admin / (see bootstrap Phase 4)
- **Yatai**: (created during Phase 4 of post-install)
