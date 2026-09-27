import json, os, uuid
import boto3

s3 = boto3.client("s3")

def handler(event, context):
    body = json.loads(event.get("body") or "{}")
    key = f"attachments/{uuid.uuid4()}-{body.get('filename', 'file')}"
    url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": os.environ["BUCKET_NAME"], "Key": key},
        ExpiresIn=300,
    )
    return {"statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"uploadUrl": url, "key": key})}
