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
  description = "MongoDB Atlas organization ID (Atlas UI > Organization Settings)"
}

variable "atlas_region" {
  type        = string
  default     = "AP_SOUTH_1"
  description = "Atlas region name matching aws_region (ap-south-1 = AP_SOUTH_1)"
}

variable "atlas_instance_size" {
  type    = string
  default = "M10"
}

variable "db_name" {
  type    = string
  default = "control_tower"
}

variable "client_name" {
  type        = string
  default     = ""
  description = "CLIENT_NAME setting: SPV/client name stamped on uploads (blank = name from the Word document)"
}

variable "admin_email" {
  type = string
}

variable "backend_image_tag" {
  type    = string
  default = "latest"
}

variable "task_cpu" {
  type    = number
  default = 1024
}

variable "task_memory" {
  type    = number
  default = 4096
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}
