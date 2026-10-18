"""Launch a dedicated Windows window, or a local browser dashboard."""
import argparse
import json
import os
from pathlib import Path
import socket
import threading
import time
import webbrowser

import uvicorn

ROOT = Path(__file__).resolve().parent


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                os.environ.setdefault("OPENAI_API_KEY", line.split("=", 1)[1].strip().strip('\"\''))


def main():
    parser = argparse.ArgumentParser(description="Apex · Assetto Corsa race engineer")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--serve", action="store_true", help="Only run the local server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--wide", action="store_true")
    parser.add_argument("--data-dir", type=Path, help="Optional separate data directory")
    args = parser.parse_args()
    load_env()
    from coach.server import create_app
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", args.port))
        except OSError:
            raise SystemExit(f"Port {args.port} is in use. Close the existing coach or pass --port 8766.")
    server = uvicorn.Server(uvicorn.Config(create_app(args.demo,args.data_dir), host="127.0.0.1", port=args.port, log_level="warning"))
    url = f"http://127.0.0.1:{args.port}"
    if args.serve:
        server.run()
        return
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        if not thread.is_alive():
            raise SystemExit("The dashboard server could not start.")
        time.sleep(0.05)
    print(f"Apex running at {url}. Close the window or press Ctrl+C to stop.")
    try:
        if args.browser:
            webbrowser.open(url)
            while thread.is_alive():
                time.sleep(0.5)
        else:
            import webview
            default_height=940 if args.wide else max(500,min(1380,webview.screens[0].height-60))
            placement_path=(args.data_dir or ROOT/'data')/'window.json'
            placement={}
            try:
                stored=json.loads(placement_path.read_text(encoding='utf-8'))
                if isinstance(stored,dict) and all(type(stored.get(key)) is int for key in ('width','height','x','y')):
                    for screen in webview.screens:
                        if screen.x<=stored['x']<screen.x+screen.width-80 and screen.y<=stored['y']<screen.y+screen.height-50:
                            placement={'x':stored['x'],'y':stored['y']}
                            if not args.wide:
                                placement.update(width=max(340,min(stored['width'],screen.width)),
                                    height=max(500,min(stored['height'],screen.height-40)))
                            break
            except (OSError,ValueError,TypeError):
                pass
            class WindowAPI:
                def set_compact(self, compact):
                    window.resize(440 if compact else 1280,window.height)
                def set_pinned(self, pinned):
                    window.on_top = bool(pinned)
                def set_opacity(self, percent):
                    from System import Action
                    opacity=max(.6,min(1,float(percent)/100))
                    window.native.Invoke(Action(lambda:setattr(window.native,'Opacity',opacity)))
                def set_regions(self, rectangles):
                    """Make space outside the HUD cards genuinely transparent."""
                    from System import Action
                    from System.Drawing import Point, Rectangle, Region
                    def apply():
                        form=window.native
                        old=form.Region
                        if rectangles is None:
                            form.Region=None
                        else:
                            origin=form.webview.PointToScreen(Point(0,0))
                            dx,dy=origin.X-form.Left,origin.Y-form.Top
                            scale=form.DeviceDpi/96
                            region=Region();region.MakeEmpty()
                            # Preserve the black title bar and draggable resize edges.
                            region.Union(Rectangle(0,0,form.Width,dy))
                            for rect in [Rectangle(0,0,dx,form.Height),
                                Rectangle(form.Width-dx,0,dx,form.Height),
                                Rectangle(0,form.Height-dx,form.Width,dx)]:region.Union(rect)
                            for rect in rectangles[:30]:
                                x,y,width,height=rect
                                region.Union(Rectangle(round(x*scale)+dx,round(y*scale)+dy,
                                    max(1,round(width*scale)),max(1,round(height*scale))))
                            form.Region=region
                        if old is not None:old.Dispose()
                        from coach.window_style import dark_frame
                        dark_frame(form.Handle.ToInt64())
                    window.native.Invoke(Action(apply))
            window = webview.create_window("Apex · Race engineer", url,
                width=placement.pop('width',1280 if args.wide else 440),height=placement.pop('height',default_height),
                **placement,min_size=(340, 500), on_top=not args.wide, js_api=WindowAPI(),
                background_color="#0b0b0d", transparent=True)
            def prepare_transparency():
                # WebView2 transparency reveals its host; extend the native glass
                # surface too, rather than revealing WinForms' white backing.
                import ctypes
                from ctypes import wintypes
                from System.Drawing import Color
                class Margins(ctypes.Structure):
                    _fields_=[(name,ctypes.c_int) for name in ('left','right','top','bottom')]
                window.native.BackColor=Color.Black
                window.native.webview.BackColor=Color.Black
                from coach.window_style import dark_frame, install_chrome
                install_chrome(window)
                def apply_frame(*_):
                    dark_frame(window.native.Handle.ToInt64())
                apply_frame()
                window.native.Activated += apply_frame
                window.native.Deactivate += apply_frame
                dwm=ctypes.WinDLL('dwmapi')
                # pywebview enables Mica in dark mode. It must be disabled or
                # transparent HTML reveals an opaque Mica sheet, not the game.
                attribute=dwm.DwmSetWindowAttribute
                attribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
                attribute.restype=ctypes.c_long
                none=ctypes.c_int(1)
                attribute(window.native.Handle.ToInt64(),38,ctypes.byref(none),ctypes.sizeof(none))
                extend=dwm.DwmExtendFrameIntoClientArea
                extend.argtypes=[wintypes.HWND,ctypes.POINTER(Margins)]
                extend.restype=ctypes.c_long
                if extend(window.native.Handle.ToInt64(),ctypes.byref(Margins(-1,-1,-1,-1)))<0:
                    print('Native transparency unavailable; choose an opaque background in Display.')
            window.events.before_show += prepare_transparency
            def save_placement():
                try:
                    placement_path.parent.mkdir(parents=True,exist_ok=True)
                    temp=placement_path.with_suffix('.tmp')
                    temp.write_text(json.dumps({'x':window.x,'y':window.y,'width':window.width,'height':window.height}),encoding='utf-8')
                    temp.replace(placement_path)
                except OSError:
                    pass
            window.events.closing += save_placement
            webview.start(gui="edgechromium")
    except KeyboardInterrupt:
        pass
    finally:
        server.should_exit = True
        thread.join(timeout=12)


if __name__ == "__main__":
    main()
