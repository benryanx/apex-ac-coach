"""Dark app-owned chrome for the transparent WinForms host."""
import ctypes
from ctypes import wintypes


def dark_frame(handle):
    # Microsoft DWMWINDOWATTRIBUTE: nonclient rendering, dark mode, border,
    # caption, text, and no system backdrop (Mica would hide the game).
    # https://learn.microsoft.com/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute
    dwm=ctypes.WinDLL('dwmapi')
    set_attribute=dwm.DwmSetWindowAttribute
    set_attribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
    set_attribute.restype=ctypes.c_long
    results=[]
    for attribute,value in ((2,2),(20,1),(34,0x000000),(35,0x131010),(36,0xf5f3f3),(38,1)):
        colour=ctypes.c_uint32(value)
        results.append(set_attribute(handle,attribute,ctypes.byref(colour),ctypes.sizeof(colour)))
    return all(result>=0 for result in results)


def install_chrome(window):
    """Region-shaped windows use classic nonclient painting; own the frame instead."""
    from System.Drawing import Color, Font, Rectangle
    from System.Windows.Forms import (Button, Cursors, DockStyle, FlatStyle,
        FormBorderStyle, Label, MouseButtons, Padding, Panel, Screen, FormWindowState)

    form=window.native
    form.FormBorderStyle=getattr(FormBorderStyle,'None')
    form.Padding=Padding(5)
    form.BackColor=Color.Black
    caption=Panel()
    caption.Dock=DockStyle.Top
    caption.Height=round(28*form.DeviceDpi/96)
    caption.BackColor=Color.FromArgb(16,16,19)
    title=Label()
    title.Text='Apex · Race engineer'
    title.AccessibleName='Window title: drag to move'
    title.ForeColor=Color.FromArgb(220,220,226)
    title.Font=Font('Segoe UI',9)
    title.Padding=Padding(6,5,0,0)
    title.Dock=DockStyle.Fill

    def maximize(*_):
        form.MaximizedBounds=Screen.FromControl(form).WorkingArea
        form.WindowState=(FormWindowState.Normal if form.WindowState==FormWindowState.Maximized
                          else FormWindowState.Maximized)

    actions=[('−','Minimize',lambda *_:setattr(form,'WindowState',FormWindowState.Minimized)),
             ('□','Maximize or restore',maximize),('×','Close',lambda *_:form.Close())]
    for text,name,action in actions:
        button=Button()
        button.Text=text
        button.AccessibleName=name
        button.Dock=DockStyle.Right
        button.Width=round(36*form.DeviceDpi/96)
        button.FlatStyle=FlatStyle.Flat
        button.FlatAppearance.BorderSize=0
        button.FlatAppearance.MouseOverBackColor=(Color.FromArgb(190,35,43) if name=='Close'
                                                 else Color.FromArgb(48,48,54))
        button.ForeColor=Color.FromArgb(235,235,240)
        button.BackColor=caption.BackColor
        button.Font=Font('Segoe UI',11)
        button.TabStop=False
        button.Click+=action
        caption.Controls.Add(button)
    caption.Controls.Add(title)
    title.BringToFront()
    form.Controls.Add(caption)
    form.webview.BringToFront()

    user=ctypes.WinDLL('user32')
    release=user.ReleaseCapture
    release.argtypes=[]
    release.restype=wintypes.BOOL
    send=user.SendMessageW
    send.argtypes=[wintypes.HWND,wintypes.UINT,ctypes.c_size_t,ctypes.c_ssize_t]
    send.restype=ctypes.c_ssize_t
    def drag(_,event):
        if event.Button==MouseButtons.Left:
            release()
            send(form.Handle.ToInt64(),0xA1,2,0)  # WM_NCLBUTTONDOWN, HTCAPTION
    title.MouseDown+=drag
    caption.MouseDown+=drag
    title.DoubleClick+=maximize
    caption.DoubleClick+=maximize

    # The black padding is also a resize target, including all four corners.
    sizing={}
    def edges(point):
        if form.WindowState==FormWindowState.Maximized:return (False,)*4
        border=form.Padding.Left
        return (point.X<border,point.Y<border,
                point.X>=form.ClientSize.Width-border,
                point.Y>=form.ClientSize.Height-border)
    def begin_resize(_,event):
        side=edges(event.Location)
        if event.Button==MouseButtons.Left and any(side):
            sizing.update(side=side,start=form.PointToScreen(event.Location),bounds=form.Bounds)
            form.Capture=True
    def move_resize(_,event):
        if sizing:
            point=form.PointToScreen(event.Location)
            dx=point.X-sizing['start'].X;dy=point.Y-sizing['start'].Y
            left,top,right,bottom=sizing['side'];bounds=sizing['bounds']
            width=max(form.MinimumSize.Width,bounds.Width+(-dx if left else dx if right else 0))
            height=max(form.MinimumSize.Height,bounds.Height+(-dy if top else dy if bottom else 0))
            form.Bounds=Rectangle(bounds.Right-width if left else bounds.Left,
                bounds.Bottom-height if top else bounds.Top,width,height)
        else:
            left,top,right,bottom=edges(event.Location)
            form.Cursor=(Cursors.SizeNWSE if (left and top) or (right and bottom) else
                         Cursors.SizeNESW if (right and top) or (left and bottom) else
                         Cursors.SizeWE if left or right else Cursors.SizeNS if top or bottom else Cursors.Default)
    def end_resize(*_):
        sizing.clear();form.Capture=False;form.Cursor=Cursors.Default
    form.MouseDown+=begin_resize
    form.MouseMove+=move_resize
    form.MouseUp+=end_resize
    form.MouseCaptureChanged+=lambda *_:sizing.clear() if not form.Capture else None
    # Retain controls and handlers for the lifetime of this window.
    form._apex_chrome=(caption,title,drag,maximize,begin_resize,move_resize,end_resize)
