-- ============================================
-- Sip & Snack Portal Database Setup Script
-- ============================================
-- This script sets up the database schema, user, and all necessary tables
-- for the Restaurant Chain Management Portal.
--
-- PREREQUISITE: Create the database manually first, then run this script.
--
-- Run this script as a PostgreSQL superuser (usually 'postgres')
-- ============================================

-- ============================================
-- 1. SETUP USER AND CONNECT TO DATABASE
-- ============================================

-- Create application user (with validation)
DO $$
BEGIN
    -- Create user only if it doesn't exist
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'sipnsnack_user') THEN
        CREATE USER sipnsnack_user WITH PASSWORD 's!pnsn@ck';
    END IF;
END
$$;

-- Grant privileges on the existing database
-- (Run this script while connected to the sipnsnack database)
GRANT ALL PRIVILEGES ON DATABASE sipnsnack TO sipnsnack_user;

-- Grant schema privileges
GRANT ALL ON SCHEMA public TO sipnsnack_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO sipnsnack_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO sipnsnack_user;

-- ============================================
-- 2. CREATE TABLES
-- ============================================

-- Enable UUID extension (required for UUID columns)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create locations table
CREATE TABLE IF NOT EXISTS locations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    address TEXT,
    city VARCHAR(100),
    state VARCHAR(100),
    zip_code VARCHAR(20),
    phone VARCHAR(20),
    email VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Drop and recreate master_menu table to handle schema changes
DROP TABLE IF EXISTS master_menu CASCADE;

-- Create master_menu table
CREATE TABLE master_menu (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    category VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    image_data TEXT, -- Base64 encoded image data
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create location_menu table (junction table for location-specific menu items)
CREATE TABLE IF NOT EXISTS location_menu (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID REFERENCES locations(id) ON DELETE CASCADE,
    master_menu_id UUID REFERENCES master_menu(id) ON DELETE CASCADE,
    price DECIMAL(10,2), -- Location can override price
    is_available BOOLEAN DEFAULT TRUE,
    section VARCHAR(20) DEFAULT 'all', -- breakfast section: morning | evening | all
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(location_id, master_menu_id)
);

-- Create orders table
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID REFERENCES locations(id),
    order_number VARCHAR(50) UNIQUE NOT NULL,
    customer_name VARCHAR(255),
    customer_phone VARCHAR(20),
    customer_email VARCHAR(255),
    order_type VARCHAR(50), -- dine-in, takeaway, delivery
    status VARCHAR(50) DEFAULT 'pending', -- pending, preparing, ready, completed, cancelled
    total_amount DECIMAL(10,2) NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create order_items table
CREATE TABLE IF NOT EXISTS order_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID REFERENCES orders(id) ON DELETE CASCADE,
    location_menu_id UUID REFERENCES location_menu(id),
    master_menu_id UUID REFERENCES master_menu(id), -- For historical reference
    item_name VARCHAR(255) NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    total_price DECIMAL(10,2) NOT NULL,
    notes TEXT
);

-- Create user_sessions table (for authentication logging)
CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_email VARCHAR(255) NOT NULL,
    user_name VARCHAR(255),
    login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    logout_time TIMESTAMP,
    ip_address INET,
    user_agent TEXT,
    is_active BOOLEAN DEFAULT TRUE
);

-- Create departments table
CREATE TABLE IF NOT EXISTS departments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    budget DECIMAL(10,2),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create positions table
CREATE TABLE IF NOT EXISTS positions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    department_id UUID REFERENCES departments(id),
    salary_min DECIMAL(10,2),
    salary_max DECIMAL(10,2),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Drop and recreate tables to handle schema changes
DROP TABLE IF EXISTS staff CASCADE;

-- Create staff table with new structure
CREATE TABLE staff (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    employee_id VARCHAR(50) UNIQUE NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE,
    phone VARCHAR(20),
    position_id UUID REFERENCES positions(id),
    department_id UUID REFERENCES departments(id),
    location_id UUID REFERENCES locations(id),
    hire_date DATE NOT NULL,
    salary DECIMAL(10,2),
    is_active BOOLEAN DEFAULT TRUE,
    address TEXT,
    city VARCHAR(100),
    state VARCHAR(100),
    zip_code VARCHAR(20),
    emergency_contact_name VARCHAR(255),
    emergency_contact_phone VARCHAR(20),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Add manager relationships after base tables exist
ALTER TABLE departments
ADD COLUMN IF NOT EXISTS manager_id UUID;
ALTER TABLE departments
ADD CONSTRAINT fk_departments_manager FOREIGN KEY (manager_id) REFERENCES staff(id);

ALTER TABLE staff
ADD COLUMN IF NOT EXISTS manager_id UUID;
ALTER TABLE staff
ADD CONSTRAINT fk_staff_manager FOREIGN KEY (manager_id) REFERENCES staff(id);

-- ============================================
-- 3. ADD UNIQUE CONSTRAINTS
-- ============================================

-- Add unique constraints for location and menu names (with error handling)
DO $$
BEGIN
    -- Add unique constraint to locations table if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'locations_name_key'
        AND table_name = 'locations'
    ) THEN
        ALTER TABLE locations ADD CONSTRAINT locations_name_key UNIQUE (name);
    END IF;

    -- Add unique constraint to master_menu table if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'master_menu_name_key'
        AND table_name = 'master_menu'
    ) THEN
        ALTER TABLE master_menu ADD CONSTRAINT master_menu_name_key UNIQUE (name);
    END IF;
EXCEPTION
    WHEN others THEN
        RAISE NOTICE 'Could not add unique constraints. Please ensure no duplicate names exist in locations or master_menu tables.';
END $$;

-- ============================================
-- 4. CREATE INDEXES FOR PERFORMANCE
-- ============================================

-- Indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_master_menu_category ON master_menu(category);
CREATE INDEX IF NOT EXISTS idx_master_menu_active ON master_menu(is_active);
CREATE INDEX IF NOT EXISTS idx_location_menu_location ON location_menu(location_id);
CREATE INDEX IF NOT EXISTS idx_location_menu_menu ON location_menu(master_menu_id);
CREATE INDEX IF NOT EXISTS idx_orders_location ON orders(location_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_email ON user_sessions(user_email);
CREATE INDEX IF NOT EXISTS idx_user_sessions_active ON user_sessions(is_active);

-- Indexes for departments table
CREATE INDEX IF NOT EXISTS idx_departments_name ON departments(name);
CREATE INDEX IF NOT EXISTS idx_departments_manager ON departments(manager_id);
CREATE INDEX IF NOT EXISTS idx_departments_active ON departments(is_active);

-- Indexes for positions table
CREATE INDEX IF NOT EXISTS idx_positions_title ON positions(title);
CREATE INDEX IF NOT EXISTS idx_positions_department ON positions(department_id);
CREATE INDEX IF NOT EXISTS idx_positions_active ON positions(is_active);

-- Indexes for staff table
CREATE INDEX IF NOT EXISTS idx_staff_employee_id ON staff(employee_id);
CREATE INDEX IF NOT EXISTS idx_staff_email ON staff(email);
CREATE INDEX IF NOT EXISTS idx_staff_position_id ON staff(position_id);
CREATE INDEX IF NOT EXISTS idx_staff_department_id ON staff(department_id);
CREATE INDEX IF NOT EXISTS idx_staff_location ON staff(location_id);
CREATE INDEX IF NOT EXISTS idx_staff_manager ON staff(manager_id);
CREATE INDEX IF NOT EXISTS idx_staff_active ON staff(is_active);
CREATE INDEX IF NOT EXISTS idx_staff_hire_date ON staff(hire_date);

-- ============================================
-- 5. SAMPLE DATA (OPTIONAL)
-- ============================================

-- Insert sample locations (IDs will be auto-generated as UUIDs)
INSERT INTO locations (name, address, city, state, zip_code, phone, email) VALUES
('Downtown Branch', '123 Main St', 'New York', 'NY', '10001', '+1-555-0101', 'downtown@sn15.com'),
('Mall Location', '456 Shopping Plaza', 'Los Angeles', 'CA', '90210', '+1-555-0102', 'mall@sn15.com'),
('Airport Terminal', '789 Terminal Rd', 'Chicago', 'IL', '60601', '+1-555-0103', 'airport@sn15.com')
ON CONFLICT DO NOTHING;

-- Delete existing order items first (removes foreign key references to location_menu)
DELETE FROM order_items;

-- Delete existing orders
DELETE FROM orders;

-- Delete existing location menu mappings (now safe since no order_items reference them)
DELETE FROM location_menu;

-- Delete existing master menu sample data
DELETE FROM master_menu;

-- Insert new master menu items from CSV data
INSERT INTO master_menu (name, description, category, image_data, is_active) VALUES
('Punugu (2)', 'Traditional South Indian snack - 2 pieces', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true),
('Punugu (4)', 'Traditional South Indian snack - 4 pieces', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true),
('Perugu Vada (2)', 'Perugu Vada - 2 pieces', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true),
('Perugu Vada (4)', 'Perugu Vada - 4 pieces', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true),
('Mysore Bajji (2)', 'Mysore Bajji - 2 pieces', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true),
('Mysore Bajji (4)', 'Mysore Bajji - 4 pieces', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true),
('Sambar Vada (4)', 'Sambar Vada - 4 pieces', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true),
('Sambar Vada (2)', 'Sambar Vada - 2 pieces', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true),
('Idly (4)', 'Traditional South Indian Idly - 4 pieces', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Idly (2)', 'Traditional South Indian Idly - 2 pieces', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Vada (4)', 'Traditional South Indian Vada - 4 pieces', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true),
('Vada (2)', 'Traditional South Indian Vada - 2 pieces', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true),
('Poori (1)', 'Traditional South Indian Poori - 1 piece', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Poori (2)', 'Traditional South Indian Poori - 2 pieces', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Sambar Idly (4)', 'Idly served with Sambar - 4 pieces', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Sambar Idly (2)', 'Idly served with Sambar - 2 pieces', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Dosa', 'Traditional South Indian Dosa', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Onion Dosa', 'Dosa with onion filling', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Tea', 'Traditional South Indian Tea', 'Beverages', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzRFQ0RDNCIvPgo8L3N2Zz4=', true),
('Coffee', 'South Indian Filter Coffee', 'Beverages', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzRFQ0RDNCIvPgo8L3N2Zz4=', true),
('Water Bottle 500 Ml', 'Mineral water bottle 500ml', 'Beverages', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzRFQ0RDNCIvPgo8L3N2Zz4=', true),
('Meals', 'Traditional South Indian Thali', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Kichidi', 'Traditional South Indian Kichidi', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Sambar Rice', 'Rice served with Sambar', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Palakura Pappu', 'Spinach dal curry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Tomato Pulusu', 'Tomato curry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Potato Fry', 'Potato fry side dish', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('All Chutney', 'Assorted chutneys', 'Sides', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzk4RDhDOCIvPgo8L3N2Zz4=', true),
('Chukku Kura Pappu', 'Ginger dal curry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Cauliflower Tomato Pulusu', 'Cauliflower tomato curry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Dondakay Fry', 'Ivy gourd fry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Gongura Chutney', 'Sorrel leaves chutney', 'Sides', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzk4RDhDOCIvPgo8L3N2Zz4=', true),
('Thotakura Pappu', 'Amaranth leaves dal', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Potato And Tomato Pulusu', 'Potato tomato curry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Ladies Finger Fry', 'Okra fry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Cabbage Fry', 'Cabbage fry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Mushroom Curry', 'Mushroom curry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Cauliflower 65 Fry', 'Spicy cauliflower fry', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true),
('Vankay Dosakay Chutney', 'Eggplant cucumber chutney', 'Sides', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzk4RDhDOCIvPgo8L3N2Zz4=', true),
('Tomato Pappu', 'Tomato dal', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Cauliflower Tomato Pulusu', 'Cauliflower tomato curry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Beans Fry', 'French beans fry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Milli Maker Kurma Or Pulusu', 'Breadfruit curry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Dumpa Eguruu', 'Sweet potato curry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Dum Biryani', 'Vegetable dum biryani', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Fry Biryani', 'Vegetable fry biryani', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Plain Biryani', 'Plain vegetable biryani', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Chicken 555', 'Spicy chicken 555', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Chicken 65', 'Spicy chicken 65', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Chicken Majestic', 'Chicken majestic', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Chilli Chicken', 'Chilli chicken', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Dragon Chicken', 'Dragon chicken', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Nilgiri Chicken', 'Nilgiri chicken', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Pepper Chicken', 'Pepper chicken', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Paneer Manchurian', 'Paneer manchurian', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Chicken Manchurian', 'Chicken manchurian', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Veg Noodles', 'Vegetable noodles', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Egg Noodles', 'Egg noodles', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Chicken Noodles', 'Chicken noodles', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Veg Manchurian', 'Vegetable manchurian', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Egg Manchurian', 'Egg manchurian', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Paneer Fried Rice', 'Paneer fried rice', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Kaju Fried Rice', 'Cashew fried rice', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Mushroom Fried Rice', 'Mushroom fried rice', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Thumsup', 'Thums Up soft drink', 'Beverages', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzRFQ0RDNCIvPgo8L3N2Zz4=', true),
('Powerup', 'Power Up soft drink', 'Beverages', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzRFQ0RDNCIvPgo8L3N2Zz4=', true),
('Water Bottle 1ltr', 'Mineral water bottle 1 liter', 'Beverages', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzRFQ0RDNCIvPgo8L3N2Zz4=', true),
('Cauliflower Tomato Pulusu', 'Cauliflower tomato curry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Vankay Tomato Curry', 'Eggplant tomato curry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Small Punugu', 'Small traditional South Indian snack', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true),
('Small Punugu (1/2)', 'Half portion small traditional snack', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true),
('Poornam', 'Traditional sweet poornam', 'Desserts', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGQTA3QSIvPgo8L3N2Zz4=', true),
('Rice', 'Steamed rice', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Meals+Chicken Curry', 'Meals with chicken curry', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Dosakai Chutney', 'Cucumber chutney', 'Sides', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzk4RDhDOCIvPgo8L3N2Zz4=', true),
('Chikudikai Tomato', 'Bitter gourd tomato curry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Gutti Vankai Fry', 'Stuffed eggplant fry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Mulakai Tomato Pulusu', 'Drumstick tomato curry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Vankai Fry', 'Eggplant fry', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Pulihora 1kg', 'Tamarind rice 1kg', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Daddojanam (1 Kg)', 'Buttermilk 1kg', 'Beverages', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzRFQ0RDNCIvPgo8L3N2Zz4=', true),
('Paramannam (1 Kg)', 'Sweet rice pudding 1kg', 'Desserts', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGQTA3QSIvPgo8L3N2Zz4=', true),
('Catering Chicken', 'Chicken for catering', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Masala Dosa', 'Dosa with potato filling', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Ghee Dosa', 'Dosa with ghee', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Egg Dosa', 'Dosa with egg', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Kanchipuram Idly', 'Special Kanchipuram idly', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Veg Fried Rice 1/2', 'Half portion vegetable fried rice', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Chicken Fried Rice (1/2)', 'Half portion chicken fried rice', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Sp Chicken Fried Rice', 'Special chicken fried rice', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Curd', 'Fresh curd/yogurt', 'Beverages', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzRFQ0RDNCIvPgo8L3N2Zz4=', true),
('Emp Fry Biryani', 'Employee special fry biryani', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Chicken Curry', 'Traditional chicken curry', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Chicken Manchurian (1/2)', 'Half portion chicken manchurian', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Emp Dum Biryani', 'Employee special dum biryani', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Beerakaya Chutney', 'Ridge gourd chutney', 'Sides', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzk4RDhDOCIvPgo8L3N2Zz4=', true),
('Egg Manchurian (1/2)', 'Half portion egg manchurian', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Paneer Noodles', 'Paneer noodles', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Single Egg Fried Rice', 'Fried rice with single egg', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Egg Mushroom Fried Rice', 'Fried rice with egg and mushroom', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Double Egg Omelette', 'Double egg omelette', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Chicken Fried Rice', 'Chicken fried rice', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Rava Kesari', 'Sweet rava kesari', 'Desserts', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGQTA3QSIvPgo8L3N2Zz4=', true),
('Pongal', 'Traditional South Indian pongal', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Bread Halwa', 'Sweet bread halwa', 'Desserts', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGQTA3QSIvPgo8L3N2Zz4=', true),
('Sambar', 'Traditional sambar', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Black Coffee', 'Black coffee without milk', 'Beverages', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzRFQ0RDNCIvPgo8L3N2Zz4=', true),
('Meals Catering', 'Meals for catering', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Veg Meals Catering', 'Vegetarian meals catering', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Meals Catering+Sweet', 'Meals with sweet for catering', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Ghee Idly (4)', 'Idly with ghee - 4 pieces', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Chapati (1)', 'Single chapati', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Chapati (2)', 'Two chapatis', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Appadam', 'Appadam/papad', 'Sides', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzk4RDhDOCIvPgo8L3N2Zz4=', true),
('Lemon Pickle', 'Traditional lemon pickle', 'Sides', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzk4RDhDOCIvPgo8L3N2Zz4=', true),
('Parcel (Legacy)', 'Legacy parcel item', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Mirchi Bajji (2)', 'Chili bajji - 2 pieces', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true),
('Mirchi Bajji (4)', 'Chili bajji - 4 pieces', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true),
('Dosakai Vankai Chutney', 'Cucumber eggplant chutney', 'Sides', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iIzk4RDhDOCIvPgo8L3N2Zz4=', true),
('Egg Fried Rice', 'Fried rice with egg', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Chicken Noodles (1/2)', 'Half portion chicken noodles', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Emp Chicken Fried Rice', 'Employee chicken fried rice', 'Non-Veg', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNDc1NyIvPgo8L3N2Zz4=', true),
('Meals Catering Veg', 'Vegetarian meals catering', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Veg Manchurian (1/4)', 'Quarter portion veg manchurian', 'Main Course', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGNkIzNSIvPgo8L3N2Zz4=', true),
('Campa', 'Traditional South Indian snack', 'Snacks', 'data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CiAgPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI0ZGRDcwMCIvPgo8L3N2Zz4=', true)
ON CONFLICT DO NOTHING;

-- Insert sample departments
INSERT INTO departments (name, description, budget, is_active) VALUES
('Management', 'Executive and managerial staff overseeing operations', 150000.00, true),
('Operations', 'Front-line staff handling customer service and operations', 200000.00, true),
('Kitchen', 'Food preparation and kitchen operations', 100000.00, true),
('Customer Service', 'Customer support and service staff', 80000.00, true),
('HR', 'Human resources and personnel management', 60000.00, true),
('Finance', 'Financial operations and accounting', 70000.00, true),
('IT', 'Information technology and systems support', 90000.00, true)
ON CONFLICT DO NOTHING;

-- Insert sample positions
INSERT INTO positions (title, description, department_id, salary_min, salary_max, is_active) VALUES
('Store Manager', 'Overall management of store operations', (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), 45000.00, 65000.00, true),
('Assistant Manager', 'Assistant to store manager', (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), 35000.00, 50000.00, true),
('Barista', 'Coffee and beverage preparation', (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), 25000.00, 35000.00, true),
('Cashier', 'Customer checkout and payment processing', (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), 22000.00, 30000.00, true),
('Kitchen Staff', 'Food preparation and kitchen operations', (SELECT id FROM departments WHERE name = 'Kitchen' LIMIT 1), 25000.00, 35000.00, true),
('Customer Service Rep', 'Customer support and assistance', (SELECT id FROM departments WHERE name = 'Customer Service' LIMIT 1), 28000.00, 38000.00, true),
('HR Manager', 'Human resources management', (SELECT id FROM departments WHERE name = 'HR' LIMIT 1), 40000.00, 55000.00, true),
('Finance Manager', 'Financial operations management', (SELECT id FROM departments WHERE name = 'Finance' LIMIT 1), 42000.00, 58000.00, true),
('IT Support', 'Technical support and systems maintenance', (SELECT id FROM departments WHERE name = 'IT' LIMIT 1), 35000.00, 50000.00, true)
ON CONFLICT DO NOTHING;

-- Insert sample staff (IDs will be auto-generated as UUIDs)
INSERT INTO staff (employee_id, first_name, last_name, email, phone, position_id, department_id, location_id, hire_date, salary, is_active, address, city, state, zip_code, emergency_contact_name, emergency_contact_phone) VALUES
('EMP001', 'John', 'Smith', 'john.smith@sn15.com', '+1-555-1001', (SELECT id FROM positions WHERE title = 'Store Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-01-15', 55000.00, true, '123 Oak St', 'New York', 'NY', '10001', 'Jane Smith', '+1-555-2001'),
('EMP002', 'Sarah', 'Johnson', 'sarah.johnson@sn15.com', '+1-555-1002', (SELECT id FROM positions WHERE title = 'Assistant Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-03-01', 45000.00, true, '456 Maple Ave', 'New York', 'NY', '10002', 'Mike Johnson', '+1-555-2002'),
('EMP003', 'Mike', 'Davis', 'mike.davis@sn15.com', '+1-555-1003', (SELECT id FROM positions WHERE title = 'Barista' LIMIT 1), (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-02-15', 32000.00, true, '789 Pine St', 'New York', 'NY', '10003', 'Lisa Davis', '+1-555-2003'),
('EMP004', 'Emily', 'Wilson', 'emily.wilson@sn15.com', '+1-555-1004', (SELECT id FROM positions WHERE title = 'Cashier' LIMIT 1), (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-04-01', 28000.00, true, '321 Elm St', 'New York', 'NY', '10004', 'David Wilson', '+1-555-2004'),
('EMP005', 'Robert', 'Brown', 'robert.brown@sn15.com', '+1-555-1005', (SELECT id FROM positions WHERE title = 'Store Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), '2023-01-20', 55000.00, true, '654 Cedar Ave', 'Los Angeles', 'CA', '90210', 'Maria Brown', '+1-555-2005'),
('EMP006', 'Lisa', 'Garcia', 'lisa.garcia@sn15.com', '+1-555-1006', (SELECT id FROM positions WHERE title = 'Kitchen Staff' LIMIT 1), (SELECT id FROM departments WHERE name = 'Kitchen' LIMIT 1), (SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), '2023-03-15', 30000.00, true, '987 Birch Blvd', 'Los Angeles', 'CA', '90211', 'Carlos Garcia', '+1-555-2006'),
('EMP007', 'David', 'Miller', 'david.miller@sn15.com', '+1-555-1007', (SELECT id FROM positions WHERE title = 'Barista' LIMIT 1), (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), (SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), '2023-05-01', 32000.00, true, '147 Walnut St', 'Los Angeles', 'CA', '90212', 'Anna Miller', '+1-555-2007'),
('EMP008', 'Jennifer', 'Martinez', 'jennifer.martinez@sn15.com', '+1-555-1008', (SELECT id FROM positions WHERE title = 'Assistant Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Airport Terminal' LIMIT 1), '2023-02-01', 45000.00, true, '258 Spruce Ln', 'Chicago', 'IL', '60601', 'Luis Martinez', '+1-555-2008')
ON CONFLICT DO NOTHING;

-- Update manager references (do this after initial insert)
UPDATE staff SET manager_id = (SELECT id FROM staff WHERE employee_id = 'EMP001') WHERE employee_id IN ('EMP002', 'EMP003', 'EMP004') AND manager_id IS NULL;
UPDATE staff SET manager_id = (SELECT id FROM staff WHERE employee_id = 'EMP005') WHERE employee_id IN ('EMP006', 'EMP007') AND manager_id IS NULL;
UPDATE staff SET manager_id = (SELECT id FROM staff WHERE employee_id = 'EMP008') WHERE employee_id = 'EMP008' AND manager_id IS NULL;

-- Update department managers
UPDATE departments SET manager_id = (SELECT id FROM staff WHERE employee_id = 'EMP001') WHERE name = 'Management' AND manager_id IS NULL;
-- (deduplicated above)

-- ============================================
-- 6. GRANT PERMISSIONS TO APPLICATION USER
-- ============================================

-- Grant all privileges on existing tables
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO sipnsnack_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO sipnsnack_user;

-- Set default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO sipnsnack_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO sipnsnack_user;

-- ============================================
-- 7. INVENTORY MANAGEMENT SYSTEM TABLES
-- ============================================

-- Create suppliers table
CREATE TABLE IF NOT EXISTS suppliers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    contact_person VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(20),
    address TEXT,
    city VARCHAR(100),
    state VARCHAR(100),
    zip_code VARCHAR(20),
    payment_terms VARCHAR(100), -- e.g., "Net 30", "COD", etc.
    notes TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create master inventory table (central catalog of all purchasable items)
CREATE TABLE IF NOT EXISTS master_inventory (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    category VARCHAR(100) NOT NULL, -- 'ingredients', 'packaging', 'equipment', 'supplies', etc.
    unit VARCHAR(50) NOT NULL, -- 'kg', 'liter', 'pieces', 'boxes', 'cans', etc.
    supplier_id UUID REFERENCES suppliers(id),
    min_order_quantity DECIMAL(10,2) DEFAULT 1,
    default_cost_per_unit DECIMAL(10,2),
    is_active BOOLEAN DEFAULT TRUE,
    barcode VARCHAR(100) UNIQUE,
    image_data TEXT, -- Base64 encoded image data
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Ensure supplier_id exists on existing installations and drop legacy columns if present
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'master_inventory' AND column_name = 'supplier_id'
    ) THEN
        ALTER TABLE master_inventory ADD COLUMN supplier_id UUID REFERENCES suppliers(id);
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'master_inventory' AND column_name = 'supplier_name'
    ) THEN
        ALTER TABLE master_inventory DROP COLUMN supplier_name;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'master_inventory' AND column_name = 'supplier_contact'
    ) THEN
        ALTER TABLE master_inventory DROP COLUMN supplier_contact;
    END IF;
END $$;

-- Create purchase lists table (shopping lists created for specific locations)
CREATE TABLE IF NOT EXISTS purchase_lists (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID REFERENCES locations(id) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_by UUID REFERENCES staff(id) NOT NULL,
    status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'submitted', 'approved', 'procured', 'cancelled')),
    total_estimated_cost DECIMAL(12,2) DEFAULT 0,
    priority VARCHAR(10) DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    required_by_date DATE,
    approved_by UUID REFERENCES staff(id),
    approved_at TIMESTAMP,
    procured_at TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Ensure unique purchase list name per location (avoid duplicates across runs)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'purchase_lists' AND constraint_type = 'UNIQUE'
          AND constraint_name = 'unique_purchase_list_location_name'
    ) THEN
        ALTER TABLE purchase_lists
        ADD CONSTRAINT unique_purchase_list_location_name UNIQUE (location_id, name);
    END IF;
END $$;

-- Create purchase list items table (items in each purchase list)
CREATE TABLE IF NOT EXISTS purchase_list_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    purchase_list_id UUID REFERENCES purchase_lists(id) ON DELETE CASCADE NOT NULL,
    master_inventory_id UUID REFERENCES master_inventory(id) NOT NULL,
    quantity_requested DECIMAL(10,2) NOT NULL,
    quantity_approved DECIMAL(10,2),
    quantity_procured DECIMAL(10,2) DEFAULT 0,
    cost_per_unit DECIMAL(10,2),
    total_cost DECIMAL(12,2),
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'procured', 'partial', 'cancelled')),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(purchase_list_id, master_inventory_id)
);

-- Create location inventory table (current stock levels at each location)
CREATE TABLE IF NOT EXISTS location_inventory (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID REFERENCES locations(id) NOT NULL,
    master_inventory_id UUID REFERENCES master_inventory(id) NOT NULL,
    current_stock DECIMAL(10,2) DEFAULT 0,
    minimum_stock_level DECIMAL(10,2) DEFAULT 0,
    maximum_stock_level DECIMAL(10,2) DEFAULT 0,
    reorder_point DECIMAL(10,2) DEFAULT 0,
    last_restock_date DATE,
    last_restock_quantity DECIMAL(10,2),
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(location_id, master_inventory_id)
);

-- Create inventory transactions table (all stock movements)
CREATE TABLE IF NOT EXISTS inventory_transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID REFERENCES locations(id) NOT NULL,
    master_inventory_id UUID REFERENCES master_inventory(id) NOT NULL,
    transaction_type VARCHAR(20) NOT NULL CHECK (transaction_type IN ('restock', 'usage', 'adjustment', 'waste', 'transfer')),
    quantity DECIMAL(10,2) NOT NULL, -- Positive for additions, negative for reductions
    previous_stock DECIMAL(10,2) NOT NULL,
    new_stock DECIMAL(10,2) NOT NULL,
    reference_id UUID, -- Can reference purchase_list_items.id, orders.id, etc.
    reference_type VARCHAR(50), -- 'purchase_list', 'order', 'manual_adjustment', etc.
    recorded_by UUID REFERENCES staff(id) NOT NULL,
    transaction_date DATE DEFAULT CURRENT_DATE,
    transaction_time TIME DEFAULT CURRENT_TIME,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create daily inventory usage table (end-of-day stock taking)
CREATE TABLE IF NOT EXISTS daily_inventory_usage (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID REFERENCES locations(id) NOT NULL,
    master_inventory_id UUID REFERENCES master_inventory(id) NOT NULL,
    date DATE NOT NULL,
    opening_stock DECIMAL(10,2) NOT NULL,
    closing_stock DECIMAL(10,2) NOT NULL,
    used_quantity DECIMAL(10,2) NOT NULL, -- Calculated: opening - closing - adjustments
    wastage_quantity DECIMAL(10,2) DEFAULT 0,
    recorded_by UUID REFERENCES staff(id) NOT NULL,
    status VARCHAR(20) DEFAULT 'recorded' CHECK (status IN ('recorded', 'verified', 'adjusted')),
    verified_by UUID REFERENCES staff(id),
    verified_at TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(location_id, master_inventory_id, date)
);

-- Create leftover food tracking table
CREATE TABLE IF NOT EXISTS leftover_food_tracking (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID REFERENCES locations(id) NOT NULL,
    master_menu_id UUID REFERENCES master_menu(id) NOT NULL,
    date DATE NOT NULL,
    quantity_prepared DECIMAL(10,2) NOT NULL,
    quantity_sold DECIMAL(10,2) NOT NULL,
    quantity_leftover DECIMAL(10,2) NOT NULL,
    disposal_method VARCHAR(50) CHECK (disposal_method IN ('donated', 'discarded', 'reused', 'sold_at_discount')),
    estimated_value DECIMAL(8,2) DEFAULT 0,
    recorded_by UUID REFERENCES staff(id) NOT NULL,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(location_id, master_menu_id, date)
);

-- Create inventory alerts table
CREATE TABLE IF NOT EXISTS inventory_alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    location_id UUID REFERENCES locations(id) NOT NULL,
    master_inventory_id UUID REFERENCES master_inventory(id) NOT NULL,
    alert_type VARCHAR(20) NOT NULL CHECK (alert_type IN ('low_stock', 'out_of_stock', 'expiring', 'reorder')),
    current_stock DECIMAL(10,2),
    threshold_value DECIMAL(10,2),
    severity VARCHAR(10) DEFAULT 'medium' CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    message TEXT NOT NULL,
    is_resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMP,
    resolved_by UUID REFERENCES staff(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- 7. PAYROLL SYSTEM TABLES
-- ============================================

-- Create employee types table (hourly, salary, temporary, consultant)
-- Create tables without dependencies first
CREATE TABLE IF NOT EXISTS employee_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(50) NOT NULL UNIQUE,
    code VARCHAR(20) NOT NULL UNIQUE,
    description TEXT,
    payment_type VARCHAR(20) NOT NULL CHECK (payment_type IN ('hourly', 'salary', 'temporary', 'consultant')),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
--Create leave request types tables
CREATE TABLE IF NOT EXISTS leave_types (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    code VARCHAR(20) NOT NULL UNIQUE,
    description TEXT,
    is_paid BOOLEAN DEFAULT FALSE,
    requires_approval BOOLEAN DEFAULT TRUE,
    max_days_per_year INTEGER,
    carry_forward_days INTEGER DEFAULT 0,
    color VARCHAR(7) DEFAULT '#007bff',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
--Create payroll cycles tables
CREATE TABLE IF NOT EXISTS payroll_cycles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    pay_date DATE NOT NULL,
    status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'processing', 'completed', 'cancelled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(start_date, end_date)
);
--Create holidays tables
CREATE TABLE IF NOT EXISTS holidays (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    date DATE NOT NULL,
    is_recurring BOOLEAN DEFAULT FALSE,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date)
);

-- Create locations and master_menu (already successful in your script)

-- (Removed duplicate block to avoid re-defining tables already created above)

-- Create remaining tables that depend on staff
CREATE TABLE IF NOT EXISTS leave_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    staff_id UUID REFERENCES staff(id) NOT NULL,
    leave_type_id UUID REFERENCES leave_types(id) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    total_days DECIMAL(5,2) NOT NULL,
    reason TEXT,
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    approved_by UUID REFERENCES staff(id),
    approved_at TIMESTAMP,
    comments TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS timesheets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    staff_id UUID REFERENCES staff(id) NOT NULL,
    payroll_cycle_id UUID REFERENCES payroll_cycles(id),
    date DATE NOT NULL,
    clock_in TIMESTAMP,
    clock_out TIMESTAMP,
    total_hours DECIMAL(6,2) DEFAULT 0,
    regular_hours DECIMAL(6,2) DEFAULT 0,
    overtime_hours DECIMAL(6,2) DEFAULT 0,
    break_hours DECIMAL(6,2) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft', 'submitted', 'approved', 'rejected')),
    notes TEXT,
    approved_by UUID REFERENCES staff(id),
    approved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(staff_id, date)
);

CREATE TABLE IF NOT EXISTS breaks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timesheet_id UUID REFERENCES timesheets(id) NOT NULL,
    break_type VARCHAR(50) NOT NULL DEFAULT 'regular',
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_minutes INTEGER,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employee_pay_rates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    staff_id UUID REFERENCES staff(id) NOT NULL,
    employee_type_id UUID REFERENCES employee_types(id) NOT NULL,
    hourly_rate DECIMAL(10,2),
    annual_salary DECIMAL(12,2),
    overtime_rate DECIMAL(10,2),
    effective_date DATE NOT NULL,
    end_date DATE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(staff_id, effective_date)
);

CREATE TABLE IF NOT EXISTS payroll_entries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    staff_id UUID REFERENCES staff(id) NOT NULL,
    payroll_cycle_id UUID REFERENCES payroll_cycles(id) NOT NULL,
    employee_type_id UUID REFERENCES employee_types(id) NOT NULL,
    regular_hours DECIMAL(6,2) DEFAULT 0,
    overtime_hours DECIMAL(6,2) DEFAULT 0,
    total_hours DECIMAL(6,2) DEFAULT 0,
    regular_pay DECIMAL(10,2) DEFAULT 0,
    overtime_pay DECIMAL(10,2) DEFAULT 0,
    gross_pay DECIMAL(10,2) DEFAULT 0,
    deductions DECIMAL(10,2) DEFAULT 0,
    net_pay DECIMAL(10,2) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'calculated' CHECK (status IN ('calculated', 'approved', 'paid', 'cancelled')),
    processed_at TIMESTAMP,
    paid_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(staff_id, payroll_cycle_id)
);

CREATE TABLE IF NOT EXISTS payments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    payroll_entry_id UUID REFERENCES payroll_entries(id) NOT NULL,
    payment_method VARCHAR(50) NOT NULL,
    payment_reference VARCHAR(100),
    amount DECIMAL(10,2) NOT NULL,
    payment_date DATE NOT NULL,
    status VARCHAR(20) DEFAULT 'completed' CHECK (status IN ('pending', 'completed', 'failed', 'cancelled')),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS leave_balances (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    staff_id UUID REFERENCES staff(id) NOT NULL,
    leave_type_id UUID REFERENCES leave_types(id) NOT NULL,
    year INTEGER NOT NULL,
    allocated_days DECIMAL(5,2) DEFAULT 0,
    used_days DECIMAL(5,2) DEFAULT 0,
    carried_forward DECIMAL(5,2) DEFAULT 0,
    remaining_days DECIMAL(5,2) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(staff_id, leave_type_id, year)
);

-- ============================================
-- 8. INVENTORY SYSTEM INDEXES
-- ============================================

-- Suppliers indexes
CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers(name);
CREATE INDEX IF NOT EXISTS idx_suppliers_email ON suppliers(email);
CREATE INDEX IF NOT EXISTS idx_suppliers_active ON suppliers(is_active);

-- Master inventory indexes
CREATE INDEX IF NOT EXISTS idx_master_inventory_category ON master_inventory(category);
CREATE INDEX IF NOT EXISTS idx_master_inventory_supplier_id ON master_inventory(supplier_id);
CREATE INDEX IF NOT EXISTS idx_master_inventory_barcode ON master_inventory(barcode);
CREATE INDEX IF NOT EXISTS idx_master_inventory_active ON master_inventory(is_active);

-- Purchase lists indexes
CREATE INDEX IF NOT EXISTS idx_purchase_lists_location ON purchase_lists(location_id);
CREATE INDEX IF NOT EXISTS idx_purchase_lists_status ON purchase_lists(status);
CREATE INDEX IF NOT EXISTS idx_purchase_lists_created_by ON purchase_lists(created_by);
CREATE INDEX IF NOT EXISTS idx_purchase_lists_priority ON purchase_lists(priority);

-- Purchase list items indexes
CREATE INDEX IF NOT EXISTS idx_purchase_list_items_list ON purchase_list_items(purchase_list_id);
CREATE INDEX IF NOT EXISTS idx_purchase_list_items_inventory ON purchase_list_items(master_inventory_id);
CREATE INDEX IF NOT EXISTS idx_purchase_list_items_status ON purchase_list_items(status);

-- Location inventory indexes
CREATE INDEX IF NOT EXISTS idx_location_inventory_location ON location_inventory(location_id);
CREATE INDEX IF NOT EXISTS idx_location_inventory_item ON location_inventory(master_inventory_id);
CREATE INDEX IF NOT EXISTS idx_location_inventory_stock ON location_inventory(current_stock);

-- Inventory transactions indexes
CREATE INDEX IF NOT EXISTS idx_inventory_transactions_location ON inventory_transactions(location_id);
CREATE INDEX IF NOT EXISTS idx_inventory_transactions_item ON inventory_transactions(master_inventory_id);
CREATE INDEX IF NOT EXISTS idx_inventory_transactions_type ON inventory_transactions(transaction_type);
CREATE INDEX IF NOT EXISTS idx_inventory_transactions_date ON inventory_transactions(transaction_date);

-- Daily inventory usage indexes
CREATE INDEX IF NOT EXISTS idx_daily_inventory_usage_location ON daily_inventory_usage(location_id);
CREATE INDEX IF NOT EXISTS idx_daily_inventory_usage_item ON daily_inventory_usage(master_inventory_id);
CREATE INDEX IF NOT EXISTS idx_daily_inventory_usage_date ON daily_inventory_usage(date);
CREATE INDEX IF NOT EXISTS idx_daily_inventory_usage_status ON daily_inventory_usage(status);

-- Leftover food tracking indexes
CREATE INDEX IF NOT EXISTS idx_leftover_food_location ON leftover_food_tracking(location_id);
CREATE INDEX IF NOT EXISTS idx_leftover_food_menu ON leftover_food_tracking(master_menu_id);
CREATE INDEX IF NOT EXISTS idx_leftover_food_date ON leftover_food_tracking(date);

-- Inventory alerts indexes
CREATE INDEX IF NOT EXISTS idx_inventory_alerts_location ON inventory_alerts(location_id);
CREATE INDEX IF NOT EXISTS idx_inventory_alerts_item ON inventory_alerts(master_inventory_id);
CREATE INDEX IF NOT EXISTS idx_inventory_alerts_type ON inventory_alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_inventory_alerts_severity ON inventory_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_inventory_alerts_resolved ON inventory_alerts(is_resolved);

-- ============================================
-- 9. PAYROLL SYSTEM INDEXES
-- ============================================

-- Core entity indexes
CREATE INDEX IF NOT EXISTS idx_departments_name ON departments(name);
CREATE INDEX IF NOT EXISTS idx_departments_manager ON departments(manager_id);
CREATE INDEX IF NOT EXISTS idx_departments_active ON departments(is_active);
CREATE INDEX IF NOT EXISTS idx_positions_title ON positions(title);
CREATE INDEX IF NOT EXISTS idx_positions_department ON positions(department_id);
CREATE INDEX IF NOT EXISTS idx_positions_active ON positions(is_active);
CREATE INDEX IF NOT EXISTS idx_staff_employee_id ON staff(employee_id);
CREATE INDEX IF NOT EXISTS idx_staff_email ON staff(email);
CREATE INDEX IF NOT EXISTS idx_staff_position_id ON staff(position_id);
CREATE INDEX IF NOT EXISTS idx_staff_department_id ON staff(department_id);
CREATE INDEX IF NOT EXISTS idx_staff_location ON staff(location_id);
CREATE INDEX IF NOT EXISTS idx_staff_manager ON staff(manager_id);
CREATE INDEX IF NOT EXISTS idx_staff_active ON staff(is_active);
CREATE INDEX IF NOT EXISTS idx_staff_hire_date ON staff(hire_date);

-- Timesheets indexes
CREATE INDEX IF NOT EXISTS idx_timesheets_staff_date ON timesheets(staff_id, date);
CREATE INDEX IF NOT EXISTS idx_timesheets_payroll_cycle ON timesheets(payroll_cycle_id);
CREATE INDEX IF NOT EXISTS idx_timesheets_status ON timesheets(status);
CREATE INDEX IF NOT EXISTS idx_leave_requests_staff ON leave_requests(staff_id);
CREATE INDEX IF NOT EXISTS idx_leave_requests_dates ON leave_requests(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_leave_requests_status ON leave_requests(status);
CREATE INDEX IF NOT EXISTS idx_payroll_entries_staff_cycle ON payroll_entries(staff_id, payroll_cycle_id);
CREATE INDEX IF NOT EXISTS idx_payroll_entries_status ON payroll_entries(status);
CREATE INDEX IF NOT EXISTS idx_payments_payroll_entry ON payments(payroll_entry_id);
CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date);
CREATE INDEX IF NOT EXISTS idx_breaks_timesheet ON breaks(timesheet_id);
CREATE INDEX IF NOT EXISTS idx_breaks_times ON breaks(start_time, end_time);

-- ============================================
-- 9. INVENTORY SYSTEM SAMPLE DATA
-- ============================================

-- Insert sample suppliers
INSERT INTO suppliers (name, contact_person, email, phone, address, city, state, zip_code, payment_terms, notes) VALUES
('Rice Suppliers Inc', 'Rajesh Kumar', 'rajesh@ricesuppliers.com', '+1-555-0101', '123 Rice Mill Rd', 'Houston', 'TX', '77001', 'Net 30', 'Premium basmati rice supplier'),
('Sugar Corp', 'Maria Garcia', 'maria@sugarcorp.com', '+1-555-0102', '456 Sugar Factory Blvd', 'Orlando', 'FL', '32801', 'Net 15', 'Refined sugar and sweeteners'),
('Tea Estates Ltd', 'Ahmed Hassan', 'ahmed@teaestates.com', '+1-555-0103', '789 Tea Plantation Ave', 'Seattle', 'WA', '98101', 'Net 30', 'South Indian tea leaves and powder'),
('Coffee Traders', 'Lisa Chen', 'lisa@coffeetraders.com', '+1-555-0104', '321 Coffee Bean St', 'Portland', 'OR', '97201', 'Net 30', 'South Indian filter coffee'),
('Dairy Products Inc', 'John Smith', 'john@dairyproducts.com', '+1-555-0105', '654 Milk Processing Ln', 'Madison', 'WI', '53701', 'Net 15', 'Milk powder and dairy ingredients'),
('Oil Refineries', 'Carlos Rodriguez', 'carlos@oilrefineries.com', '+1-555-0106', '987 Oil Extraction Rd', 'Dallas', 'TX', '75201', 'Net 30', 'Vegetable cooking oils'),
('Salt Works', 'Emma Wilson', 'emma@saltworks.com', '+1-555-0107', '147 Salt Mine Blvd', 'Salt Lake City', 'UT', '84101', 'Net 15', 'Iodized table salt'),
('Spice Traders', 'David Kumar', 'david@spicetraders.com', '+1-555-0108', '258 Spice Market St', 'Atlanta', 'GA', '30301', 'Net 30', 'Indian spices and seasonings'),
('Packaging Supplies', 'Sarah Johnson', 'sarah@packaging.com', '+1-555-0112', '369 Package Factory Ave', 'Chicago', 'IL', '60601', 'Net 30', 'Paper plates, cups, and packaging'),
('Cleaning Supplies Co', 'Mike Davis', 'mike@cleaningsupplies.com', '+1-555-0116', '741 Clean St', 'Detroit', 'MI', '48201', 'Net 15', 'Cleaning and maintenance supplies'),
('Fresh Produce Market', 'Anna Lee', 'anna@freshproduce.com', '+1-555-0119', '852 Market Square', 'Phoenix', 'AZ', '85001', 'COD', 'Fresh vegetables and fruits')
ON CONFLICT DO NOTHING;

-- Insert sample master inventory items
INSERT INTO master_inventory (name, description, category, unit, supplier_id, min_order_quantity, default_cost_per_unit, barcode) VALUES
('Rice (Basmati)', 'Premium basmati rice for biryani and rice dishes', 'ingredients', 'kg', (SELECT id FROM suppliers WHERE name = 'Rice Suppliers Inc' LIMIT 1), 10.00, 2.50, 'RICE001'),
('Sugar', 'Refined white sugar for beverages and desserts', 'ingredients', 'kg', (SELECT id FROM suppliers WHERE name = 'Sugar Corp' LIMIT 1), 5.00, 1.20, 'SUGAR001'),
('Tea Powder', 'Premium tea powder for South Indian tea', 'ingredients', 'kg', (SELECT id FROM suppliers WHERE name = 'Tea Estates Ltd' LIMIT 1), 2.00, 8.50, 'TEA001'),
('Coffee Powder', 'South Indian filter coffee powder', 'ingredients', 'kg', (SELECT id FROM suppliers WHERE name = 'Coffee Traders' LIMIT 1), 1.00, 12.00, 'COFFEE001'),
('Milk Powder', 'Dairy milk powder for tea and coffee', 'ingredients', 'kg', (SELECT id FROM suppliers WHERE name = 'Dairy Products Inc' LIMIT 1), 2.00, 6.00, 'MILK001'),
('Cooking Oil', 'Vegetable cooking oil', 'ingredients', 'liter', (SELECT id FROM suppliers WHERE name = 'Oil Refineries' LIMIT 1), 5.00, 3.50, 'OIL001'),
('Salt', 'Iodized table salt', 'ingredients', 'kg', (SELECT id FROM suppliers WHERE name = 'Salt Works' LIMIT 1), 1.00, 0.50, 'SALT001'),
('Turmeric Powder', 'Ground turmeric spice', 'ingredients', 'kg', (SELECT id FROM suppliers WHERE name = 'Spice Traders' LIMIT 1), 0.50, 4.00, 'TURMERIC001'),
('Red Chili Powder', 'Ground red chili spice', 'ingredients', 'kg', (SELECT id FROM suppliers WHERE name = 'Spice Traders' LIMIT 1), 0.50, 5.50, 'CHILI001'),
('Coriander Powder', 'Ground coriander spice', 'ingredients', 'kg', (SELECT id FROM suppliers WHERE name = 'Spice Traders' LIMIT 1), 0.50, 3.50, 'CORIANDER001'),
('Garam Masala', 'Mixed spice blend', 'ingredients', 'kg', (SELECT id FROM suppliers WHERE name = 'Spice Traders' LIMIT 1), 0.25, 15.00, 'GARAM001'),
('Paper Plates (Small)', 'Disposable paper plates 6 inch', 'packaging', 'pieces', (SELECT id FROM suppliers WHERE name = 'Packaging Supplies' LIMIT 1), 100.00, 0.08, 'PLATES001'),
('Paper Cups (200ml)', 'Disposable paper cups for tea/coffee', 'packaging', 'pieces', (SELECT id FROM suppliers WHERE name = 'Packaging Supplies' LIMIT 1), 200.00, 0.05, 'CUPS001'),
('Plastic Spoons', 'Disposable plastic spoons', 'packaging', 'pieces', (SELECT id FROM suppliers WHERE name = 'Packaging Supplies' LIMIT 1), 500.00, 0.02, 'SPOONS001'),
('Napkins', 'Paper napkins', 'packaging', 'pieces', (SELECT id FROM suppliers WHERE name = 'Packaging Supplies' LIMIT 1), 1000.00, 0.01, 'NAPKINS001'),
('Cleaning Solution', 'Multi-purpose cleaning solution', 'supplies', 'liter', (SELECT id FROM suppliers WHERE name = 'Cleaning Supplies Co' LIMIT 1), 5.00, 4.00, 'CLEAN001'),
('Dish Soap', 'Dish washing liquid', 'supplies', 'liter', (SELECT id FROM suppliers WHERE name = 'Cleaning Supplies Co' LIMIT 1), 2.00, 3.00, 'SOAP001'),
('Garbage Bags', 'Plastic garbage bags', 'supplies', 'pieces', (SELECT id FROM suppliers WHERE name = 'Cleaning Supplies Co' LIMIT 1), 100.00, 0.15, 'BAGS001'),
('Vegetables (Mixed)', 'Fresh mixed vegetables', 'ingredients', 'kg', (SELECT id FROM suppliers WHERE name = 'Fresh Produce Market' LIMIT 1), 5.00, 2.00, 'VEG001'),
('Onions', 'Fresh onions', 'ingredients', 'kg', (SELECT id FROM suppliers WHERE name = 'Fresh Produce Market' LIMIT 1), 10.00, 1.50, 'ONIONS001'),
('Potatoes', 'Fresh potatoes', 'ingredients', 'kg', (SELECT id FROM suppliers WHERE name = 'Fresh Produce Market' LIMIT 1), 20.00, 1.00, 'POTATO001'),
('Tomatoes', 'Fresh tomatoes', 'ingredients', 'kg', (SELECT id FROM suppliers WHERE name = 'Fresh Produce Market' LIMIT 1), 5.00, 2.50, 'TOMATO001')
ON CONFLICT DO NOTHING;

-- Insert sample location inventory for each location
INSERT INTO location_inventory (location_id, master_inventory_id, current_stock, minimum_stock_level, maximum_stock_level, reorder_point) VALUES
-- Downtown Branch inventory
((SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Rice (Basmati)' LIMIT 1), 25.0, 10.0, 50.0, 15.0),
((SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Sugar' LIMIT 1), 8.0, 5.0, 20.0, 8.0),
((SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Tea Powder' LIMIT 1), 2.5, 1.0, 5.0, 2.0),
((SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Coffee Powder' LIMIT 1), 1.2, 0.5, 3.0, 1.0),
((SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Paper Cups (200ml)' LIMIT 1), 1500.0, 500.0, 2000.0, 800.0),

-- Mall Location inventory
((SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Rice (Basmati)' LIMIT 1), 30.0, 10.0, 50.0, 15.0),
((SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Sugar' LIMIT 1), 12.0, 5.0, 20.0, 8.0),
((SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Tea Powder' LIMIT 1), 3.0, 1.0, 5.0, 2.0),
((SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Coffee Powder' LIMIT 1), 1.8, 0.5, 3.0, 1.0),
((SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Paper Cups (200ml)' LIMIT 1), 2000.0, 500.0, 2000.0, 800.0),

-- Airport Terminal inventory
((SELECT id FROM locations WHERE name = 'Airport Terminal' LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Rice (Basmati)' LIMIT 1), 20.0, 10.0, 50.0, 15.0),
((SELECT id FROM locations WHERE name = 'Airport Terminal' LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Sugar' LIMIT 1), 6.0, 5.0, 20.0, 8.0),
((SELECT id FROM locations WHERE name = 'Airport Terminal' LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Tea Powder' LIMIT 1), 1.5, 1.0, 5.0, 2.0),
((SELECT id FROM locations WHERE name = 'Airport Terminal' LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Coffee Powder' LIMIT 1), 0.8, 0.5, 3.0, 1.0),
((SELECT id FROM locations WHERE name = 'Airport Terminal' LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Paper Cups (200ml)' LIMIT 1), 1000.0, 500.0, 2000.0, 800.0)
ON CONFLICT DO NOTHING;

-- Insert sample purchase list
INSERT INTO purchase_lists (location_id, name, description, created_by, status, total_estimated_cost, priority) VALUES
((SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), 'Weekly Stock Replenishment', 'Regular weekly inventory replenishment for Downtown Branch', (SELECT id FROM staff WHERE employee_id = 'EMP001' LIMIT 1), 'approved', 250.00, 'normal')
ON CONFLICT DO NOTHING;

-- Insert sample purchase list items
INSERT INTO purchase_list_items (purchase_list_id, master_inventory_id, quantity_requested, quantity_approved, cost_per_unit, total_cost, status) VALUES
((SELECT id FROM purchase_lists WHERE name = 'Weekly Stock Replenishment' AND location_id = (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1) LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Rice (Basmati)' LIMIT 1), 15.0, 15.0, 2.50, 37.50, 'procured'),
((SELECT id FROM purchase_lists WHERE name = 'Weekly Stock Replenishment' AND location_id = (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1) LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Sugar' LIMIT 1), 5.0, 5.0, 1.20, 6.00, 'procured'),
((SELECT id FROM purchase_lists WHERE name = 'Weekly Stock Replenishment' AND location_id = (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1) LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Tea Powder' LIMIT 1), 1.0, 1.0, 8.50, 8.50, 'procured'),
((SELECT id FROM purchase_lists WHERE name = 'Weekly Stock Replenishment' AND location_id = (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1) LIMIT 1), (SELECT id FROM master_inventory WHERE name = 'Paper Cups (200ml)' LIMIT 1), 500.0, 500.0, 0.05, 25.00, 'pending')
ON CONFLICT DO NOTHING;

-- ============================================
-- 10. PAYROLL SYSTEM SAMPLE DATA
-- ============================================

-- Insert employee types
INSERT INTO employee_types (name, code, description, payment_type, is_active) VALUES
('Full-time Salaried', 'FT_SALARIED', 'Regular full-time employees paid annual salary', 'salary', true),
('Part-time Hourly', 'PT_HOURLY', 'Part-time employees paid hourly wages', 'hourly', true),
('Temporary Help', 'TEMPORARY', 'Temporary seasonal or project-based workers', 'temporary', true),
('Consultant', 'CONSULTANT', 'External consultants and contractors', 'consultant', true)
ON CONFLICT DO NOTHING;

-- Insert leave types (required by leave_balances sample data below)
INSERT INTO leave_types (name, code, description, is_paid, requires_approval, max_days_per_year, carry_forward_days, color, is_active) VALUES
('Vacation Leave', 'VACATION', 'Annual vacation leave', true, true, 15, 5, '#28a745', true),
('Sick Leave', 'SICK', 'Medical/sick leave', true, false, 10, 0, '#dc3545', true)
ON CONFLICT DO NOTHING;

INSERT INTO positions (title, description, department_id, salary_min, salary_max, is_active) VALUES
('Store Manager', 'Overall management of store operations', (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), 45000.00, 65000.00, true),
('Assistant Manager', 'Assistant to store manager', (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), 35000.00, 50000.00, true),
('Barista', 'Coffee and beverage preparation', (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), 25000.00, 35000.00, true),
('Cashier', 'Customer checkout and payment processing', (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), 22000.00, 30000.00, true),
('Kitchen Staff', 'Food preparation and kitchen operations', (SELECT id FROM departments WHERE name = 'Kitchen' LIMIT 1), 25000.00, 35000.00, true),
('Customer Service Rep', 'Customer support and assistance', (SELECT id FROM departments WHERE name = 'Customer Service' LIMIT 1), 28000.00, 38000.00, true),
('HR Manager', 'Human resources management', (SELECT id FROM departments WHERE name = 'HR' LIMIT 1), 40000.00, 55000.00, true),
('Finance Manager', 'Financial operations management', (SELECT id FROM departments WHERE name = 'Finance' LIMIT 1), 42000.00, 58000.00, true),
('IT Support', 'Technical support and systems maintenance', (SELECT id FROM departments WHERE name = 'IT' LIMIT 1), 35000.00, 50000.00, true)
ON CONFLICT DO NOTHING;

INSERT INTO staff (employee_id, first_name, last_name, email, phone, position_id, department_id, location_id, hire_date, salary, is_active, address, city, state, zip_code, emergency_contact_name, emergency_contact_phone) VALUES
('EMP001', 'John', 'Smith', 'john.smith@sn15.com', '+1-555-1001', (SELECT id FROM positions WHERE title = 'Store Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-01-15', 55000.00, true, '123 Oak St', 'New York', 'NY', '10001', 'Jane Smith', '+1-555-2001'),
('EMP002', 'Sarah', 'Johnson', 'sarah.johnson@sn15.com', '+1-555-1002', (SELECT id FROM positions WHERE title = 'Assistant Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-03-01', 45000.00, true, '456 Maple Ave', 'New York', 'NY', '10002', 'Mike Johnson', '+1-555-2002'),
('EMP003', 'Mike', 'Davis', 'mike.davis@sn15.com', '+1-555-1003', (SELECT id FROM positions WHERE title = 'Barista' LIMIT 1), (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-02-15', 32000.00, true, '789 Pine St', 'New York', 'NY', '10003', 'Lisa Davis', '+1-555-2003'),
('EMP004', 'Emily', 'Wilson', 'emily.wilson@sn15.com', '+1-555-1004', (SELECT id FROM positions WHERE title = 'Cashier' LIMIT 1), (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), (SELECT id FROM locations WHERE name = 'Downtown Branch' LIMIT 1), '2023-04-01', 28000.00, true, '321 Elm St', 'New York', 'NY', '10004', 'David Wilson', '+1-555-2004'),
('EMP005', 'Robert', 'Brown', 'robert.brown@sn15.com', '+1-555-1005', (SELECT id FROM positions WHERE title = 'Store Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), '2023-01-20', 55000.00, true, '654 Cedar Ave', 'Los Angeles', 'CA', '90210', 'Maria Brown', '+1-555-2005'),
('EMP006', 'Lisa', 'Garcia', 'lisa.garcia@sn15.com', '+1-555-1006', (SELECT id FROM positions WHERE title = 'Kitchen Staff' LIMIT 1), (SELECT id FROM departments WHERE name = 'Kitchen' LIMIT 1), (SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), '2023-03-15', 30000.00, true, '987 Birch Blvd', 'Los Angeles', 'CA', '90211', 'Carlos Garcia', '+1-555-2006'),
('EMP007', 'David', 'Miller', 'david.miller@sn15.com', '+1-555-1007', (SELECT id FROM positions WHERE title = 'Barista' LIMIT 1), (SELECT id FROM departments WHERE name = 'Operations' LIMIT 1), (SELECT id FROM locations WHERE name = 'Mall Location' LIMIT 1), '2023-05-01', 32000.00, true, '147 Walnut St', 'Los Angeles', 'CA', '90212', 'Anna Miller', '+1-555-2007'),
('EMP008', 'Jennifer', 'Martinez', 'jennifer.martinez@sn15.com', '+1-555-1008', (SELECT id FROM positions WHERE title = 'Assistant Manager' LIMIT 1), (SELECT id FROM departments WHERE name = 'Management' LIMIT 1), (SELECT id FROM locations WHERE name = 'Airport Terminal' LIMIT 1), '2023-02-01', 45000.00, true, '258 Spruce Ln', 'Chicago', 'IL', '60601', 'Luis Martinez', '+1-555-2008')
ON CONFLICT DO NOTHING;

-- Update manager_id for staff and departments
-- (deduplicated above)
-- Updates retained earlier in the script

-- Insert remaining data
INSERT INTO employee_pay_rates (staff_id, employee_type_id, hourly_rate, annual_salary, overtime_rate, effective_date, is_active) VALUES
((SELECT id FROM staff WHERE employee_id = 'EMP001'), (SELECT id FROM employee_types WHERE code = 'FT_SALARIED'), NULL, 55000.00, NULL, '2023-01-15', true),
((SELECT id FROM staff WHERE employee_id = 'EMP002'), (SELECT id FROM employee_types WHERE code = 'FT_SALARIED'), NULL, 45000.00, NULL, '2023-03-01', true),
((SELECT id FROM staff WHERE employee_id = 'EMP003'), (SELECT id FROM employee_types WHERE code = 'PT_HOURLY'), 16.50, NULL, 1.5, '2023-02-15', true),
((SELECT id FROM staff WHERE employee_id = 'EMP004'), (SELECT id FROM employee_types WHERE code = 'PT_HOURLY'), 14.25, NULL, 1.5, '2023-04-01', true),
((SELECT id FROM staff WHERE employee_id = 'EMP005'), (SELECT id FROM employee_types WHERE code = 'FT_SALARIED'), NULL, 55000.00, NULL, '2023-01-20', true),
((SELECT id FROM staff WHERE employee_id = 'EMP006'), (SELECT id FROM employee_types WHERE code = 'PT_HOURLY'), 15.00, NULL, 1.5, '2023-03-15', true),
((SELECT id FROM staff WHERE employee_id = 'EMP007'), (SELECT id FROM employee_types WHERE code = 'PT_HOURLY'), 16.50, NULL, 1.5, '2023-05-01', true),
((SELECT id FROM staff WHERE employee_id = 'EMP008'), (SELECT id FROM employee_types WHERE code = 'FT_SALARIED'), NULL, 45000.00, NULL, '2023-02-01', true)
ON CONFLICT DO NOTHING;

INSERT INTO leave_balances (staff_id, leave_type_id, year, allocated_days, used_days, remaining_days) VALUES
((SELECT id FROM staff WHERE employee_id = 'EMP001'), (SELECT id FROM leave_types WHERE code = 'VACATION'), 2025, 15.0, 5.0, 10.0),
((SELECT id FROM staff WHERE employee_id = 'EMP001'), (SELECT id FROM leave_types WHERE code = 'SICK'), 2025, 10.0, 2.0, 8.0),
((SELECT id FROM staff WHERE employee_id = 'EMP002'), (SELECT id FROM leave_types WHERE code = 'VACATION'), 2025, 15.0, 3.0, 12.0),
((SELECT id FROM staff WHERE employee_id = 'EMP002'), (SELECT id FROM leave_types WHERE code = 'SICK'), 2025, 10.0, 1.0, 9.0)
ON CONFLICT DO NOTHING;

INSERT INTO timesheets (staff_id, date, clock_in, clock_out, total_hours, regular_hours, break_hours, status) VALUES
((SELECT id FROM staff WHERE employee_id = 'EMP003'), '2025-10-01', '2025-10-01 08:00:00', '2025-10-01 16:30:00', 8.0, 8.0, 0.5, 'approved'),
((SELECT id FROM staff WHERE employee_id = 'EMP004'), '2025-10-01', '2025-10-01 09:00:00', '2025-10-01 17:00:00', 8.0, 8.0, 0.5, 'approved'),
((SELECT id FROM staff WHERE employee_id = 'EMP006'), '2025-10-01', '2025-10-01 10:00:00', '2025-10-01 18:00:00', 8.0, 8.0, 0.5, 'approved'),
((SELECT id FROM staff WHERE employee_id = 'EMP007'), '2025-10-01', '2025-10-01 11:00:00', '2025-10-01 19:00:00', 8.0, 8.0, 0.5, 'approved')
ON CONFLICT DO NOTHING;

INSERT INTO breaks (timesheet_id, break_type, start_time, end_time, duration_minutes, notes) VALUES
((SELECT id FROM timesheets WHERE staff_id = (SELECT id FROM staff WHERE employee_id = 'EMP003' LIMIT 1) AND date = '2025-10-01' LIMIT 1), 'lunch', '2025-10-01 12:00:00', '2025-10-01 12:30:00', 30, 'Lunch break'),
((SELECT id FROM timesheets WHERE staff_id = (SELECT id FROM staff WHERE employee_id = 'EMP004' LIMIT 1) AND date = '2025-10-01' LIMIT 1), 'lunch', '2025-10-01 12:30:00', '2025-10-01 13:00:00', 30, 'Lunch break')
ON CONFLICT DO NOTHING;

-- Retain other parts of the original script (e.g., user creation, permissions, other inserts, etc.)

-- ============================================
-- SETUP COMPLETE
-- ============================================
-- Database: sipnsnack
-- User: sipnsnack_user
-- Tables created: 28 (17 existing + 11 inventory tables)
-- Unique constraints added
-- Sample data inserted
--
-- Next steps:
-- 1. Update your .env file with database credentials
-- 2. Run: python app.py
-- 3. Visit: http://localhost:5000
-- ============================================

-- Display completion message
DO $$
BEGIN
    RAISE NOTICE '================================================';
    RAISE NOTICE 'Sip & Snack Portal Database Setup Complete!';
    RAISE NOTICE '================================================';
END $$;
