import re
import urllib.parse

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "utm_id",
    "gclid", "fbclid", "yclid", "mc_cid", "mc_eid", "ref", "ref_src", "source", 
    "campaign", "_ga", "igshid", "si", "spm", "mkt_tok", "vero_id", "oly_anon_id", "oly_enc_id"
}

def canonicalize_url(url: str) -> str:
    if not url:
        return ""
        
    url = url.strip()
    
    # 1. Предварительная доменная нормализация
    # YouTube short links to standard watch links
    if "youtu.be/" in url:
        match = re.search(r"youtu\.be/([a-zA-Z0-9_-]+)", url)
        if match:
            video_id = match.group(1)
            url = f"https://www.youtube.com/watch?v={video_id}"
            
    # arXiv PDF links to abstract pages
    if "arxiv.org/pdf/" in url:
        match = re.search(r"arxiv\.org/pdf/(\d+\.\d+)(?:\.pdf)?", url)
        if match:
            arxiv_id = match.group(1)
            url = f"https://arxiv.org/abs/{arxiv_id}"
            
    # Parse URL parts
    parsed = urllib.parse.urlparse(url)
    
    scheme = parsed.scheme.lower()
    if not scheme:
        scheme = "https"
        
    host = parsed.netloc.lower()
    if not host:
        return url
        
    # IDN (punycode) conversion
    try:
        host_parts = host.split(":")
        domain = host_parts[0]
        port = host_parts[1] if len(host_parts) > 1 else ""
        domain = domain.encode("idna").decode("ascii")
        host = f"{domain}:{port}" if port else domain
    except Exception:
        pass
        
    # Remove standard ports
    if scheme == "http" and host.endswith(":80"):
        host = host[:-3]
    elif scheme == "https" and host.endswith(":443"):
        host = host[:-4]
        
    # Path normalization
    path = parsed.path
    path = urllib.parse.unquote(path)  # decode safe percent-encoded characters
    path = re.sub(r'/{2,}', '/', path)  # replace multiple slashes
    
    # Remove trailing slash
    if path.endswith("/"):
        path = path[:-1]
        
    # Filter and sort query parameters
    query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    filtered_params = []
    
    for k, v in query_params:
        k_lower = k.lower()
        if k_lower in TRACKING_PARAMS or not k or not v:
            continue
        filtered_params.append((k, v))
        
    # Sort key-value pairs
    filtered_params.sort(key=lambda x: x[0])
    
    # Rebuild query string
    new_query = urllib.parse.urlencode(filtered_params)
    
    # 2. Пост-доменная нормализация
    # GitHub repo cleanup
    if host == "github.com":
        new_query = ""
        # GitHub repos do not require trailing slash or parts like /blob/main/
        # e.g., https://github.com/owner/repo/blob/main/README.md -> leave path, but query parameter is empty.
        
    # Habr clean query
    if "habr.com" in host:
        new_query = ""
        
    # OpenAI & Google Research clean queries
    if "openai.com" in host or "research.google" in host:
        new_query = ""
        
    # Build final canonical URL without fragment
    canonical = urllib.parse.urlunparse((
        scheme,
        host,
        path,
        "",
        new_query,
        ""
    ))
    
    return canonical
