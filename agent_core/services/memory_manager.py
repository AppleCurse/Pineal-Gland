import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("agent_core.memory_manager")

class MemoryManager:
    """Manages the persistent memory of BehavioralProfiles.

    Responsibilities:
    1. Write Policy: Decides whether a new profile should be saved based on confidence/stability.
    2. Delta Tracking: Compares a new profile to the last saved one and records differences.
    3. Semantic Graph Preparation: Formats memory queries for reasoning/planning.
    """

    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.memory_file = self.data_dir / "profile_memory.json"

    def _load(self) -> Dict[str, Any]:
        if self.memory_file.exists():
            try:
                return json.loads(self.memory_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.error(f"Memory okuma hatası: {e}")
        return {}

    def _save(self, data: Dict[str, Any]) -> None:
        try:
            self.memory_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Memory kaydetme hatası: {e}")

    def _should_write(self, profile: Dict[str, Any]) -> bool:
        """Write policy: confidence > 0.60, stability > 0.40."""
        confidence = profile.get("overall_confidence", 0.0)

        # We also want to check stability. Since it's nested, we'll take an average of stabilities
        # or require at least one signal to be stable. Let's average them.
        stabilities = []
        for signal in ["communication_signals", "topic_affinity", "posting_pattern", "interaction_pattern"]:
            sig_data = profile.get(signal, {})
            if isinstance(sig_data, dict) and "stability" in sig_data:
                stabilities.append(sig_data.get("stability", 0.0))

        avg_stability = sum(stabilities) / max(len(stabilities), 1) if stabilities else 0.0

        if confidence > 0.60 and avg_stability > 0.40:
            return True

        logger.info(f"Profil kayit reddedildi: confidence={confidence:.2f}, avg_stability={avg_stability:.2f}")
        return False

    def process_profile(self, platform: str, username: str, new_profile: Dict[str, Any]) -> Dict[str, Any]:
        """Process a newly analyzed profile. Tracks deltas and saves if policy allows."""
        if not self._should_write(new_profile):
            return {"status": "rejected", "reason": "Did not meet write policy thresholds (confidence > 0.6, stability > 0.4)"}

        key = f"{platform}:{username.lower()}"
        memory = self._load()

        history = memory.get(key, [])
        now = datetime.now(timezone.utc).isoformat()

        if not history:
            history.append({
                "timestamp": now,
                "profile": new_profile,
                "delta": None
            })
            memory[key] = history
            self._save(memory)
            return {"status": "new", "delta": None}

        last_record = history[-1]
        last_profile = last_record["profile"]

        # Compare profiles
        delta = self._compare(last_profile, new_profile)

        # Only save if there's a meaningful difference, or just save the latest point in time?
        # A good policy is to append to history.
        history.append({
            "timestamp": now,
            "profile": new_profile,
            "delta": delta
        })
        memory[key] = history
        self._save(memory)

        return {"status": "updated", "delta": delta}

    def _compare(self, old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
        """Compares two profiles and returns the delta."""
        delta = {"changed_fields": [], "details": {}}

        # Helper to compare specific fields inside a signal
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
                        "evidence": new_sig.get("evidence", [])
                    }

        compare_signal("communication_signals", "tone_style")
        compare_signal("communication_signals", "emotional_expressiveness")
        compare_signal("posting_pattern", "frequency_indicator")
        compare_signal("interaction_pattern", "response_style")
        compare_signal("interaction_pattern", "conflict_engagement")

        # Topic Affinity (Lists)
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
                    "evidence": new_topic.get("evidence", [])
                }

        return delta

    def get_behavioral_evolution(self, platform: str, username: str) -> Optional[Dict[str, Any]]:
        """Provides a timeline of how the user's behavior has evolved.
        This prepares the memory system to act as a semantic graph node for the Planner.
        """
        key = f"{platform}:{username.lower()}"
        memory = self._load()
        history = memory.get(key, [])

        if not history:
            return None

        evolution = {
            "entity": key,
            "observations_count": len(history),
            "first_seen": history[0]["timestamp"],
            "last_seen": history[-1]["timestamp"],
            "significant_shifts": []
        }

        for record in history:
            if record.get("delta") and record["delta"].get("changed_fields"):
                evolution["significant_shifts"].append({
                    "timestamp": record["timestamp"],
                    "changes": record["delta"]["changed_fields"],
                    "details": record["delta"]["details"]
                })

        return evolution
