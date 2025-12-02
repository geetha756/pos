# Machines API Documentation for Node-RED Integration

This document provides instructions for integrating Vada and Idly machines with the Sip & Snack Portal using the push method.

## Overview

The portal provides REST API endpoints to receive machine data via HTTP POST requests. Your Node-RED flows should send data continuously to these endpoints.

## Base URL

**Development:** `http://127.0.0.1:5000`  
**Production:** `https://portal.snfifteen.com`

## Endpoints

### 1. Push Vada Machine Data

**Endpoint:** `POST /machines/api/push/vada`

**URL Examples:**
- Development: `http://127.0.0.1:5000/machines/api/push/vada`
- Production: `https://portal.snfifteen.com/machines/api/push/vada`

### 2. Push Idly Machine Data

**Endpoint:** `POST /machines/api/push/idly`

**URL Examples:**
- Development: `http://127.0.0.1:5000/machines/api/push/idly`
- Production: `https://portal.snfifteen.com/machines/api/push/idly`

## Request Format

### Headers
```
Content-Type: application/json
```

### Request Body (JSON)

Both endpoints accept the same JSON structure. The frontend dashboard expects specific fields to display data correctly:

#### Vada Machine Expected Fields:

```json
{
  "machine_id": "vada-001",              // Optional: Unique identifier for the machine
  "status": "active",                    // Required: One of: "active", "idle", "error", "maintenance"
  "temperature": 85.5,                    // REQUIRED for Vada: Oil temperature in Celsius (displayed as "Oil Temperature")
  "humidity": 65.0,                       // Optional: Humidity percentage (0-100)
  "pressure": 1.2,                       // Optional: Pressure in PSI or bar
  "battery_level": 95,                   // Optional: Battery percentage (0-100)
  "signal_strength": 85,                 // Optional: Signal strength (0-100)
  "production_count": 150,                // REQUIRED for Vada: Total vadas dispensed (displayed as "Dispensed Count")
  "cycle_count": 25,                     // Optional: Number of cycles completed (default: 0)
  "error_code": null,                    // Optional: Error code if any
  "error_message": null,                  // Optional: Error description
  "location_id": "uuid-string",           // Optional: Location UUID from portal
  "metadata": {                           // Optional: Additional custom data
    "batch_number": "B001",
    "recipe_id": "R001",
    "voltage": "230 V",                   // Power metrics (optional but recommended)
    "current": "5.2 A",                   // Power metrics (optional but recommended)
    "power": "1200 W",                    // Power metrics (optional but recommended)
    "energy": "2.5 kWh",                  // Power metrics (optional but recommended)
    "frequency": "50 Hz",                 // Power metrics (optional but recommended)
    "powerFactor": "0.95"                 // Power metrics (optional but recommended)
  }
}
```

#### Idly Machine Expected Fields:

```json
{
  "machine_id": "idly-001",              // Optional: Unique identifier for the machine
  "status": "active",                    // Required: One of: "active", "idle", "error", "maintenance"
  "temperature": 90.0,                     // REQUIRED for Idly: Water temperature in Celsius (displayed as "Water Temperature")
  "humidity": 70.0,                       // Optional: Humidity percentage (0-100)
  "pressure": 1.5,                       // REQUIRED for Idly: Pressure in PSI (displayed as "Pressure Data")
  "battery_level": 90,                   // Optional: Battery percentage (0-100)
  "signal_strength": 80,                 // Optional: Signal strength (0-100)
  "production_count": 200,                // Optional: Total items produced (default: 0)
  "cycle_count": 30,                     // Optional: Number of cycles completed (default: 0)
  "error_code": null,                    // Optional: Error code if any
  "error_message": null,                  // Optional: Error description
  "location_id": "uuid-string",           // Optional: Location UUID from portal
  "metadata": {                           // Optional: Additional custom data
    "batch_number": "B002",
    "recipe_id": "R002",
    "voltage": "230 V",                   // Power metrics (optional but recommended)
    "current": "4.8 A",                   // Power metrics (optional but recommended)
    "power": "1100 W",                    // Power metrics (optional but recommended)
    "energy": "2.2 kWh",                  // Power metrics (optional but recommended)
    "frequency": "50 Hz",                 // Power metrics (optional but recommended)
    "powerFactor": "0.92"                 // Power metrics (optional but recommended)
  }
}
```

### Field Descriptions

