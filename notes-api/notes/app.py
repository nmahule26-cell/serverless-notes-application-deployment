import json, os, uuid, time
from decimal import Decimal
import boto3

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])

def resp(status, body=None):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=lambda o: int(o) if isinstance(o, Decimal) else str(o)) if body is not None else "",
    }

def handler(event, context):
    method = event["requestContext"]["http"]["method"]
    note_id = (event.get("pathParameters") or {}).get("id")

    if method == "POST":
        data = json.loads(event.get("body") or "{}")
        if not data.get("title"):
            return resp(400, {"error": "title is required"})
        item = {"id": str(uuid.uuid4()), "title": data["title"],
                "content": data.get("content", ""), "createdAt": int(time.time())}
        table.put_item(Item=item)
        return resp(201, item)

    if method == "GET" and note_id:
        item = table.get_item(Key={"id": note_id}).get("Item")
        return resp(200, item) if item else resp(404, {"error": "not found"})

    if method == "GET":
        return resp(200, table.scan(Limit=50).get("Items", []))

    if method == "DELETE" and note_id:
        table.delete_item(Key={"id": note_id})
        return resp(204)

    return resp(405, {"error": "method not allowed"})
