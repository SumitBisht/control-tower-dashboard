output "site_url" {
  value = "https://${local.domain}"
}

output "public_ip" {
  value = aws_eip.this.public_ip
}

output "ssh" {
  value = "ssh -i <your-key.pem> ec2-user@${aws_eip.this.public_ip}"
}

output "admin_email" {
  value = var.admin_email
}

output "admin_password" {
  value     = random_password.admin.result
  sensitive = true # terraform output -raw admin_password
}
