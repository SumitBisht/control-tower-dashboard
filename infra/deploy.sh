#!/usr/bin/env bash
# Build + ship backend image and frontend bundle to the infrastructure created by Terraform.
# Usage (from repo root):  infra/deploy.sh [--image-only] [image-tag]
set -euo pipefail

IMAGE_ONLY=0
if [ "${1:-}" = "--image-only" ]; then IMAGE_ONLY=1; shift; fi
TAG="${1:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)}"
TF="terraform -chdir=infra/terraform"
REGION="${AWS_REGION:-$($TF output -raw aws_region 2>/dev/null || echo ap-south-1)}"

ECR="$($TF output -raw ecr_repository_url)"
echo ">> Backend image $ECR:$TAG"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${ECR%%/*}"
docker build -t "$ECR:$TAG" -t "$ECR:latest" backend
docker push "$ECR:$TAG"
docker push "$ECR:latest"
[ "$IMAGE_ONLY" = 1 ] && { echo "Image pushed. Now run the full terraform apply."; exit 0; }

BUCKET="$($TF output -raw web_bucket)"
DIST="$($TF output -raw cloudfront_distribution_id)"
CLUSTER="$($TF output -raw ecs_cluster)"
SERVICE="$($TF output -raw ecs_service)"

echo ">> Rolling the ECS service"
aws ecs update-service --region "$REGION" --cluster "$CLUSTER" --service "$SERVICE" --force-new-deployment >/dev/null
aws ecs wait services-stable --region "$REGION" --cluster "$CLUSTER" --services "$SERVICE"

echo ">> Frontend"
(cd frontend && npm ci && npm run build)
aws s3 sync frontend/dist "s3://$BUCKET" --delete --cache-control "public,max-age=31536000,immutable" --exclude index.html
aws s3 cp frontend/dist/index.html "s3://$BUCKET/index.html" --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/index.html" >/dev/null

echo "Done: $($TF output -raw app_url)"
