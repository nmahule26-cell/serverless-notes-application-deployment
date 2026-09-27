# Serverless Notes Application Deployment

A serverless notes API built with AWS SAM, using API Gateway, Lambda, DynamoDB, S3, and Cognito for authentication.

## Architecture

The system has two paths:

- **Runtime path**: a client calls **API Gateway**, which invokes one of two **Lambda** functions, which read/write **DynamoDB** (notes) or **S3** (attachments).
- **Deploy path**: an **EC2** instance runs the **SAM CLI**, which drives **CloudFormation** to create every resource above.

## Workflow

1. Launch EC2 and attach an IAM role.
2. Install the SAM CLI (and confirm the AWS CLI is present).
3. Create the project files.
4. Run `sam build`, then `sam deploy --guided`.
5. Read the API URL from the stack outputs.
6. Test with `curl`.
7. Verify results in the DynamoDB, S3, and CloudWatch consoles.
8. Delete the stack when finished.

---

## Step 1: IAM Role & EC2 Creation

- **AMI**: Amazon Linux 2023
- **Instance type**: `t3.micro` (free-tier eligible in most accounts)
- **Security group**: allow SSH (port 22) from your IP only. No other inbound ports are needed — the API itself runs on AWS, not on the EC2 instance.
- **IAM Role**: attach an instance profile to the EC2 instance rather than running `aws configure` with long-lived access keys. Use `AdministratorAccess` initially, since SAM needs to create IAM roles, Lambda functions, API Gateway, DynamoDB, S3, and CloudFormation stacks. Restrict this policy once the deployment is working.

## Step 2: Connect and Install Tools

```bash
sudo dnf update -y          # refreshes the package list and updates existing software
sudo dnf install -y python3.12 unzip jq
aws --version                # AWS CLI v2 is preinstalled on Amazon Linux 2023

# Install SAM CLI
cd ~
wget https://github.com/aws/aws-sam-cli/releases/latest/download/aws-sam-cli-linux-x86_64.zip
unzip aws-sam-cli-linux-x86_64.zip -d sam-installation
sudo ./sam-installation/install
sam --version

python3.12 --version
```

> SAM CLI is the core tool here — it builds and deploys the serverless stack (Lambdas, API Gateway, DynamoDB, S3 from the architecture diagram) via CloudFormation.

## Step 3: Check AWS Access and Region

```bash
aws configure set region us-east-1     # use your preferred region
aws sts get-caller-identity            # should show the EC2 role ARN
```

On EC2, instead of manually configuring an access key and secret key, the best practice is to attach an IAM role to the instance itself — AWS automatically feeds temporary credentials from that role to the CLI. This step sets the working region, then confirms the instance can authenticate to AWS before deploying real infrastructure.

## Step 4: Create the Project Files

```bash
mkdir -p ~/notes-api/notes ~/notes-api/upload && cd ~/notes-api
```

Four files are required:
- `template.yaml`
- `notes/app.py`
- `upload/app.py`
- `notes-app.html` (owned by `ec2-user`, placed in `~/notes-api/`)

### `template.yaml`

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: Serverless notes API

Globals:
  Function:
    Runtime: python3.12
    Timeout: 10
    MemorySize: 256
    Environment:
      Variables:
        TABLE_NAME: !Ref NotesTable
        BUCKET_NAME: !Ref AttachmentsBucket

Resources:
  # Cognito — user authentication
  UserPool:
    Type: AWS::Cognito::UserPool
    Properties:
      UserPoolName: notes-user-pool
      UsernameAttributes: [email]
      AutoVerifiedAttributes: [email]

  UserPoolClient:
    Type: AWS::Cognito::UserPoolClient
    Properties:
      UserPoolId: !Ref UserPool
      GenerateSecret: false
      ExplicitAuthFlows:
        - ALLOW_USER_PASSWORD_AUTH
        - ALLOW_REFRESH_TOKEN_AUTH

  # API Gateway (HTTP API)
  NotesHttpApi:
    Type: AWS::Serverless::HttpApi
    Properties:
      CorsConfiguration:
        AllowOrigins: ["*"]
        AllowHeaders: ["Authorization", "Content-Type"]
        AllowMethods: ["GET", "POST", "DELETE", "OPTIONS"]
      Auth:
        DefaultAuthorizer: CognitoJwt
        Authorizers:
          CognitoJwt:
            IdentitySource: $request.header.Authorization
            JwtConfiguration:
              issuer: !Sub https://cognito-idp.${AWS::Region}.amazonaws.com/${UserPool}
              audience:
                - !Ref UserPoolClient

  # DynamoDB — the Notes table
  NotesTable:
    Type: AWS::DynamoDB::Table
    Properties:
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: id
          AttributeType: S
      KeySchema:
        - AttributeName: id
          KeyType: HASH

  # S3 — attachments bucket
  AttachmentsBucket:
    Type: AWS::S3::Bucket
    Properties:
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
        BlockPublicPolicy: true
        IgnorePublicAcls: true
        RestrictPublicBuckets: true
      BucketEncryption:
        ServerSideEncryptionConfiguration:
          - ServerSideEncryptionByDefault:
              SSEAlgorithm: AES256

  # The two Lambda functions
  NotesFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: notes/
      Handler: app.handler
      Policies:
        - DynamoDBCrudPolicy:
            TableName: !Ref NotesTable
      Events:
        Create:
          Type: HttpApi
          Properties: { ApiId: !Ref NotesHttpApi, Path: /notes, Method: POST }
        List:
          Type: HttpApi
          Properties: { ApiId: !Ref NotesHttpApi, Path: /notes, Method: GET }
        Get:
          Type: HttpApi
          Properties: { ApiId: !Ref NotesHttpApi, Path: '/notes/{id}', Method: GET }
        Delete:
          Type: HttpApi
          Properties: { ApiId: !Ref NotesHttpApi, Path: '/notes/{id}', Method: DELETE }

  UploadFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: upload/
      Handler: app.handler
      Policies:
        - S3WritePolicy:
            BucketName: !Ref AttachmentsBucket
      Events:
        Upload:
          Type: HttpApi
          Properties: { ApiId: !Ref NotesHttpApi, Path: /upload, Method: POST }

