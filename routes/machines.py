"""
Machines API Routes
Handles data ingestion from Node-RED flows for Vada and Idly machines
"""
from flask import Blueprint, request, jsonify
from database import execute_query, execute_query_one
from datetime import datetime
import uuid
import json

machines_bp = Blueprint('machines', __name__)


def init_machines_schema():
    """Initialize the machines data table if it doesn't exist"""
    execute_query("""
        CREATE TABLE IF NOT EXISTS machine_data (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            machine_type VARCHAR(50) NOT NULL CHECK (machine_type IN ('vada', 'idly')),
            machine_id VARCHAR(100), -- Optional: unique identifier for the physical machine
            status VARCHAR(50) DEFAULT 'active', -- active, idle, error, maintenance
            temperature DECIMAL(10, 2), -- Temperature in Celsius
            humidity DECIMAL(10, 2), -- Humidity percentage
            pressure DECIMAL(10, 2), -- Pressure in PSI or bar
            battery_level INTEGER, -- Battery percentage (0-100)
            signal_strength INTEGER, -- Signal strength (0-100)
            production_count INTEGER DEFAULT 0, -- Total items produced
            cycle_count INTEGER DEFAULT 0, -- Number of cycles completed
            error_code VARCHAR(50), -- Error code if any
            error_message TEXT, -- Error description
            location_id UUID REFERENCES locations(id), -- Optional: link to location
            metadata JSONB, -- Flexible JSON field for additional machine-specific data
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # Create indexes for efficient querying
    execute_query("""
        CREATE INDEX IF NOT EXISTS idx_machine_data_type ON machine_data(machine_type);
    """)
    execute_query("""
        CREATE INDEX IF NOT EXISTS idx_machine_data_received_at ON machine_data(received_at DESC);
    """)
    execute_query("""
        CREATE INDEX IF NOT EXISTS idx_machine_data_machine_id ON machine_data(machine_id);
    """)


@machines_bp.route('/api/push/vada', methods=['POST'])
def push_vada_data():
    """
    Endpoint to receive data from Vada machine via Node-RED
    
    Expected JSON payload:
    {
        "machine_id": "vada-001",  // Optional
        "status": "active",  // active, idle, error, maintenance
        "temperature": 85.5,  // Celsius
        "humidity": 65.0,  // Percentage
        "pressure": 1.2,  // PSI or bar
        "battery_level": 95,  // 0-100
        "signal_strength": 85,  // 0-100
        "production_count": 150,  // Total items produced
        "cycle_count": 25,  // Number of cycles
        "error_code": null,  // Optional error code
        "error_message": null,  // Optional error message
        "location_id": "uuid-string",  // Optional location UUID
        "metadata": {  // Optional additional data
            "batch_number": "B001",
            "recipe_id": "R001",
            "custom_field": "value"
        }
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'No JSON data provided'
            }), 400
        
        # Extract and validate required fields
        machine_type = 'vada'
        machine_id = data.get('machine_id')
        status = data.get('status', 'active')
        temperature = data.get('temperature')
        humidity = data.get('humidity')
        pressure = data.get('pressure')
        battery_level = data.get('battery_level')
        signal_strength = data.get('signal_strength')
        production_count = data.get('production_count', 0)
        cycle_count = data.get('cycle_count', 0)
        error_code = data.get('error_code')
        error_message = data.get('error_message')
        location_id = data.get('location_id')
        metadata = data.get('metadata', {})
        
        # Validate status
        valid_statuses = ['active', 'idle', 'error', 'maintenance']
        if status not in valid_statuses:
            status = 'active'
        
        # Store metadata as JSONB
        metadata_json = json.dumps(metadata) if metadata else None
        
        # Insert data into database
        execute_query("""
            INSERT INTO machine_data (
                machine_type, machine_id, status, temperature, humidity, pressure,
                battery_level, signal_strength, production_count, cycle_count,
                error_code, error_message, location_id, metadata, received_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
        """, (
            machine_type, machine_id, status, temperature, humidity, pressure,
            battery_level, signal_strength, production_count, cycle_count,
            error_code, error_message, location_id, metadata_json
        ))
        
        return jsonify({
            'success': True,
            'message': 'Vada machine data received successfully',
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        print(f"Error receiving vada machine data: {e}")
        return jsonify({
            'success': False,
            'error': f'Failed to process data: {str(e)}'
        }), 500


@machines_bp.route('/api/push/idly', methods=['POST'])
def push_idly_data():
    """
    Endpoint to receive data from Idly machine via Node-RED
    
    Expected JSON payload (same structure as vada):
    {
        "machine_id": "idly-001",
        "status": "active",
        "temperature": 90.0,
        "humidity": 70.0,
        "pressure": 1.5,
        "battery_level": 90,
        "signal_strength": 80,
        "production_count": 200,
        "cycle_count": 30,
        "error_code": null,
        "error_message": null,
        "location_id": "uuid-string",
        "metadata": {
            "batch_number": "B002",
            "recipe_id": "R002"
        }
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': 'No JSON data provided'
            }), 400
        
        # Extract and validate required fields
        machine_type = 'idly'
        machine_id = data.get('machine_id')
        status = data.get('status', 'active')
        temperature = data.get('temperature')
        humidity = data.get('humidity')
        pressure = data.get('pressure')
        battery_level = data.get('battery_level')
        signal_strength = data.get('signal_strength')
        production_count = data.get('production_count', 0)
        cycle_count = data.get('cycle_count', 0)
        error_code = data.get('error_code')
        error_message = data.get('error_message')
        location_id = data.get('location_id')
        metadata = data.get('metadata', {})
        
        # Validate status
        valid_statuses = ['active', 'idle', 'error', 'maintenance']
        if status not in valid_statuses:
            status = 'active'
        
        # Store metadata as JSONB
        metadata_json = json.dumps(metadata) if metadata else None
        
        # Insert data into database
        execute_query("""
            INSERT INTO machine_data (
                machine_type, machine_id, status, temperature, humidity, pressure,
                battery_level, signal_strength, production_count, cycle_count,
                error_code, error_message, location_id, metadata, received_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
        """, (
            machine_type, machine_id, status, temperature, humidity, pressure,
            battery_level, signal_strength, production_count, cycle_count,
            error_code, error_message, location_id, metadata_json
        ))
        
        return jsonify({
            'success': True,
            'message': 'Idly machine data received successfully',
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        print(f"Error receiving idly machine data: {e}")
        return jsonify({
            'success': False,
            'error': f'Failed to process data: {str(e)}'
        }), 500


@machines_bp.route('/api/data', methods=['GET'])
def get_machine_data():
    """
    API endpoint to fetch machine data for the dashboard
    
    Query parameters:
    - machine_type: 'vada' or 'idly' (optional, returns both if not specified)
    - machine_id: specific machine ID (optional)
    - limit: number of records to return (default: 100, max: 1000)
    - hours: fetch data from last N hours (default: 24)
    """
    try:
        machine_type = request.args.get('machine_type')  # 'vada' or 'idly'
        machine_id = request.args.get('machine_id')
        limit = min(int(request.args.get('limit', 100)), 1000)
        hours = max(1, min(int(request.args.get('hours', 24)), 720))  # Between 1 and 720 hours (30 days)
        
        # Build query - using parameterized query for safety
        query = """
            SELECT 
                id, machine_type, machine_id, status, temperature, humidity, pressure,
                battery_level, signal_strength, production_count, cycle_count,
                error_code, error_message, location_id, metadata,
                received_at, created_at
            FROM machine_data
            WHERE received_at >= NOW() - (%s || ' hours')::INTERVAL
        """
        params = [str(hours)]
        
        if machine_type:
            query += " AND machine_type = %s"
            params.append(machine_type)
        
        if machine_id:
            query += " AND machine_id = %s"
            params.append(machine_id)
        
        query += " ORDER BY received_at DESC LIMIT %s"
        params.append(limit)
        
        records = execute_query(query, tuple(params), fetch=True) or []
        
        # Convert to JSON-serializable format with frontend-compatible field names
        result = []
        for record in records:
            metadata = record.get('metadata') or {}
            machine_type = record['machine_type']
            
            # Base record structure
            formatted_record = {
                'id': str(record['id']),
                'machine_type': machine_type,
                'machine_id': record.get('machine_id'),
                'status': record['status'],
                'temperature': float(record['temperature']) if record.get('temperature') else None,
                'humidity': float(record['humidity']) if record.get('humidity') else None,
                'pressure': float(record['pressure']) if record.get('pressure') else None,
                'battery_level': record.get('battery_level'),
                'signal_strength': record.get('signal_strength'),
                'production_count': record.get('production_count', 0),
                'cycle_count': record.get('cycle_count', 0),
                'error_code': record.get('error_code'),
                'error_message': record.get('error_message'),
                'location_id': str(record['location_id']) if record.get('location_id') else None,
                'metadata': metadata,
                'received_at': record['received_at'].isoformat() if record.get('received_at') else None,
                'created_at': record['created_at'].isoformat() if record.get('created_at') else None
            }
            
            # Add alternative field names for Vada machine (frontend compatibility)
            if machine_type == 'vada':
                if formatted_record['temperature'] is not None:
                    formatted_record['temp'] = formatted_record['temperature']
                    formatted_record['oilTemp'] = formatted_record['temperature']
                    formatted_record['oil_temperature'] = formatted_record['temperature']
                if formatted_record['production_count'] is not None:
                    formatted_record['completed'] = formatted_record['production_count']
                    formatted_record['dispensedCount'] = formatted_record['production_count']
                    formatted_record['dispensed_count'] = formatted_record['production_count']
                    formatted_record['count'] = formatted_record['production_count']
            
            # Add alternative field names for Idly machine (frontend compatibility)
            elif machine_type == 'idly':
                if formatted_record['temperature'] is not None:
                    formatted_record['waterTemp'] = formatted_record['temperature']
                    formatted_record['temp'] = formatted_record['temperature']
                    formatted_record['water_temperature'] = formatted_record['temperature']
                if formatted_record['pressure'] is not None:
                    formatted_record['pressureData'] = formatted_record['pressure']
                    formatted_record['pressure_value'] = formatted_record['pressure']
                    formatted_record['psi'] = formatted_record['pressure']
            
            # Add power metrics from metadata to root level for easier access
            if metadata:
                if 'voltage' in metadata:
                    formatted_record['voltage'] = metadata['voltage']
                if 'current' in metadata:
                    formatted_record['current'] = metadata['current']
                if 'power' in metadata:
                    formatted_record['power'] = metadata['power']
                if 'energy' in metadata:
                    formatted_record['energy'] = metadata['energy']
                if 'frequency' in metadata:
                    formatted_record['frequency'] = metadata['frequency']
                if 'powerFactor' in metadata:
                    formatted_record['powerFactor'] = metadata['powerFactor']
            
            result.append(formatted_record)
        
        return jsonify({
            'success': True,
            'data': result,
            'count': len(result)
        }), 200
        
    except Exception as e:
        print(f"Error fetching machine data: {e}")
        return jsonify({
            'success': False,
            'error': f'Failed to fetch data: {str(e)}'
        }), 500


@machines_bp.route('/api/data/latest', methods=['GET'])
def get_latest_machine_data():
    """
    Get the latest data point for each machine type
    
    Returns the most recent record for vada and idly machines
    """
    try:
        machine_type = request.args.get('machine_type')  # Optional filter
        
        if machine_type:
            # Get latest for specific machine type
            query = """
                SELECT 
                    id, machine_type, machine_id, status, temperature, humidity, pressure,
                    battery_level, signal_strength, production_count, cycle_count,
                    error_code, error_message, location_id, metadata,
                    received_at, created_at
                FROM machine_data
                WHERE machine_type = %s
                ORDER BY received_at DESC
                LIMIT 1
            """
            record = execute_query_one(query, (machine_type,))
            
            if not record:
                return jsonify({
                    'success': True,
                    'data': None,
                    'machine_type': machine_type
                }), 200
            
            # Extract metadata for power metrics
            metadata = record.get('metadata') or {}
            
            # Format response to match frontend expectations
            result = {
                'id': str(record['id']),
                'machine_type': record['machine_type'],
                'machine_id': record.get('machine_id'),
                'status': record['status'],
                'temperature': float(record['temperature']) if record.get('temperature') else None,
                'humidity': float(record['humidity']) if record.get('humidity') else None,
                'pressure': float(record['pressure']) if record.get('pressure') else None,
                'battery_level': record.get('battery_level'),
                'signal_strength': record.get('signal_strength'),
                'production_count': record.get('production_count', 0),
                'cycle_count': record.get('cycle_count', 0),
                'error_code': record.get('error_code'),
                'error_message': record.get('error_message'),
                'location_id': str(record['location_id']) if record.get('location_id') else None,
                'metadata': metadata,
                'received_at': record['received_at'].isoformat() if record.get('received_at') else None,
                'created_at': record['created_at'].isoformat() if record.get('created_at') else None
            }
            
            # For Vada: Add alternative field names that frontend might look for
            if record['machine_type'] == 'vada':
                # Frontend looks for: temp, temperature, oilTemp, oil_temperature, oilTemperature, etc.
                if result['temperature'] is not None:
                    result['temp'] = result['temperature']
                    result['oilTemp'] = result['temperature']
                # Frontend looks for: completed, dispensedCount, dispensed_count, count, etc.
                if result['production_count'] is not None:
                    result['completed'] = result['production_count']
                    result['dispensedCount'] = result['production_count']
                    result['count'] = result['production_count']
            
            # For Idly: Add alternative field names that frontend might look for
            elif record['machine_type'] == 'idly':
                # Frontend looks for: waterTemp, temp, temperature, water_temperature
                if result['temperature'] is not None:
                    result['waterTemp'] = result['temperature']
                    result['temp'] = result['temperature']
                    result['water_temperature'] = result['temperature']
                # Frontend looks for: pressureData, pressure, pressure_value, psi
                if result['pressure'] is not None:
                    result['pressureData'] = result['pressure']
                    result['pressure_value'] = result['pressure']
                    result['psi'] = result['pressure']
            
            # Add power metrics from metadata to root level for easier access
            if metadata:
                if 'voltage' in metadata:
                    result['voltage'] = metadata['voltage']
                if 'current' in metadata:
                    result['current'] = metadata['current']
                if 'power' in metadata:
                    result['power'] = metadata['power']
                if 'energy' in metadata:
                    result['energy'] = metadata['energy']
                if 'frequency' in metadata:
                    result['frequency'] = metadata['frequency']
                if 'powerFactor' in metadata:
                    result['powerFactor'] = metadata['powerFactor']
            
            return jsonify({
                'success': True,
                'data': result
            }), 200
        else:
            # Get latest for both machine types
            vada_query = """
                SELECT 
                    id, machine_type, machine_id, status, temperature, humidity, pressure,
                    battery_level, signal_strength, production_count, cycle_count,
                    error_code, error_message, location_id, metadata,
                    received_at, created_at
                FROM machine_data
                WHERE machine_type = 'vada'
                ORDER BY received_at DESC
                LIMIT 1
            """
            idly_query = """
                SELECT 
                    id, machine_type, machine_id, status, temperature, humidity, pressure,
                    battery_level, signal_strength, production_count, cycle_count,
                    error_code, error_message, location_id, metadata,
                    received_at, created_at
                FROM machine_data
                WHERE machine_type = 'idly'
                ORDER BY received_at DESC
                LIMIT 1
            """
            
            vada_record = execute_query_one(vada_query)
            idly_record = execute_query_one(idly_query)
            
            def format_record(record):
                if not record:
                    return None
                
                # Extract metadata for power metrics
                metadata = record.get('metadata') or {}
                
                # Format response to match frontend expectations
                result = {
                    'id': str(record['id']),
                    'machine_type': record['machine_type'],
                    'machine_id': record.get('machine_id'),
                    'status': record['status'],
                    'temperature': float(record['temperature']) if record.get('temperature') else None,
                    'humidity': float(record['humidity']) if record.get('humidity') else None,
                    'pressure': float(record['pressure']) if record.get('pressure') else None,
                    'battery_level': record.get('battery_level'),
                    'signal_strength': record.get('signal_strength'),
                    'production_count': record.get('production_count', 0),
                    'cycle_count': record.get('cycle_count', 0),
                    'error_code': record.get('error_code'),
                    'error_message': record.get('error_message'),
                    'location_id': str(record['location_id']) if record.get('location_id') else None,
                    'metadata': metadata,
                    'received_at': record['received_at'].isoformat() if record.get('received_at') else None,
                    'created_at': record['created_at'].isoformat() if record.get('created_at') else None
                }
                
                # For Vada: Add alternative field names that frontend might look for
                if record['machine_type'] == 'vada':
                    # Frontend looks for: temp, temperature, oilTemp, oil_temperature, oilTemperature, etc.
                    if result['temperature'] is not None:
                        result['temp'] = result['temperature']
                        result['oilTemp'] = result['temperature']
                    # Frontend looks for: completed, dispensedCount, dispensed_count, count, etc.
                    if result['production_count'] is not None:
                        result['completed'] = result['production_count']
                        result['dispensedCount'] = result['production_count']
                        result['count'] = result['production_count']
                
                # For Idly: Add alternative field names that frontend might look for
                elif record['machine_type'] == 'idly':
                    # Frontend looks for: waterTemp, temp, temperature, water_temperature
                    if result['temperature'] is not None:
                        result['waterTemp'] = result['temperature']
                        result['temp'] = result['temperature']
                        result['water_temperature'] = result['temperature']
                    # Frontend looks for: pressureData, pressure, pressure_value, psi
                    if result['pressure'] is not None:
                        result['pressureData'] = result['pressure']
                        result['pressure_value'] = result['pressure']
                        result['psi'] = result['pressure']
                
                # Add power metrics from metadata to root level for easier access
                if metadata:
                    if 'voltage' in metadata:
                        result['voltage'] = metadata['voltage']
                    if 'current' in metadata:
                        result['current'] = metadata['current']
                    if 'power' in metadata:
                        result['power'] = metadata['power']
                    if 'energy' in metadata:
                        result['energy'] = metadata['energy']
                    if 'frequency' in metadata:
                        result['frequency'] = metadata['frequency']
                    if 'powerFactor' in metadata:
                        result['powerFactor'] = metadata['powerFactor']
                
                return result
            
            return jsonify({
                'success': True,
                'data': {
                    'vada': format_record(vada_record),
                    'idly': format_record(idly_record)
                }
            }), 200
            
    except Exception as e:
        print(f"Error fetching latest machine data: {e}")
        return jsonify({
            'success': False,
            'error': f'Failed to fetch latest data: {str(e)}'
        }), 500


@machines_bp.route('/api/stats', methods=['GET'])
def get_machine_stats():
    """
    Get aggregated statistics for machines
    
    Returns production counts, error rates, uptime, etc.
    """
    try:
        machine_type = request.args.get('machine_type')
        hours = max(1, min(int(request.args.get('hours', 24)), 720))  # Between 1 and 720 hours
        
        query = """
            SELECT 
                machine_type,
                COUNT(*) as total_records,
                MAX(production_count) as max_production,
                MIN(production_count) as min_production,
                AVG(temperature) as avg_temperature,
                AVG(humidity) as avg_humidity,
                AVG(battery_level) as avg_battery,
                COUNT(CASE WHEN status = 'error' THEN 1 END) as error_count,
                COUNT(CASE WHEN status = 'active' THEN 1 END) as active_count,
                MAX(received_at) as last_update
            FROM machine_data
            WHERE received_at >= NOW() - (%s || ' hours')::INTERVAL
        """
        params = [str(hours)]
        
        if machine_type:
            query += " AND machine_type = %s"
            params.append(machine_type)
        
        query += " GROUP BY machine_type"
        
        records = execute_query(query, tuple(params), fetch=True) or []
        
        result = []
        for record in records:
            result.append({
                'machine_type': record['machine_type'],
                'total_records': record['total_records'],
                'max_production': record['max_production'],
                'min_production': record['min_production'],
                'avg_temperature': float(record['avg_temperature']) if record.get('avg_temperature') else None,
                'avg_humidity': float(record['avg_humidity']) if record.get('avg_humidity') else None,
                'avg_battery': float(record['avg_battery']) if record.get('avg_battery') else None,
                'error_count': record['error_count'],
                'active_count': record['active_count'],
                'last_update': record['last_update'].isoformat() if record.get('last_update') else None
            })
        
        return jsonify({
            'success': True,
            'data': result
        }), 200
        
    except Exception as e:
        print(f"Error fetching machine stats: {e}")
        return jsonify({
            'success': False,
            'error': f'Failed to fetch stats: {str(e)}'
        }), 500