| Field | Type | Required | Description | Frontend Display |
|-------|------|----------|-------------|------------------|
| `machine_id` | string | No | Unique identifier for the physical machine (e.g., "vada-001", "idly-002") | Not displayed directly |
| `status` | string | **Yes** | Machine status: "active", "idle", "error", or "maintenance" | Shown as status badge (Ready/Offline) |
| `temperature` | number | **Yes** | **Vada:** Oil temperature in Celsius<br>**Idly:** Water temperature in Celsius | **Vada:** "Oil Temperature" card<br>**Idly:** "Water Temperature" card |
| `humidity` | number | No | Humidity percentage (0-100) | Not currently displayed |
| `pressure` | number | **Yes (Idly)** | Pressure reading in PSI or bar | **Idly:** "Pressure Data" card |
| `battery_level` | integer | No | Battery percentage (0-100) | Not currently displayed |
| `signal_strength` | integer | No | Signal strength percentage (0-100) | Not currently displayed |
| `production_count` | integer | **Yes (Vada)** | **Vada:** Total vadas dispensed<br>**Idly:** Total items produced | **Vada:** "Dispensed Count" card<br>**Idly:** Not displayed |
| `cycle_count` | integer | No | Number of production cycles completed (default: 0) | Not currently displayed |
| `error_code` | string | No | Error code if machine is in error state | Not currently displayed |
| `error_message` | string | No | Human-readable error description | Not currently displayed |
| `location_id` | string (UUID) | No | Location UUID from the portal (if machine is linked to a location) | Not displayed directly |
| `metadata` | object | No | Additional custom data. Can include power metrics: `voltage`, `current`, `power`, `energy`, `frequency`, `powerFactor` | Power metrics shown in "Power" card when clicked |

### Frontend Dashboard Display Mapping

The React dashboard displays data as follows:

#### Vada Machine Dashboard:
- **Status Badge:** Shows "Ready" (green) or "Offline" (red) based on `status` field
- **Oil Temperature Card:** Displays `temperature` value with "°C" unit
- **Dispensed Count Card:** Displays `production_count` value
- **Power Card:** Shows power metrics from `metadata` object:
  - `metadata.voltage` → "Voltage"
  - `metadata.current` → "Current"
  - `metadata.power` → "Active Power"
  - `metadata.energy` → "Energy"
  - `metadata.frequency` → "Frequency"
  - `metadata.powerFactor` → "Power Factor"

#### Idly Machine Dashboard:
- **Status Badge:** Shows "Machine ON" (green) or "Machine OFF" (red) based on `status` field
- **Water Temperature Card:** Displays `temperature` value with "°C" unit
- **Pressure Data Card:** Displays `pressure` value with "PSI" unit
- **Power Card:** Shows power metrics from `metadata` object (same as Vada)

### Important Notes:

1. **Temperature Field:**
   - For Vada: This is the **oil temperature** (displayed as "Oil Temperature")
   - For Idly: This is the **water temperature** (displayed as "Water Temperature")

2. **Production Count:**
   - For Vada: This is **critical** - it shows the total number of vadas dispensed
   - For Idly: Currently not displayed but can be included for future use

3. **Pressure:**
   - For Idly: This is **critical** - it shows the pressure reading in PSI
   - For Vada: Optional but can be included

4. **Power Metrics:**
   - Should be included in the `metadata` object
   - Format: `"voltage": "230 V"`, `"current": "5.2 A"`, etc.
   - These are displayed when user clicks the "Power" card

## Response Format

### Success Response

**Status Code:** `200 OK`

```json
{
  "success": true,
  "message": "Vada machine data received successfully",
  "timestamp": "2024-11-29T12:34:56.789Z"
}
```

### Error Response

**Status Code:** `400 Bad Request` or `500 Internal Server Error`

```json
{
  "success": false,
  "error": "Error message describing what went wrong"
}
```

## Node-RED Integration Example

### HTTP Request Node Configuration

1. **Method:** `POST`
2. **URL:** 
   - For Vada: `http://127.0.0.1:5000/machines/api/push/vada`
   - For Idly: `http://127.0.0.1:5000/machines/api/push/idly`
3. **Headers:**
   ```
   Content-Type: application/json
   ```
4. **Body:** JSON payload with machine data

### Example Node-RED Flow

