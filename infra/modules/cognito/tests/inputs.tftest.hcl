# Input checks for the user pool: the hosted login domain prefix and the sign-in origins.
# Uses a mocked AWS provider: no credentials, no AWS calls. Run from modules/cognito:
#   terraform init -backend=false && terraform test

mock_provider "aws" {
  mock_data "aws_region" {
    defaults = {
      name = "us-east-1"
    }
  }
}

variables {
  name_prefix         = "lusiform-test"
  domain_prefix       = "lusiform-staging-test"
  web_base_urls       = ["http://localhost:5173"]
  deletion_protection = false
}

run "valid_prefix_and_localhost_origin_plan" {
  command = plan

  assert {
    condition     = aws_cognito_user_pool_domain.this.domain == "lusiform-staging-test"
    error_message = "the domain prefix is used as given"
  }

  assert {
    condition     = contains(aws_cognito_user_pool_client.web.callback_urls, "http://localhost:5173/auth/callback") && length(aws_cognito_user_pool_client.web.callback_urls) == 1
    error_message = "the localhost origin becomes the callback URL"
  }
}

run "placeholder_prefix_with_uppercase_is_rejected" {
  command = plan

  variables {
    domain_prefix = "lusiform-staging-CHANGE-ME"
  }

  expect_failures = [var.domain_prefix]
}

run "reserved_word_in_prefix_is_rejected" {
  command = plan

  variables {
    domain_prefix = "lusiform-cognito"
  }

  expect_failures = [var.domain_prefix]
}

run "plain_http_non_localhost_origin_is_rejected" {
  command = plan

  variables {
    web_base_urls = ["http://staging.example.com"]
  }

  expect_failures = [var.web_base_urls]
}

run "no_origin_at_all_is_rejected" {
  command = plan

  variables {
    web_base_urls = []
  }

  expect_failures = [var.web_base_urls]
}
