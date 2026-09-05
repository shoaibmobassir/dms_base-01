"""
Manifest Signer: Generates Tamper-Evident Signed Legal Export ZIP Packages (SHA-256 + HMAC/Ed25519).
Clean-room independent implementation.
"""

from datetime import datetime
import hashlib
import hmac
import io
import json
import os
from typing import Any, Dict, List, Tuple
import zipfile


class ManifestSigner:
    """Creates cryptographically verifiable legal export bundles."""

    def __init__(self, signing_secret: str = "firmos-tamper-evident-export-signing-secret-2026"):
        self.secret = os.environ.get("DOWNLOAD_SIGNING_SECRET", signing_secret).encode("utf-8")

    def build_signed_export_zip(
        self,
        export_title: str,
        files: List[Tuple[str, bytes]],  # (relative_path, content_bytes)
        metadata: Dict[str, Any],
    ) -> bytes:
        zip_buffer = io.BytesIO()
        manifest_files: List[Dict[str, Any]] = []

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Write each payload file and compute its SHA-256 hash
            for path, data in files:
                zf.writestr(path, data)
                sha256_hash = hashlib.sha256(data).hexdigest()
                manifest_files.append({
                    "path": path,
                    "sha256": sha256_hash,
                    "byte_size": len(data),
                })

            # 2. Construct Manifest object
            manifest_obj = {
                "title": export_title,
                "created_at": datetime.utcnow().isoformat() + "Z",
                "issuer": "FirmOS Legal Intelligence & DMS",
                "spec_version": "1.0-tamper-evident",
                "metadata": metadata,
                "files": manifest_files,
            }

            # 3. Compute cryptographic signature over the canonical manifest JSON
            canonical_manifest_bytes = json.dumps(manifest_obj, sort_keys=True).encode("utf-8")
            signature = hmac.new(self.secret, canonical_manifest_bytes, hashlib.sha256).hexdigest()
            manifest_obj["hmac_sha256_signature"] = signature

            # 4. Write manifest.json into the root of the ZIP
            zf.writestr("MANIFEST.json", json.dumps(manifest_obj, indent=2))

        return zip_buffer.getvalue()

    def verify_manifest(self, manifest_json_str: str) -> bool:
        """Verifies if the manifest signature is valid and authentic."""
        try:
            data = json.loads(manifest_json_str)
            sig = data.pop("hmac_sha256_signature", None)
            if not sig:
                return False
            canonical = json.dumps(data, sort_keys=True).encode("utf-8")
            expected_sig = hmac.new(self.secret, canonical, hashlib.sha256).hexdigest()
            return hmac.compare_digest(sig, expected_sig)
        except Exception:
            return False


_signer_instance: Optional[ManifestSigner] = None


def get_manifest_signer() -> ManifestSigner:
    global _signer_instance
    if _signer_instance is None:
        _signer_instance = ManifestSigner()
    return _signer_instance
