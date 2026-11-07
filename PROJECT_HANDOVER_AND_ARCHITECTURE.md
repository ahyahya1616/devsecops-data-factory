# Zero-Trust DevSecOps & MLOps Platform — Project Handover & Architecture Guide

> **Date**: November 7, 2026  
> **Author**: Antigravity Pair Programmer & Yahya Ahmane  
> **AWS Account ID**: `240797212774` | **Region**: `us-east-1`  
> **Status**: Infrastructure successfully torn down (`terraform destroy`) to eliminate overnight AWS charges. All code, manifests, and configurations are committed and pushed to 3 GitHub repositories.

---

## 1. Executive Summary & Architecture Overview

This project implements an enterprise-grade, Zero-Trust DevSecOps and MLOps platform on **Amazon EKS** using an isolated multi-repository GitOps architecture:

```
+----------------------------------------------------------------------------------------------------+
|                                    AWS CLOUD (us-east-1)                                           |
|                                                                                                    |
|  +--------------------------- VPC: 10.0.0.0/16 -------------------------------------------------+  |
|  |  Public Subnets (10.0.1.0/24, 10.0.2.0/24)                                                   |  |
|  |    --> Internet Gateway (IGW) + Single Elastic IP / NAT Gateway                              |  |
|  |                                                                                              |  |
|  |  Private Subnets (10.0.10.0/24, 10.0.11.0/24) [Zero External IPs]                            |  |
|  |    +-------------------- Amazon EKS Cluster: zero-trust-mlops-cluster --------------------+  |  |
|  |    |  Kubernetes v1.37.1 | IAM OIDC Provider Enabled                                      |  |  |
|  |    |  Managed Node Group: 2x m7i-flex.large (Free-Tier Compliant)                          |  |  |
|  |    |                                                                                      |  |  |
|  |    |  [Kyverno v1.19.2 Admission Controllers]                                             |  |  |
|  |    |    - disallow-latest-tag (Mandates immutable Git SHA tags)                           |  |  |
|  |    |    - restrict-ecr-registry (Rejects public registries like DockerHub)                |  |  |
|  |    |                                                                                      |  |  |
|  |    |  [eBPF NetworkPolicy Engine via aws-node agent]                                      |  |  |
|  |    |    - default-deny-all (Kernel-level ingress/egress drop)                             |  |  |
|  |    |    - allow-pipeline-egress (Whitelists CoreDNS UDP/53, ECR/S3/Yahoo HTTPS/443)        |  |  |
|  |    |    - SSRF Drop: Explicitly blocks AWS IMDS 169.254.169.254 and VPC CIDRs             |  |  |
|  |    |                                                                                      |  |  |
|  |    |  [Kubeflow Namespace Workloads]                                                      |  |  |
|  |    |    - financial-data-agent Pod/Job (Runs as financial-data-sa with IRSA)              |  |  |
|  |    |    - Kubeflow Pipelines (KFP) standalone engine                                      |  |  |
|  |    +--------------------------------------------------------------------------------------+  |  |
|  +----------------------------------------------------------------------------------------------+  |
|                                                                                                    |
|  +------------------------------ Storage & Security Perimeter ----------------------------------+  |
|  |  - Amazon ECR: 240797212774.dkr.ecr.us-east-1.amazonaws.com/financial-data-agent              |  |
|  |  - Amazon S3:  s3://mlops-financial-data-240797212774-lab (AES-256 Server-Side Encrypted)     |  |
|  |  - IRSA Role:  zero-trust-mlops-cluster-financial-agent-s3-role (OIDC Token Federation)       |  |
|  +----------------------------------------------------------------------------------------------+  |
+----------------------------------------------------------------------------------------------------+
```

---

## 2. Multi-Repository GitOps Structure

The codebase is strictly decoupled across three dedicated Git repositories:

