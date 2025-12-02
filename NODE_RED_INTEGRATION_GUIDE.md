# Node-RED Integration Guide for Machines Dashboard

This guide provides step-by-step instructions for the Node-RED team to configure flows that push machine data to the Sip & Snack Portal.

## Overview

You need to create two separate Node-RED flows (or one flow with two branches) that continuously send data from:
1. **Vada Machine** → Portal endpoint
2. **Idly Machine** → Portal endpoint

## Step-by-Step Setup

### Step 1: Determine Your Data Source

Identify where your machine data comes from in Node-RED:
- MQTT messages
- HTTP requests
- Serial port readings
- Modbus/TCP
- Custom nodes
- etc.

### Step 2: Configure HTTP Request Nodes

For each machine (Vada and Idly), you'll need:

#### 2.1 Add HTTP Request Node

1. Drag an **HTTP Request** node onto your flow
2. Double-click to configure it

#### 2.2 Configure HTTP Request Node Settings

**For Vada Machine:**
- **Method:** `POST`
- **URL:** 
  - Development: `http://127.0.0.1:5000/machines/api/push/vada`
  - Production: `https://portal.snfifteen.com/machines/api/push/vada`
- **Headers:** 
  - Add header: `Content-Type` = `application/json`
- **Return:** `a parsed JSON object` or `UTF-8 string`

**For Idly Machine:**
- **Method:** `POST`
- **URL:** 
  - Development: `http://127.0.0.1:5000/machines/api/push/idly`
  - Production: `https://portal.snfifteen.com/machines/api/push/idly`
- **Headers:** 
  - Add header: `Content-Type` = `application/json`
- **Return:** `a parsed JSON object` or `UTF-8 string`

### Step 3: Format the Data (Function Node)

Add a **Function** node before the HTTP Request node to format your data:

#### Example Function Node Code for Vada:

```javascript
// Format data for Vada machine
// IMPORTANT: Frontend expects temperature (oil temp) and production_count
msg.headers = {
    "Content-Type": "application/json"
};

msg.payload = {
    "machine_id": msg.machine_id || "vada-001",  // Your machine identifier
    "status": msg.status || "active",            // "active", "idle", "error", "maintenance"
    "temperature": msg.temperature || msg.oilTemp || msg.temp,  // REQUIRED: Oil temperature in Celsius
    "humidity": msg.humidity,                    // Optional: Humidity percentage (0-100)
    "pressure": msg.pressure,                    // Optional: Pressure in PSI/bar
    "battery_level": msg.battery_level,          // Optional: Battery % (0-100)
    "signal_strength": msg.signal_strength,      // Optional: Signal strength % (0-100)
    "production_count": msg.production_count || msg.completed || msg.dispensedCount || 0,  // REQUIRED: Total vadas dispensed
    "cycle_count": msg.cycle_count || 0,        // Optional: Number of cycles
    "error_code": msg.error_code || null,       // Optional: Error code if any
    "error_message": msg.error_message || null, // Optional: Error description
    "location_id": msg.location_id || null,     // Optional: location UUID
    "metadata": {                                // Optional: custom data
        "batch_number": msg.batch_number,
        "recipe_id": msg.recipe_id,
        // Power metrics (optional but recommended for Power card display)
        "voltage": msg.voltage || msg.V || null,
        "current": msg.current || msg.I || null,
        "power": msg.power || msg.P || null,
        "energy": msg.energy || msg.E || null,
        "frequency": msg.frequency || msg.F || null,
        "powerFactor": msg.powerFactor || msg.pf || msg.PF || null
    }
};

return msg;
```

#### Example Function Node Code for Idly:

