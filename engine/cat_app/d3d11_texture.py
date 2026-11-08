"""A Direct3D 11 texture for the SteamVR tab (Windows only).

SteamVR's compositor is Direct3D 11, and this is how most overlay apps (XSOverlay, OVR Toolkit, Unity
overlays) hand it their pictures: a D3D11 texture on the graphics card that SteamVR copies from. The tab is
drawn by Qt as before, the finished picture is copied into this one texture (the same texture every time),
and its address goes to SteamVR's SetOverlayTexture. No OpenGL/Direct3D sharing, no picture files, and no
big uploads between programs, which is what made the earlier versions flicker.

Plain ctypes over d3d11.dll, so nothing extra to install. Only the four calls needed are used.
"""

import ctypes
from ctypes import POINTER, Structure, byref, c_uint, c_void_p, wintypes

DXGI_FORMAT_R8G8B8A8_UNORM = 28
DXGI_FORMAT_B8G8R8A8_UNORM = 87  # the byte order Qt's own pictures use (Format_ARGB32 on Windows), so no converting
D3D11_BIND_SHADER_RESOURCE = 0x8
D3D_DRIVER_TYPE_UNKNOWN = 0  # required when a specific adapter is given
D3D_DRIVER_TYPE_HARDWARE = 1
D3D11_SDK_VERSION = 7

# vtable slots (d3d11.h): ID3D11Device::CreateTexture2D, ID3D11DeviceContext::UpdateSubresource and ::Flush,
# IUnknown::Release
DEVICE_CREATE_TEXTURE2D = 5
CONTEXT_UPDATE_SUBRESOURCE = 48
CONTEXT_FLUSH = 111
RELEASE = 2
FACTORY1_ENUM_ADAPTERS1 = 12  # IDXGIFactory1::EnumAdapters1
ADAPTER1_GET_DESC1 = 10       # IDXGIAdapter1::GetDesc1


class GUID(Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]


IID_IDXGIFactory1 = GUID(0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))


class LUID(Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class DXGI_ADAPTER_DESC1(Structure):  # noqa: N801
    _fields_ = [("Description", ctypes.c_wchar * 128), ("VendorId", c_uint), ("DeviceId", c_uint),
                ("SubSysId", c_uint), ("Revision", c_uint), ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t), ("SharedSystemMemory", ctypes.c_size_t),
                ("AdapterLuid", LUID), ("Flags", c_uint)]


class DXGI_SAMPLE_DESC(Structure):  # noqa: N801
    _fields_ = [("Count", c_uint), ("Quality", c_uint)]


class D3D11_TEXTURE2D_DESC(Structure):  # noqa: N801
    _fields_ = [("Width", c_uint), ("Height", c_uint), ("MipLevels", c_uint), ("ArraySize", c_uint),
                ("Format", c_uint), ("SampleDesc", DXGI_SAMPLE_DESC), ("Usage", c_uint), ("BindFlags", c_uint),
                ("CPUAccessFlags", c_uint), ("MiscFlags", c_uint)]


def _method(obj, slot, restype, *argtypes):
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtbl[slot])


def _adapter(index):
    """The graphics card SteamVR renders on (index from IVRSystem.getDXGIOutputInfo), and its name.
    This PC has two (an NVIDIA card and AMD graphics in the CPU): the texture must live on SteamVR's."""
    factory = c_void_p()
    hr = ctypes.WinDLL("dxgi").CreateDXGIFactory1(byref(IID_IDXGIFactory1), byref(factory))
    if hr != 0 or not factory:
        raise OSError(f"CreateDXGIFactory1 failed (0x{hr & 0xFFFFFFFF:08X})")
    adapter = c_void_p()
    try:
        enum = _method(factory, FACTORY1_ENUM_ADAPTERS1, wintypes.LONG, c_uint, POINTER(c_void_p))
        hr = enum(factory, index, byref(adapter))
        if hr != 0 or not adapter:
            raise OSError(f"no graphics card number {index} (0x{hr & 0xFFFFFFFF:08X})")
        desc = DXGI_ADAPTER_DESC1()
        _method(adapter, ADAPTER1_GET_DESC1, wintypes.LONG, POINTER(DXGI_ADAPTER_DESC1))(adapter, byref(desc))
        return adapter, desc.Description
    finally:
        _method(factory, RELEASE, c_uint)(factory)


class D3D11Texture:
    def __init__(self, width, height, adapter_index):
        self.width, self.height = width, height
        self.device = c_void_p()
        self.context = c_void_p()
        self.texture = c_void_p()
        level = c_uint()
        if adapter_index is None or adapter_index < 0:
            raise OSError("SteamVR didn't say which graphics card it uses")
        adapter, self.adapter_name = _adapter(adapter_index)
        d3d11 = ctypes.WinDLL("d3d11")
        try:
            hr = d3d11.D3D11CreateDevice(adapter, D3D_DRIVER_TYPE_UNKNOWN, None, 0, None, 0, D3D11_SDK_VERSION,
                                         byref(self.device), byref(level), byref(self.context))
        finally:
            _method(adapter, RELEASE, c_uint)(adapter)
        if hr != 0 or not self.device:
            raise OSError(f"D3D11CreateDevice failed (0x{hr & 0xFFFFFFFF:08X})")
        desc = D3D11_TEXTURE2D_DESC(width, height, 1, 1, DXGI_FORMAT_B8G8R8A8_UNORM, DXGI_SAMPLE_DESC(1, 0),
                                    0, D3D11_BIND_SHADER_RESOURCE, 0, 0)
        create = _method(self.device, DEVICE_CREATE_TEXTURE2D, wintypes.LONG,
                         POINTER(D3D11_TEXTURE2D_DESC), c_void_p, POINTER(c_void_p))
        hr = create(self.device, byref(desc), None, byref(self.texture))
        if hr != 0 or not self.texture:
            self.close()
            raise OSError(f"CreateTexture2D failed (0x{hr & 0xFFFFFFFF:08X})")
        self._update = _method(self.context, CONTEXT_UPDATE_SUBRESOURCE, None,
                               c_void_p, c_uint, c_void_p, c_void_p, c_uint, c_uint)
        self._flush = _method(self.context, CONTEXT_FLUSH, None)

    @property
    def handle(self):
        """The ID3D11Texture2D pointer, for openvr.Texture_t.handle."""
        return self.texture.value

    def upload(self, address, row_bytes):
        """Copies a top-row-first BGRA picture (width x height) at this memory address into the texture,
        straight from Qt's picture: no conversion and no extra copies on the way."""
        self._update(self.context, self.texture, 0, None, address, row_bytes, 0)
        self._flush(self.context)

    def close(self):
        for p in (self.texture, self.context, self.device):
            if p:
                try:
                    _method(p, RELEASE, c_uint)(p)
                except OSError:
                    pass
        self.texture = self.context = self.device = c_void_p()