| Repository Name | Local Path | Remote GitHub URL | Purpose & Contents |
| :--- | :--- | :--- | :--- |
| **Application Repo** | `/home/yahya-ahmane/mlops_project` | `https://github.com/ahyahya1616/devsecops-data-factory.git` | Python ingestion agent (`scraper.py`), `Dockerfile`, requirements, pipeline scripts. |
| **Infrastructure Repo** | `/home/yahya-ahmane/mlops_project/mlops_infrastructure` | `https://github.com/ahyahya1616/mlops_infrastructure.git` | Modular Terraform for VPC, EKS cluster, Node Groups, ECR, S3, and IRSA IAM bindings. |
| **Manifests Repo** | `/home/yahya-ahmane/mlops_project/mlops_k8s_manifests` | `https://github.com/ahyahya1616/mlops_k8s_manifests.git` | Kyverno policies, eBPF NetworkPolicies, KFP standalone manifests, and automated exploit tests. |

---

## 3. What We Have Built & Verified Today

### Phase 1 & 2: VPC, EKS & eBPF Networking
- Built modular Terraform infrastructure:
  - `modules/vpc`: VPC `10.0.0.0/16`, 2 public subnets, 2 private subnets, IGW, and 1 NAT Gateway (`3.214.51.241`).
  - `modules/eks`: EKS cluster `zero-trust-mlops-cluster` (Kubernetes v1.37.1) with IAM OIDC provider.
  - Managed Node Group: 2 worker nodes using **`m7i-flex.large`** (2 vCPU, 8 GB RAM, x86_64).
  - Add-ons: `vpc-cni`, `coredns`, `kube-proxy`.
  - Configured native AWS VPC CNI eBPF Network Policy agent (`ENABLE_NETWORK_POLICY=true`, running `aws-eks-nodeagent`).

### Phase 3: Zero-Static-Credentials Storage (ECR, S3 & IRSA)
- **Private Amazon ECR**: `240797212774.dkr.ecr.us-east-1.amazonaws.com/financial-data-agent` configured with vulnerability scan-on-push and lifecycle expiration rules.
- **Encrypted S3 Data Lake**: `s3://mlops-financial-data-240797212774-lab` with AES256 server-side encryption and 4-point public access block.
- **IAM Roles for Service Accounts (IRSA)**:
  - IAM Role `zero-trust-mlops-cluster-financial-agent-s3-role` trusted via OIDC condition `system:serviceaccount:kubeflow:financial-data-sa`.
  - Scoped IAM policy granting `s3:PutObject`, `s3:GetObject`, and `s3:ListBucket` strictly to the lab bucket.
  - Kubernetes ServiceAccount `financial-data-sa` in `kubeflow` namespace annotated with the IAM Role ARN.
  - Verified live: pods assume IAM credentials dynamically via AWS STS WebIdentity token injection without any static keys (`AWS_ACCESS_KEY_ID`).

### Phase 4 & 5: Admission Control & eBPF Security Policies
- **Kyverno Admission Controller v1.19.2** (Helm chart 3.9.2):
  - `disallow-latest-tag`: Blocks images with `:latest` or untagged references; mandates explicit Git SHA or semver tags.
  - `restrict-ecr-registry`: Restricts workloads in `kubeflow` namespace exclusively to the private ECR registry.
- **eBPF Network Policies**:
  - `default-deny-all`: Kernel-level default-deny posture for all inbound and outbound traffic in `kubeflow`.
  - `allow-pipeline-egress`: Allows `app: financial-data-agent` pods to query CoreDNS (port 53) and make HTTPS calls (port 443) to Yahoo Finance, S3, and ECR.
  - **SSRF Mitigation**: Explicitly drops traffic to AWS IMDS (`169.254.169.254/32`) and internal VPC CIDRs (`10.0.0.0/16`, `172.20.0.0/16`).
  - `allow-kfp-platform`: Allows intra-namespace communication between KFP internal components while preserving IMDS drop.

### Phase 6: Live Workload Ingestion & Exploit Tests Verification
- **Application Build & Push**:
  - Updated `scraper.py` with `upload_to_s3()` using `boto3`.
  - Built Docker image `240797212774.dkr.ecr.us-east-1.amazonaws.com/financial-data-agent:sha-968cd0a`.
  - Pushed to ECR.
- **Live Ingestion Job**:
  - Deployed `financial-agent-job.yaml` to `kubeflow` namespace.
  - Fetched AAPL, MSFT, and GOOGL historical records (384 total records).
  - Persisted locally as Parquet (21.13 KB).
  - Uploaded to `s3://mlops-financial-data-240797212774-lab/data/market_data_20261107_215300.parquet` using IRSA tokens.