```javascript
// Format data for Idly machine
// IMPORTANT: Frontend expects temperature (water temp) and pressure
msg.headers = {
    "Content-Type": "application/json"
};

msg.payload = {
    "machine_id": msg.machine_id || "idly-001",
    "status": msg.status || msg.machineStatus || "active",  // "active", "idle", "error", "maintenance"
    "temperature": msg.temperature || msg.waterTemp || msg.temp || msg.water_temperature,  // REQUIRED: Water temperature in Celsius
    "humidity": msg.humidity,                    // Optional: Humidity percentage (0-100)
    "pressure": msg.pressure || msg.pressureData || msg.pressure_value || msg.psi,  // REQUIRED: Pressure in PSI
    "battery_level": msg.battery_level,          // Optional: Battery % (0-100)
    "signal_strength": msg.signal_strength,      // Optional: Signal strength % (0-100)
    "production_count": msg.production_count || 0,  // Optional: Total items produced
    "cycle_count": msg.cycle_count || 0,        // Optional: Number of cycles
    "error_code": msg.error_code || null,       // Optional: Error code if any
    "error_message": msg.error_message || null, // Optional: Error description
    "location_id": msg.location_id || null,     // Optional: location UUID
    "metadata": {                                // Optional: custom data
        "batch_number": msg.batch_number,
        "recipe_id": msg.recipe_id,
        // Power metrics (optional but recommended for Power card display)
        "voltage": msg.voltage || msg.V || null,
        "current": msg.current || msg.I || null,
        "power": msg.power || msg.P || null,
        "energy": msg.energy || msg.E || null,
        "frequency": msg.frequency || msg.F || null,
        "powerFactor": msg.powerFactor || msg.pf || msg.PF || null
    }
};

return msg;
```

### Step 4: Set Up Continuous Pushing

You have several options for continuous data pushing:

#### Option A: Using Inject Node (Simple Timer)

1. Add an **Inject** node
2. Configure it to repeat every **10-15 seconds** (recommended)
3. Connect it to your data source or directly to the Function node

**Inject Node Settings:**
- **Repeat:** `interval`
- **Interval:** `10` seconds (or your preferred interval)

#### Option B: Using Your Existing Data Source

If your machine data already comes in via MQTT, HTTP, Serial, etc.:
1. Connect your data source node to the Function node
2. The Function node will format and forward data whenever it arrives
3. No additional timer needed

### Step 5: Add Error Handling (Optional but Recommended)

Add error handling to retry failed requests:

#### 5.1 Add Catch Node

1. Add a **Catch** node
2. Connect it to your flow (it will catch errors from any node in the same tab)
3. Connect it to a **Function** node for retry logic

#### 5.2 Retry Logic Function Node:

```javascript
// Retry logic for failed requests
if (msg.error) {
    // Log the error
    node.warn("Failed to send machine data: " + msg.error.message);
    
    // Optionally: Store failed message for later retry
    // You can use a delay node here to retry after a few seconds
}

return null; // Don't forward error messages
```

#### 5.3 Add Delay Node for Retries (Optional)

1. Add a **Delay** node after the Catch node
2. Configure: **Rate limit** or **Delayed** (e.g., 5 seconds)
3. Connect back to your HTTP Request node for retry

### Step 6: Complete Flow Structure

Your flow should look like this:

```
[Data Source] → [Function: Format Data] → [HTTP Request] → [Success Handler]
                     ↓
              [Catch: Error Handler] → [Delay: Retry] → [HTTP Request]
```

## Complete Example Flows

### Example 1: Simple Timer-Based Flow

```
[Inject: Every 10s] → [Function: Format Vada Data] → [HTTP Request: POST to /push/vada]
```

**Inject Node:**
- Repeat: Every 10 seconds

**Function Node:**
```javascript
msg.headers = {"Content-Type": "application/json"};
msg.payload = {
    "machine_id": "vada-001",
    "status": "active",
    "temperature": 85.5,
    "humidity": 65.0,
    "pressure": 1.2,
    "battery_level": 95,
    "signal_strength": 85,
    "production_count": 150,
    "cycle_count": 25
};
return msg;
```

**HTTP Request Node:**
- Method: POST
- URL: `http://127.0.0.1:5000/machines/api/push/vada`
- Headers: (set in Function node)

### Example 2: MQTT-Based Flow

```
[MQTT In: machine/vada/data] → [Function: Format Vada Data] → [HTTP Request: POST to /push/vada]
```

**MQTT In Node:**
- Topic: `machine/vada/data`
- Output: `auto-detect` or `JSON object`

