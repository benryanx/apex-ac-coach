"""Original Assetto Corsa shared memory (not ACC/Evo). All units explicit.

The stable SDK structure prefixes are read using Windows' UTF-16 and pack(4).
OpenFileMapping opens existing pages read-only; it never creates fake pages.
"""
from __future__ import annotations

import ctypes as C
import math
import sys
import time
from dataclasses import dataclass, field, asdict

I, F, W = C.c_int32, C.c_float, C.c_uint16


class Physics(C.LittleEndianStructure):
    _pack_ = 4
    _fields_ = [("packet", I), ("gas", F), ("brake", F), ("fuel", F),
                ("gear", I), ("rpm", I), ("steer", F), ("speed", F),
                ("velocity", F * 3), ("acc_g", F * 3)] + [
        (name, F * 4) for name in ("slip", "load", "pressure", "wheel_speed",
        "wear", "dirt", "temperature", "camber", "suspension")] + [
        ("drs", F), ("tc", F), ("heading", F), ("pitch", F), ("roll", F),
        ("cg_height", F), ("damage", F * 5), ("tyres_out", I),
        ("pit_limiter", I), ("abs", F)]


class Graphics(C.LittleEndianStructure):
    _pack_ = 4
    _fields_ = [("packet", I), ("status", I), ("session", I)] + [
        (name, W * 15) for name in ("current", "last", "best", "split")] + [
        ("laps", I), ("position", I), ("current_ms", I), ("last_ms", I),
        ("best_ms", I), ("time_left", F), ("distance", F), ("in_pit", I),
        ("sector", I), ("last_sector_ms", I), ("total_laps", I),
        ("compound", W * 33), ("replay_speed", F), ("progress", F),
        ("coordinates", F * 3), ("penalty", F), ("flag", I),
        ("ideal_line", I), ("in_pit_lane", I), ("surface_grip", F)]


class Static(C.LittleEndianStructure):
    _pack_ = 4
    _fields_ = [("sm_version", W * 15), ("ac_version", W * 15),
        ("sessions", I), ("cars", I)] + [
        (name, W * 33) for name in ("car", "track", "first_name", "surname", "nickname")] + [
        ("sectors", I), ("max_torque", F), ("max_power", F), ("max_rpm", I),
        ("max_fuel", F), ("suspension_max", F * 4), ("tyre_radius", F * 4),
        ("max_turbo", F), ("deprecated1", F), ("deprecated2", F),
        ("penalties", I), ("fuel_rate", F), ("tyre_rate", F), ("damage_rate", F),
        ("blankets", I), ("stability", F), ("auto_clutch", I), ("auto_blip", I),
        ("has_drs", I), ("has_ers", I), ("has_kers", I), ("kers_max", F),
        ("engine_brake_count", I), ("ers_count", I), ("length", F),
        ("configuration", W * 33)]


def utf16(value):
    return bytes(value).decode("utf-16-le", errors="replace").split("\0", 1)[0]


@dataclass
class Sample:
    timestamp: float = 0
    packet: int = 0
    source: str = "ac"
    status: str = "waiting"
    car: str = "Assetto Corsa"
    driver: str = ""
    car_display_name: str = ""
    track: str = "Waiting for session"
    configuration: str = ""
    speed: float = 0
    rpm: int = 0
    max_rpm: int = 8000
    rpm_limit_known: bool = False
    gear: int = 0
    throttle: float = 0
    brake: float = 0
    steer: float = 0
    fuel: float = 0
    slip: list = field(default_factory=lambda: [0] * 4)
    temperatures: list = field(default_factory=lambda: [0] * 4)
    tyres_out: int = 0
    penalty: float = 0
    in_pit: bool = False
    lap: int = 0
    lap_ms: int = 0
    last_ms: int = 0
    sector: int = 0
    sector_count: int = 3
    last_sector_ms: int = 0
    progress: float = 0
    length: float = 0
    x: float = 0
    z: float = 0
    heading: float = 0
    session_type: int = -1
    session_time_left: float = 0
    session_total_laps: int = 0
    position: int = 0
    car_count: int = 0
    flag: int = 0
    damage: list = field(default_factory=lambda: [0] * 5)
    acc_g: list = field(default_factory=lambda: [0] * 3)
    opponents: list = field(default_factory=list)
    opponents_available: bool = False
    opponents_status: str = "Roster bridge unavailable"
    opponents_transport: str = ""

    def dict(self):
        return asdict(self)


