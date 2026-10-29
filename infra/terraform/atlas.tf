resource "mongodbatlas_project" "this" {
  name   = var.name
  org_id = var.atlas_org_id
}

resource "mongodbatlas_advanced_cluster" "this" {
  project_id   = mongodbatlas_project.this.id
  name         = var.name
  cluster_type = "REPLICASET"

  replication_specs {
    region_configs {
      provider_name = "AWS"
      region_name   = var.atlas_region
      priority      = 7
      electable_specs {
        instance_size = var.atlas_instance_size
        node_count    = 3
      }
    }
  }
}

# Only the NAT gateway IP may reach the cluster.
resource "mongodbatlas_project_ip_access_list" "nat" {
  project_id = mongodbatlas_project.this.id
  ip_address = aws_eip.nat.public_ip
  comment    = "${var.name} ECS tasks via NAT"
}

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "mongodbatlas_database_user" "app" {
  project_id         = mongodbatlas_project.this.id
  username           = "${var.name}-app"
  password           = random_password.db.result
  auth_database_name = "admin"
  roles {
    role_name     = "readWrite"
    database_name = var.db_name
  }
}

locals {
  atlas_srv = mongodbatlas_advanced_cluster.this.connection_strings[0].standard_srv
  mongodb_uri = replace(
    local.atlas_srv, "mongodb+srv://",
    "mongodb+srv://${mongodbatlas_database_user.app.username}:${random_password.db.result}@"
  )
}
