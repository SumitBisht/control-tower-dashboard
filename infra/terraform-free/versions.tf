terraform {
  required_version = ">= 1.6"
  required_providers {
    aws          = { source = "hashicorp/aws", version = "~> 5.60" }
    mongodbatlas = { source = "mongodb/mongodbatlas", version = "~> 1.21" }
    random       = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = { Project = var.name, ManagedBy = "terraform" }
  }
}

# Credentials come from env: MONGODB_ATLAS_PUBLIC_KEY / MONGODB_ATLAS_PRIVATE_KEY
provider "mongodbatlas" {}
