# Kubeflow Platform Smoke Tests

## hello-world-pipeline.py

Minimal KFP v2 pipeline that verifies the full Kubeflow platform stack end-to-end.

### What it tests

- ✓ KFP API reachability (port-forward to ml-pipeline service)
- ✓ Pipeline compilation to YAML
- ✓ Pipeline upload and execution
- ✓ Artifact storage in SeaweedFS
- ✓ UI visibility (check KFP dashboard)

### Prerequisites

1. **Kubeflow platform deployed** using the kubeflow-argo-manifests
2. **KFP Python SDK installed:**
   ```bash
   pip install kfp>=2.0
   ```

3. **Port-forward to KFP API:**
   ```bash
   kubectl port-forward -n kubeflow svc/ml-pipeline 3000:8888 &
   ```

### Usage

```bash
python3 scripts/hello-world-pipeline.py
```

### Expected Output

```
✓ Pipeline compiled to hello-world-pipeline.yaml
✓ Run created: <run-id>
✓ Check the KFP UI at http://localhost:3000 for results
✓ Artifacts stored in SeaweedFS mlpipeline bucket
```

### Troubleshooting

**Error: Connection refused**
- Ensure port-forward is active: `kubectl port-forward -n kubeflow svc/ml-pipeline 3000:8888`
- Check ml-pipeline pod status: `kubectl get pods -n kubeflow | grep ml-pipeline`

**Error: mlpipeline bucket not found**
- SeaweedFS creates the bucket on first write automatically
- If error persists, check SeaweedFS deployment: `kubectl get pods -n kubeflow | grep seaweedfs`

**Pipeline not visible in UI**
- Wait 10 seconds for dashboard to refresh
- Check if Istio virtual service is properly configured for dashboard
- Verify istio-injection is enabled: `kubectl get ns kubeflow --show-labels`

### Next Steps

After successful smoke test:
1. Deploy custom ML models using KServe (RawDeployment mode)
2. Run hyperparameter tuning with Katib
3. Deploy training jobs with Training Operator
4. Create Tensor workflows with Spark Operator
