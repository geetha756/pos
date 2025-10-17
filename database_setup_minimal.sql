-- ============================================
-- Sip & Snack Portal - Minimal Database Setup
-- ============================================
-- This script creates only the essential database structure
-- without sample data.
--
-- PREREQUISITE: Create the database manually first, then run this script.
--
-- Run this script as a PostgreSQL superuser (usually 'postgres')
-- ============================================

-- Create application user
CREATE USER sipnsnack_user WITH PASSWORD 's!pnsn@ck';

-- Grant privileges on the existing database
-- (Run this script while connected to the sipnsnack database)
GRANT ALL PRIVILEGES ON DATABASE sipnsnack TO sipnsnack_user;

-- Grant schema privileges
GRANT ALL ON SCHEMA public TO sipnsnack_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO sipnsnack_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO sipnsnack_user;

-- Enable UUID extension (required for UUID columns)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- CREATE TABLES
-- ============================================

-- Create locations table
CREATE TABLE IF NOT EXISTS locations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
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
    name VARCHAR(255) NOT NULL,
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

-- ============================================
-- CREATE INDEXES FOR PERFORMANCE
-- ============================================

CREATE INDEX IF NOT EXISTS idx_master_menu_category ON master_menu(category);
CREATE INDEX IF NOT EXISTS idx_master_menu_active ON master_menu(is_active);
CREATE INDEX IF NOT EXISTS idx_location_menu_location ON location_menu(location_id);
CREATE INDEX IF NOT EXISTS idx_location_menu_menu ON location_menu(master_menu_id);
CREATE INDEX IF NOT EXISTS idx_orders_location ON orders(location_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);

-- ============================================
-- GRANT PERMISSIONS
-- ============================================

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO sipnsnack_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO sipnsnack_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO sipnsnack_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO sipnsnack_user;

-- ============================================
-- SETUP COMPLETE
-- ============================================
-- Database: sipnsnack
-- User: sipnsnack_user
-- Tables created: 5
--
-- Next steps:
-- 1. Update your .env file and run python app.py
-- ============================================

-- Display completion message
DO $$
BEGIN
    RAISE NOTICE 'Sip & Snack Portal database setup complete!';
END $$;
