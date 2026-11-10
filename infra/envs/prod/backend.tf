terraform {
  backend "s3" {
    bucket       = "lusiform"
    key          = "lusiform/platform/prod.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}