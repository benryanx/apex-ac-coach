"""Exercise real Win32 mappings with private test names, never the game's pages."""
import ctypes
import mmap
import sys
import uuid

import pytest

from coach.telemetry import ACReader, Physics, Graphics, Static


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 shared memory")


def wide(target, value):
    raw=value.encode('utf-16-le')
    ctypes.memmove(ctypes.addressof(target), raw, len(raw))


def test_read_real_named_mappings_and_reconnect():
    names=[f'apex_test_{uuid.uuid4().hex}_{i}' for i in range(3)]
    reader=ACReader(page_names=names)
    # It must not create placeholder mappings before the producer appears.
    assert reader.read().status=='waiting'
    assert not reader.pages
    pages=[]
    try:
        p,g,s=Physics(),Graphics(),Static()
        p.packet=1;p.speed=144.5;p.gear=4;p.rpm=6500;p.gas=.7
        p.slip[:]=[.1,.2,.3,.4]
        g.packet=1;g.status=2;g.session=2;g.position=4;g.flag=2;g.progress=.42;g.laps=2;g.current_ms=42000
        g.time_left=123.5;g.total_laps=10
        p.damage[:]=[10,0,5,0,0]
        g.coordinates[:]=[120,0,250]
        s.max_rpm=8500;s.sectors=3;s.length=5000
        wide(s.car,'test_gt3');wide(s.track,'test_circuit');wide(s.configuration,'gp')
        for name,structure in zip(names,(p,g,s)):
            page=mmap.mmap(-1,ctypes.sizeof(structure),tagname=name)
            page.write(bytes(structure));pages.append(page)
        reader.next_attach=0
        result=reader.read()
        assert result.status=='live'
        assert result.speed==pytest.approx(144.5)
        assert result.gear==3
        assert result.car=='test_gt3'
        assert result.track=='test_circuit'
        assert result.configuration=='gp'
        assert result.length==5000
        assert result.progress==pytest.approx(.42)
        assert result.slip==pytest.approx([.1,.2,.3,.4])
        assert result.position==4 and result.session_type==2 and result.flag==2
        assert result.session_time_left==123.5 and result.session_total_laps==10
        assert result.damage==[10,0,5,0,0]
        # A stopped producer must be treated as disconnected, not live forever.
        reader.last_change-=4
        assert reader.read().status=='disconnected'
        assert not reader.pages
    finally:
        reader.close()
        for page in pages: page.close()
