"""Deterministic telemetry analysis. The voice model never calculates lap deltas."""
from __future__ import annotations

import bisect
import json
import math
import time
import uuid
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .telemetry import Sample
from .race import RaceAwareness
from .profile import DrivingProfile
from .corners import CornerCoach, learn_turns


def lap_time(ms):
    return f"{int(ms // 60000)}:{(ms % 60000) / 1000:06.3f}"


class CoachEngine:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.identity = None
        self.previous = None
        self.reference = None
        self.events = deque(maxlen=30)
        self.laps = []
        self.cooldowns = {}
        self.sustained = {}
        self.sectors = []
        self.last_voice = -100
        self.session_id = uuid.uuid4().hex[:12]
        self.race = RaceAwareness()
        self.profile = None
        self.corners = CornerCoach()
        self.reset_lap(False)

    def reset_lap(self, full):
        self.samples = []
        self.bins = set()
        self.full_lap = full
        self.clean = True
        self.issues = Counter()
        self.sectors = []
        self.last_sector = None
        self.sustained = {}
        self.lap_hints = set()

    def emit(self, kind, text, now, cooldown=12, voice=True, priority=False):
        if now - self.cooldowns.get(kind, -100) < cooldown:
            return
        self.cooldowns[kind] = now
        speak = voice and (priority or kind in ("lap","overtake","position","position_lost") or now - self.last_voice >= 9)
        if speak:
            self.last_voice = now
        event = {"id": uuid.uuid4().hex, "kind": kind, "text": text,
                 "lap": self.previous.lap+1 if self.previous else 1,
                 "time": datetime.now(timezone(timedelta(hours=10))).strftime("%H:%M:%S"), "speak": speak}
        self.events.appendleft(event)
        if kind in ("understeer", "oversteer", "off_track", "incident", "overtake"):
            self.issues[kind] += 1
        return event

    def reference_path(self):
        import hashlib
        name = hashlib.sha256(json.dumps(self.identity).encode()).hexdigest()[:20]
        return self.data_dir / "references" / f"{name}.json"

    def set_identity(self, sample):
        self.identity = (sample.source, sample.car, sample.track, sample.configuration)
        self.reference = None
        self.laps = []
        self.events.clear()
        self.cooldowns.clear()
        self.last_voice = -100
        self.session_id = uuid.uuid4().hex[:12]
        try:
            data = json.loads(self.reference_path().read_text(encoding="utf-8"))
            if data.get("identity") == list(self.identity) and len(data["samples"]) > 20:
                self.reference = data
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.reset_lap(sample.progress < 0.02 and sample.lap_ms < 2000)
        self.previous = None
        self.race = RaceAwareness()
        self.profile = DrivingProfile(self.data_dir,self.identity)
        self.corners = CornerCoach(learn_turns(self.reference['samples']) if self.reference else [])

    def ref_at(self, progress):
        if not self.reference:
            return None
        points = self.reference["samples"]
        i = bisect.bisect_left([p["p"] for p in points], progress)
        if i >= len(points):
            return None
        if i == 0:
            return points[0] if progress >= points[0]["p"] else None
        a, b = points[i - 1], points[i]
        weight = (progress - a["p"]) / max(1e-8, b["p"] - a["p"])
        return {key: a[key] + (b[key] - a[key]) * weight for key in ("p", "ms", "speed")}

    def finish_lap(self, s):
        if not self.samples:
            return
        complete = (self.full_lap and self.samples[-1]["p"] > 0.97
                    and s.last_ms > 0 and len(self.samples) > 20)
        eligible = complete and self.clean
        old_best = self.reference["time_ms"] if self.reference else None
        best = eligible and (old_best is None or s.last_ms < old_best)
        profile_report=self.profile.finish_lap(s.last_ms,complete,eligible)
        sector_times = list(self.sectors)
        if complete and len(sector_times) == s.sector_count - 1:
            sector_times.append(max(0, s.last_ms - sum(sector_times)))
        summary = {"lap": s.lap, "time_ms": s.last_ms, "clean": eligible,
            "partial": not complete, "best": best,
            "delta_ms": s.last_ms - old_best if old_best else None,
            "max_speed": round(max(p["speed"] for p in self.samples), 1),
            "issues": dict(self.issues), "sectors": sector_times,
            "position": s.position or None,
            "driving_stats":profile_report,
            "corner_exits":dict(self.corners.laps.get(s.lap-1,{'observed_turns':0,'clean_exits':0})),
            "timestamp": datetime.now(timezone.utc).isoformat()}
        if not complete:
            text = "Partial lap recorded. Cross the line and complete a clean lap to build a reference."
        else:
            comparison = "Your first clean reference is set." if best and not old_best else (
                "You matched your reference." if old_best and abs(s.last_ms - old_best) < 10 else
                f"{abs(s.last_ms - old_best) / 1000:.2f} seconds {'faster' if s.last_ms < old_best else 'slower'} than your reference." if old_best else "")
            focus = ("Next lap, build throttle more progressively on corner exit." if self.issues["oversteer"] else
                     "Next lap, ease entry speed and let the front tyres settle." if self.issues["understeer"] else
                     "Keep the inputs smooth and repeat that rhythm.")
            text = f"Lap {s.lap}, {lap_time(s.last_ms)}. {comparison} {focus}"
            if not self.clean:
                text += " This lap included pit running, a penalty, a track-limits excursion or an incident; reference unchanged."
        if profile_report and profile_report['encouragement']:text+=' '+profile_report['encouragement']
        if summary['corner_exits']['clean_exits']:
            text+=f" {summary['corner_exits']['clean_exits']} clean turn exits observed."
        summary["summary"] = text
        self.laps.insert(0, summary)
        self.laps = self.laps[:200]
        self.emit("lap", text, s.timestamp, cooldown=0)
        if best:
            self.reference = {"identity": list(self.identity), "time_ms": s.last_ms,
                "sectors": sector_times, "samples": self.samples.copy(),
                "corners": self.learn_corners(self.samples)}
            self.corners.set_turns(learn_turns(self.samples))
            path = self.reference_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.reference), encoding="utf-8")
            temp.replace(path)
        self.persist()

    @staticmethod
    def learn_corners(samples):
        # A learned braking zone is a practical approach cue, not a named corner.
        zones = []
        active = False
        for point in samples:
            if point["brake"] > 0.25 and not active:
                if not zones or point["p"] - zones[-1]["p"] > 0.025:
                    zones.append({"p": point["p"], "label": f"Braking zone {len(zones) + 1}"})
                active = True
            elif point["brake"] < 0.1:
                active = False
        return zones

    def persist(self):
        path = self.data_dir / "sessions" / f"{self.session_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.export(), indent=2), encoding="utf-8")

    def export(self):
        return {"session": self.session_id, "identity": self.identity,
                "laps": self.laps, "events": list(self.events),
                "race": {"overtakes":self.race.overtakes,"incidents":list(self.race.incidents),"incident_count":self.race.incident_count},
                "driving_profile":self.profile.data if self.profile else None,
                "learned_turns":self.corners.turns,
                "validity_note": "Clean means no observed >2 tyres out, penalty, pit running, telemetry gap or detected incident. AC's full lap validity flag is not read."}

    def update(self, s: Sample):
        now = s.timestamp
        active = s.status == "live"
        grip = "Monitoring" if active else "No live analysis"
        next_zone = None
        delta = None
        speed_delta = None
        race_state = None
        if active:
            identity = (s.source, s.car, s.track, s.configuration)
            if identity != self.identity or (self.previous and (s.session_type!=self.previous.session_type or
                s.lap < self.previous.lap or (s.lap == self.previous.lap and s.lap_ms < self.previous.lap_ms - 1500))):
                self.set_identity(s)
            prev = self.previous
            if prev and s.lap > prev.lap:
                if s.lap == prev.lap + 1 and prev.progress > 0.9 and s.progress < 0.1:
                    self.finish_lap(s)
                else:self.profile.reset_lap()
                self.reset_lap(s.progress < 0.02)
            if prev and s.sector != prev.sector and s.sector > 0 and s.lap == prev.lap:
                if s.sector == prev.sector + 1 and s.last_sector_ms > 0:
                    self.sectors.append(s.last_sector_ms)
                    ref_sectors = self.reference.get("sectors", []) if self.reference else []
                    comparison = ""
                    if s.sector <= len(ref_sectors):
                        diff = s.last_sector_ms - ref_sectors[s.sector - 1]
                        comparison = ", matched the reference" if abs(diff) < 10 else f", {abs(diff)/1000:.2f} seconds {'up' if diff < 0 else 'down'} on reference"
                    event=self.emit("sector", f"Sector {s.sector}: {s.last_sector_ms/1000:.2f}{comparison}.", now,
                        voice=bool(comparison) and abs(diff)>=100)
                    if event:event['facts']={'delta_ms':diff if comparison else None}
            if s.in_pit or s.tyres_out > 2 or s.penalty > 0:
                self.clean = False
            race_state, race_events = self.race.update(s)
            pass_facts=iter(self.race.pass_facts)
            for event_kind, event_text, priority in race_events:
                event=self.emit(event_kind,event_text,now,cooldown=0,priority=priority)
                if event_kind=='overtake':
                    facts=next(pass_facts)
                    if event:event['facts']=facts.copy()
                self.profile.record_race_event(event_kind,s,self.race.last_position_change,
                    self.race.incidents[0]['kind'] if self.race.incidents else None)
                if event_kind == "incident": self.clean = False
            if s.tyres_out > 2 and s.speed > 40:
                self.emit("off_track", "Track limits. Bring it back smoothly and reset for the next corner.", now, 20)
            # Relative axle slip is a heuristic; no claim of measured slip angles.
            front = sum(abs(v) for v in s.slip[:2]) / 2
            rear = sum(abs(v) for v in s.slip[2:]) / 2
            turning = abs(s.steer) > 0.06 and s.speed > 45 and not s.in_pit
            kind = None
            if turning and rear - front > 0.18 and rear > 0.22 and s.throttle > 0.2:
                kind, grip = "oversteer", "Rear slip · possible oversteer"
            elif turning and front - rear > 0.18 and front > 0.22:
                kind, grip = "understeer", "Front slip · possible understeer"
            for candidate in ("understeer", "oversteer"):
                if candidate != kind:
                    self.sustained.pop(candidate, None)
            if kind:
                started = self.sustained.setdefault(kind, now)
                if now - started > 0.45 and kind not in self.lap_hints:
                    cue = ("The rear looks a little lively on exit. Try feeding the power in a touch more gently." if kind == "oversteer" else
                           "Looks like the front's sliding there. A little less entry speed might help it turn.")
                    if self.emit(kind,cue,now,75):self.lap_hints.add(kind)
            for event_kind,event_text in self.profile.observe(s,kind):
                self.emit(event_kind,event_text,now,cooldown=45)
            corner_exit=self.corners.observe(s,kind,any(event[0]=='incident' for event in race_events))
            if corner_exit:
                reference=self.ref_at(s.progress)
                if reference:
                    corner_exit['reference_speed_delta']=round(s.speed-reference['speed'],1)
                    self.corners.last_result['reference_speed_delta']=corner_exit['reference_speed_delta']
                text=f"Clean observed exit from {corner_exit['label'].lower()}: steering unwound, back on throttle, speed building; no sustained slip, new damage or track-limits excursion observed through the turn."
                if corner_exit['reference_speed_delta'] is not None and corner_exit['reference_speed_delta']>=2:
                    text+=f" {corner_exit['reference_speed_delta']:.1f} km/h faster than your reference at the same exit position."
                event=self.emit('clean_exit',text,now,cooldown=0,voice=self.corners.allow_praise(s))
                if event:
                    event['facts']=corner_exit.copy()
                    if event['speak']:self.corners.praised_exit(s)
            if not s.in_pit:
                ref = self.ref_at(s.progress)
                if ref:
                    delta, speed_delta = s.lap_ms - ref["ms"], s.speed - ref["speed"]
                if self.reference and s.length > 0:
                    zones = self.reference.get("corners", [])
                    if zones:
                        zone = min(zones, key=lambda p: (p["p"] - s.progress) % 1)
                        distance = ((zone["p"] - s.progress) % 1) * s.length
                        next_zone = {**zone, "distance": round(distance), "estimated": True}
                        eta = distance / max(1, s.speed / 3.6)
                        if 3 < eta < 7 and s.brake < 0.1:
                            self.emit("zone_" + zone["label"], f"Learned braking zone ahead, approximately {round(distance/10)*10} metres. Eyes up.", now, 35)
            bin_id = int(s.progress * 1000)
            if bin_id not in self.bins and (not self.samples or s.progress > self.samples[-1]["p"]):
                self.bins.add(bin_id)
                self.samples.append({"p": s.progress, "ms": s.lap_ms, "speed": s.speed,
                    "x": s.x, "z": s.z, "brake": s.brake, "throttle": s.throttle})
            self.previous = s
        else:
            # Never evaluate old telemetry while paused, replaying or disconnected.
            self.sustained.clear()
            if self.profile:self.profile.observe(s)
            self.corners.observe(s)
            race_state, _ = self.race.update(s)
            if s.status in ("disconnected", "waiting") and self.previous:
                self.clean = False
                self.full_lap = False
        map_points = self.reference["samples"] if self.reference else self.samples
        return {"session_id":self.session_id, "telemetry": s.dict(), "race":race_state,
            "profile":self.profile.snapshot(s) if self.profile else None,
            "analysis": {"grip": grip, "delta_ms": delta,
            "speed_delta": speed_delta, "next_zone": next_zone,
            "corner":self.corners.snapshot(s),
            "reference_ms": self.reference["time_ms"] if self.reference else None,
            "reference_ready": bool(self.reference), "clean": self.clean,
            "sectors": self.sectors, "reference_sectors": self.reference.get("sectors", []) if self.reference else []},
            "map": [{"p": p["p"], "x": p["x"], "z": p["z"]} for p in map_points[::3]],
            "events": list(self.events), "laps": self.laps[:20]}
