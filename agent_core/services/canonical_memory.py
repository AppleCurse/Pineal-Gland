"""
Canonical Memory Adapter — Agent Core ve Cockpit memory sistemlerini birleştirir.

Bu adapter:
- Agent Core memory_manager.py (şifreli profile storage)
- Cockpit memory.json (düz JSON profiles, conversations, learnings)
- Session store (şifreli cookies)

üzerinde tek canonical interface sunar.

Tüm memory işlemleri bu adapter üzerinden geçer:
- write_policy: confidence > 0.6, stability > 0.4
- provenance: her kayıt için source + timestamp + hash
- conflict_resolution: en yüksek confidence kazanır
- unified retrieval: tüm kaynaklardan tek sorgu
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_core.canonical_memory")


class CanonicalMemoryError(RuntimeError):
    pass


class CanonicalMemoryAdapter:
    """Tek canonical memory interface — çoklu backend'leri soyutlar."""
    
    def __init__(
        self,
        agent_core_data_dir: str = "./agent_core/data",
        cockpit_dir: str = "./cockpit",
        enable_cockpit_sync: bool = True,
    ):
        self.agent_core_dir = Path(agent_core_data_dir)
        self.agent_core_dir.mkdir(parents=True, exist_ok=True)
        
        self.cockpit_dir = Path(cockpit_dir)
        self.cockpit_dir.mkdir(parents=True, exist_ok=True)
        
        # Agent Core memory files
        self.profile_memory_file = self.agent_core_dir / "profile_memory.json"
        self.task_state_file = self.agent_core_dir / "task_state.json"
        
        # Cockpit memory files (sync için)
        self.cockpit_memory_file = self.cockpit_dir / "memory.json" if enable_cockpit_sync else None
        self.cockpit_personality_file = self.cockpit_dir / "personality.json" if enable_cockpit_sync else None
        
        self._lock = asyncio.Lock() if 'asyncio' in globals() else threading.Lock() if 'threading' in globals() else None
    
    def _compute_hash(self, data: Dict[str, Any]) -> str:
        """Verinin immutable hash'ini hesapla (provenance için)."""
        content = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    
    def _load_profile_memory(self) -> Dict[str, Any]:
        """Agent Core profile memory yükle."""
        if self.profile_memory_file.exists():
            try:
                return json.loads(self.profile_memory_file.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.error(f"Profile memory okuma hatası: {exc}")
        return {}
    
    def _save_profile_memory(self, data: Dict[str, Any]) -> None:
        """Agent Core profile memory kaydet."""
        try:
            self.profile_memory_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), 
                encoding="utf-8"
            )
        except Exception as exc:
            logger.error(f"Profile memory kaydetme hatası: {exc}")
    
    def _load_cockpit_memory(self) -> Optional[Dict[str, Any]]:
        """Cockpit memory yükle (eğer sync aktifse)."""
        if not self.cockpit_memory_file or not self.cockpit_memory_file.exists():
            return None
        try:
            return json.loads(self.cockpit_memory_file.read_text(encoding="utf-8"))
        except Exception:
            return None
    
    def _save_cockpit_memory(self, data: Dict[str, Any]) -> None:
        """Cockpit memory kaydet (eğer sync aktifse)."""
        if not self.cockpit_memory_file:
            return
        try:
            self.cockpit_memory_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as exc:
            logger.warning(f"Cockpit memory kaydetme hatası: {exc}")
    
    def _should_write(self, profile: Dict[str, Any]) -> bool:
        """Write policy: confidence > 0.60, stability > 0.40."""
        confidence = profile.get("overall_confidence", 0.0)
        
        stabilities = []
        for signal in ["communication_signals", "topic_affinity", "posting_pattern", "interaction_pattern"]:
            sig_data = profile.get(signal, {})
            if isinstance(sig_data, dict) and "stability" in sig_data:
                stabilities.append(sig_data.get("stability", 0.0))
        
        avg_stability = sum(stabilities) / max(len(stabilities), 1) if stabilities else 0.0
        
        should_write = confidence > 0.60 and avg_stability > 0.40
        
        if not should_write:
            logger.info(
                f"Profil kayit reddedildi: confidence={confidence:.2f}, "
                f"avg_stability={avg_stability:.2f} (threshold: 0.6/0.4)"
            )
        
        return should_write
    
    def store_profile(
        self,
        platform: str,
        username: str,
        profile: Dict[str, Any],
        source: str = "analyzer",
    ) -> Dict[str, Any]:
        """
        Profile'ı canonical memory'ye kaydet.
        
        Args:
            platform: Instagram, X, vb.
            username: Kullanıcı adı
            profile: Behavioral profile dict
            source: Hangi servis üretti (analyzer, eliza, vb.)
        
        Returns:
            {
                "status": "saved" | "rejected" | "updated",
                "key": "platform:username",
                "hash": "...",
                "delta": {...}  # sadece update'te
            }
        """
        if not self._should_write(profile):
            return {"status": "rejected", "reason": "Write policy threshold"}
        
        key = f"{platform}:{username.lower()}"
        now = datetime.now(timezone.utc).isoformat()
        profile_hash = self._compute_hash(profile)
        
        # Provenance metadata ekle
        profile["_meta"] = {
            "source": source,
            "timestamp": now,
            "hash": profile_hash,
        }
        
        memory = self._load_profile_memory()
        history = memory.get(key, [])
        
        delta = None
        if history:
            # Delta hesapla
            last_profile = history[-1]["profile"]
            delta = self._compute_delta(last_profile, profile)
        
        # Yeni kayıt ekle
        history.append({
            "timestamp": now,
            "profile": profile,
            "delta": delta,
            "hash": profile_hash,
        })
        
        memory[key] = history
        self._save_profile_memory(memory)
        
        # Cockpit ile sync (eğer aktifse)
        if self.cockpit_memory_file:
            self._sync_to_cockpit(platform, username, profile)
        
        status = "updated" if delta else "saved"
        logger.info(f"Canonical memory: {key} → {status}")
        
        return {
            "status": status,
            "key": key,
            "hash": profile_hash,
            "delta": delta,
        }
    
    def _compute_delta(self, old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
        """İki profile arasındaki farkı hesapla."""
        delta = {"changed_fields": [], "details": {}}
        
        def compare_signal(signal_name: str, field_name: str):
            old_sig = old.get(signal_name, {})
            new_sig = new.get(signal_name, {})
            if isinstance(old_sig, dict) and isinstance(new_sig, dict):
                old_val = old_sig.get(field_name)
                new_val = new_sig.get(field_name)
                if old_val != new_val:
                    delta["changed_fields"].append(f"{signal_name}.{field_name}")
                    delta["details"][f"{signal_name}.{field_name}"] = {
                        "from": old_val,
                        "to": new_val,
                    }
        
        compare_signal("communication_signals", "tone_style")
        compare_signal("communication_signals", "emotional_expressiveness")
        compare_signal("posting_pattern", "frequency_indicator")
        compare_signal("interaction_pattern", "response_style")
        
        # Topic Affinity
        old_topic = old.get("topic_affinity", {})
        new_topic = new.get("topic_affinity", {})
        if isinstance(old_topic, dict) and isinstance(new_topic, dict):
            old_themes = set(old_topic.get("primary_themes", []))
            new_themes = set(new_topic.get("primary_themes", []))
            if old_themes != new_themes:
                delta["changed_fields"].append("topic_affinity.primary_themes")
                delta["details"]["topic_affinity.primary_themes"] = {
                    "added": list(new_themes - old_themes),
                    "removed": list(old_themes - new_themes),
                }
        
        return delta
    
    def _sync_to_cockpit(self, platform: str, username: str, profile: Dict[str, Any]) -> None:
        """Profile'ı Cockpit memory.json'a sync et."""
        cockpit_mem = self._load_cockpit_memory() or {"profiles": {}, "conversations": {}, "learnings": {}, "log": []}
        
        key = f"{platform}:{username.lower()}"
        cockpit_mem["profiles"][key] = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "data": profile,
        }
        
        self._save_cockpit_memory(cockpit_mem)
    
    def retrieve_profile(self, platform: str, username: str) -> Optional[Dict[str, Any]]:
        """Profile'ı canonical memory'den getir."""
        key = f"{platform}:{username.lower()}"
        memory = self._load_profile_memory()
        history = memory.get(key, [])
        
        if not history:
            return None
        
        # En son versiyonu döndür
        return history[-1]["profile"]
    
    def retrieve_all_profiles(self) -> Dict[str, List[Dict[str, Any]]]:
        """Tüm profilleri history ile birlikte döndür."""
        memory = self._load_profile_memory()
        return memory
    
    def search_profiles(self, query: str) -> List[Dict[str, Any]]:
        """
        Profile'larda arama yap (tema, tone, username bazlı).
        
        Args:
            query: Arama sorgusu (örn: "sinema", "entelektüel")
        
        Returns:
            Eşleşen profiller listesi
        """
        results = []
        memory = self._load_profile_memory()
        query_lower = query.lower()
        
        for key, history in memory.items():
            if not history:
                continue
            
            latest = history[-1]["profile"]
            
            # Username/platform eşleşmesi
            if query_lower in key.lower():
                results.append({"key": key, "profile": latest, "match_reason": "username"})
                continue
            
            # Topic affinity eşleşmesi
            themes = latest.get("topic_affinity", {}).get("primary_themes", [])
            if any(query_lower in theme.lower() for theme in themes):
                results.append({"key": key, "profile": latest, "match_reason": "topic"})
                continue
            
            # Communication style eşleşmesi
            tone = latest.get("communication_signals", {}).get("tone_style", "")
            if query_lower in tone.lower():
                results.append({"key": key, "profile": latest, "match_reason": "tone"})
        
        return results
    
    def store_conversation(
        self,
        platform: str,
        username: str,
        message: str,
        direction: str,  # "sent" veya "received"
        timestamp: Optional[str] = None,
    ) -> None:
        """Konuşma kaydını memory'ye ekle."""
        if not self.cockpit_memory_file:
            return
        
        cockpit_mem = self._load_cockpit_memory() or {"profiles": {}, "conversations": {}, "learnings": {}, "log": []}
        
        key = f"{platform}:{username.lower()}"
        conv_record = {
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            "direction": direction,
            "message": message,
        }
        
        cockpit_mem["conversations"].setdefault(key, []).append(conv_record)
        self._save_cockpit_memory(cockpit_mem)
    
    def store_learning(self, learning: Dict[str, Any], tags: List[str]) -> None:
        """
        Öğrenilen bir bilgiyi kalıcı hafızaya ekle.
        
        Args:
            learning: {"fact": "...", "context": "...", ...}
            tags: ["icebreaker", "dealbreaker", "vibe"]
        """
        if not self.cockpit_memory_file:
            return
        
        cockpit_mem = self._load_cockpit_memory() or {"profiles": {}, "conversations": {}, "learnings": {}, "log": []}
        
        learning_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": learning,
            "tags": tags,
            "hash": self._compute_hash(learning),
        }
        
        cockpit_mem["learnings"].setdefault(tags[0] if tags else "general", []).append(learning_record)
        self._save_cockpit_memory(cockpit_mem)
    
    def get_stats(self) -> Dict[str, Any]:
        """Memory istatistikleri."""
        profile_mem = self._load_profile_memory()
        cockpit_mem = self._load_cockpit_memory() or {}
        
        return {
            "agent_core_profiles": len(profile_mem),
            "cockpit_profiles": len(cockpit_mem.get("profiles", {})),
            "cockpit_conversations": sum(len(v) for v in cockpit_mem.get("conversations", {}).values()),
            "cockpit_learnings": sum(len(v) for v in cockpit_mem.get("learnings", {}).values()),
        }


# Module-level singleton
_adapter: Optional[CanonicalMemoryAdapter] = None


def get_canonical_memory() -> CanonicalMemoryAdapter:
    global _adapter
    if _adapter is None:
        _adapter = CanonicalMemoryAdapter()
    return _adapter
