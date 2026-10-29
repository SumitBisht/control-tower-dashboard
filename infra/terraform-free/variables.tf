variable "name" {
  type    = string
  default = "control-tower"
}

variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

variable "atlas_org_id" {
  type        = string
  description = "MongoDB Atlas organization ID"
}

variable "atlas_region" {
  type        = string
  default     = "AP_SOUTH_1"
  description = "Atlas region name matching aws_region (M0 is only offered in some regions - check the Atlas UI)"
}

variable "instance_type" {
  type        = string
  default     = "t3.micro"
  description = "Free-tier eligible type for your account (t3.micro, or t2.micro in regions without t3). t3.small if credits allow: 1 GB is tight for big reports."
}

variable "key_name" {
  type        = string
  description = "Name of an existing EC2 key pair (EC2 console > Key Pairs) used for SSH deploys"
}

variable "ssh_cidr" {
  type        = string
  description = "Your public IP in CIDR form, e.g. 203.0.113.7/32. Only this address may SSH in."
}

variable "admin_email" {
  type = string
}

variable "client_name" {
  type    = string
  default = ""
}

variable "domain" {
  type        = string
  default     = ""
  description = "Your own hostname pointing at the Elastic IP. Blank = use <ip-with-dashes>.sslip.io (free, works with Let's Encrypt)"
}

variable "volume_size_gb" {
  type    = number
  default = 30 # free tier includes 30 GB of EBS
}

variable "db_name" {
  type    = string
  default = "control_tower"
}
