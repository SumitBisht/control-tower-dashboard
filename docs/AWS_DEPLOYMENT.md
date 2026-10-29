# AWS deployment (MongoDB Atlas)

> **Status:** the Terraform in `infra/terraform` has **not been applied or `terraform validate`d** by its author
> (no Terraform/AWS access was available). Treat the first `terraform plan` as a review step.

## Architecture
```
Browser ──HTTPS──▶ CloudFront ──┬─ default  ─▶ S3 (React build, private, OAC)
                                └─ /api/*   ─▶ ALB (HTTP, only CloudFront may reach it, secret header)
                                                 └▶ ECS Fargate (FastAPI, private subnets)
                                                      ├▶ MongoDB Atlas (M10 replica set, via NAT IP allow-list)
                                                      ├▶ S3 uploads bucket (Word files + photos, private, versioned)
                                                      └▶ Secrets Manager (MONGODB_URI, JWT_SECRET, ADMIN_PASSWORD)
```
The UI and API share one CloudFront domain, so there is no CORS setup and the API is not directly exposed.

| File | Creates |
|---|---|
| `network.tf` | VPC, 2 public + 2 private subnets, IGW, one NAT gateway |
| `atlas.tf` | Atlas project, M10 3-node cluster, app DB user (readWrite on `control_tower`), IP allow-list = NAT IP |
| `secrets.tf` | Generated JWT secret, admin password, DB URI in Secrets Manager |
| `storage.tf` | Uploads bucket, web bucket, ECR repository |
| `alb.tf`, `ecs.tf` | ALB locked to CloudFront, Fargate cluster/service/task, IAM roles, log group |
| `frontend.tf` | CloudFront (SPA rewrite + `/api/*` behaviour), OAC, bucket policy |

## Prerequisites
- AWS CLI authenticated to the target account; Terraform ≥ 1.6; Docker; Node 20+.
- An Atlas **organization ID** and an organization **API key** (Organization Access Manager → API Keys, role
  *Organization Project Creator*). Export it — never put it in a file:
  ```bash
  export MONGODB_ATLAS_PUBLIC_KEY=...   MONGODB_ATLAS_PRIVATE_KEY=...
  ```

## First deployment
```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars      # set atlas_org_id, admin_email, client_name
terraform init
terraform apply -target=aws_ecr_repository.backend   # the ECS service needs an image to exist first
cd ../.. && infra/deploy.sh --image-only             # build + push the backend image
cd infra/terraform && terraform apply                # full stack (Atlas cluster takes ~7-10 min)
cd ../.. && infra/deploy.sh                          # roll ECS, build + publish the frontend, invalidate CloudFront
```
(After the first time, only `infra/deploy.sh` is needed for app releases; `terraform apply` for infrastructure changes.
`deploy.sh` is a bash script — run it from Git Bash/WSL on Windows.)

Then open `terraform output app_url`. Sign in as `admin_email`; the password is in Secrets Manager:
```bash
aws secretsmanager get-secret-value --secret-id control-tower/ADMIN_PASSWORD --query SecretString --output text
```
Create a real admin account in **Users**, then disable or re-password the seeded one.

## Configuration
| Setting | Where |
|---|---|
| `CLIENT_NAME` (SPV/client name on uploads) | `client_name` in `terraform.tfvars`; per-upload form value overrides it |
| Self-registration | `ALLOW_SELF_REGISTRATION` in `ecs.tf` (set `false` to make it admin-created only) |
| Size / region | `atlas_instance_size`, `task_cpu`, `task_memory`, `desired_count`, `aws_region` + `atlas_region` |

## Cost (rough, ap-south-1, always-on)
Atlas M10 ≈ US$60/mo · NAT gateway ≈ US$35/mo · ALB ≈ US$20/mo · Fargate 1 vCPU/4 GB ≈ US$50/mo (reports with photos are ~100 MB; 4 GB leaves headroom) · S3/CloudFront/logs: a few dollars.
Use a smaller Atlas tier or a shared tier for dev by changing `atlas_instance_size`.

## Known limitations / hardening to do before production
1. **Public Atlas endpoint.** Access is restricted to the NAT IP and TLS, but traffic leaves the VPC. Upgrade to Atlas PrivateLink
   (`mongodbatlas_privatelink_endpoint` + `aws_vpc_endpoint`) to remove the NAT dependency for DB traffic.
2. **ALB ↔ CloudFront is HTTP.** The ALB only accepts CloudFront's IP range plus a secret header, but the hop is unencrypted. With a
   custom domain: add an ACM certificate, an HTTPS listener, switch `origin_protocol_policy` to `https-only`, and add a Route 53 alias.
3. **Default `*.cloudfront.net` domain.** Add `aliases` + ACM cert (us-east-1) to the distribution for a branded URL.
4. **Terraform state** is local. Configure an S3 backend with DynamoDB locking before more than one person applies.
5. **Single NAT / single task.** Raise `desired_count` for availability; add a NAT per AZ if the NAT AZ matters to you.
6. **No WAF / rate limiting** on login. Attach AWS WAF to CloudFront (rate-based rule on `/api/auth/login`).
7. **Atlas backups** are on by default for M10+, but test a restore, and review the Atlas project's alerting.
8. The generated DB password and JWT secret are also stored in Terraform state — protect the state bucket accordingly.

## Teardown
`terraform destroy` (the uploads bucket must be emptied first — it is versioned). This deletes the Atlas cluster and its data.
