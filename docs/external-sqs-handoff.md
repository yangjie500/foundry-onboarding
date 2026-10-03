# External SQS integration handoff

## Purpose and current status

This is the handoff checklist for connecting the Foundry workflow-ingress
Lambda to an SQS queue owned by another team. The application stack can import
an existing Standard queue, create a least-privilege ingress role, and activate
the Lambda event-source mapping in a separate deployment.

Development continues to use the project-owned simulation queue. Staging and
production remain in `disabled` mode, so this capability does not connect to an
external queue until reviewed values are added to the relevant configuration.

Never put credentials, secret values, or real message contents in environment
YAML, Lambda environment values, Step Functions input/output, fixtures, logs,
or this document.

## Information required from the external team

Obtain these items through the approved team handoff process:

- Full queue ARN, AWS account ID, and AWS Region.
- Confirmation that it is a **Standard** queue. FIFO is not currently supported.
- Encryption type: SQS-managed, unencrypted, or customer-managed KMS. For a
  customer-managed key, obtain its full key ARN.
- Confirmation that the queue and Foundry Lambda use the same AWS Region.
- Visibility timeout. It should be at least six times the ingress Lambda timeout.
- Retention period, redrive `maxReceiveCount`, DLQ ARN, DLQ owner, alerting owner,
  and replay/runbook contact.
- Expected normal and burst message rates.
- Approval of [`sqs-onboarding-contract.md`](sqs-onboarding-contract.md), including
  the stable request identifier used for idempotency.
- Whether SNS or another upstream service wraps or changes the SQS message body.
- Queue-policy and KMS-key-policy owners, approval process, and implementation
  contacts.

Do not guess missing values. Keep ingestion `disabled` until these details are
approved.

## Configuration modes

- `development` creates the project-owned development queue and DLQ and connects
  the ingress Lambda.
- `external` imports a queue by ARN and creates the ingress Lambda. Mapping
  activation is controlled separately for a safe cross-team handoff.
- `disabled` creates neither an ingress Lambda nor an event-source mapping.

Start an integration environment with the mapping disabled:

```yaml
ingestion:
  sqs:
    mode: external
    batch_size: 10
    external:
      queue_arn: arn:<partition>:sqs:<region>:<queue-account>:<queue-name>
      kms_key_arn: arn:<partition>:kms:<region>:<queue-account>:key/<key-id>
      event_source_mapping_enabled: false
```

Omit `kms_key_arn` when the queue does not use a customer-managed key. Alias ARNs
are not accepted. The queue ARN Region must match `aws_region`; the KMS key must
belong to the queue's account and Region.

## Two-deployment activation

1. Obtain and validate the external-team information above.
2. Configure `mode: external` and `event_source_mapping_enabled: false`.
3. Run `make synth ENV=<environment>` and `make diff ENV=<environment>`. Confirm
   that no `AWS::SQS::Queue` or `AWS::SQS::QueuePolicy` will be created.
4. Deploy. Give the `SqsWorkflowIngressRoleArn` stack output to the queue owner.
   This deployment creates the consumer role but does not poll the queue.
5. The external team grants that role the queue permissions below and, if needed,
   updates its KMS key policy.
6. After both policy owners confirm their changes, set
   `event_source_mapping_enabled: true`.
7. Run synth and diff again. Expect one `AWS::Lambda::EventSourceMapping` and still
   no queue or queue-policy resources.
8. Deploy, send an approved non-sensitive test message, and verify the Lambda,
   Step Functions execution, partial-batch behavior, alarms, and DLQ process.

If validation fails, set `event_source_mapping_enabled: false` and deploy to stop
polling while the teams investigate.

## Queue policy owned by the external team

Replace the placeholders with the exact deployed role and queue ARNs. The external
team owns this resource policy; Foundry CDK does not modify it.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowFoundryIngressConsumer",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:<partition>:iam::<foundry-account>:role/<deployed-ingress-role>"
      },
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:ChangeMessageVisibility",
        "sqs:GetQueueUrl",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes"
      ],
      "Resource": "arn:<partition>:sqs:<region>:<queue-account>:<queue-name>"
    }
  ]
}
```

Foundry adds the matching identity policy to the ingress role. It does not need
`sqs:SendMessage`, DLQ access, wildcard queue access, or queue administration.

## KMS key policy owned by the external team

This applies only to a customer-managed KMS key. The key-policy owner must allow
the exact ingress role to decrypt:

```json
{
  "Sid": "AllowFoundryIngressDecrypt",
  "Effect": "Allow",
  "Principal": {
    "AWS": "arn:<partition>:iam::<foundry-account>:role/<deployed-ingress-role>"
  },
  "Action": "kms:Decrypt",
  "Resource": "*"
}
```

`Resource` is `*` in a KMS key policy because that policy is attached to one key.
Foundry's identity policy separately limits `kms:Decrypt` to the exact configured
key ARN. A cross-account queue encrypted with the AWS-managed SQS key cannot be
used; the owner must use a customer-managed key with the appropriate policy or
SQS-managed encryption.

## Ownership boundary

| Responsibility | Foundry team | External queue team |
| --- | --- | --- |
| Ingress Lambda and execution role | Owns | Receives role ARN |
| Lambda event-source mapping | Owns | Confirms readiness |
| Step Functions permission | Owns | None |
| Queue, DLQ, policy, retention and redrive | Does not modify | Owns |
| Customer-managed KMS key and policy | Adds exact identity permission | Owns resource policy |
| Message contract | Validates at ingress | Produces approved contract |

## AWS references

- [Cross-account SQS event-source example](https://docs.aws.amazon.com/lambda/latest/dg/with-sqs-cross-account-example.html)
- [Lambda SQS configuration guidance](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-configure.html)
- [SQS Lambda trigger restrictions](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-configure-lambda-function-trigger.html)
- [SQS access-denied troubleshooting](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/troubleshooting-access-denied.html)
