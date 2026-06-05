import os
import sys
import json
import base64
import time
import threading
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify
import requests
from Crypto.Cipher import AES

# Redefine print to flush output immediately
import builtins
def print(*args, **kwargs):
    kwargs.setdefault('flush', True)
    builtins.print(*args, **kwargs)

app = Flask(__name__)

# Thread-safe global variables for proxy caching and tracking
PROXY_CACHE = []
LAST_PROXY_FETCH_TIME = 0
CACHE_TTL = 300  # 5 minutes
LAST_WORKING_PROXY = None
proxy_lock = threading.Lock()

# Persistent session pool for TCP Keep-Alive
SESSION_POOL = {}
session_pool_lock = threading.Lock()

def get_persistent_session(proxy=None):
    global SESSION_POOL
    proxy_key = proxy if proxy else "direct"
    with session_pool_lock:
        if proxy_key in SESSION_POOL:
            return SESSION_POOL[proxy_key]
        
        session = requests.Session()
        if proxy:
            proxy_url = proxy if proxy.startswith("http") else f"http://{proxy}"
            session.proxies = {
                "http": proxy_url,
                "https": proxy_url
            }
        
        # Set persistent headers
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
            'Authorization': 'Basic c3VwZXJ1c2VyOkl0Z2lAMTIz',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Origin': 'https://www.iffcotokio.co.in',
            'Referer': 'https://www.iffcotokio.co.in/'
        })
        
        # Configure connection pooling limits
        adapter = requests.adapters.HTTPAdapter(pool_connections=25, pool_maxsize=25)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        SESSION_POOL[proxy_key] = session
        return session

# AES decryption/encryption configuration (key from Iffco Angular bundle)
DECRYPTION_KEY = b"g2t4k6inlFi2XS2g"

def decrypt_response(encrypted_b64):
    try:
        ciphertext = base64.b64decode(encrypted_b64)
        cipher = AES.new(DECRYPTION_KEY, AES.MODE_ECB)
        decrypted_bytes = cipher.decrypt(ciphertext)
        
        # Unpad PKCS7
        pad_len = decrypted_bytes[-1]
        if 1 <= pad_len <= 16:
            decrypted_bytes = decrypted_bytes[:-pad_len]
            
        return decrypted_bytes.decode('utf-8', errors='ignore')
    except Exception as e:
        return f"Decryption Error: {e}"

def encrypt_payload(data):
    try:
        if isinstance(data, (dict, list)):
            data_str = json.dumps(data)
        else:
            data_str = str(data)
            
        raw = data_str.encode('utf-8')
        
        # Pad raw data to 16 bytes block size (PKCS7)
        pad_len = 16 - (len(raw) % 16)
        raw += bytes([pad_len] * pad_len)
        
        cipher = AES.new(DECRYPTION_KEY, AES.MODE_ECB)
        encrypted_bytes = cipher.encrypt(raw)
        
        return base64.b64encode(encrypted_bytes).decode('utf-8')
    except Exception as e:
        return f"Encryption Error: {e}"