**Function Node:**
```javascript
// Assuming MQTT message contains: {"temp": 85.5, "humidity": 65, ...}
msg.headers = {"Content-Type": "application/json"};
msg.payload = {
    "machine_id": "vada-001",
    "status": msg.payload.status || "active",
    "temperature": msg.payload.temp || msg.payload.temperature,
    "humidity": msg.payload.humidity,
    "pressure": msg.payload.pressure,
    "battery_level": msg.payload.battery || msg.payload.battery_level,
    "signal_strength": msg.payload.signal || msg.payload.signal_strength,
    "production_count": msg.payload.production || msg.payload.production_count || 0,
    "cycle_count": msg.payload.cycles || msg.payload.cycle_count || 0,
    "error_code": msg.payload.error_code || null,
    "error_message": msg.payload.error_message || null
};
return msg;
```

### Example 3: Modbus/Serial-Based Flow

```
[Modbus Read] → [Function: Parse & Format] → [HTTP Request: POST to /push/vada]
```

**Function Node:**
```javascript
// Parse Modbus/Serial data and format for portal
msg.headers = {"Content-Type": "application/json"};

// Map your Modbus registers to portal fields
msg.payload = {
    "machine_id": "vada-001",
    "status": determineStatus(msg.modbus_data), // Your logic here
    "temperature": msg.modbus_data.register_100, // Map to your registers
    "humidity": msg.modbus_data.register_101,
    "pressure": msg.modbus_data.register_102,
    "battery_level": msg.modbus_data.register_103,
    "signal_strength": msg.modbus_data.register_104,
    "production_count": msg.modbus_data.register_105 || 0,
    "cycle_count": msg.modbus_data.register_106 || 0
};

function determineStatus(data) {
    if (data.error_flag) return "error";
    if (data.maintenance_mode) return "maintenance";
    if (data.running) return "active";
    return "idle";
}

return msg;
```

## Field Mapping Guide

Map your machine's data fields to the portal's expected format. **Bold fields are critical for frontend display:**

| Portal Field | Your Machine Field | Type | Notes | Frontend Display |
|--------------|-------------------|------|-------|------------------|
| `machine_id` | Your machine identifier | string | e.g., "vada-001", "idly-002" | Not displayed |
| `status` | Machine state | string | **REQUIRED** - Must be: "active", "idle", "error", "maintenance" | Status badge (Ready/Offline) |
| `temperature` | **Vada:** oilTemp, temp<br>**Idly:** waterTemp, temp, water_temperature | number | **REQUIRED** - Celsius | **Vada:** "Oil Temperature" card<br>**Idly:** "Water Temperature" card |
| `humidity` | Humidity reading | number | Optional - Percentage (0-100) | Not displayed |
| `pressure` | pressure, pressureData, pressure_value, psi | number | **REQUIRED for Idly** - PSI or bar | **Idly:** "Pressure Data" card |
| `battery_level` | Battery percentage | integer | Optional - 0-100 | Not displayed |
| `signal_strength` | Signal strength | integer | Optional - 0-100 | Not displayed |
| `production_count` | **Vada:** completed, dispensedCount, count<br>**Idly:** production_count | integer | **REQUIRED for Vada** - Total items produced | **Vada:** "Dispensed Count" card |
| `cycle_count` | Cycles completed | integer | Optional - Number of cycles | Not displayed |
| `error_code` | Error code | string | Optional, null if no error | Not displayed |
| `error_message` | Error description | string | Optional, null if no error | Not displayed |
| `location_id` | Location UUID | string | Optional, from portal | Not displayed |
| `metadata.voltage` | voltage, V | string | Optional - Power metrics | "Power" card (when clicked) |
| `metadata.current` | current, I | string | Optional - Power metrics | "Power" card (when clicked) |
| `metadata.power` | power, P | string | Optional - Power metrics | "Power" card (when clicked) |
| `metadata.energy` | energy, E | string | Optional - Power metrics | "Power" card (when clicked) |
| `metadata.frequency` | frequency, F | string | Optional - Power metrics | "Power" card (when clicked) |
| `metadata.powerFactor` | powerFactor, pf, PF | string | Optional - Power metrics | "Power" card (when clicked) |

