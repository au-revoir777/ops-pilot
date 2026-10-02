# =============================================================================
# OpsPilot — Terraform Main Configuration
# =============================================================================
# This is a skeleton. Full implementation in Phase 14.
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "OpsPilot"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}
