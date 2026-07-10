import os
import subprocess
import time
import json
import random
import string

# Add gcloud to PATH
os.environ["PATH"] += os.pathsep + r"C:\Users\imonm\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin"

PROJECT_ID = "imons-projects"
REGION = "us-central1"
SECRET_NAME = "enterprise-config"
FUNCTION_NAME = "asset-metadata-processor"

def run_cmd(cmd, check=True, capture=True, shell=True):
    print(f"Executing: {cmd}")
    result = subprocess.run(cmd, shell=shell, text=True, capture_output=capture)
    if check and result.returncode != 0:
        print(f"ERROR: Command failed with exit code {result.returncode}")
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
        raise RuntimeError(f"Command execution failed: {cmd}")
    return result

def enable_apis():
    print("Enabling required APIs...")
    apis = [
        "storage.googleapis.com",
        "cloudfunctions.googleapis.com",
        "eventarc.googleapis.com",
        "secretmanager.googleapis.com",
        "firestore.googleapis.com",
        "cloudbuild.googleapis.com",
        "artifactregistry.googleapis.com",
        "run.googleapis.com",
        "pubsub.googleapis.com"
    ]
    run_cmd(f"gcloud services enable {' '.join(apis)} --project {PROJECT_ID}")
    # Wait for APIs to propagate
    time.sleep(10)

def setup_firestore():
    print("Setting up Firestore (Native Mode)...")
    try:
        run_cmd(f"gcloud firestore databases create --location={REGION} --type=firestore-native --project {PROJECT_ID}", check=False)
    except Exception:
        pass # Might already exist

def setup_secret():
    print("Setting up Secret Manager...")
    try:
        run_cmd(f"gcloud secrets create {SECRET_NAME} --replication-policy=\"automatic\" --project {PROJECT_ID}", check=False)
    except Exception:
        pass # Might already exist
    
    config_data = json.dumps({
        "processing_mode": "enterprise_secure",
        "retention_days": 365,
        "classification": "CONFIDENTIAL"
    })
    
    # Write to temp file to avoid quoting issues in command line
    with open("temp_secret.json", "w") as f:
        f.write(config_data)
        
    run_cmd(f"gcloud secrets versions add {SECRET_NAME} --data-file=temp_secret.json --project {PROJECT_ID}")
    os.remove("temp_secret.json")

def get_project_number():
    res = run_cmd(f"gcloud projects describe {PROJECT_ID} --format=\"value(projectNumber)\"")
    return res.stdout.strip()

def setup_permissions():
    print("Setting up IAM permissions...")
    project_number = get_project_number()
    compute_sa = f"{project_number}-compute@developer.gserviceaccount.com"
    
    roles = [
        "roles/secretmanager.secretAccessor",
        "roles/datastore.user",
        "roles/artifactregistry.reader"
    ]
    
    for role in roles:
        run_cmd(f"gcloud projects add-iam-policy-binding {PROJECT_ID} --member=\"serviceAccount:{compute_sa}\" --role=\"{role}\"", check=False)
        
    # GCS service account needs pubsub.publisher for Eventarc
    storage_sa_raw = run_cmd(f"gcloud storage service-agent --project={PROJECT_ID}", check=False)
    storage_sa = storage_sa_raw.stdout.strip()
    if storage_sa:
        run_cmd(f"gcloud projects add-iam-policy-binding {PROJECT_ID} --member=\"serviceAccount:{storage_sa}\" --role=\"roles/pubsub.publisher\"", check=False)

        
    time.sleep(10) # Wait for IAM propagation

def create_bucket():
    print("Creating Cloud Storage Bucket...")
    suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    bucket_name = f"enterprise-secure-asset-vault-{suffix}"
    try:
        run_cmd(f"gcloud storage buckets create gs://{bucket_name} --project {PROJECT_ID} --location {REGION} --uniform-bucket-level-access")
    except Exception as e:
        print(f"Bucket creation failed, might need retry: {e}")
        raise
    return bucket_name

def deploy_function(bucket_name):
    print("Deploying Cloud Function (Gen 2)...")
    project_number = get_project_number()
    compute_sa = f"{project_number}-compute@developer.gserviceaccount.com"
    
    cmd = (
        f"gcloud functions deploy {FUNCTION_NAME} "
        f"--gen2 "
        f"--runtime=python310 "
        f"--region={REGION} "
        f"--source=src "
        f"--entry-point=process_asset "
        f"--trigger-event-filters=\"type=google.cloud.storage.object.v1.finalized\" "
        f"--trigger-event-filters=\"bucket={bucket_name}\" "
        f"--trigger-location={REGION} "
        f"--set-env-vars=PROJECT_ID={PROJECT_ID},SECRET_ID={SECRET_NAME},ENVIRONMENT=production "
        f"--service-account={compute_sa} "
        f"--project={PROJECT_ID} "
        f"--quiet"
    )
    run_cmd(cmd)

def main():
    try:
        print("Starting Enterprise Deployment...")
        enable_apis()
        setup_firestore()
        setup_secret()
        setup_permissions()
        bucket_name = create_bucket()
        
        # Save bucket name for test/cleanup scripts
        with open("deployed_env.json", "w") as f:
            json.dump({"bucket_name": bucket_name}, f)
            
        deploy_function(bucket_name)
        print("Deployment completed successfully.")
        
    except Exception as e:
        print(f"Deployment failed: {e}")
        exit(1)

if __name__ == "__main__":
    main()
