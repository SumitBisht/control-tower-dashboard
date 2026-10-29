resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "random_password" "admin" {
  length  = 20
  special = false
}

locals {
  secret_names = ["MONGODB_URI", "JWT_SECRET", "ADMIN_PASSWORD"]
  secret_values = {
    MONGODB_URI    = local.mongodb_uri
    JWT_SECRET     = random_password.jwt.result
    ADMIN_PASSWORD = random_password.admin.result
  }
}

resource "aws_secretsmanager_secret" "app" {
  for_each                = toset(local.secret_names)
  name                    = "${var.name}/${each.key}"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "app" {
  for_each      = toset(local.secret_names)
  secret_id     = aws_secretsmanager_secret.app[each.key].id
  secret_string = local.secret_values[each.key]
}
