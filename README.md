# IFFCO Tokio Vehicle Registration Lookup API

A high-performance Flask API to retrieve vehicle registration profiles (including chassis number, engine number, and model variant details) from the IFFCO Tokio portal using parallel proxy execution and TCP connection pooling.

## Features

- **Streamlined Workflow**: Performs only the 4 essential network calls to resolve registration profiles.
- **TCP Connection Reuse**: Maintains a persistent connection pool via global sessions, bypassing TCP/SSL handshake overhead.
- **Session Isolation**: Automatically clears cookies per-request, preventing session collisions for concurrent/consecutive lookup tasks.
- **Static & Authenticated Proxy Support**: Loads user-defined premium proxies from `proxies.txt`.
- **Parallel Query Fallback**: Executes concurrent queries across multiple candidate proxies using a `ThreadPoolExecutor` if the cached fast-path proxy goes offline.

---

## Installation

1. **Install Python 3.8+**
2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

---

## Configuration

You can configure your proxies in two ways:

### 1. Environment Variable (Secure & Recommended for Vercel/Production)
Create a `PROXIES` environment variable in the Vercel/hosting dashboard.
- Set the value as a list of proxies separated by commas or newlines:
  ```text
  38.154.203.95:5863:tbuombnh:4pd2nzus99xj,198.105.121.200:6462:tbuombnh:4pd2nzus99xj
  ```
> [!WARNING]
> Since your GitHub repository is **Public**, you should **DELETE `proxies.txt` from GitHub** to prevent other people from stealing your Webshare proxy credentials and bandwidth. Using the `PROXIES` environment variable allows you to keep credentials completely private.

### 2. Local File Configuration (For Local Testing)
Place a `proxies.txt` file in the root of the folder. 
Supported formats:
- **Authenticated (Webshare Default)**: `ip:port:username:password`
- **Standard HTTP Proxy**: `ip:port`

> [!TIP]
> **To achieve 2–3s lookup speeds**: Buy or configure **Indian (IN)** proxies on your proxy dashboard. Since the target IFFCO portal is hosted in India, Indian proxies reduce round-trip network delays (RTT) from ~250ms to ~30ms.

---

## Running the Server

Start the Flask application:
```bash
python app.py
```
By default, the server runs locally on **`http://localhost:5000`**.

---

## API Usage

### Query Vehicle Details

* **Endpoint**: `/api/vehicle`
* **Method**: `GET` or `POST`
* **Query Parameters** (GET) or **JSON fields** (POST):
  * `reg_no` (Required): The vehicle registration number (e.g. `GJ05CP0239`).
  * `mobile` (Optional): The callback lead phone number.

#### Example Request (GET)
```bash
curl -s "http://localhost:5000/api/vehicle?reg_no=GJ05CP0239"
```

#### Example Response
```json
{
  "vehicle": {
    "chasisNo": "MA3EWDE1S00169912",
    "engineNo": "K10BN1300119",
    "fastLaneSuccess": true,
    "fuelType": "PETROL+CNG",
    "manufacturer": "MARUTI",
    "model": "WAGONR",
    "vehicleMakeDetails": "MARUTI WAGONR 1.0 LXI LE 998 CC PETROL+CNG",
    "yearOfMake": "2010"
  }
}
```
*(All empty/null properties are dynamically filtered out of the response).*

---

## Deploying to Vercel

The folder contains a [vercel.json](file:///c:/Users/Shakir/OneDrive/Desktop/New folder/chaloms vehicle/iffco_api/vercel.json) file which enables hosting the Flask app on Vercel's serverless infrastructure.

### Steps to Deploy:

1. **Install Vercel CLI**:
   ```bash
   npm install -g vercel
   ```
2. **Login to Vercel**:
   ```bash
   vercel login
   ```
3. **Deploy**:
   Navigate to the `iffco_api` folder and run:
   ```bash
   vercel
   ```
   Follow the prompts to configure and link the project.
4. **Important Considerations for Serverless Deployments**:
   - **Ephemeral Memory**: In-memory state tracking (like the `LAST_WORKING_PROXY` cache) will persist within warm serverless container instances but resets when containers recycle or scale to zero.
   - **Execution Timeouts**: Vercel's free tier has a 10-second request timeout limit. Since the streamlined 4-step lookup takes 4–5 seconds over US/Europe proxies and 2–3 seconds over Indian proxies, make sure to use **Indian (IN)** proxies in `proxies.txt` to keep execution safely within boundaries and avoid serverless timeouts.

