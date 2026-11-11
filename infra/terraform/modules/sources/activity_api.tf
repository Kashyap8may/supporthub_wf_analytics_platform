# Activity tracker API: DynamoDB holds activity segments; a Lambda serves
# GET /activities?updated_since=&page_token= behind API Gateway with an API key and usage plan.
# A REST API (not an HTTP API) is used because only REST APIs support API keys and usage plans.

resource "aws_dynamodb_table" "segments" {
  name         = "${local.p}-activity-segments"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "segment_id"

  attribute {
    name = "segment_id"
    type = "S"
  }
  attribute {
    name = "updated_day"
    type = "S"
  }
  attribute {
    name = "updated_at"
    type = "S"
  }

  # Incremental pulls query one UTC day of updated_at at a time instead of scanning the table.
  global_secondary_index {
    name            = "by_updated_day"
    hash_key        = "updated_day"
    range_key       = "updated_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = false
  }
}

data "archive_file" "activity_api" {
  type        = "zip"
  source_dir  = var.activity_api_source_dir
  output_path = "${path.module}/.build/activity_api.zip"
  excludes    = ["__pycache__", "__pycache__/handler.cpython-313.pyc"]
}

resource "aws_iam_role" "activity_api" {
  name = "${local.p}-activity-api"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "activity_api" {
  name = "read-segments"
  role = aws_iam_role.activity_api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:Query", "dynamodb:Scan"]
        Resource = [aws_dynamodb_table.segments.arn, "${aws_dynamodb_table.segments.arn}/index/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.activity_api.arn}:*"
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "activity_api" {
  name              = "/aws/lambda/${local.p}-activity-api"
  retention_in_days = 14
}

resource "aws_lambda_function" "activity_api" {
  function_name    = "${local.p}-activity-api"
  role             = aws_iam_role.activity_api.arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = "handler.handler"
  filename         = data.archive_file.activity_api.output_path
  source_code_hash = data.archive_file.activity_api.output_base64sha256
  memory_size      = 256
  timeout          = 15

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.segments.name
      INDEX_NAME = "by_updated_day"
    }
  }

  depends_on = [aws_cloudwatch_log_group.activity_api]
}

resource "aws_api_gateway_rest_api" "activity" {
  name        = "${local.p}-activity-api"
  description = "Activity tracker API for SupportHub"
  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_resource" "activities" {
  rest_api_id = aws_api_gateway_rest_api.activity.id
  parent_id   = aws_api_gateway_rest_api.activity.root_resource_id
  path_part   = "activities"
}

resource "aws_api_gateway_method" "get_activities" {
  rest_api_id      = aws_api_gateway_rest_api.activity.id
  resource_id      = aws_api_gateway_resource.activities.id
  http_method      = "GET"
  authorization    = "NONE"
  api_key_required = true
}

resource "aws_api_gateway_integration" "get_activities" {
  rest_api_id             = aws_api_gateway_rest_api.activity.id
  resource_id             = aws_api_gateway_resource.activities.id
  http_method             = aws_api_gateway_method.get_activities.http_method
  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = aws_lambda_function.activity_api.invoke_arn
}

resource "aws_api_gateway_deployment" "activity" {
  rest_api_id = aws_api_gateway_rest_api.activity.id
  triggers = {
    redeploy = sha1(jsonencode([
      aws_api_gateway_resource.activities.id,
      aws_api_gateway_method.get_activities.id,
      aws_api_gateway_integration.get_activities.id,
    ]))
  }
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "v1" {
  rest_api_id   = aws_api_gateway_rest_api.activity.id
  deployment_id = aws_api_gateway_deployment.activity.id
  stage_name    = "v1"
}

resource "aws_api_gateway_usage_plan" "activity" {
  name = "${local.p}-activity-api"
  api_stages {
    api_id = aws_api_gateway_rest_api.activity.id
    stage  = aws_api_gateway_stage.v1.stage_name
  }
  throttle_settings {
    rate_limit  = 20
    burst_limit = 40
  }
  quota_settings {
    limit  = 100000
    period = "DAY"
  }
}

resource "aws_api_gateway_api_key" "activity" {
  name = "${local.p}-activity-api"
}

resource "aws_api_gateway_usage_plan_key" "activity" {
  key_id        = aws_api_gateway_api_key.activity.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.activity.id
}

resource "aws_lambda_permission" "activity_api" {
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.activity_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.activity.execution_arn}/*/GET/activities"
}