- **Automated Exploit Suite (`run_exploit_suite.sh`) Results**:
  ```
  ==================================================================
  TEST RESULTS: 3 Passed, 0 Failed (100% Zero-Trust Compliance)
  ==================================================================
  [PASS] Test 1: Kyverno blocked unapproved Docker Hub registry.
  [PASS] Test 2: Kyverno blocked mutable ':latest' image tag.
  [PASS] Test 3: eBPF NetworkPolicy dropped AWS IMDS (169.254.169.254) SSRF probe.
  ```

---

## 4. Key Gotchas, Fixes & Troubleshooting History

1. **AWS Free-Tier Instance Restriction**:
   - *Problem*: Attempting to launch `t3.large` worker nodes failed with `InvalidParameterCombination - The specified instance type is not eligible for Free Tier`.
   - *Fix*: Switched node group instance type to **`m7i-flex.large`** (supported by the account's Free-Tier policy, x86_64, 2 vCPU, 8 GB RAM). Node group boots in ~1m19s.
2. **Terraform IAM Role Attachment Schema**:
   - *Problem*: `aws_iam_role_policy_attachment` expected `role` (name) instead of `role_arn`.
   - *Fix*: Standardized on `aws_iam_role.<name>.name` in `modules/eks/main.tf` and `modules/irsa/main.tf`.
3. **Kyverno Pipe Delimiter**:
   - Kyverno pattern matching supports pipe syntax: `"240797212774.dkr.ecr.us-east-1.amazonaws.com/* | gcr.io/ml-pipeline/* | ..."`.
4. **Clean Teardown Pre-flight**:
   - S3 buckets containing objects and ECR repositories containing images reject Terraform deletion unless emptied or configured with `force_destroy = true` / `force_delete = true`. Both modules have been permanently configured with force deletion flags.

---

## 5. How to Resume Tomorrow (Step-by-Step Runbook)

When you resume tomorrow, follow this rapid sequence to bring everything back up in ~15 minutes:

### Step 1: Re-provision AWS Infrastructure (Terraform)
```bash
cd /home/yahya-ahmane/mlops_project/mlops_infrastructure
terraform apply -auto-approve
```
*Wait ~10-12 minutes for EKS cluster and nodes to become Ready.*

### Step 2: Configure kubectl Context
```bash
aws eks update-kubeconfig --name zero-trust-mlops-cluster --region us-east-1
kubectl get nodes
```

### Step 3: Install Kyverno & Enforce Policies
```bash
cd /home/yahya-ahmane/mlops_project/mlops_k8s_manifests/01-security-policies/kyverno
./install.sh
kubectl apply -f disallow-latest-tag.yaml
kubectl apply -f restrict-ecr-registry.yaml
```

### Step 4: Apply eBPF Network Policies
```bash
cd /home/yahya-ahmane/mlops_project/mlops_k8s_manifests/01-security-policies/network-policies
kubectl apply -f default-deny-all.yaml
kubectl apply -f allow-pipeline-egress.yaml
kubectl apply -f allow-kfp-platform.yaml
```

### Step 5: Build and Push Ingestion Image to ECR
```bash
cd /home/yahya-ahmane/mlops_project
GIT_SHA=$(git rev-parse --short HEAD)
ECR_URI="240797212774.dkr.ecr.us-east-1.amazonaws.com/financial-data-agent:sha-${GIT_SHA}"

aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 240797212774.dkr.ecr.us-east-1.amazonaws.com
docker build -t ${ECR_URI} .
docker push ${ECR_URI}
```

### Step 6: Run the Exploit Verification Suite
```bash
cd /home/yahya-ahmane/mlops_project/mlops_k8s_manifests/04-exploit-tests
./run_exploit_suite.sh
```

### Step 7: Kubeflow Pipelines Standalone Deployment & UI Access
```bash
# Apply KFP cluster CRDs and application manifests
kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/cluster-scoped-resources?ref=2.2.0"
kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/env/platform-agnostic?ref=2.2.0"

# Wait for KFP API server to be ready
kubectl wait --for=condition=available --timeout=300s deployment/ml-pipeline -n kubeflow

# Port-forward UI to localhost:8080
kubectl port-forward -n kubeflow svc/ml-pipeline-ui 8080:80
```
Then write and submit `pipeline.py` using `kfp.dsl` to schedule the automated agent runs!