def get_free_proxies():
    # 1. Try to load from environment variable first (secure for Vercel/production)
    env_proxies = os.environ.get("PROXIES")
    if env_proxies:
        try:
            static_proxies = []
            # Split by comma or newline
            lines = env_proxies.replace(",", "\n").split("\n")
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(":")
                if len(parts) == 4:
                    ip, port, user, pwd = parts
                    static_proxies.append(f"http://{user}:{pwd}@{ip}:{port}")
                elif "@" in line:
                    static_proxies.append(line if line.startswith("http") else f"http://{line}")
                else:
                    static_proxies.append(line if line.startswith("http") else f"http://{line}")
            if static_proxies:
                return static_proxies
        except Exception as e:
            print(f"Error parsing PROXIES environment variable: {e}")

    # 2. Try to load static proxies from proxies.txt first
    if os.path.exists("proxies.txt"):
        try:
            static_proxies = []
            with open("proxies.txt", "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(":")
                    if len(parts) == 4:
                        ip, port, user, pwd = parts
                        static_proxies.append(f"http://{user}:{pwd}@{ip}:{port}")
                    elif "@" in line:
                        static_proxies.append(line if line.startswith("http") else f"http://{line}")
                    else:
                        static_proxies.append(line if line.startswith("http") else f"http://{line}")
            if static_proxies:
                return static_proxies
        except Exception as e:
            print(f"Error reading proxies.txt: {e}")

    # 3. Fallback to cached/ProxyScrape list
    global PROXY_CACHE, LAST_PROXY_FETCH_TIME
    now = time.time()
    with proxy_lock:
        if PROXY_CACHE and (now - LAST_PROXY_FETCH_TIME < CACHE_TTL):
            return list(PROXY_CACHE)
    
    try:
        # Fetch HTTPS-capable, anonymous proxies with short timeouts from ProxyScrape (strictly Indian proxies)
        url = 'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=IN&ssl=yes&anonymity=anonymous'
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            proxies = [line.strip() for line in r.text.split('\n') if line.strip()]
            if proxies:
                with proxy_lock:
                    PROXY_CACHE = proxies
                    LAST_PROXY_FETCH_TIME = now
                return proxies
    except Exception as e:
        print(f"Error fetching proxy list from ProxyScrape: {e}")
    
    with proxy_lock:
        return list(PROXY_CACHE) if PROXY_CACHE else []

def execute_vehicle_query_with_proxy(reg_no, mobile_no="8894659552", proxy=None, timeout=5):
    proxies = None
    if proxy:
        proxy_url = proxy if proxy.startswith("http") else f"http://{proxy}"
        proxies = {
            "http": proxy_url,
            "https": proxy_url
        }

    # Step 1: Register lookup request on landing page to obtain URN
    save_url = "https://www.iffcotokio.co.in/content/iffcotokio/saverequest.json"
    save_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        "Referer": "https://www.iffcotokio.co.in/"
    }
    save_files = {
        'redirect': (None, 'PCP_REN'),
        'contractType': (None, 'PCP'),
        'regno': (None, reg_no),
        'mobile': (None, mobile_no),
        'whatsappAlerts': (None, 'Y'),
        'redirectUrl': (None, '/portal/private-car'),
        'pagePath': (None, '/'),
        'formName': (None, 'quick-renew'),
        'utm_source': (None, '')
    }

    try:
        r_save = requests.post(save_url, headers=save_headers, files=save_files, timeout=timeout, proxies=proxies)
        if r_save.status_code != 200:
            return {"error": f"Registration failed on landing page (Status {r_save.status_code})"}
        
        res_json = r_save.json()
        redirect_url = res_json.get("redirectUrl", "")
        if not redirect_url:
            return {"error": "No redirect URL in registration response", "details": res_json}
            
        parsed_url = urlparse(redirect_url)
        queries = parse_qs(parsed_url.query)
        urn_list = queries.get("urn")
        if not urn_list:
            return {"error": "URN parameter not found in redirect URL", "redirectUrl": redirect_url}
        urn = urn_list[0]
    except Exception as e:
        return {"error": f"Error during landing page registration: {e}"}

    # Get a persistent session for TCP reuse
    session = get_persistent_session(proxy)
    # Clear cookies so concurrent or consecutive requests don't leak session context
    session.cookies.clear()

    # Step 2: Associate the URN with a fresh session context
    request_url = 'https://online.iffcotokio.co.in/portal-services/request'
    raw_payload = {
        "urn": urn,
        "cpid": None,
        "nginx": "agail"
    }
    encrypted_zQ = encrypt_payload(raw_payload)
    
    try:
        r_req = session.post(request_url, json={"zQ": encrypted_zQ}, timeout=timeout)
        if r_req.status_code != 200:
            return {"error": f"Failed to submit request payload (Status {r_req.status_code})"}
    except Exception as e:
        return {"error": f"Error during context request binding: {e}"}

    # Step 3: Trigger vehicle lookup via Fastlane (Vahan API)
    quick_info_url = 'https://online.iffcotokio.co.in/portal-services/vehicle/quick-info'
    try:
        session.get(quick_info_url, timeout=timeout)
    except Exception as e:
        return {"error": f"Error triggering Fastlane lookup: {e}"}

    # Step 4: Fetch populated session context containing full details
    context_url = 'https://online.iffcotokio.co.in/portal-services/context/data'
    try:
        r_final = session.get(context_url, timeout=timeout)
        if r_final.status_code != 200:
            return {"error": f"Failed to retrieve context data (Status {r_final.status_code})"}
        
        final_json = r_final.json()
        enc_obj = final_json.get("object")
        if enc_obj:
            decrypted_final = decrypt_response(enc_obj)
            return json.loads(decrypted_final)
        else:
            return {"error": "No encrypted object returned in final response", "details": final_json}
    except Exception as e:
        return {"error": f"Error fetching populated vehicle context: {e}"}

