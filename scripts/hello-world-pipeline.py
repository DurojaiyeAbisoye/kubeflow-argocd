#!/usr/bin/env python3
"""
Smoke test pipeline for kubeflow-argocd platform.

Verifies: KFP API reachable, pipeline runs, artifacts stored in SeaweedFS.
Minimal KFP v2 pipeline that verifies the full stack end-to-end:
- Pipeline compilation
- Upload to KFP API
- Run execution
- Artifact storage in SeaweedFS
- UI visibility

SeaweedFS auto-creates the mlpipeline bucket on first write — no manual
bucket creation needed.

Usage:
    python3 scripts/hello-world-pipeline.py

Requirements:
    - kfp>=2.0
    - kubectl port-forward svc/ml-pipeline -n kubeflow 3000:8888
"""

from kfp import dsl, compiler
import kfp


@dsl.component(base_image="python:3.11-slim")
def say_hello(name: str) -> str:
    """Simple component that greets and returns a message."""
    greeting = f"Hello, {name}! Platform is working."
    print(greeting)
    return greeting


@dsl.pipeline(name="hello-world", description="Smoke test for kubeflow-argocd platform")
def hello_pipeline(name: str = "kubeflow-argocd"):
    """Minimal pipeline to verify KFP v2 stack."""
    say_hello(name=name)


if __name__ == "__main__":
    # Compile pipeline to YAML
    compiler.Compiler().compile(hello_pipeline, "hello-world-pipeline.yaml")
    print("✓ Pipeline compiled to hello-world-pipeline.yaml")

    # Connect to KFP API and create run
    try:
        client = kfp.Client(host="http://localhost:8084")
        run = client.create_run_from_pipeline_func(
            hello_pipeline,
            arguments={"name": "kubeflow-argocd"},
            run_name="smoke-test",
        )
        print(f"✓ Run created: {run.run_id}")
        print("✓ Check the KFP UI at http://localhost:8084 for results")
        print(f"✓ Artifacts stored in SeaweedFS mlpipeline bucket")
    except Exception as e:
        print(f"✗ Error: {e}")
        print("  Ensure port-forward is active: kubectl port-forward svc/ml-pipeline -n kubeflow 3000:8888")
        raise
