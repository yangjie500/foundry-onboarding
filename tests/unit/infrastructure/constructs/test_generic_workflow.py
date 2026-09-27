import aws_cdk as cdk
from aws_cdk import aws_lambda as lambda_
from aws_cdk.assertions import Match, Template

from infrastructure.constructs import GenericWorkflow


def _template() -> Template:
    app = cdk.App()
    stack = cdk.Stack(app, "TestStack")
    processor = lambda_.Function(
        stack,
        "Processor",
        runtime=lambda_.Runtime.PYTHON_3_14,
        handler="index.handler",
        code=lambda_.Code.from_inline("def handler(event, context): return event"),
    )

    GenericWorkflow(
        stack,
        "Workflow",
        state_machine_name="foundry-dev-generic-workflow",
        processor=processor,
    )

    return Template.from_stack(stack)


def test_generic_workflow_routes_and_transforms_echo_input() -> None:
    template = _template()

    template.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {
            "StateMachineName": "foundry-dev-generic-workflow",
            "StateMachineType": "STANDARD",
            "DefinitionString": {
                "Fn::Join": [
                    "",
                    Match.array_with(
                        [
                            Match.string_like_regexp(
                                '"StartAt":"Route action".*'
                                '"Variable":"\\$\\.action".*'
                                '"StringEquals":"echo".*'
                                '"Default":"Unsupported action".*'
                                '"Error":"UnsupportedAction".*'
                                '"Resource":"$'
                            ),
                            {
                                "Fn::GetAtt": [
                                    Match.string_like_regexp("^Processor"),
                                    "Arn",
                                ]
                            },
                            Match.string_like_regexp(
                                '^","Parameters":\\{'
                                '"schema_version\\.\\$":"\\$\\.schema_version",'
                                '"request_id\\.\\$":"\\$\\.request_id",'
                                '"message\\.\\$":"\\$\\.payload\\.message"'
                                '\\}\\}\\},"TimeoutSeconds":300\\}$'
                            ),
                        ]
                    ),
                ]
            },
        },
    )


def test_generic_workflow_can_invoke_only_the_processor() -> None:
    template = _template()

    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "lambda:InvokeFunction",
                                "Effect": "Allow",
                                "Resource": Match.array_with(
                                    [
                                        {
                                            "Fn::GetAtt": [
                                                Match.string_like_regexp("^Processor"),
                                                "Arn",
                                            ]
                                        }
                                    ]
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )
