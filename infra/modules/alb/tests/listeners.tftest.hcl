# Listener layout with and without a certificate, and the HTTPS guard. Uses a mocked AWS
# provider: no credentials, no AWS calls. Run from modules/alb:
#   terraform init -backend=false && terraform test

mock_provider "aws" {
  mock_resource "aws_lb" {
    defaults = {
      arn      = "arn:aws:elasticloadbalancing:us-east-1:111111111111:loadbalancer/app/lusiform-test-api/0123456789abcdef"
      dns_name = "lusiform-test-api-123.us-east-1.elb.amazonaws.com"
    }
  }

  mock_resource "aws_lb_target_group" {
    defaults = {
      arn = "arn:aws:elasticloadbalancing:us-east-1:111111111111:targetgroup/lusiform-test-api/0123456789abcdef"
    }
  }

  mock_resource "aws_lb_listener" {
    defaults = {
      arn = "arn:aws:elasticloadbalancing:us-east-1:111111111111:listener/app/lusiform-test-api/0123456789abcdef/0123456789abcdef"
    }
  }
}

variables {
  name_prefix         = "lusiform-test"
  vpc_id              = "vpc-0123456789abcdef0"
  public_subnet_ids   = ["subnet-0123456789abcdef0", "subnet-0123456789abcdef1"]
  security_group_id   = "sg-0123456789abcdef0"
  target_port         = 8443
  deletion_protection = false
}

run "staging_without_a_certificate_serves_http_and_forwards" {
  command = apply # mocked

  variables {
    certificate_arn = null
    require_https   = false
  }

  assert {
    condition     = length(aws_lb_listener.https) == 0 && length(aws_lb_listener.http_redirect) == 0
    error_message = "without a certificate there is no HTTPS listener and no redirect"
  }

  assert {
    condition     = length(aws_lb_listener.http_forward) == 1 && aws_lb_listener.http_forward[0].port == 80
    error_message = "without a certificate, port 80 forwards to the API"
  }

  assert {
    condition     = output.base_url == "http://lusiform-test-api-123.us-east-1.elb.amazonaws.com"
    error_message = "the base URL must say http:// so nobody assumes TLS"
  }

  assert {
    condition     = aws_lb_target_group.api.protocol == "HTTPS"
    error_message = "the load balancer still reaches the API over TLS"
  }
}

run "with_a_certificate_serves_https_and_redirects_http" {
  command = apply # mocked

  variables {
    certificate_arn = "arn:aws:acm:us-east-1:111111111111:certificate/00000000-0000-0000-0000-000000000000"
    require_https   = true
  }

  assert {
    condition     = length(aws_lb_listener.https) == 1 && aws_lb_listener.https[0].port == 443
    error_message = "with a certificate the load balancer serves HTTPS on 443"
  }

  assert {
    condition     = length(aws_lb_listener.http_redirect) == 1 && length(aws_lb_listener.http_forward) == 0
    error_message = "with a certificate, port 80 only redirects to HTTPS"
  }

  assert {
    condition     = startswith(output.base_url, "https://")
    error_message = "the base URL must be https://"
  }
}

run "prod_without_a_certificate_is_refused" {
  command = plan

  variables {
    certificate_arn = null
    require_https   = true
  }

  expect_failures = [aws_lb.this]
}

run "placeholder_certificate_arn_is_rejected" {
  command = plan

  variables {
    certificate_arn = "arn:aws:acm:us-east-1:ACCOUNT_ID:certificate/CERTIFICATE_ID"
    require_https   = false
  }

  expect_failures = [var.certificate_arn]
}