Outputs:
  ApiUrl:
    Value: !Sub "https://${NotesHttpApi}.execute-api.${AWS::Region}.amazonaws.com"
  UserPoolId:
    Value: !Ref UserPool
  UserPoolClientId:
    Value: !Ref UserPoolClient
  TableName:
    Value: !Ref NotesTable
  BucketName:
    Value: !Ref AttachmentsBucket
```

## Step 5: Validate, Build, Deploy

```bash
sam validate --lint
sam build                  # or: sam build --use-container
sam deploy --guided
```

- **`sam validate --lint`** — checks `template.yaml` for syntax errors before building or deploying. `--lint` is stricter, catching style/quality issues too, not just whether the file parses. A cheap sanity check that catches typos early.
- **`sam build`** — compiles your source code (`notes/app.py`, `upload/app.py`) into deployable build artifacts.
- **`sam deploy --guided`** — the actual deployment. It pushes build artifacts to AWS and tells CloudFormation to create the stack. The `--guided` flag walks you through an interactive setup the first time only; it asks a series of questions and saves your answers so future deploys don't need to ask again.

## Step 6: Get the Output (Your API URL)

```bash
aws cloudformation describe-stacks --stack-name notes-api \
  --query "Stacks[0].Outputs" --output table          # full stack output details

API=$(aws cloudformation describe-stacks --stack-name notes-api \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
echo $API
```

## Step 7: Test and Gather Stack Values

```bash
API=$(aws cloudformation describe-stacks --stack-name notes-api \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)
CLIENT_ID=$(aws cloudformation describe-stacks --stack-name notes-api \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text)
POOL_ID=$(aws cloudformation describe-stacks --stack-name notes-api \
  --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text)

echo $API $CLIENT_ID $POOL_ID
```

## Step 8: Create a User

**Create user:**

```bash
aws cognito-idp sign-up --client-id $CLIENT_ID \
  --username <your-email> --password '<YourPassword>'

aws cognito-idp admin-confirm-sign-up --user-pool-id $POOL_ID \
  --username <your-email>
```

**Verify:**

```bash
aws cognito-idp admin-get-user --user-pool-id $POOL_ID \
  --username <your-email> --query UserStatus
```

**Get a token:**

```bash
TOKEN=$(aws cognito-idp initiate-auth --client-id $CLIENT_ID \
  --auth-flow USER_PASSWORD_AUTH \
  --auth-parameters USERNAME=<your-email>,PASSWORD='<YourPassword>' \
  --query "AuthenticationResult.IdToken" --output text)

echo $TOKEN
```

> ⚠️ Avoid committing real email addresses or passwords to source control or shared docs. Use placeholders as above and keep real credentials in a local, untracked file.

## Step 9: Create a Note from the CLI

Create a note and save its id:

```bash
ID=$(curl -s -X POST $API/notes \
  -H "Authorization: $TOKEN" -H "Content-Type: application/json" \
  -d '{"title":"Hello","content":"Serverless!"}' | jq -r .id)
echo $ID
```

Read the data back:

```bash
curl -s $API/notes -H "Authorization: $TOKEN" | jq
curl -s $API/notes/$ID -H "Authorization: $TOKEN" | jq
```

## Step 10: Run the Front End

```bash
cd ~ec2-user/notes-api
python3 -m http.server 8080
```

Before opening it in your browser, open port 8080 in the EC2 Security Group:

1. EC2 Console → **Instances** → select your instance.
2. **Security** tab → click the Security Group link.
3. **Edit inbound rules** → **Add rule**.
4. Type: `Custom TCP`, Port: `8080`, Source: **My IP** (safer) or `0.0.0.0/0` (open to anyone — fine for a quick demo only).
5. **Save rules**.

Then browse to:

```
http://<public-ip>:8080/notes-app.html
```

---

## Cleanup

When you're done testing, delete the stack to avoid ongoing charges:

```bash
sam delete --stack-name notes-api
```

## Notes on Security

- The IAM role used here (`AdministratorAccess`) is intentionally broad to simplify the initial deployment. Scope it down to only the services actually used (Lambda, API Gateway, DynamoDB, S3, CloudFormation, Cognito) before using this in anything beyond a demo.
- Keep SSH restricted to your IP, and close port 8080 (or restrict it to your IP) once you're finished testing the front end.
- Rotate or remove any test Cognito users and sample credentials after the demo.
