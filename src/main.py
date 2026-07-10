import os
import json
import logging
from datetime import datetime, timezone
import functions_framework
from cloudevents.http import CloudEvent
from google.cloud import storage, secretmanager, firestore

# Configure structured logging for enterprise observability
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("enterprise-asset-processor")

# Initialize global clients to reuse across invocations for performance
try:
    secret_client = secretmanager.SecretManagerServiceClient()
    firestore_client = firestore.Client()
    storage_client = storage.Client()
except Exception as e:
    logger.error(json.dumps({
        "severity": "CRITICAL",
        "message": "Failed to initialize Google Cloud clients.",
        "error": str(e)
    }))
    raise

PROCESSOR_VERSION = "1.0.0"
ENVIRONMENT = os.environ.get("ENVIRONMENT", "production")

def get_secret(project_id: str, secret_id: str, version_id: str = "latest") -> dict:
    """
    Securely retrieves enterprise configuration from Secret Manager.
    """
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
    try:
        response = secret_client.access_secret_version(request={"name": name})
        payload = response.payload.data.decode("UTF-8")
        return json.loads(payload)
    except Exception as e:
        logger.error(json.dumps({
            "severity": "ERROR",
            "message": f"Failed to access secret {secret_id}",
            "error": str(e)
        }))
        raise

@functions_framework.cloud_event
def process_asset(cloud_event: CloudEvent):
    """
    Eventarc trigger that processes newly uploaded assets in the Secure Vault.
    """
    event_id = cloud_event["id"]
    event_time = cloud_event["time"]
    
    logger.info(json.dumps({
        "severity": "INFO",
        "message": f"Received CloudEvent ID: {event_id}",
        "eventType": cloud_event["type"],
        "eventId": event_id
    }))

    try:
        # Extract payload
        data = cloud_event.data
        
        bucket_name = data.get("bucket")
        file_name = data.get("name")
        
        if not bucket_name or not file_name:
            raise ValueError("Event data missing 'bucket' or 'name' fields.")
            
        project_id = os.environ.get("PROJECT_ID")
        secret_id = os.environ.get("SECRET_ID", "enterprise-config")
        
        if not project_id:
            # Fallback to fetching project ID from environment if possible
            project_id = os.environ.get("GCP_PROJECT", os.environ.get("GOOGLE_CLOUD_PROJECT"))
        
        # 1. Read configuration securely
        config = get_secret(project_id, secret_id)
        
        logger.info(json.dumps({
            "severity": "INFO",
            "message": "Successfully retrieved configuration from Secret Manager.",
            "eventId": event_id
        }))
        
        # 2. Collect metadata
        metadata = {
            "fileName": file_name,
            "bucket": bucket_name,
            "generation": data.get("generation"),
            "contentType": data.get("contentType"),
            "size": int(data.get("size", 0)),
            "crc32c": data.get("crc32c"),
            "md5Hash": data.get("md5Hash"),
            "storageClass": data.get("storageClass"),
            "eventId": event_id,
            "uploadedTimestamp": event_time,
            "processedTimestamp": datetime.now(timezone.utc).isoformat(),
            "processorVersion": PROCESSOR_VERSION,
            "environment": ENVIRONMENT,
            "status": "PROCESSED",
            "configApplied": config.get("processing_mode", "standard")
        }
        
        # 3. Store metadata inside Firestore
        collection_name = "asset-catalog"
        doc_ref = firestore_client.collection(collection_name).document()
        doc_ref.set(metadata)
        
        logger.info(json.dumps({
            "severity": "INFO",
            "message": f"Successfully processed asset and updated catalog.",
            "metadata": metadata,
            "firestoreDocumentId": doc_ref.id,
            "eventId": event_id
        }))
        
        return "OK", 200

    except Exception as e:
        logger.error(json.dumps({
            "severity": "ERROR",
            "message": "Error processing asset event.",
            "error": str(e),
            "eventId": event_id
        }))
        # Re-raise to ensure event delivery can be retried if configured
        raise
