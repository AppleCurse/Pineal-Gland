"""Postiz mantığında şifreli oturum/çerez deposu.

Oturum bilgileri düz metin diskte SAKLANMAZ; AES-GCM ile şifrelenir ve
(platform, hesap) bazında yalıtılır. Anahtar SESSION_STORE_KEY (32/64 hex)
ortam değişkeninden PBKDF2 ile türetilir.

Bağımlılık: cryptography  (pip install cryptography)
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_core.session_store")


class SessionStoreError(RuntimeError):
    pass


class SessionStore:
    def __init__(self, path: str, key_hex: str):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._enabled = bool(key_hex)
        self._key: Optional[bytes] = None
        if self._enabled:
            self._key = self._derive_key(key_hex)
        else:
            logger.warning("SESSION_STORE_KEY bos — oturum depolama devre disi")

    @staticmethod
    def _derive_key(key_hex: str) -> bytes:
        try:
            raw = bytes.fromhex(key_hex)
        except ValueError as exc:
            raise SessionStoreError("SESSION_STORE_KEY hex formatında olmalı") from exc
        if len(raw) not in (32, 64):
            raise SessionStoreError("SESSION_STORE_KEY 32 veya 64 hex karakter olmalı")
        return hashlib.pbkdf2_hmac("sha256", raw, b"agent-cockpit-session", 200_000, dklen=32)

    # -- şifreleme ----------------------------------------------------------
    def _encrypt(self, payload: str) -> str:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise SessionStoreError("cryptography paketi gerekli: pip install cryptography") from exc
        nonce = secrets.token_bytes(12)
        ct = AESGCM(self._key).encrypt(nonce, payload.encode("utf-8"), None)
        return base64.b64encode(nonce + ct).decode()

    def _decrypt(self, blob: str) -> str:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise SessionStoreError("cryptography paketi gerekli: pip install cryptography") from exc
        try:
            data = base64.b64decode(blob)
            nonce, ct = data[:12], data[12:]
            return AESGCM(self._key).decrypt(nonce, ct, None).decode("utf-8")
        except Exception as exc:
            raise SessionStoreError(f"oturum çözülemedi (anahtar değişmiş olabilir): {exc}") from exc

    # -- disk ----------------------------------------------------------------
    def _load_disk(self) -> Dict[str, Dict[str, str]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("oturum dosyası okunamadı: %s", exc)
            return {}

    def _flush(self, data: Dict[str, Dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # -- API -----------------------------------------------------------------
    def save(self, platform: str, account: str, cookies: Dict[str, Any], refresh_token: Optional[str] = None) -> None:
        """Oturumu şifreleyip (platform, hesap) altına kaydeder."""
        if not self._enabled:
            logger.debug("session_store devre disi — save atlandi")
            return
        from datetime import datetime, timezone

        record = {"cookies": cookies}
        record["saved_at"] = datetime.now(timezone.utc).isoformat()
        if refresh_token:
            record["refresh_token"] = refresh_token
        encrypted = self._encrypt(json.dumps(record, ensure_ascii=False))
        with self._lock:
            data = self._load_disk()
            data.setdefault(platform, {})[account] = encrypted
            self._flush(data)
        logger.info("oturum kaydedildi: %s / %s", platform, account)

    def load(self, platform: str, account: str) -> Optional[Dict[str, Any]]:
        if not self._enabled:
            return None
        with self._lock:
            data = self._load_disk()
            blob = data.get(platform, {}).get(account)
            if not blob:
                return None
            try:
                return json.loads(self._decrypt(blob))
            except SessionStoreError as exc:
                logger.error("oturum okunamadı: %s", exc)
                return None

    def delete(self, platform: str, account: str) -> bool:
        if not self._enabled:
            return False
        with self._lock:
            data = self._load_disk()
            bucket = data.get(platform)
            if bucket and account in bucket:
                del bucket[account]
                self._flush(data)
                logger.info("oturum silindi: %s / %s", platform, account)
                return True
        return False

    def list_accounts(self, platform: Optional[str] = None) -> List[str]:
        if not self._enabled:
            return []
        with self._lock:
            data = self._load_disk()
            if platform:
                return list(data.get(platform, {}).keys())
            return [f"{p}/{a}" for p, accs in data.items() for a in accs]

    def rotate_refresh_token(self, platform: str, account: str, new_token: str) -> bool:
        """Eski oturumu yeni refresh token ile yeniler (Postiz token döndürme mantığı)."""
        record = self.load(platform, account)
        if record is None:
            return False
        record["refresh_token"] = new_token
        self.save(platform, account, record.get("cookies", {}), refresh_token=new_token)
        return True
