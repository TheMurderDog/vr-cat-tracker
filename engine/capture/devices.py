"""The cameras Windows has, in DirectShow order, with their names and device paths, using only ctypes.

OpenCV's DirectShow backend numbers cameras in this same order, so entry i is OpenCV device id i (with
cameras.backend: dshow). The device path names the USB device and port, so it stays the same when the order
changes (a VR headset's camera plugged in or out shifts every id after it). That is what cameras.devices
and cameras.exclude in settings/cameras.yaml rely on. On anything but Windows, or if it fails, list_devices
returns None and only the plain ids are used.
"""

import ctypes
import sys
import uuid
from ctypes import POINTER, byref, c_ulong, c_void_p, c_wchar_p

S_OK, S_FALSE = 0, 1
VT_BSTR = 8


def _guid(s):
    return (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(s).bytes_le)


CLSID_SystemDeviceEnum = "{62BE5D10-60EB-11d0-BD3B-00A0C911CE86}"
IID_ICreateDevEnum = "{29840822-5B84-11D0-BD3B-00A0C911CE86}"
CLSID_VideoInputDeviceCategory = "{860BB310-5D01-11d0-BD3B-00A0C911CE86}"
IID_IPropertyBag = "{55272A00-42CB-11CE-8135-00AA004BB851}"


def _method(obj, index, *argtypes):
    """Method number `index` of a COM interface pointer, as a callable taking the arguments after `this`."""
    vtable = ctypes.cast(ctypes.cast(obj, POINTER(c_void_p))[0], POINTER(c_void_p))
    fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)(vtable[index])
    return lambda *args: fn(obj, *args)


def _release(obj):
    if obj:
        vtable = ctypes.cast(ctypes.cast(obj, POINTER(c_void_p))[0], POINTER(c_void_p))
        ctypes.WINFUNCTYPE(c_ulong, c_void_p)(vtable[2])(obj)


def _read(bag, prop):
    var = (ctypes.c_byte * 24)()  # a VARIANT: vt at offset 0, the BSTR pointer at offset 8
    oleaut = ctypes.windll.oleaut32
    try:
        if _method(bag, 3, c_wchar_p, c_void_p, c_void_p)(prop, ctypes.addressof(var), None) != S_OK:
            return None
        if ctypes.c_ushort.from_buffer(var).value != VT_BSTR:
            return None
        return ctypes.wstring_at(c_void_p.from_buffer(var, 8).value)
    except OSError:
        return None
    finally:
        oleaut.VariantClear(c_void_p(ctypes.addressof(var)))


def list_devices():
    """[(name, device path or None)] for every video capture device, in DirectShow order; None if unavailable."""
    if sys.platform != "win32":
        return None
    ole = ctypes.windll.ole32
    init = ole.CoInitializeEx(None, 2)  # apartment threaded, as DirectShow expects; fine if already initialised
    dev_enum, mon_enum = c_void_p(), c_void_p()
    out = []
    # the GUIDs stay referenced for the whole call: a temporary one can be freed before Windows reads it, which
    # (seen from a background thread) makes it enumerate some other category, e.g. every DirectShow filter
    clsid_enum, iid_enum = _guid(CLSID_SystemDeviceEnum), _guid(IID_ICreateDevEnum)
    video_category, iid_bag = _guid(CLSID_VideoInputDeviceCategory), _guid(IID_IPropertyBag)
    try:
        if ole.CoCreateInstance(byref(clsid_enum), None, 1, byref(iid_enum), byref(dev_enum)) != S_OK:
            return None
        hr = _method(dev_enum, 3, c_void_p, POINTER(c_void_p), c_ulong)(
            ctypes.addressof(video_category), byref(mon_enum), 0)
        if hr == S_FALSE or not mon_enum:
            return []  # no cameras at all
        if hr != S_OK:
            return None
        while True:
            mon, fetched = c_void_p(), c_ulong()
            if _method(mon_enum, 3, c_ulong, POINTER(c_void_p), POINTER(c_ulong))(1, byref(mon), byref(fetched)) != S_OK \
                    or not fetched.value:
                break
            bag = c_void_p()
            try:
                if _method(mon, 9, c_void_p, c_void_p, c_void_p, POINTER(c_void_p))(
                        None, None, ctypes.addressof(iid_bag), byref(bag)) == S_OK:
                    out.append((_read(bag, "FriendlyName") or "camera", _read(bag, "DevicePath")))
                else:
                    out.append(("camera", None))
            finally:
                _release(bag)
                _release(mon)
        return out
    except OSError:
        return None
    finally:
        _release(mon_enum)
        _release(dev_enum)
        if init in (S_OK, S_FALSE):
            ole.CoUninitialize()


HEADSET_WORDS = ("etronvideo", "index", "valve", "vive", "oculus", "quest", "rift", "pico", "reverb", "mixed reality", "hololens")


def looks_like_headset(name):
    """True for names like 'eTronVideo' (the Valve Index's camera) or 'HTC Vive': a VR headset's own camera."""
    n = (name or "").lower()
    return any(w in n for w in HEADSET_WORDS)


if __name__ == "__main__":
    for i, (name, path) in enumerate(list_devices() or []):
        print(i, name, path)
