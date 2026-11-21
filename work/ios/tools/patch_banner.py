"""给 companion 加：mDNS 广播 superlocator.local + 启动横幅 + 二维码页（QR.svg / QR.png）。

跑法：python tools/patch_banner.py
"""
import io
import re
from pathlib import Path

SRC = Path("companion/superlocator.py")
text = SRC.read_text(encoding="utf-8")

if "_print_banner" in text:
    print("already patched")
    raise SystemExit(0)

HELPERS = '''
# ---------------------------------------------------------------- 局域网彩蛋
_MDNS = None          # (Zeroconf, ServiceInfo)


def mdns_start(http_port: int) -> str:
    """广播 superlocator.local:http_port，手机不用记 IP。失败返回空串。"""
    global _MDNS
    try:
        from zeroconf import Zeroconf, ServiceInfo
    except Exception:
        return ""
    try:
        ip = _lan_ip()
        info = ServiceInfo(
            "_http._tcp.local.",
            "SuperLocator._http._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=int(http_port),
            properties={"path": "/", "app": "superlocator"},
            server="superlocator.local.",
        )
        zc = Zeroconf()
        zc.register_service(info)
        _MDNS = (zc, info)
        return "superlocator.local"
    except Exception:
        return ""


def mdns_stop() -> None:
    global _MDNS
    if not _MDNS:
        return
    try:
        zc, info = _MDNS
        zc.unregister_service(info)
        zc.close()
    except Exception:
        pass
    _MDNS = None


def qr_svg(url: str) -> bytes:
    """不依赖 Pillow 的二维码：qrcode 的 SVG 工厂。"""
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, border=2, box_size=10)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()


def qr_png(url: str) -> bytes:
    """有 Pillow 就走 PNG（相机识别更快），没有回退 SVG。"""
    try:
        import qrcode
        from PIL import Image  # noqa: F401
    except Exception:
        return b""
    img = qrcode.make(url, border=2, box_size=8)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _print_banner(http_port: int) -> None:
    ip = _lan_ip()
    name = mdns_start(http_port)
    urls = []
    if name:
        urls.append(f"http://{name}:{http_port}/")
    urls.append(f"http://{ip}:{http_port}/")

    line = "=" * 60
    print("")
    print(line)
    print("  超级虚拟定位 · 电脑端已就绪（这个窗口不要关）")
    print("  iPhone 用 Safari 打开下面任意一行：")
    for u in urls:
        print(f"      {u}")
    print("  手机上直接扫码也行：相机对着下面这块方块")
    print(line)
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(urls[0])
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception:
        print("  （没装 qrcode，跳过二维码，手打上面的地址即可）")
    print(line)
    print("  首次使用：手机页面顶部粘激活码 → 点「激活」→ 就能选轨迹 / 路径")
    print(line)
    print("")

'''

# 1) 插入 helper（放在 _WebHandler 之前）
anchor = "class _WebHandler(http.server.BaseHTTPRequestHandler):"
assert anchor in text
text = text.replace(anchor, HELPERS.lstrip("\n") + "\n\n" + anchor, 1)

# 2) /qr 路由
anchor2 = '        if path == "/api/status":'
assert anchor2 in text
qr_route = '''        if path in ("/qr.png", "/qr.svg"):
            port = int(self.server.server_address[1])          # type: ignore[attr-defined]
            url = f"http://{_lan_ip()}:{port}/"
            png = qr_png(url) if path.endswith(".png") else b""
            if png:
                self._send(png, "image/png")
            else:
                self._send(qr_svg(url), "image/svg+xml")
            return
        if path == "/api/status":'''
text = text.replace(anchor2, qr_route, 1)

# 3) serve 启动时打横幅
old = '''    if args.http_port:
        web = WebBridge((args.host, args.http_port), srv)
        threading.Thread(target=web.serve_forever, daemon=True).start()
        print(f"网页版（iPhone Safari 直接打开，不用装任何东西）：http://{_lan_ip()}:{args.http_port}/")'''
assert old in text
new = '''    if args.http_port:
        web = WebBridge((args.host, args.http_port), srv)
        threading.Thread(target=web.serve_forever, daemon=True).start()
        _print_banner(args.http_port)'''
text = text.replace(old, new, 1)

# 4) 退出时停掉 mDNS
old2 = '''    finally:
        player.stop()
        srv.server_close()'''
assert old2 in text
text = text.replace(old2, '''    finally:
        player.stop()
        mdns_stop()
        srv.server_close()''', 1)

SRC.write_text(text, encoding="utf-8", newline="\n")
print("patched companion/superlocator.py")