class ACReader:
    def __init__(self, page_names=None):
        self.page_names = page_names or ("acpmf_physics", "acpmf_graphics", "acpmf_static")
        self.pages = []
        self.last_packet = None
        self.last_change = time.monotonic()
        self.next_attach = 0
        if sys.platform == "win32":
            from ctypes import wintypes as T
            self.kernel = C.WinDLL("kernel32", use_last_error=True)
            self.kernel.OpenFileMappingW.argtypes = [T.DWORD, T.BOOL, T.LPCWSTR]
            self.kernel.OpenFileMappingW.restype = T.HANDLE
            self.kernel.MapViewOfFile.argtypes = [T.HANDLE, T.DWORD, T.DWORD, T.DWORD, C.c_size_t]
            self.kernel.MapViewOfFile.restype = C.c_void_p
            self.kernel.UnmapViewOfFile.argtypes = [C.c_void_p]
            self.kernel.CloseHandle.argtypes = [T.HANDLE]

    def close(self):
        for handle, address, _ in self.pages:
            self.kernel.UnmapViewOfFile(address)
            self.kernel.CloseHandle(handle)
        self.pages = []
        self.last_packet = None

    def attach(self):
        if sys.platform != "win32" or time.monotonic() < self.next_attach:
            return False
        self.next_attach = time.monotonic() + 1
        for name, cls in zip(self.page_names, (Physics, Graphics, Static)):
            handle = self.kernel.OpenFileMappingW(4, False, name)
            if not handle:
                self.close()
                return False
            address = self.kernel.MapViewOfFile(handle, 4, 0, 0, C.sizeof(cls))
            if not address:
                self.kernel.CloseHandle(handle)
                self.close()
                return False
            self.pages.append((handle, address, cls))
        self.last_change = time.monotonic()
        return True

    @staticmethod
    def snapshot(address, cls):
        # Retry if the game's packet ID changed while copying a page.
        for _ in range(3):
            before = C.c_int32.from_address(address).value
            result = cls.from_buffer_copy(C.string_at(address, C.sizeof(cls)))
            if before == C.c_int32.from_address(address).value:
                return result
        raise ValueError("Telemetry changed during read")

    def read(self):
        if not self.pages and not self.attach():
            return Sample()
        p, g = [self.snapshot(address, cls) for _, address, cls in self.pages[:2]]
        _, address, cls = self.pages[2]
        s = cls.from_buffer_copy(C.string_at(address, C.sizeof(cls)))
        key = (p.packet, g.packet)
        if key != self.last_packet:
            self.last_packet = key
            self.last_change = time.monotonic()
        elif time.monotonic() - self.last_change > 3:
            self.close()
            return Sample(status="disconnected")
        floats = [p.speed, p.steer, p.fuel, p.gas, p.brake, p.heading, g.penalty, g.time_left,
                  g.progress, s.length, *p.slip, *p.temperature, *p.damage, *p.acc_g, *g.coordinates]
        if not all(math.isfinite(v) for v in floats) or not 0 <= g.progress <= 1:
            raise ValueError("Invalid telemetry sample")
        return Sample(timestamp=time.monotonic(), packet=p.packet,
            status={0: "waiting", 1: "replay", 2: "live", 3: "paused"}.get(g.status, "waiting"),
            car=utf16(s.car), track=utf16(s.track), configuration=utf16(s.configuration),
            speed=p.speed, rpm=p.rpm, max_rpm=s.max_rpm or 8000, rpm_limit_known=s.max_rpm>0, gear=p.gear - 1,
            throttle=p.gas, brake=p.brake, steer=p.steer, fuel=p.fuel,
            slip=list(p.slip), temperatures=list(p.temperature), tyres_out=p.tyres_out,
            penalty=g.penalty, in_pit=bool(g.in_pit or g.in_pit_lane),
            lap=g.laps, lap_ms=g.current_ms, last_ms=g.last_ms, sector=g.sector,
            sector_count=max(1, s.sectors), last_sector_ms=g.last_sector_ms,
            progress=g.progress, length=s.length, x=g.coordinates[0], z=g.coordinates[2], heading=p.heading,
            session_type=g.session, session_time_left=g.time_left, session_total_laps=g.total_laps,
            position=g.position, car_count=s.cars, flag=g.flag,
            damage=list(p.damage), acc_g=list(p.acc_g))