### Critical Fields for Frontend Display:

**Vada Machine:**
- ✅ `status` - Shows Ready/Offline badge
- ✅ `temperature` - Displays as "Oil Temperature" card
- ✅ `production_count` - Displays as "Dispensed Count" card
- ⭐ `metadata.power`, `metadata.voltage`, `metadata.current`, etc. - Shows in "Power" card

**Idly Machine:**
- ✅ `status` - Shows Machine ON/OFF badge
- ✅ `temperature` - Displays as "Water Temperature" card
- ✅ `pressure` - Displays as "Pressure Data" card
- ⭐ `metadata.power`, `metadata.voltage`, `metadata.current`, etc. - Shows in "Power" card

## Testing Your Flow

### Test with Debug Node

1. Add a **Debug** node after your Function node
2. Deploy the flow
3. Trigger the flow (manually or via timer)
4. Check the Debug panel to see the formatted JSON

### Test with HTTP Response

1. Add a **Debug** node after your HTTP Request node
2. Check the response in Debug panel
3. Expected response:
```json
{
    "success": true,
    "message": "Vada machine data received successfully",
    "timestamp": "2024-11-29T12:34:56.789Z"
}
```

### Manual Test with Inject Node

1. Add an **Inject** node
2. Set payload to test data:
```json
{
    "machine_id": "vada-001",
    "status": "active",
    "temperature": 85.5,
    "humidity": 65.0
}
```
3. Connect to Function → HTTP Request
4. Click the Inject button
5. Check Debug panel for response

## Recommended Push Frequency

- **Minimum:** Every 30 seconds (for basic monitoring)
- **Recommended:** Every 10-15 seconds (for responsive dashboard)
- **Maximum:** Every 5 seconds (for real-time updates)

**Note:** More frequent updates = better real-time visibility, but also more server load. Start with 10-15 seconds and adjust as needed.

## Error Handling Best Practices

1. **Always check HTTP response status:**
```javascript
// In a Function node after HTTP Request
if (msg.statusCode === 200) {
    node.log("Data sent successfully");
} else {
    node.warn("Failed to send data: " + msg.statusCode);
    // Implement retry logic here
}
```

2. **Log errors for debugging:**
```javascript
// Use node.error() for critical errors
node.error("Critical error: " + msg.error.message, msg);
```

3. **Implement retry with exponential backoff:**
```javascript
// Store retry count in msg.retryCount
if (!msg.retryCount) msg.retryCount = 0;
if (msg.retryCount < 3) {
    msg.retryCount++;
    // Delay increases: 1s, 2s, 4s
    return {payload: msg, delay: Math.pow(2, msg.retryCount) * 1000};
}
```

## Production Checklist

Before deploying to production:

- [ ] Change URL from `http://127.0.0.1:5000` to `https://portal.snfifteen.com`
- [ ] Test both vada and idly endpoints
- [ ] Verify data is being received in portal dashboard
- [ ] Set up error handling and retry logic
- [ ] Configure appropriate push frequency (10-15 seconds)
- [ ] Test error scenarios (network failure, invalid data, etc.)
- [ ] Verify machine_id is unique for each physical machine
- [ ] Ensure status field uses correct values ("active", "idle", "error", "maintenance")

## Support

If you encounter issues:

1. **Check HTTP Request response:** Add Debug node after HTTP Request
2. **Verify JSON format:** Use JSONLint or Debug node to validate
3. **Check network connectivity:** Test URL in browser or with curl
4. **Review error messages:** Check Node-RED debug panel and portal logs

## Quick Reference

**Vada Endpoint:**
- Development: `http://127.0.0.1:5000/machines/api/push/vada`
- Production: `https://portal.snfifteen.com/machines/api/push/vada`

**Idly Endpoint:**
- Development: `http://127.0.0.1:5000/machines/api/push/idly`
- Production: `https://portal.snfifteen.com/machines/api/push/idly`

**Required Headers:**
```
Content-Type: application/json
```

**Minimum Required Fields:**
```json
{
    "status": "active"
}
```

All other fields are optional but recommended for full functionality.

