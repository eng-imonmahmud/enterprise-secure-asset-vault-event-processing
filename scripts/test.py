import os
import json
import time
import subprocess
from google.cloud import storage, firestore

# Add gcloud to PATH
os.environ["PATH"] += os.pathsep + r"C:\Users\imonm\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin"

# Set credentials for Google Cloud Python libraries
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"E:\VS Code Project\enterprise-secure-asset-vault-event-processing\imons-projects-14ba0d56ccce.json"

PROJECT_ID = "imons-projects"

def run_cmd(cmd, check=True):
    print(f"Executing: {cmd}")
    result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if check and result.returncode != 0:
        print(f"ERROR: Command failed with exit code {result.returncode}")
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
        raise RuntimeError(f"Command execution failed: {cmd}")
    return result

def main():
    try:
        with open("deployed_env.json", "r") as f:
            env = json.load(f)
        bucket_name = env["bucket_name"]
    except Exception as e:
        print("Failed to load deployed_env.json. Did deploy.py complete successfully?")
        raise
        
    print(f"Testing pipeline using bucket: {bucket_name}")
    
    # 1. Create a dummy file
    test_filename = "enterprise_test_asset.txt"
    with open(test_filename, "w") as f:
        f.write("CONFIDENTIAL ENTERPRISE ASSET DATA")
        
    # 2. Upload to Cloud Storage
    print("Uploading test asset to Cloud Storage...")
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(test_filename)
    blob.upload_from_filename(test_filename)
    print(f"Uploaded {test_filename} to gs://{bucket_name}/")
    
    # 3. Wait for Eventarc and Cloud Function to process
    print("Waiting for processing (15 seconds)...")
    time.sleep(15)
    
    # 4. Check Firestore
    print("Checking Firestore for metadata record...")
    firestore_client = firestore.Client(project=PROJECT_ID)
    collection = firestore_client.collection("asset-catalog")
    docs = collection.where(filter=firestore.FieldFilter("fileName", "==", test_filename)).get()
    
    if not docs:
        print("ERROR: Metadata record not found in Firestore. Check Cloud Logging for errors.")
        exit(1)
        
    for doc in docs:
        print(f"SUCCESS: Found document {doc.id}")
        print(json.dumps(doc.to_dict(), indent=2))
        
    # 5. Retrieve Logs
    print("Retrieving Cloud Function logs...")
    logs = run_cmd(f"gcloud logging read \"resource.type=cloud_function AND resource.labels.function_name=asset-metadata-processor AND severity>=INFO\" --limit=10 --project={PROJECT_ID}", check=False)
    print("--- LOGS ---")
    print(logs.stdout)
    
    print("End-to-End Test Completed Successfully.")

if __name__ == "__main__":
    main()
