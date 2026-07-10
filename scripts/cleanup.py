import os
import json
import subprocess

# Add gcloud to PATH
os.environ["PATH"] += os.pathsep + r"C:\Users\imonm\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin"

PROJECT_ID = "imons-projects"
REGION = "us-central1"
SECRET_NAME = "enterprise-config"
FUNCTION_NAME = "asset-metadata-processor"

def run_cmd(cmd, check=False):
    print(f"Executing: {cmd}")
    result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if check and result.returncode != 0:
        print(f"ERROR: Command failed with exit code {result.returncode}")
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
    return result

def main():
    print("Starting cleanup of billable Google Cloud resources...")
    
    # 1. Load bucket name
    try:
        with open("deployed_env.json", "r") as f:
            env = json.load(f)
        bucket_name = env.get("bucket_name")
    except Exception:
        bucket_name = None
        print("deployed_env.json not found, skipping bucket deletion unless specified.")
        
    # 2. Delete Cloud Function (also deletes associated Eventarc trigger)
    print("Deleting Cloud Function...")
    run_cmd(f"gcloud functions delete {FUNCTION_NAME} --gen2 --region={REGION} --project={PROJECT_ID} --quiet")
    
    # 3. Delete Secret
    print("Deleting Secret Manager Secret...")
    run_cmd(f"gcloud secrets delete {SECRET_NAME} --project={PROJECT_ID} --quiet")
    
    # 4. Delete Bucket
    if bucket_name:
        print(f"Deleting Cloud Storage Bucket gs://{bucket_name}...")
        # Empty bucket first
        run_cmd(f"gcloud storage rm -r gs://{bucket_name}/**")
        run_cmd(f"gcloud storage buckets delete gs://{bucket_name} --project={PROJECT_ID}")
    
    # 5. Delete Artifact Registry Repository (created by Gen 2 function)
    print("Deleting Artifact Registry repositories for Cloud Functions...")
    # Cloud Functions creates a repository named `gcf-artifacts` by default
    run_cmd(f"gcloud artifacts repositories delete gcf-artifacts --location={REGION} --project={PROJECT_ID} --quiet")
    
    print("Cleanup Completed. Please verify via Google Cloud Console.")

if __name__ == "__main__":
    main()
