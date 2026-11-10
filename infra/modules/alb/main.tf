# Public application load balancer for the API. TLS 1.2+ in, HTTPS to the targets
# (TLS from the load balancer to the service, security.md). HTTP only redirects.

resource "aws_lb" "this" {
  name               = "${var.name_prefix}-api"
  load_balancer_type = "application"
  internal           = false
  subnets            = var.public_subnet_ids
  security_groups    = [var.security_group_id]

  drop_invalid_header_fields = true
  enable_deletion_protection = var.deletion_protection
}

resource "aws_lb_target_group" "api" {
  name        = "${var.name_prefix}-api"
  vpc_id      = var.vpc_id
  target_type = "ip"
  port        = var.target_port
  protocol    = "HTTPS"

  deregistration_delay = 30

  health_check {
    path                = var.health_check_path
    protocol            = "HTTPS"
    matcher             = "200"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
    timeout             = 5
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
