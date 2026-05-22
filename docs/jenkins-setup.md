# Jenkins Setup Guide

## Step 1 — Install Plugins
Manage Jenkins → Plugins → Available → Install:
- Pipeline
- AWS Credentials Plugin
- Amazon Web Services SDK :: All
- Blue Ocean (optional)

## Step 2 — Add AWS Credentials
Manage Jenkins → Credentials → System → Global → Add Credentials
- Kind: AWS Credentials
- ID: `aws-credentials`  ← must match Jenkinsfile
- Add your Access Key + Secret Key

## Step 3 — Install Tools on Jenkins Agent
```bash
# Terraform
wget https://releases.hashicorp.com/terraform/1.6.0/terraform_1.6.0_linux_amd64.zip
unzip terraform_1.6.0_linux_amd64.zip && mv terraform /usr/local/bin/

# AWS CLI v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip awscliv2.zip && sudo ./aws/install

# Python + boto3
sudo apt-get install -y python3 python3-pip jq
pip3 install boto3
```

## Step 4 — Update Jenkinsfile
Edit `jenkins/Jenkinsfile` — update these 3 lines:
```groovy
AWS_REGION           = 'ap-south-1'              // your region
LAMBDA_FUNCTION_NAME = 'tf-analyzer-dev-analyzer' // from: terraform output lambda_function_name
TF_WORKING_DIR       = 'terraform'                // path to terraform in YOUR repo
```

## Step 5 — Create Pipeline Job
1. New Item → Pipeline → name: `terraform-analyzer`
2. Pipeline Definition: Pipeline script from SCM
3. SCM: Git → your repo URL
4. Script Path: `jenkins/Jenkinsfile`
5. Save → Build with Parameters

## Step 6 — Set Approval Users
The `WAIT_APPROVAL` gate only lets specific users approve.
Edit Jenkinsfile: `submitter: 'admin,devops-leads'`
These must be valid Jenkins usernames.

## How Manual Approval Works
1. High-risk plan detected → Jenkins build turns YELLOW (paused)
2. Email arrives in Gmail with full security report
3. DevOps lead opens Jenkins → clicks the paused build
4. Sees the approval prompt → clicks APPROVE or REJECT
5. If APPROVE → terraform apply runs
6. If REJECT → build fails with audit note saved
