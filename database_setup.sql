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

-- Create master_menu table
CREATE TABLE IF NOT EXISTS master_menu (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL UNIQUE,
    description TEXT,
    price DECIMAL(10,2) NOT NULL,
    category VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    image_url VARCHAR(500),
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
    id SERIAL PRIMARY KEY,
    user_email VARCHAR(255) NOT NULL,
    user_name VARCHAR(255),
    login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    logout_time TIMESTAMP,
    ip_address INET,
    user_agent TEXT,
    is_active BOOLEAN DEFAULT TRUE
);

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

-- ============================================
-- 5. SAMPLE DATA (OPTIONAL)
-- ============================================

-- Insert sample locations (IDs will be auto-generated as UUIDs)
INSERT INTO locations (name, address, city, state, zip_code, phone, email) VALUES
('Downtown Branch', '123 Main St', 'New York', 'NY', '10001', '+1-555-0101', 'downtown@sipnsnack.com'),
('Mall Location', '456 Shopping Plaza', 'Los Angeles', 'CA', '90210', '+1-555-0102', 'mall@sipnsnack.com'),
('Airport Terminal', '789 Terminal Rd', 'Chicago', 'IL', '60601', '+1-555-0103', 'airport@sipnsnack.com')
ON CONFLICT DO NOTHING;

-- Insert sample master menu items (IDs will be auto-generated as UUIDs)
INSERT INTO master_menu (name, description, price, category, is_active) VALUES
('Classic Coffee', 'Freshly brewed coffee', 3.50, 'Beverages', true),
('Cappuccino', 'Espresso with steamed milk foam', 4.25, 'Beverages', true),
('Green Tea', 'Organic green tea', 2.75, 'Beverages', true),
('Grilled Cheese Sandwich', 'Melted cheese on toasted bread', 6.99, 'Main Course', true),
('Caesar Salad', 'Crisp romaine lettuce with caesar dressing', 8.50, 'Salads', true),
('Chocolate Brownie', 'Rich chocolate brownie with vanilla ice cream', 5.25, 'Desserts', true),
('French Fries', 'Crispy golden fries', 4.50, 'Snacks', true),
('Ice Cream Sundae', 'Vanilla ice cream with chocolate sauce', 4.99, 'Desserts', true)
ON CONFLICT DO NOTHING;

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
-- SETUP COMPLETE
-- ============================================
-- Database: sipnsnack
-- User: sipnsnack_user
-- Tables created: 6
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
