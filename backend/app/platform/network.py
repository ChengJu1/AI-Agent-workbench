"""Public-only HTTP with DNS pinning at the socket boundary and bounded redirects."""
import ipaddress
import socket
import ssl
import time
from urllib.parse import urlsplit, urljoin, urlunsplit, quote

import httpcore
from app.errors import ServiceError


def public_addresses(host, port):
    try:
        addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    except OSError as error:
        raise ServiceError('网页域名无法解析，请稍后重试。', 502) from error
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ServiceError('仅允许公开互联网地址，不能访问本机、内网或保留地址。', 403)
    return addresses


def validate_url(url):
    try:
        parsed = urlsplit(url)
        if len(url) > 3000 or parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        if parsed.port not in (None, 80, 443):
            raise ValueError()
        host = parsed.hostname.encode('idna').decode('ascii')
        if any(ord(c) < 32 for c in url):
            raise ValueError()
    except (ValueError, UnicodeError) as error:
        raise ServiceError('请提供不含账号密码的公开 HTTP/HTTPS 网页地址（80/443 端口）。', 422) from error
    public_addresses(host, parsed.port or (443 if parsed.scheme == 'https' else 80))
    return parsed


class PublicBackend(httpcore.SyncBackend):
    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        addresses = public_addresses(host, port)
        # httpcore still uses the original hostname for TLS certificate verification.
        return super().connect_tcp(addresses[0], port, timeout, local_address, socket_options)


class PublicHttp:
    def request(self, url, method='GET', headers=None, body=None, max_bytes=2_000_000, follow=True):
        started = time.monotonic()
        with httpcore.ConnectionPool(ssl_context=ssl.create_default_context(), network_backend=PublicBackend(), max_connections=2) as pool:
            for _ in range(6):
                parsed = validate_url(url)
                host = parsed.hostname.encode('idna').decode('ascii')
                host = '[' + host + ']' if ':' in host else host
                netloc = host + (':' + str(parsed.port) if parsed.port else '')
                url = urlunsplit((parsed.scheme, netloc, quote(parsed.path or '/', safe="/%:@!$&'()*+,;=-._~"),
                                  quote(parsed.query, safe="%=&;:+,/?@!$'()*-._~"), ''))
                outgoing = {'User-Agent': 'Workbench/1.0 (public-page-reader)', 'Accept-Encoding': 'identity'}
                outgoing.update(headers or {})
                for key in list(outgoing):
                    if key.lower() in ('host', 'content-length', 'connection', 'proxy-authorization', 'accept-encoding'):
                        outgoing.pop(key)
                outgoing['Accept-Encoding'] = 'identity'
                try:
                    with pool.stream(method, url, headers=outgoing, content=body,
                                     extensions={'timeout': dict(connect=8, read=8, write=8, pool=8)}) as response:
                        result_headers = [(key.decode('latin1'), value.decode('latin1')) for key, value in response.headers]
                        lookup = {key.lower(): value for key, value in result_headers}
                        if follow and response.status in (301, 302, 303, 307, 308):
                            target = lookup.get('location')
                            if not target:
                                raise ServiceError('网页重定向缺少目标地址。', 502)
                            url = urljoin(url, target)
                            continue
                        chunks, size = [], 0
                        for chunk in response.iter_stream():
                            size += len(chunk)
                            if size > max_bytes or time.monotonic() - started > 25:
                                raise ServiceError('网页过大或读取超时，请选择更具体的页面。', 422)
                            chunks.append(chunk)
                        return {'url': url, 'status': response.status, 'headers': result_headers, 'body': b''.join(chunks)}
                except ServiceError:
                    raise
                except Exception as error:
                    raise ServiceError('网页读取失败，请检查网络或稍后重试；未绕过网站限制。', 502) from error
        raise ServiceError('网页重定向次数过多。', 422)