```javascript
// Example function node to format data
msg.payload = {
    "machine_id": "vada-001",
    "status": msg.status || "active",
    "temperature": msg.temperature,
    "humidity": msg.humidity,
    "pressure": msg.pressure,
    "battery_level": msg.battery_level,
    "signal_strength": msg.signal_strength,
    "production_count": msg.production_count || 0,
    "cycle_count": msg.cycle_count || 0,
    "error_code": msg.error_code || null,
    "error_message": msg.error_message || null,
    "location_id": msg.location_id || null,
    "metadata": {
        "batch_number": msg.batch_number,
        "recipe_id": msg.recipe_id
    }
};

msg.headers = {
    "Content-Type": "application/json"
};

return msg;
```

### Recommended Push Frequency

- **Minimum:** Every 30 seconds (for real-time monitoring)
- **Recommended:** Every 10-15 seconds (for responsive dashboard updates)
- **Maximum:** Every 5 seconds (to avoid overwhelming the server)

**Note:** The portal stores all received data points, so you can adjust the frequency based on your needs. More frequent updates provide better real-time visibility.

## Data Retrieval Endpoints (For Dashboard)

The portal also provides endpoints to retrieve machine data for the dashboard:

### Get Latest Data

**Endpoint:** `GET /machines/api/data/latest`

**Query Parameters:**
- `machine_type` (optional): `"vada"` or `"idly"` - Filter by machine type

**Example:**
```
GET /machines/api/data/latest
GET /machines/api/data/latest?machine_type=vada
```

**Response:**
```json
{
  "success": true,
  "data": {
    "vada": {
      "id": "uuid",
      "machine_type": "vada",
      "machine_id": "vada-001",
      "status": "active",
      "temperature": 85.5,
      "humidity": 65.0,
      "pressure": 1.2,
      "battery_level": 95,
      "signal_strength": 85,
      "production_count": 150,
      "cycle_count": 25,
      "error_code": null,
      "error_message": null,
      "location_id": null,
      "metadata": {},
      "received_at": "2024-11-29T12:34:56.789Z",
      "created_at": "2024-11-29T12:34:56.789Z"
    },
    "idly": {
      // Similar structure for idly machine
    }
  }
}
```

### Get Historical Data

**Endpoint:** `GET /machines/api/data`

**Query Parameters:**
- `machine_type` (optional): `"vada"` or `"idly"`
- `machine_id` (optional): Specific machine ID
- `limit` (optional): Number of records (default: 100, max: 1000)
- `hours` (optional): Fetch data from last N hours (default: 24)

**Example:**
```
GET /machines/api/data?machine_type=vada&limit=50&hours=12
```

### Get Statistics

**Endpoint:** `GET /machines/api/stats`

**Query Parameters:**
- `machine_type` (optional): `"vada"` or `"idly"`
- `hours` (optional): Time range in hours (default: 24)

**Example:**
```
GET /machines/api/stats?machine_type=vada&hours=24
```

## Testing

### Using cURL

**Test Vada endpoint:**
```bash
curl -X POST http://127.0.0.1:5000/machines/api/push/vada \
  -H "Content-Type: application/json" \
  -d '{
    "machine_id": "vada-001",
    "status": "active",
    "temperature": 85.5,
    "humidity": 65.0,
    "pressure": 1.2,
    "battery_level": 95,
    "signal_strength": 85,
    "production_count": 150,
    "cycle_count": 25
  }'
```

**Test Idly endpoint:**
```bash
curl -X POST http://127.0.0.1:5000/machines/api/push/idly \
  -H "Content-Type: application/json" \
  -d '{
    "machine_id": "idly-001",
    "status": "active",
    "temperature": 90.0,
    "humidity": 70.0,
    "pressure": 1.5,
    "battery_level": 90,
    "signal_strength": 80,
    "production_count": 200,
    "cycle_count": 30
  }'
```

## Error Handling

1. **Network Errors:** Implement retry logic in Node-RED with exponential backoff
2. **Invalid Data:** The API will return a 400 error with details about missing/invalid fields
3. **Server Errors:** The API will return a 500 error - log these for debugging

## Security Notes

- Currently, the endpoints are open (no authentication required for push endpoints)
- For production, consider implementing API key authentication
- Use HTTPS in production to encrypt data in transit

## Support

For issues or questions:
1. Check the response error messages
2. Verify the JSON payload format matches the documentation
3. Ensure the Content-Type header is set to `application/json`
4. Verify network connectivity to the portal server

## Changelog

- **2024-11-29:** Initial API documentation created

