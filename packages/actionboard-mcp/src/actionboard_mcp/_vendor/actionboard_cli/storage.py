"""ActionBoard CLI: storage."""
import base64
import datetime
import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

def _sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signature_key(secret_key, date_stamp, region_name, service_name):
    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region_name)
    k_service = _sign(k_region, service_name)
    k_signing = _sign(k_service, "aws4_request")
    return k_signing


def upload_bytes_to_s3(bucket, region, key, body_bytes, content_type, aws_creds, metadata=None, opener=None):
    """Upload bytes to S3 using AWS Signature Version 4 (standard library only)."""
    if not aws_creds or not aws_creds.get("access_key") or not aws_creds.get("secret_key"):
        raise RuntimeError(
            "AWS credentials not found for S3 upload. Set AWS_ACCESS_KEY_ID and "
            "AWS_SECRET_ACCESS_KEY, configure ~/.aws/credentials, or run "
            "`python submit_mission.py configure --aws-access-key-id ... --aws-secret-access-key ...`."
        )

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    host = "%s.s3.%s.amazonaws.com" % (bucket, region)
    # Encode URI path segments per RFC 3986
    canonical_uri = "/" + "/".join(urllib.parse.quote(seg, safe="-_.~") for seg in key.lstrip("/").split("/"))
    payload_hash = hashlib.sha256(body_bytes).hexdigest()

    headers_to_sign = {
        "content-type": content_type,
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if aws_creds.get("session_token"):
        headers_to_sign["x-amz-security-token"] = aws_creds["session_token"]

    if metadata:
        for mk, mv in metadata.items():
            clean_k = re.sub(r"[^a-z0-9_-]", "", str(mk).lower())
            clean_v = re.sub(r"[^\x20-\x7e]", "", str(mv)).strip()
            if clean_k and clean_v:
                headers_to_sign["x-amz-meta-" + clean_k] = clean_v

    sorted_header_keys = sorted(headers_to_sign.keys())
    canonical_headers = "".join("%s:%s\n" % (k, headers_to_sign[k]) for k in sorted_header_keys)
    signed_headers = ";".join(sorted_header_keys)

    canonical_request = "\n".join([
        "PUT",
        canonical_uri,
        "",
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = "%s/%s/s3/aws4_request" % (date_stamp, region)
    string_to_sign = "\n".join([
        algorithm,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    signing_key = _get_signature_key(aws_creds["secret_key"], date_stamp, region, "s3")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization_header = (
        "%s Credential=%s/%s, SignedHeaders=%s, Signature=%s"
        % (algorithm, aws_creds["access_key"], credential_scope, signed_headers, signature)
    )

    url = "https://%s%s" % (host, canonical_uri)
    req_headers = {k: v for k, v in headers_to_sign.items() if k != "host"}
    req_headers["Authorization"] = authorization_header
    req_headers["Content-Length"] = str(len(body_bytes))

    req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method="PUT")
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(req, timeout=60) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError("S3 PUT HTTP %s for %s: %s" % (exc.code, url, err_body or exc.reason))
    except urllib.error.URLError as exc:
        raise RuntimeError("S3 network error for %s: %s" % (url, exc.reason))

    return {
        "bucket": bucket,
        "key": key.lstrip("/"),
        "size": len(body_bytes),
        "region": region,
        "s3_uri": "s3://%s/%s" % (bucket, key.lstrip("/")),
        "url": "https://%s/%s" % (host, key.lstrip("/")),
    }


def upload_bytes_via_pod(pod_hostname, pod_id, board_id, file_name, body_bytes, content_type, folder_name="missions", opener=None):
    """Upload through the pod web app's own upload route (what the web UI uses), so no AWS keys are needed."""
    from .common import DEFAULT_S3_REGION
    boundary = "----actionboardcli%s" % base64.b16encode(os.urandom(12)).decode("ascii")
    safe_name = file_name.replace('"', "").replace("\r", "").replace("\n", "")
    chunks = []
    for name, value in (("boardId", board_id), ("fileName", safe_name), ("folderName", folder_name)):
        chunks.append(
            ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (boundary, name, value)).encode("utf-8")
        )
    chunks.append(
        ('--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\nContent-Type: %s\r\n\r\n'
         % (boundary, safe_name, content_type)).encode("utf-8")
    )
    chunks.append(body_bytes)
    chunks.append(("\r\n--%s--\r\n" % boundary).encode("utf-8"))

    url = "https://%s/api/s3/knowledge-base/upload" % pod_hostname
    req = urllib.request.Request(
        url,
        data=b"".join(chunks),
        headers={
            "Content-Type": "multipart/form-data; boundary=%s" % boundary,
            "Cookie": "podId=%s" % pod_id,
            "Accept": "application/json",
            "User-Agent": "ActionBoard-CLI/1.2",
        },
        method="POST",
    )
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError("pod upload HTTP %s for %s: %s" % (exc.code, file_name, err_body[:300] or exc.reason))
    except urllib.error.URLError as exc:
        raise RuntimeError("pod upload network error (%s): %s" % (url, exc.reason))

    try:
        res = json.loads(raw)
    except ValueError:
        res = {}
    if not isinstance(res, dict) or not res.get("bucket") or not res.get("key"):
        raise RuntimeError("pod upload for %s returned no S3 location: %s" % (file_name, raw[:300]))
    region = res.get("region") or DEFAULT_S3_REGION
    return {
        "bucket": res["bucket"],
        "key": res["key"],
        "size": len(body_bytes),
        "region": region,
        "s3_uri": res.get("fileUri") or "s3://%s/%s" % (res["bucket"], res["key"]),
        "url": res.get("fileUrl") or "https://%s.s3.%s.amazonaws.com/%s" % (res["bucket"], region, res["key"]),
    }


def download_bytes_from_s3(bucket, region, key, aws_creds, opener=None):
    """Download bytes from S3 using AWS Signature Version 4 GET (standard library only)."""
    if not aws_creds or not aws_creds.get("access_key") or not aws_creds.get("secret_key"):
        raise RuntimeError("AWS credentials not configured for S3 download")

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    host = "%s.s3.%s.amazonaws.com" % (bucket, region)
    canonical_uri = "/" + "/".join(urllib.parse.quote(seg, safe="-_.~") for seg in key.lstrip("/").split("/"))
    payload_hash = hashlib.sha256(b"").hexdigest()

    headers_to_sign = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if aws_creds.get("session_token"):
        headers_to_sign["x-amz-security-token"] = aws_creds["session_token"]

    sorted_header_keys = sorted(headers_to_sign.keys())
    canonical_headers = "".join("%s:%s\n" % (k, headers_to_sign[k]) for k in sorted_header_keys)
    signed_headers = ";".join(sorted_header_keys)

    canonical_request = "\n".join([
        "GET",
        canonical_uri,
        "",
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = "%s/%s/s3/aws4_request" % (date_stamp, region)
    string_to_sign = "\n".join([
        algorithm,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    signing_key = _get_signature_key(aws_creds["secret_key"], date_stamp, region, "s3")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization_header = (
        "%s Credential=%s/%s, SignedHeaders=%s, Signature=%s"
        % (algorithm, aws_creds["access_key"], credential_scope, signed_headers, signature)
    )

    url = "https://%s%s" % (host, canonical_uri)
    req_headers = {k: v for k, v in headers_to_sign.items() if k != "host"}
    req_headers["Authorization"] = authorization_header

    req = urllib.request.Request(url, headers=req_headers, method="GET")
    open_fn = opener or urllib.request.urlopen
    with open_fn(req, timeout=60) as resp:
        return resp.read()


