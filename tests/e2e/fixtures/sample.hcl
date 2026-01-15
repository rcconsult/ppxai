# Sample HCL file for e2e testing (generic HCL, not Terraform-specific)

application "myapp" {
  name    = "My Application"
  version = "2.0.0"
  enabled = true
}

service "api" {
  port     = 8080
  protocol = "http"

  healthcheck {
    path     = "/health"
    interval = "30s"
    timeout  = "5s"
  }
}

service "worker" {
  port     = 9000
  protocol = "grpc"
  replicas = 3
}

database "primary" {
  driver = "postgresql"
  host   = "db.example.com"
  port   = 5432

  connection {
    pool_size    = 10
    max_lifetime = "1h"
    idle_timeout = "10m"
  }
}

logging {
  level  = "info"
  format = "json"

  outputs = ["stdout", "file"]

  file {
    path       = "/var/log/myapp.log"
    max_size   = "100MB"
    max_backups = 5
  }
}

features {
  experimental = false
  beta_access  = true

  flags = {
    new_ui     = true
    dark_mode  = false
    api_v2     = true
  }
}