class DemoReader:
    """A clearly labelled, accelerated fictional circuit; no game data."""
    duration = 66

    def __init__(self):
        self.started = time.monotonic()

    @staticmethod
    def point(progress):
        a = progress * 2 * math.pi
        return 700 * math.cos(a) + 220 * math.cos(2 * a), 450 * math.sin(a) - 130 * math.sin(3 * a)

    def read(self):
        t = time.monotonic() - self.started
        lap = int(t // self.duration)
        progress = (t % self.duration) / self.duration
        phase = progress * 2 * math.pi
        speed = 175 + 75 * math.cos(phase * 5)
        steer = 0.3 * math.sin(phase * 5)
        slip = [0.07] * 4
        if 0.22 < progress < 0.25:
            slip[:2] = [0.44, 0.42]
        if 0.61 < progress < 0.64:
            slip[2:] = [0.46, 0.48]
        x, z = self.point(progress)
        # Fictional race scenario: pass at .31, contact at .72, loss at .82.
        position = 5 if progress < .31 or progress > .82 else 4
        opponent_progress = (progress + (.003 if progress < .31 else -.003)) % 1
        opponent_x, opponent_z = self.point(opponent_progress)
        opponents=[{"id":1,"name":"Alex Morgan · Demo","car":"ks_ferrari_488_gt3",
            "car_name":"Ferrari 488 GT3","position":4 if position==5 else 5,
            "lap":lap,"progress":opponent_progress,"in_pit":False,"speed":speed,
            "x":opponent_x,"z":opponent_z}]
        names=['Sam Riley','Jamie Chen','Taylor Lewis','Casey Patel','Jordan Diaz',
               'Robin Clarke','Drew Kim','Charlie Evans','Rory Blake','Avery Wilson']
        models=[('ks_mercedes_amg_gt3','Mercedes-AMG GT3'),('bmw_z4_gt3','BMW Z4 GT3'),
                ('ks_audi_r8_lms_2016','Audi R8 LMS 2016')]
        for i,rank in enumerate([1,2,3,6,7,8,9,10,11,12]):
            distance=max(0,lap+progress+(position-rank)*.04)
            other_lap=int(distance);other_progress=distance-other_lap
            other_x,other_z=self.point(other_progress);model,label=models[i%len(models)]
            opponents.append({'id':i+2,'name':names[i]+' · Demo','car':model,'car_name':label,
                'position':rank,'lap':other_lap,'progress':other_progress,'in_pit':False,
                'speed':speed,'x':other_x,'z':other_z})
        damaged = progress > .72
        return Sample(timestamp=time.monotonic(), packet=int(t * 20), source="demo", status="live",
            car="Porsche 911 GT3 R · Demo", driver="You · Demo",car_display_name="Porsche 911 GT3 R 2016",
            track="Engineering circuit", speed=speed,
            rpm=int(4000 + speed * 12), rpm_limit_known=True, gear=max(2, min(6, int(speed / 45) + 1)),
            throttle=max(0.08, math.cos(phase * 5)), brake=max(0, -math.sin(phase * 5)) * 0.8,
            steer=steer, fuel=max(0, 38 - t / 160), slip=slip,
            temperatures=[82 + 4 * math.sin(t + i) for i in range(4)], lap=lap,
            lap_ms=int((t % self.duration) * 1000), last_ms=66000 if lap else 0,
            sector=int(progress * 3), last_sector_ms=22000, progress=progress, length=4200,
            x=x, z=z, heading=phase, session_type=2, position=position, car_count=12,
            damage=[15 if damaged else 0, 0, 0, 0, 0],
            opponents_available=True, opponents_status='Simulated roster',opponents_transport='demo',opponents=opponents)