def mask_proxy(proxy_url):
    if not proxy_url:
        return "direct"
    try:
        parsed = urlparse(proxy_url)
        host = parsed.netloc.split("@")[-1]
        return f"{parsed.scheme}://{host}"
    except Exception:
        return "proxy"

def execute_vehicle_query(reg_no, mobile_no="8894659552"):
    global LAST_WORKING_PROXY
    import random
    logs = []
    proxy_used = None
    
    # 1. Fast-path check: attempt lookup using the LAST_WORKING_PROXY first
    with proxy_lock:
        fast_proxy = LAST_WORKING_PROXY
        
    if fast_proxy:
        masked_fast = mask_proxy(fast_proxy)
        logs.append(f"Fast-path: attempting query via last working proxy {masked_fast}...")
        print(f"Fast-path check: attempting query via last working proxy {fast_proxy}...")
        result = execute_vehicle_query_with_proxy(reg_no, mobile_no, fast_proxy, timeout=5)
        if isinstance(result, dict) and "vehicle" in result:
            vehicle_data = result["vehicle"]
            if vehicle_data.get("fastLaneSuccess") and vehicle_data.get("chasisNo"):
                logs.append(f"Fast-path success: resolved vehicle details (chassis: {vehicle_data.get('chasisNo')})")
                print(f"  [Success] Fast-path proxy {fast_proxy} resolved full vehicle details (chassis: {vehicle_data.get('chasisNo')})")
                return result, logs, fast_proxy
            else:
                logs.append("Fast-path warning: connected but chassis/engine was empty.")
                print(f"  [Warning] Fast-path proxy {fast_proxy} connected but chassis/engine was empty.")
        else:
            err_msg = result.get('error', 'Unknown Error') if isinstance(result, dict) else str(result)
            logs.append(f"Fast-path failed: {err_msg}. Clearing last working proxy.")
            print(f"  [Failed] Fast-path proxy {fast_proxy} failed: {err_msg}. Clearing last working proxy.")
            with proxy_lock:
                if LAST_WORKING_PROXY == fast_proxy:
                    LAST_WORKING_PROXY = None

    # 2. Fallback to parallel execution
    proxy_list = get_free_proxies()
    if not proxy_list:
        logs.append("Proxy list empty. Running direct query...")
        print("ProxyScrape list empty. Running direct query...")
        result = execute_vehicle_query_with_proxy(reg_no, mobile_no, proxy=None, timeout=5)
        return result, logs, None

    # Filter out fast_proxy from the search if it already failed
    if fast_proxy and fast_proxy in proxy_list:
        proxy_list = [p for p in proxy_list if p != fast_proxy]
        
    random.shuffle(proxy_list)
    candidates = proxy_list[:10]
    if not candidates:
        logs.append("No other proxy candidates. Running direct query...")
        print("No other proxy candidates. Running direct query...")
        result = execute_vehicle_query_with_proxy(reg_no, mobile_no, proxy=None, timeout=5)
        return result, logs, None

    logs.append(f"Attempting query for {reg_no} in parallel across {len(candidates)} proxies.")
    print(f"Attempting query for {reg_no} in parallel across {len(candidates)} proxies...")
    
    best_fallback = None
    best_fallback_proxy = None
    best_fallback_lock = threading.Lock()
    
    # We use ThreadPoolExecutor to run queries in parallel
    with ThreadPoolExecutor(max_workers=len(candidates)) as executor:
        future_to_proxy = {
            executor.submit(execute_vehicle_query_with_proxy, reg_no, mobile_no, proxy, 5): proxy 
            for proxy in candidates
        }
        
        # As soon as we get a response, process it
        for future in as_completed(future_to_proxy):
            proxy = future_to_proxy[future]
            masked_p = mask_proxy(proxy)
            try:
                result = future.result()
                if isinstance(result, dict) and "vehicle" in result:
                    vehicle_data = result["vehicle"]
                    if vehicle_data.get("fastLaneSuccess") and vehicle_data.get("chasisNo"):
                        logs.append(f"Proxy success: {masked_p} resolved vehicle details (chassis: {vehicle_data.get('chasisNo')})")
                        print(f"  [Success] Proxy {proxy} resolved full vehicle details (chassis: {vehicle_data.get('chasisNo')})")
                        with proxy_lock:
                            LAST_WORKING_PROXY = proxy
                        # Cancel remaining pending futures to save resources
                        executor.shutdown(wait=False, cancel_futures=True)
                        return result, logs, proxy
                    else:
                        logs.append(f"Proxy warning: {masked_p} connected, but lookup returned empty chassis/engine data.")
                        print(f"  [Warning] Proxy {proxy} connected, but Vahan lookup returned empty chassis/engine data.")
                        with best_fallback_lock:
                            if best_fallback is None:
                                best_fallback = result
                                best_fallback_proxy = proxy
                else:
                    err_msg = result.get('error', 'Unknown Error') if isinstance(result, dict) else str(result)
                    logs.append(f"Proxy failed: {masked_p} - {err_msg}")
                    print(f"  [Failed] Proxy {proxy} failed: {err_msg}")
            except Exception as exc:
                logs.append(f"Proxy exception: {masked_p} - {exc}")
                print(f"  [Error] Proxy {proxy} generated an exception: {exc}")

    # If any proxy returned a structured result (even if Vahan was empty/unsuccessful), return the best fallback
    with best_fallback_lock:
        if best_fallback:
            logs.append(f"Returning best response from parallel proxy attempts via {mask_proxy(best_fallback_proxy)}")
            print("Returning the best response from parallel proxy attempts...")
            return best_fallback, logs, best_fallback_proxy

    # Fallback to direct connection if all proxies completely timed out / errored
    logs.append("All proxies failed. Falling back to direct connection.")
    print("All proxies failed. Falling back to direct connection...")
    result = execute_vehicle_query_with_proxy(reg_no, mobile_no, proxy=None, timeout=5)
    return result, logs, None

