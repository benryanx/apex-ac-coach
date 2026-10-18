"""Optional Assetto Corsa Python app. Compatible with AC's bundled Python 3.3.

Copies race roster data only to the companion on this PC. No game controls.
"""
import json
import os
import ac
import acsys
try:
    import socket
except ImportError:
    # AC's embedded Python commonly omits _socket.pyd. File transport needs no DLL.
    socket = None

_socket = None
_elapsed = 0.0
_reported_error = False
_car_labels = {}
_roster_path = None


def car_details(car_id):
    value = ac.getCarName(car_id)
    model = value[:100] if isinstance(value, str) else ''
    if model not in _car_labels:
        label = model
        # AC returns a content identifier. Prefer the installed car's UI name.
        if model and model not in ('.', '..') and not any(c in model for c in '/\\:'):
            path = os.path.join(os.path.dirname(__file__), '..', '..', '..',
                                'content', 'cars', model, 'ui', 'ui_car.json')
            try:
                with open(path, 'r', encoding='utf-8-sig', errors='replace') as source:
                    details = json.loads(source.read(262144), strict=False)
                if isinstance(details.get('name'), str):
                    label = ' '.join(details['name'].split())[:100] or model
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        if len(_car_labels) >= 200:
            _car_labels.clear()
        _car_labels[model] = label
    return model, _car_labels[model]


def acMain(ac_version):
    global _socket, _roster_path
    _roster_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'roster.json')
    if socket is not None:
        try:
            _socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            _socket.setblocking(False)
        except OSError:
            _socket = None
    app = ac.newApp('Apex Bridge')
    ac.setSize(app, 220, 55)
    ac.addLabel(app, 'Apex race roster -> local companion')
    ac.log('Apex Bridge: ready; local roster file enabled')
    return 'Apex Bridge'


def acUpdate(delta_t):
    global _elapsed, _reported_error
    _elapsed += delta_t
    if _elapsed < 0.2 or (_socket is None and _roster_path is None):
        return
    _elapsed = 0.0
    try:
        cars = []
        for car_id in range(min(100, ac.getCarsCount())):
            if not ac.isConnected(car_id):
                continue
            coords = ac.getCarState(car_id, acsys.CS.WorldPosition)
            model, label = car_details(car_id)
            driver = ac.getDriverName(car_id)
            cars.append({
                'id': car_id,
                'name': driver[:80] if isinstance(driver, str) else '',
                'car': model, 'car_name': label,
                'position': int(ac.getCarRealTimeLeaderboardPosition(car_id)),
                'lap': int(ac.getCarState(car_id, acsys.CS.LapCount)),
                'progress': float(ac.getCarState(car_id, acsys.CS.NormalizedSplinePosition)),
                'speed': float(ac.getCarState(car_id, acsys.CS.SpeedKMH)),
                'x': float(coords[0]), 'z': float(coords[2]),
                'in_pit': bool(ac.isCarInPit(car_id) or ac.isCarInPitline(car_id))
            })
        payload = {
            'version': 1,
            'identity': [str(ac.getCarName(0)), str(ac.getTrackName(0)), str(ac.getTrackConfiguration(0))],
            'cars': cars
        }
        raw = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode('utf-8')
        if len(raw) <= 65507:
            if _roster_path is not None:
                temp = _roster_path + '.tmp'
                with open(temp, 'wb') as output:
                    output.write(raw)
                os.replace(temp, _roster_path)
            if _socket is not None:
                _socket.sendto(raw, ('127.0.0.1', 9876))
    except Exception as error:
        if not _reported_error:
            ac.log('Apex Bridge: ' + str(error))
            _reported_error = True


def acShutdown():
    global _socket
    if _socket is not None:
        _socket.close()
        _socket = None
