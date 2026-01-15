# Sample Terraform file for e2e testing

terraform {
  required_version = ">= 1.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "development"
}

variable "instance_count" {
  description = "Number of instances"
  type        = number
  default     = 2
}

resource "aws_instance" "web" {
  ami           = "ami-12345678"
  instance_type = "t3.micro"
  count         = var.instance_count

  tags = {
    Name        = "web-server"
    Environment = var.environment
    Managed     = "terraform"
  }
}

resource "aws_security_group" "web_sg" {
  name        = "web-security-group"
  description = "Security group for web servers"

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

output "instance_ids" {
  description = "IDs of EC2 instances"
  value       = aws_instance.web[*].id
}

output "public_ips" {
  description = "Public IPs of EC2 instances"
  value       = aws_instance.web[*].public_ip
}