def clean_empty_values(data):
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            cleaned_v = clean_empty_values(v)
            if cleaned_v not in [None, "", {}, []]:
                cleaned[k] = cleaned_v
        return cleaned
    elif isinstance(data, list):
        cleaned = []
        for item in data:
            cleaned_item = clean_empty_values(item)
            if cleaned_item not in [None, "", {}, []]:
                cleaned.append(cleaned_item)
        return cleaned
    else:
        return data

@app.route('/')
def home():
    return jsonify({
        "status": "success",
        "message": "IFFCO Tokio Vehicle Registration Lookup API is running!",
        "endpoints": {
            "query_vehicle": "/api/vehicle?reg_no=<REGISTRATION_NO>"
        }
    })

@app.route('/api/vehicle', methods=['GET', 'POST'])
def query_vehicle():
    reg_no = ""
    mobile_no = "8894659552"

    if request.method == 'POST':
        # Support JSON POST requests
        req_data = request.get_json(silent=True) or {}
        reg_no = req_data.get('reg_no', '').strip().upper()
        mobile_no = req_data.get('mobile', mobile_no).strip()
    else:
        # Support GET requests
        reg_no = request.args.get('reg_no', '').strip().upper()
        mobile_no = request.args.get('mobile', mobile_no).strip()

    if not reg_no:
        return jsonify({
            "status": "error",
            "message": "Missing required parameter 'reg_no'. Provide it in the query string or as a JSON body field."
        }), 400

    start_time = time.time()
    result, logs, proxy_used = execute_vehicle_query(reg_no, mobile_no)
    elapsed_time = round(time.time() - start_time, 2)
    
    if isinstance(result, dict) and "error" in result:
        return jsonify({
            "status": "error",
            "message": result["error"],
            "details": result.get("details", result.get("raw", "")),
            "dev_info": {
                "developer": "saahiyo-cloud",
                "elapsed_time_seconds": elapsed_time
            }
        }), 500

    # Filter result to keep only essential vehicle information for OSINT tool
    if isinstance(result, dict):
        vehicle_data = result.get("vehicle")
        if isinstance(vehicle_data, dict):
            vehicle_keys_to_keep = {
                "registrationNo", "chasisNo", "engineNo", "manufacturer", "model", "variant",
                "fuelType", "seatingCapacity", "dateOfFirstRegistration", 
                "monthAndYearOfRegistartion", "yearOfMake", "vehicleAge", "stateName", "cityName", 
                "cityDisplayName", "policyNumber", "previousInsurer", "previousPolicyNo", 
                "previousPolicyExpiryDate", "hypothecation"
            }
            cleaned_vehicle = {k: v for k, v in vehicle_data.items() if k in vehicle_keys_to_keep}
            result = {"vehicle": cleaned_vehicle}

    # Filter out empty, None, and empty nested structures
    filtered_result = clean_empty_values(result)
    
    # Append dev_info node
    filtered_result["dev_info"] = {
        "developer": "saahiyo-cloud",
        "elapsed_time_seconds": elapsed_time
    }
    
    return jsonify(filtered_result)

if __name__ == '__main__':
    # Run the server locally on port 5000
    app.run(host='0.0.0.0', port=5000, debug=True)
